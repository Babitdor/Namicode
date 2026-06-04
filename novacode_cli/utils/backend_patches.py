"""Safety patches for third-party LLM backends that don't handle all content block types.

When the read_file tool returns a ToolMessage with content_blocks of type "file"
(e.g. PDFs), some backends like Ollama crash with:
    "Blocks of type file not supported."

This module monkey-patches the conversion functions to handle unsupported block
types gracefully, converting them to text or skipping them instead of raising.

The primary defense is in FileTrackerMiddleware (converts file blocks → text at
the tool-result layer).  This module is a safety net for any file blocks that
escape that layer (e.g. from restored sessions or third-party tools).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_patched = False
_fs_host_path_patched = False
_write_file_content_patched = False


def apply_write_file_dict_content_patch() -> None:
    """Tolerate a dict/list ``content`` passed to the ``write_file`` tool.

    Models (especially weaker ones, and any time the content *is* JSON) often
    emit the ``content`` argument as a structured object rather than a string —
    e.g. /init's semantic-extraction subagents write a graph fragment and pass
    ``content={"nodes": [...], "edges": [...]}``. deepagents' ``WriteFileSchema``
    types ``content: str``, so langchain's ``_parse_input`` rejects the call at
    pydantic validation *before* the tool body runs:

        1 validation error for WriteFileSchema / content
        Input should be a valid string ... input_type=dict

    The file is never written and the chunk is lost (LangSmith shows no tool
    error because it fails at arg validation). This wraps the schema's
    ``model_validate`` so a dict/list ``content`` is JSON-serialized to a string
    first — the deliverable file then contains exactly the intended JSON.
    Idempotent and best-effort.
    """
    global _write_file_content_patched
    if _write_file_content_patched:
        return

    try:
        import deepagents.middleware.filesystem as _fsmod
    except ImportError:
        return

    schema = getattr(_fsmod, "WriteFileSchema", None)
    if schema is None:
        return

    import json

    _orig_model_validate = schema.model_validate.__func__  # unwrap classmethod

    def _patched_model_validate(cls, obj, *args, **kwargs):
        if isinstance(obj, dict):
            content = obj.get("content")
            if isinstance(content, (dict, list)):
                obj = {**obj, "content": json.dumps(content, ensure_ascii=False)}
        return _orig_model_validate(cls, obj, *args, **kwargs)

    schema.model_validate = classmethod(_patched_model_validate)
    _write_file_content_patched = True
    logger.debug("Applied write_file dict-content coercion patch")


def apply_filesystem_host_path_patch() -> None:
    """Make deepagents' ``validate_path`` tolerate host paths inside the project.

    The model frequently passes a real host absolute path (e.g.
    ``B:/…/novacode_cli/prompts/plan_agent.jinja``) to a file tool because it
    sees such paths everywhere (IDE context, ``@mentions``, traces).
    ``FilesystemMiddleware`` validates the path *before* the backend via
    ``validate_path``, which rejects any drive-letter path outright:

        "Windows absolute paths are not supported: B:/… Please use virtual
         paths starting with / (e.g., /workspace/file.txt)"

    This wraps ``validate_path`` so any host path at/under the current project
    root is first rewritten to its ``/``-rooted virtual form (see
    :func:`novacode_cli.integrations.host_path.host_path_to_virtual`). Paths that
    are already virtual, relative, or outside the project are passed through
    unchanged, so genuinely-invalid paths still raise the original helpful error.

    Idempotent and best-effort: a missing/renamed symbol just leaves the stock
    behavior in place.
    """
    global _fs_host_path_patched
    if _fs_host_path_patched:
        return

    try:
        import deepagents.middleware.filesystem as _fsmod
    except ImportError:
        return

    _original = getattr(_fsmod, "validate_path", None)
    if _original is None:
        return

    from novacode_cli.integrations.host_path import host_path_to_virtual

    def _current_workspace_root() -> str | None:
        try:
            from pathlib import Path

            from novacode_cli.config.config import settings

            return str(settings.project_root or Path.cwd())
        except Exception:  # noqa: BLE001
            return None

    def _patched_validate_path(path: Any, *, allowed_prefixes: Any = None) -> str:
        try:
            if isinstance(path, str):
                root = _current_workspace_root()
                if root:
                    path = host_path_to_virtual(path, root)
        except Exception:  # noqa: BLE001
            pass  # Never let normalization break validation; fall through.
        return _original(path, allowed_prefixes=allowed_prefixes)

    _fsmod.validate_path = _patched_validate_path
    _fs_host_path_patched = True
    logger.debug("Applied filesystem host-path normalization patch")


def apply_ollama_content_block_patch() -> None:
    """Monkey-patch langchain_ollama to handle 'file' type content blocks.

    The stock _get_image_from_data_content_block only supports type="image"
    and raises ValueError for any other type. We patch the message-conversion
    loop to:
    - Skip file/audio/video content blocks with a log message instead of crashing
    - Filter out empty image entries that result from skipped blocks
    """
    global _patched
    if _patched:
        return

    try:
        import langchain_ollama.chat_models as _ollama_mod
    except ImportError:
        return

    # Patch 1: Make _get_image_from_data_content_block tolerate non-image blocks
    _original_fn = getattr(_ollama_mod, "_get_image_from_data_content_block", None)
    if _original_fn is None:
        return

    _SKIP_SENTINEL = object()  # Returned for blocks that should be skipped entirely

    def _patched_get_image_from_data_content_block(block: dict) -> Any:
        """Handle image and file content blocks for Ollama message conversion.

        Returns base64 image data for image blocks.
        For file blocks (PDF, etc.) and other unsupported types, returns the
        _SKIP_SENTINEL object so the caller can filter it from the images list.
        """
        block_type = block.get("type", "unknown")

        if block_type == "image":
            return _original_fn(block)

        if block_type == "file":
            mime_type = block.get("mime_type", "unknown")
            logger.info(
                f"Skipping unsupported 'file' content block (mime_type={mime_type}) "
                f"in Ollama message conversion. PDF text extraction should have "
                f"been handled upstream by FileTrackerMiddleware."
            )
            return _SKIP_SENTINEL

        logger.warning(
            f"Skipping unsupported content block type '{block_type}' "
            f"in Ollama message conversion"
        )
        return _SKIP_SENTINEL

    _ollama_mod._get_image_from_data_content_block = _patched_get_image_from_data_content_block

    # Patch 2: Wrap _convert_messages_to_ollama_messages to filter sentinel values
    # from the images list. Without this, sentinel objects would end up in the
    # API payload sent to Ollama.
    _original_convert = getattr(
        _ollama_mod.ChatOllama, "_convert_messages_to_ollama_messages", None
    )
    if _original_convert is None:
        _patched = True
        return

    def _patched_convert(self: Any, messages: Any) -> list[dict[str, Any]]:
        result = _original_convert(self, messages)
        # Filter out sentinel objects from images lists in each message
        for msg_dict in result:
            if "images" in msg_dict:
                filtered = [
                    img for img in msg_dict["images"]
                    if img is not _SKIP_SENTINEL
                ]
                # Remove images key entirely if no images remain
                if filtered:
                    msg_dict["images"] = filtered
                else:
                    msg_dict.pop("images", None)
        return result

    _ollama_mod.ChatOllama._convert_messages_to_ollama_messages = _patched_convert  # type: ignore

    # Also patch the async variant if it exists (some versions split sync/async paths)
    _original_aconvert = getattr(
        _ollama_mod.ChatOllama, "_aconvert_messages_to_ollama_messages", None
    )
    if _original_aconvert is not None:
        async def _patched_aconvert(self: Any, messages: Any) -> list[dict[str, Any]]:
            result = await _original_aconvert(self, messages)
            for msg_dict in result:
                if "images" in msg_dict:
                    filtered = [
                        img for img in msg_dict["images"]
                        if img is not _SKIP_SENTINEL
                    ]
                    if filtered:
                        msg_dict["images"] = filtered
                    else:
                        msg_dict.pop("images", None)
            return result

        _ollama_mod.ChatOllama._aconvert_messages_to_ollama_messages = _patched_aconvert  # type: ignore

    _patched = True
    logger.debug("Applied Ollama content block + message-conversion patch for file type support")