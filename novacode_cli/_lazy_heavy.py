"""Keep `transformers`/`torch` out of Nova's startup import graph.

``langchain_core.language_models.base`` does, at module scope::

    try:
        from transformers import GPT2TokenizerFast
        _HAS_TRANSFORMERS = True
    except ImportError:
        _HAS_TRANSFORMERS = False

That import is only ever used for a *fallback* GPT-2 token counter
(``_get_token_ids_default_method``), but ``transformers`` eagerly pulls in
``torch``, ``numpy``, ``huggingface_hub`` and ``PIL``. Measured on this project:

    full import of novacode_cli.main   305 MB RSS, ~13 s, 4056 modules
    with transformers/torch excluded   145 MB RSS, ~2.4 s, 3053 modules

Nova talks to hosted model APIs and takes token counts from the provider
(``get_num_tokens_from_messages``, with char-based fallbacks at every call
site), so it never needs the GPT-2 tokenizer. Paying 160 MB of resident memory
and ~10 s of startup for it caused real problems on memory-constrained machines
(paging-file exhaustion, failed subprocess spawns).

This installs a meta-path finder that makes ``import transformers`` raise
``ImportError`` — the exact exception langchain_core already handles — so it
cleanly takes the ``_HAS_TRANSFORMERS = False`` branch.

Escape hatch: set ``NOVA_ALLOW_TRANSFORMERS=1`` to disable the guard. Anything
that genuinely needs the library (a local HF model, say) can also call
:func:`allow_transformers` first.
"""

from __future__ import annotations

import os
import sys
from typing import Any

#: Top-level packages kept out of the startup graph.
_BLOCKED = frozenset({"transformers", "torch"})

_ENV_OPT_OUT = "NOVA_ALLOW_TRANSFORMERS"


class _HeavyImportGuard:
    """Meta-path finder that refuses the heavy optional deps.

    Raising ``ImportError`` (rather than returning ``None``) is deliberate: the
    consumers of these packages all wrap the import in ``try/except
    ImportError`` and degrade gracefully. Returning ``None`` would just let the
    real finder load them.
    """

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> None:  # noqa: ANN401, ARG002
        if name.split(".")[0] in _BLOCKED:
            msg = (
                f"{name!r} is not imported at Nova startup (it costs ~160 MB of "
                f"resident memory and is only needed for a fallback tokenizer). "
                f"Set {_ENV_OPT_OUT}=1 if you really need it."
            )
            raise ImportError(msg)
        return None


_guard: _HeavyImportGuard | None = None


def install() -> bool:
    """Install the guard. Returns True if it is now active.

    No-ops when the user opted out, or when the packages are already imported
    (blocking then would be pointless — the memory is already committed).
    """
    global _guard
    if os.environ.get(_ENV_OPT_OUT, "").strip().lower() in ("1", "true", "yes"):
        return False
    if _guard is not None:
        return True
    if any(mod in sys.modules for mod in _BLOCKED):
        return False
    _guard = _HeavyImportGuard()
    sys.meta_path.insert(0, _guard)
    return True


def allow_transformers() -> None:
    """Remove the guard so ``transformers``/``torch`` can be imported again."""
    global _guard
    if _guard is not None:
        try:
            sys.meta_path.remove(_guard)
        except ValueError:
            pass
        _guard = None


def is_active() -> bool:
    """Whether the guard is currently installed."""
    return _guard is not None
