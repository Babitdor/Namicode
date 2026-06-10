"""Shared limits for the memory tiers.

Single source of truth for the per-file character budget used on both the
**write** side (Semantic-tier compaction in ``hermes/memory_tiers.py``) and the
**read** side (prompt-injection truncation in ``memory/agent_memory.py``). These
were previously two independent ``MAX_MEMORY_CHARS = 12_000`` constants that
could silently drift.

Compaction invariant (keep-newest):
    Memory files are written newest-first (new sections/lessons are prepended,
    above older ones). Both compaction and injection-time truncation therefore
    keep the **head** of the file — which is the most recent content. Any new
    memory writer MUST prepend, not append, to preserve this.
"""

from __future__ import annotations

# Maximum characters per memory file before compaction / truncation
# (~3,000 tokens at 4 chars/token). Prevents unbounded prompt growth.
MAX_MEMORY_CHARS = 12_000
