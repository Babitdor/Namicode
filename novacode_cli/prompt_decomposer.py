"""Prompt decomposition for multi-intent user requests.

Splits a natural-language prompt that contains multiple sequential
intentions into independent sub-prompts, so the agent can execute them
one at a time with full conversation context between steps.

The decomposer is deliberately **conservative**: it only splits when it
detects clear, strong signals that the user is asking for multiple
distinct tasks.  When in doubt, it keeps the prompt intact — a single
overly-broad prompt is always safer than a wrongly-split one.

Supported decomposition signals
-------------------------------
1. **Numbered lists** — "1. Do X  2. Do Y  3. Do Z"
2. **Sequential connectors** — "Do X, and then do Y", "After that, do Y"
3. **Ordinal starters** — "First, do X. Second, do Y. Third, do Z"
4. **Bullet lists** — "- Do X\\n- Do Y" (only in plain-text, not rendered markdown)

Things that are NOT decomposed
-------------------------------
- Simple "and" connecting objects: "Fix bug A and bug B"
- "or" alternatives: "Use Redis or Memcached"
- "with"/"using" modifiers: "Create an API with auth"
- Short prompts (< 20 chars)
- Code/quotes: content inside backticks, quotes, or brackets
- Prompts that are already a single clear intent

Configuration
-------------
Decomposition can be toggled on/off via the SessionState attribute
``prompt_decomposition_enabled`` (default: True).  The ``/decompose``
slash command lets the user toggle at runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class DecompositionResult:
    """Result of prompt decomposition.

    Attributes:
        sub_prompts: Ordered list of sub-prompts to execute sequentially.
            If decomposition didn't trigger, this is [original_prompt].
        original: The original un-decomposed prompt.
        decomposed: True if the prompt was actually split into >1 sub-prompts.
        reason: Human-readable reason for the decomposition decision.
    """

    sub_prompts: list[str]
    original: str
    decomposed: bool
    reason: str = ""


# Maximum number of sub-prompts to produce.
# Prevents degenerate cases where a long numbered list produces 20 sub-tasks.
_MAX_SUB_PROMPTS = 5

# Minimum prompt length (chars) to even consider decomposition.
_MIN_PROMPT_LENGTH = 20


def decompose_prompt(prompt: str, max_sub_prompts: int = _MAX_SUB_PROMPTS) -> DecompositionResult:
    """Decompose a multi-intent prompt into sequential sub-prompts.

    This is the main entry point.  It tries each decomposition strategy
    in order and returns the first successful match, or the original
    prompt if none trigger.

    Args:
        prompt: The user's raw input prompt.
        max_sub_prompts: Maximum number of sub-prompts to produce.

    Returns:
        A DecompositionResult with the sub-prompts and metadata.
    """
    stripped = prompt.strip()

    # Too short to decompose
    if len(stripped) < _MIN_PROMPT_LENGTH:
        return DecompositionResult(sub_prompts=[prompt], original=prompt, decomposed=False)

    # Try each decomposition strategy in priority order
    strategies = [
        _try_numbered_list,
        _try_ordinal_starters,
        _try_sequential_connectors,
        _try_bullet_list,
    ]

    for strategy in strategies:
        result = strategy(stripped, max_sub_prompts)
        if result is not None and len(result) > 1:
            # Add step context to each sub-prompt
            enriched = _enrich_sub_prompts(result, len(result))
            return DecompositionResult(
                sub_prompts=enriched,
                original=prompt,
                decomposed=True,
                reason=f"Split into {len(result)} steps via {strategy.__name__}",
            )

    # No decomposition triggered
    return DecompositionResult(sub_prompts=[prompt], original=prompt, decomposed=False)


# ---------------------------------------------------------------------------
# Decomposition Strategies
# ---------------------------------------------------------------------------


def _try_numbered_list(prompt: str, max_sub_prompts: int) -> list[str] | None:
    r"""Detect numbered-list patterns: 1. Do X  2. Do Y  3. Do Z

    Matches items that start with a 1-2 digit number followed by a
    period/paren and a space.  Works for both:
    - Inline lists: "1. Fix auth 2. Add rate limiting 3. Write tests"
    - Line-separated lists: "1. Fix auth\n2. Add rate limiting\n3. Write tests"

    Requires at least 2 numbered items with sequential numbering.

    Does NOT match:
    - "2024 was a good year" (4-digit years)
    - "1 test passed" (no period/paren after number)
    - "3.14 is pi" (decimal number, not list item)
    """
    # Inline pattern: number + period + space + capitalized text, terminated
    # by the next number or end of string.
    inline_pattern = r"(?:^|(?<=\s))(\d{1,2})[.)]\s+([A-Z].+?)(?=(?:\s+\d{1,2}[.)]\s)|$)"
    matches = list(re.finditer(inline_pattern, prompt, re.DOTALL))

    # If inline didn't match, try newline-separated pattern
    if len(matches) < 2:
        line_pattern = r"(?:^|\n)\s*(\d{1,2})[.)]\s+(.+?)(?=(?:\n\s*\d{1,2}[.)]\s)|$)"
        matches = list(re.finditer(line_pattern, prompt, re.DOTALL))

    if len(matches) < 2:
        return None

    # Verify the numbers are sequential (1, 2, 3...) and start at 1
    numbers = [int(m.group(1)) for m in matches]
    if numbers != list(range(1, len(numbers) + 1)):
        return None

    # Reject if first number > 1 (could be a mid-sentence number)
    if numbers[0] != 1:
        return None

    items = []
    for m in matches:
        text = m.group(2).strip().rstrip(".")
        if text:
            items.append(text)

    if len(items) < 2:
        return None

    return items[:max_sub_prompts]


def _try_ordinal_starters(prompt: str, max_sub_prompts: int) -> list[str] | None:
    r"""Detect 'First, do X. Second, do Y. Third, do Z.' patterns.

    Matches sentence-starting ordinals (First, Second, Third, etc.)
    followed by a comma and an imperative clause.
    """
    ordinals = [
        r"First", r"Second", r"Third", r"Fourth", r"Fifth",
        r"first", r"second", r"third", r"fourth", r"fifth",
    ]
    ordinal_pattern = "|".join(ordinals)

    # Pattern: start of string or after sentence-ending punctuation,
    # then an ordinal word, comma, then text until the next ordinal or end.
    pattern = rf"(?:^|[.!?]\s*)(?:{ordinal_pattern}),\s*(.+?)(?=(?:[.!?]\s*(?:{ordinal_pattern}),)|$)"
    matches = list(re.finditer(pattern, prompt, re.IGNORECASE | re.DOTALL))

    if len(matches) < 2:
        return None

    items = []
    for m in matches:
        text = m.group(1).strip().rstrip(".")
        if text:
            items.append(text)

    if len(items) < 2:
        return None

    return items[:max_sub_prompts]


def _try_sequential_connectors(prompt: str, max_sub_prompts: int) -> list[str] | None:
    r"""Detect sequential connector patterns.

    Matches phrases like:
    - "Do X, and then do Y"
    - "Do X. After that, do Y"
    - "Do X. Next, do Y"
    - "Do X. Then, do Y"

    Does NOT match:
    - "and then" inside code: `npm install and then npm test`
    - "next" as a non-imperative: "The next thing is..."
    """
    # Strip code blocks and inline code to avoid false positives
    clean = _strip_code_blocks(prompt)

    # Split on sequential connectors that sit at a clause/sentence boundary.
    # The key signal is: (sentence boundary) + (connector) + (imperative verb).
    connectors = [
        r",\s+and\s+then\s+",      # ", and then "
        r"\.\s+After\s+that,?\s+", # ". After that, " or ". After that "
        r"\.\s+Next,?\s+",         # ". Next, " or ". Next "
        r"\.\s+Then,?\s+",         # ". Then, " or ". Then "
        r"\.\s+Also,?\s+",         # ". Also, " or ". Also "
        r"\.\s+Finally,?\s+",      # ". Finally, " or ". Finally "
        r"\.\s+Afterwards,?\s+",   # ". Afterwards, " or ". Afterwards "
    ]

    # Try each connector pattern
    for conn_pattern in connectors:
        parts = re.split(conn_pattern, clean, flags=re.IGNORECASE)
        if len(parts) >= 2:
            # Verify the parts aren't too short (avoid splitting on "ok. Then go" → ["ok", "go"])
            items = []
            for p in parts:
                p = p.strip().rstrip(".")
                if len(p) >= 5:  # Sub-prompts must be at least 5 chars
                    items.append(p)

            if len(items) >= 2:
                return items[:max_sub_prompts]

    return None


def _try_bullet_list(prompt: str, max_sub_prompts: int) -> list[str] | None:
    r"""Detect bullet-list patterns: - Do X\n- Do Y\n- Do Z

    Only matches when there are at least 2 bullet items on separate lines.
    Ignores single bullet points (common in markdown).

    Does NOT match bullet lists inside code blocks.
    """
    clean = _strip_code_blocks(prompt)

    # Pattern: line start, bullet marker (- or * or •), space, text
    pattern = r"(?:^|\n)\s*[-*•]\s+(.+?)(?=(?:\n\s*[-*•]\s)|$)"
    matches = list(re.finditer(pattern, clean, re.DOTALL))

    if len(matches) < 2:
        return None

    items = []
    for m in matches:
        text = m.group(1).strip()
        if text and len(text) >= 10:
            items.append(text)

    if len(items) < 2:
        return None

    return items[:max_sub_prompts]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks and inline code from text.

    This prevents false-positive splits on connectors that appear
    inside code (e.g., "run `npm install and then npm test`").

    Args:
        text: Input text.

    Returns:
        Text with code blocks replaced by a placeholder.
    """
    # Remove fenced code blocks (```...```)
    result = re.sub(r"```[\s\S]*?```", " [code block] ", text)
    # Remove inline code (`...`)
    result = re.sub(r"`[^`]+`", " [code] ", result)
    return result


