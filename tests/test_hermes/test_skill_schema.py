"""Tests for the canonical SKILL.md schema — frontmatter normalization + validation."""

from __future__ import annotations

from novacode_cli.skills.schema import (
    CANONICAL_SECTIONS,
    DEFAULT_VERSION,
    normalize_skill_frontmatter,
    render_schema_block,
    validate_skill_structure,
)


class TestNormalize:
    def test_injects_version_and_tags_for_bare_body(self):
        out = normalize_skill_frontmatter("## Procedure\n1. do it", "my-skill", "Use when X")
        assert out.startswith("---\n")
        assert "name: my-skill" in out
        assert 'description: "Use when X"' in out
        assert f"version: {DEFAULT_VERSION}" in out
        assert "tags: []" in out
        assert "## Procedure\n1. do it" in out

    def test_preserves_existing_frontmatter_and_extra_keys(self):
        content = (
            '---\nname: keep\ndescription: "d"\nversion: 2.1.0\n'
            "tags: [a, b]\nauthor: nova\n---\n\nbody here"
        )
        out = normalize_skill_frontmatter(content, "fallback", "fallbackdesc")
        assert "name: keep" in out          # existing wins over fallback
        assert "version: 2.1.0" in out
        assert "tags: [a, b]" in out
        assert "author: nova" in out        # extra author key preserved
        assert "body here" in out

    def test_idempotent(self):
        once = normalize_skill_frontmatter("## Procedure\nx", "s", "trigger")
        twice = normalize_skill_frontmatter(once, "s", "trigger")
        assert once == twice

    def test_fills_missing_name_and_description(self):
        out = normalize_skill_frontmatter("body", "auto-name")
        assert "name: auto-name" in out
        assert "Reusable workflow: auto-name" in out


class TestValidate:
    def test_complete_skill_has_no_issues(self):
        body = "\n".join(f"## {s}\nx" for s in CANONICAL_SECTIONS)
        content = normalize_skill_frontmatter(body, "s", "trigger")
        assert validate_skill_structure(content) == []

    def test_flags_missing_frontmatter_and_sections(self):
        issues = validate_skill_structure("just text, no frontmatter")
        assert any("frontmatter" in i for i in issues)
        assert any("When to Use" in i for i in issues)


def test_render_schema_block_mentions_all_sections():
    block = render_schema_block()
    for section in CANONICAL_SECTIONS:
        assert section in block
