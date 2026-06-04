"""Tests for the condensed remote tool-activity digest (anti-flood)."""

from novacode_cli.remote.bridge import format_tool_digest


def test_empty_is_blank():
    assert format_tool_digest([]) == ""
    assert format_tool_digest([None, ""]) == ""  # type: ignore[list-item]


def test_single_tool():
    out = format_tool_digest(["read_file"])
    assert out.startswith("🔧 1 tool call ·")
    assert "`read_file`" in out  # backtick-wrapped for Telegram Markdown safety
    assert "×" not in out  # no multiplier for a single use


def test_counts_and_order_preserved():
    out = format_tool_digest(["read_file", "read_file", "grep", "read_file", "grep"])
    assert "5 tool calls" in out
    # first-seen order: read_file before grep; counts shown as ×N
    assert out.index("read_file×3") < out.index("grep×2")


def test_distinct_cap_collapses_to_more():
    names = [f"t{i}" for i in range(12)]
    out = format_tool_digest(names, max_shown=4)
    assert "+8 more" in out
    assert "12 tool calls" in out


def test_telegram_markdown_safe():
    """Underscored tool names must be wrapped in backticks so Telegram's
    Markdown parser doesn't treat them as italics and reject the message."""
    out = format_tool_digest(["read_file", "write_file"])
    body = out.split("·", 1)[1].strip()
    assert body.startswith("`") and body.endswith("`")