def _enrich_sub_prompts(sub_prompts: list[str], total: int) -> list[str]:
    """Add step context to each sub-prompt.

    Prepends a brief context line so the agent knows it's working
    on part of a larger request.  This helps the agent:
    - Understand it should complete only this step, not the whole request
    - Know how many steps remain
    - Connect current work to the overall goal

    Args:
        sub_prompts: Raw sub-prompts from a decomposition strategy.
        total: Total number of sub-prompts.

    Returns:
        Enriched sub-prompts with step context.
    """
    enriched = []
    for i, sub_prompt in enumerate(sub_prompts, 1):
        if total <= 1:
            enriched.append(sub_prompt)
        else:
            enriched.append(
                f"[Step {i} of {total} — complete this step, then stop and wait for the next.]\n\n{sub_prompt}"
            )
    return enriched


def format_decomposition_message(result: DecompositionResult) -> str:
    """Format a human-readable decomposition summary for the console.

    Args:
        result: The decomposition result.

    Returns:
        Rich-formatted string to print before executing sub-prompts.
    """
    if not result.decomposed:
        return ""

    lines = [f"[bold cyan]Decomposing into {len(result.sub_prompts)} steps:[/bold cyan]"]
    for i, sp in enumerate(result.sub_prompts, 1):
        # Show first 80 chars of each sub-prompt
        preview = sp.split("\n")[0][:80]
        if len(sp.split("\n")[0]) > 80:
            preview += "..."
        lines.append(f"  [dim]{i}.[/dim] {preview}")

    return "\n".join(lines)