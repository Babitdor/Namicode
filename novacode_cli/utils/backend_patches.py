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