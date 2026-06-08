"""Utilities for accurate token counting using LangChain models."""

import hashlib
import json
import os
import warnings
from pathlib import Path

# Suppress transformers warnings about missing ML frameworks
# We only need transformers for token counting, not model inference
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
warnings.filterwarnings("ignore", message=".*PyTorch.*TensorFlow.*Flax.*")

from langchain_core.messages import SystemMessage

from novacode_cli.config.config import settings
from novacode_cli.prompts import render_template

# Cache file name stored alongside the agent directory
_TOKEN_CACHE_FILENAME = "token_cache.json"


def _prompt_hash(full_system_prompt: str) -> str:
    """SHA-256 fingerprint of the assembled system prompt."""
    return hashlib.sha256(full_system_prompt.encode("utf-8")).hexdigest()


def _load_token_cache(agent_dir: Path, prompt_hash: str) -> int | None:
    """Return cached token count if the prompt hash matches, else None."""
    cache_path = agent_dir / _TOKEN_CACHE_FILENAME
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("hash") == prompt_hash:
            return int(data["tokens"])
    except Exception:
        pass
    return None


def _save_token_cache(agent_dir: Path, prompt_hash: str, tokens: int) -> None:
    """Persist the token count keyed by prompt hash."""
    try:
        agent_dir.mkdir(parents=True, exist_ok=True)
        cache_path = agent_dir / _TOKEN_CACHE_FILENAME
        cache_path.write_text(
            json.dumps({"hash": prompt_hash, "tokens": tokens}),
            encoding="utf-8",
        )
    except Exception:
        pass


def calculate_baseline_tokens(
    model, agent_dir: Path, system_prompt: str, assistant_id: str
) -> int:
    """Calculate baseline context tokens using the model's official tokenizer.

    This uses the model's get_num_tokens_from_messages() method to get
    accurate token counts for the initial context (system prompt + agent.md).

    Results are cached to disk keyed by SHA-256 of the full assembled prompt,
    so repeat startups with the same prompt skip the (potentially slow)
    tokenisation step entirely.

    Note: Tool definitions cannot be accurately counted before the first API call
    due to LangChain limitations. They will be included in the total after the
    first message is sent (~5,000 tokens).

    Args:
        model: LangChain model instance (ChatAnthropic or ChatOpenAI)
        agent_dir: Path to agent directory containing agent.md
        system_prompt: The base system prompt string
        assistant_id: The agent identifier for path references

    Returns:
        Token count for system prompt + agent.md (tools not included)
    """
    # Load user agent.md content
    agent_md_path = agent_dir / "agent.md"
    user_memory = ""
    if agent_md_path.exists():
        user_memory = agent_md_path.read_text(encoding="utf-8")

    # Load project agent.md content
    from .config.config import _find_project_agent_md, _find_project_root

    project_memory = ""
    project_root = _find_project_root()
    if project_root:
        project_md_paths = _find_project_agent_md(project_root)
        if project_md_paths:
            try:
                contents = []
                for path in project_md_paths:  # type: ignore
                    contents.append(path.read_text(encoding="utf-8"))
                project_memory = "\n\n".join(contents)
            except Exception:
                pass

    # Build the complete system prompt as it will be sent
    memory_section = (
        f"<user_memory>\n{user_memory or '(No user agent.md)'}\n</user_memory>\n\n"
        f"<project_memory>\n{project_memory or '(No project agent.md)'}\n</project_memory>"
    )

    memory_system_prompt = get_memory_system_prompt(
        assistant_id, project_root, bool(project_memory)
    )

    full_system_prompt = (
        memory_section + "\n\n" + system_prompt + "\n\n" + memory_system_prompt
    )

    # --- Cache check ---
    prompt_hash = _prompt_hash(full_system_prompt)
    cached = _load_token_cache(agent_dir, prompt_hash)
    if cached is not None:
        return cached

    # --- Compute ---
    tokens = _count_tokens_for_prompt(model, full_system_prompt)

    # --- Persist ---
    _save_token_cache(agent_dir, prompt_hash, tokens)
    return tokens


def _count_tokens_for_prompt(model, full_system_prompt: str) -> int:
    """Run the actual (potentially slow) token counting, with fallbacks."""
    messages = [SystemMessage(content=full_system_prompt)]

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Token indices sequence length is longer than",
            )
            warnings.filterwarnings(
                "ignore",
                message=".*transformers.*",
            )
            return model.get_num_tokens_from_messages(messages)
    except Exception:
        pass

    # Fallback 1: Anthropic SDK native token counter
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.count_tokens(  # type: ignore
            model=getattr(
                model,
                "model_name",
                getattr(model, "model", "claude-3-5-sonnet-20241022"),
            ),
            system=full_system_prompt,
            messages=[],
        )
        return response.input_tokens
    except Exception:
        pass

    # Fallback 2: tiktoken cl100k_base
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(full_system_prompt))
    except Exception:
        pass

    # Fallback 3: character estimate
    return len(full_system_prompt) // 4


def get_memory_system_prompt(
    assistant_id: str,
    project_root: Path | None = None,
    has_project_memory: bool = False,
) -> str:
    """Get the long-term memory system prompt text.

    Args:
        assistant_id: The agent identifier for path references
        project_root: Path to the detected project root (if any)
        has_project_memory: Whether project memory was loaded
    """
    agent_dir = settings.get_agent_dir(assistant_id)
    agent_dir_absolute = str(agent_dir)
    agent_dir_display = f"~/.nova/{assistant_id}"

    if project_root and has_project_memory:
        project_memory_info = f"`{project_root}` (detected)"
    elif project_root:
        project_memory_info = f"`{project_root}` (no agent.md found)"
    else:
        project_memory_info = "None (not in a git project)"

    if project_root:
        project_deepagents_dir = f"{project_root}/.nova"
    else:
        project_deepagents_dir = "[project-root]/.nova (not in a project)"

    return render_template(
        "longterm_memory.jinja",
        agent_dir_absolute=agent_dir_absolute,
        agent_dir_display=agent_dir_display,
        project_memory_info=project_memory_info,
        project_deepagents_dir=project_deepagents_dir,
    )
