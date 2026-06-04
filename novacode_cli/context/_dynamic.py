"""Dynamic context-window detection for Ollama models.

Private to the ``context`` package. Probes a locally-installed Ollama for a
model's real context length via ``ollama show``, cached for the process
lifetime. Used by :mod:`novacode_cli.context._analysis` as the first source for
``get_context_window_size`` (Ollama models only).
"""

from __future__ import annotations

import logging
import re
import subprocess
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def get_ollama_context_length(model_name: str) -> Optional[int]:
    """Get context length for an Ollama model dynamically.

    Uses caching to avoid repeated Ollama queries. Results are cached
    for the lifetime of the process.

    Args:
        model_name: Name of the Ollama model (e.g., "glm-5:cloud")

    Returns:
        Context length in tokens, or None if not found.
    """
    try:
        result = subprocess.run(
            ["ollama", "show", model_name],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.warning(f"Failed to get context for {model_name}: {result.stderr}")
            return None

        output = result.stdout

        # Look for a "context length" line, e.g. "context length      202752"
        for line in output.split("\n"):
            if "context" in line.lower() and "length" in line.lower():
                match = re.search(r"(\d+)", line)
                if match:
                    context_length = int(match.group(1))
                    logger.info(
                        f"Detected context length for {model_name}: "
                        f"{context_length:,} tokens"
                    )
                    return context_length

        logger.warning(f"No context length found for {model_name}")
        return None

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting context for {model_name}")
        return None
    except FileNotFoundError:
        logger.error("Ollama not found. Make sure Ollama is installed and in PATH.")
        return None
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error getting context for {model_name}: {e}")
        return None
