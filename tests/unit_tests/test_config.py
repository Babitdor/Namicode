"""Tests for config module including project discovery utilities."""

from pathlib import Path

from namicode_cli.config.config import _find_project_agent_md, _find_project_root


class TestProjectRootDetection:
    """Test project root detection via .git directory."""

    def test_find_project_root_with_git(self, tmp_path: Path) -> None:
        """Test that project root is found when .git directory exists."""
        # Create a mock project structure
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        git_dir = project_root / ".git"
        git_dir.mkdir()

        # Create a subdirectory to search from
        subdir = project_root / "src" / "components"
        subdir.mkdir(parents=True)

        # Should find project root from subdirectory
        result = _find_project_root(subdir)
        assert result == project_root

    def test_find_project_root_no_git(self, tmp_path: Path) -> None:
        """Test that None is returned when no .git directory exists."""
        # Create directory without .git
        no_git_dir = tmp_path / "no-git"
        no_git_dir.mkdir()

        result = _find_project_root(no_git_dir)
        assert result is None

    def test_find_project_root_nested_git(self, tmp_path: Path) -> None:
        """Test that nearest .git directory is found (not parent repos)."""
        # Create nested git repos
        outer_repo = tmp_path / "outer"
        outer_repo.mkdir()
        (outer_repo / ".git").mkdir()

        inner_repo = outer_repo / "inner"
        inner_repo.mkdir()
        (inner_repo / ".git").mkdir()

        # Should find inner repo, not outer
        result = _find_project_root(inner_repo)
        assert result == inner_repo


class TestProjectAgentMdFinding:
    """Test finding project-specific config files.

    _find_project_agent_md returns list[Path] — ALL files that exist, in
    general-to-specific order so that more-specific files override earlier ones:
      1. NAMI.md (root)
      2. .nami/NAMI.md
      3. CLAUDE.md (root)
      4. .claude/CLAUDE.md
    """

    def test_find_claude_md_in_claude_dir(self, tmp_path: Path) -> None:
        """Test finding CLAUDE.md in .claude/ directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        claude_md = claude_dir / "CLAUDE.md"
        claude_md.write_text("Claude Code instructions")

        result = _find_project_agent_md(project_root)
        assert result == [claude_md]

    def test_find_claude_md_in_root(self, tmp_path: Path) -> None:
        """Test finding CLAUDE.md in project root."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        root_claude_md = project_root / "CLAUDE.md"
        root_claude_md.write_text("Root CLAUDE.md")

        result = _find_project_agent_md(project_root)
        assert result == [root_claude_md]

    def test_find_nami_md_in_nami_dir(self, tmp_path: Path) -> None:
        """Test finding NAMI.md in .nami/ directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        nami_dir = project_root / ".nami"
        nami_dir.mkdir()
        nami_md = nami_dir / "NAMI.md"
        nami_md.write_text("Nami instructions")

        result = _find_project_agent_md(project_root)
        assert result == [nami_md]

    def test_find_nami_md_in_root(self, tmp_path: Path) -> None:
        """Test finding NAMI.md in project root (created by /init)."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        root_nami_md = project_root / "NAMI.md"
        root_nami_md.write_text("# Project Documentation")

        result = _find_project_agent_md(project_root)
        assert result == [root_nami_md]

    def test_find_agent_md_not_found(self, tmp_path: Path) -> None:
        """Test that empty list is returned when no config file exists."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = _find_project_agent_md(project_root)
        assert result == []

    def test_all_files_returned_when_multiple_exist(self, tmp_path: Path) -> None:
        """Test that ALL existing files are returned in general-to-specific order."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        root_nami_md = project_root / "NAMI.md"
        root_nami_md.write_text("Root NAMI.md")

        nami_dir = project_root / ".nami"
        nami_dir.mkdir()
        nami_dir_md = nami_dir / "NAMI.md"
        nami_dir_md.write_text("In .nami/")

        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        claude_dir_md = claude_dir / "CLAUDE.md"
        claude_dir_md.write_text("In .claude/")

        result = _find_project_agent_md(project_root)
        assert result == [root_nami_md, nami_dir_md, claude_dir_md]

    def test_priority_claude_dir_over_root(self, tmp_path: Path) -> None:
        """Test that both .claude/CLAUDE.md and root NAMI.md are returned."""
        project_root = tmp_path / "project"
        project_root.mkdir()

        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        claude_dir_md = claude_dir / "CLAUDE.md"
        claude_dir_md.write_text("In .claude/")

        root_nami_md = project_root / "NAMI.md"
        root_nami_md.write_text("Root NAMI.md")

        result = _find_project_agent_md(project_root)
        assert result == [root_nami_md, claude_dir_md]
