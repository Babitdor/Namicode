"""NOVA CLI - Interactive AI coding assistant."""

# Must run before langchain_core is imported: it pulls in `transformers` (and
# therefore torch/numpy/PIL) at module scope for a fallback tokenizer Nova never
# uses, costing ~160 MB RSS and ~10 s of startup. See novacode_cli._lazy_heavy.
from novacode_cli import _lazy_heavy as _lazy_heavy

_lazy_heavy.install()

# from novacode_cli.main import cli_main

__all__ = []
