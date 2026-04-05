"""Unit tests for SkillsMiddleware functionality."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from novacode_cli.skills.middleware import SkillsMiddleware


class TestSkillsMiddlewareInit:
    """Test SkillsMiddleware initialization."""

    def test_init_basic(self, tmp_path: Path) -> None:
        """Test basic initialization."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="test-agent",
        )

        assert middleware.skills_dir == skills_dir
        assert middleware.assistant_id == "test-agent"
        assert middleware.project_skills_dir is None
        assert middleware.project_skills_dirs == []

    def test_init_with_project_skills_dir(self, tmp_path: Path) -> None:
        """Test initialization with project skills directory."""
        skills_dir = tmp_path / "user_skills"
        project_skills = tmp_path / "project_skills"
        skills_dir.mkdir()
        project_skills.mkdir()

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="test-agent",
            project_skills_dir=project_skills,
        )

        assert middleware.project_skills_dir == project_skills

    def test_init_with_multiple_project_dirs(self, tmp_path: Path) -> None:
        """Test initialization with multiple project skills directories."""
        skills_dir = tmp_path / "user_skills"
        project1 = tmp_path / ".Nova" / "skills"
        project2 = tmp_path / ".claude" / "skills"
        skills_dir.mkdir()
        project1.mkdir(parents=True)
        project2.mkdir(parents=True)

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="test-agent",
            project_skills_dirs=[project1, project2],
        )

        assert middleware.project_skills_dirs == [project1, project2]

    def test_skills_dir_expands_user(self, tmp_path: Path) -> None:
        """Test that skills_dir expands ~ in path."""
        # We can't easily test actual ~ expansion, but test that Path is used
        middleware = SkillsMiddleware(
            skills_dir=str(tmp_path),
            assistant_id="agent",
        )
        assert isinstance(middleware.skills_dir, Path)


class TestSkillsMiddlewareProperties:
    """Test SkillsMiddleware properties."""

    def test_skills_dir_display(self, tmp_path: Path) -> None:
        """Test skills_dir_display returns correct format."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path / "skills",
            assistant_id="my-agent",
        )

        display = middleware.skills_dir_display
        assert display == "~/.Nova/my-agent/skills"

    def test_skills_dir_absolute(self, tmp_path: Path) -> None:
        """Test skills_dir_absolute returns absolute path string."""
        skills_dir = tmp_path / "skills"
        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="agent",
        )

        assert middleware.skills_dir_absolute == str(skills_dir)


class TestSkillsMiddlewareFormatLocations:
    """Test _format_skills_locations method."""

    def test_format_user_skills_only(self, tmp_path: Path) -> None:
        """Test formatting with only user skills directory."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        result = middleware._format_skills_locations()
        assert "~/.Nova/agent/skills" in result
        assert "User Skills" in result

    def test_format_with_single_project_dir(self, tmp_path: Path) -> None:
        """Test formatting with single project directory."""
        project_dir = tmp_path / "project" / ".Nova" / "skills"
        middleware = SkillsMiddleware(
            skills_dir=tmp_path / "user",
            assistant_id="agent",
            project_skills_dir=project_dir,
        )

        result = middleware._format_skills_locations()
        assert "Project Skills" in result
        assert str(project_dir) in result

    def test_format_with_multiple_project_dirs(self, tmp_path: Path) -> None:
        """Test formatting with multiple project directories."""
        project1 = tmp_path / ".Nova" / "skills"
        project2 = tmp_path / ".claude" / "skills"
        middleware = SkillsMiddleware(
            skills_dir=tmp_path / "user",
            assistant_id="agent",
            project_skills_dirs=[project1, project2],
        )

        result = middleware._format_skills_locations()
        assert "Project Skills" in result
        assert str(project1) in result
        assert str(project2) in result


class TestSkillsMiddlewareFormatSkillsList:
    """Test _format_skills_list method."""

    def test_format_empty_skills(self, tmp_path: Path) -> None:
        """Test formatting with no skills available."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        result = middleware._format_skills_list([])
        assert "No skills available" in result
        assert "~/.Nova/agent/skills" in result

    def test_format_user_skills(self, tmp_path: Path) -> None:
        """Test formatting user skills."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        skills = [
            {
                "name": "web-research",
                "description": "Research topics on the web",
                "path": "/path/to/web-research/SKILL.md",
                "source": "user",
            },
            {
                "name": "code-review",
                "description": "Review code for issues",
                "path": "/path/to/code-review/SKILL.md",
                "source": "user",
            },
        ]

        result = middleware._format_skills_list(skills)
        assert "User Skills" in result
        assert "web-research" in result
        assert "Research topics on the web" in result
        assert "code-review" in result
        assert "Review code for issues" in result

    def test_format_project_skills(self, tmp_path: Path) -> None:
        """Test formatting project skills."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        skills = [
            {
                "name": "deploy",
                "description": "Deploy the application",
                "path": "/project/.Nova/skills/deploy/SKILL.md",
                "source": "project",
            },
        ]

        result = middleware._format_skills_list(skills)
        assert "Project Skills" in result
        assert "deploy" in result
        assert "Deploy the application" in result

    def test_format_mixed_skills(self, tmp_path: Path) -> None:
        """Test formatting both user and project skills."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        skills = [
            {
                "name": "user-skill",
                "description": "A user skill",
                "path": "/user/skills/user-skill/SKILL.md",
                "source": "user",
            },
            {
                "name": "project-skill",
                "description": "A project skill",
                "path": "/project/skills/project-skill/SKILL.md",
                "source": "project",
            },
        ]

        result = middleware._format_skills_list(skills)
        assert "User Skills" in result
        assert "Project Skills" in result
        assert "user-skill" in result
        assert "project-skill" in result


class TestSkillsMiddlewareBeforeAgent:
    """Test before_agent method."""

    def test_before_agent_loads_skills(self, tmp_path: Path) -> None:
        """Test that before_agent loads skills from directories."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create a skill
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

Instructions here.
""")

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="agent",
        )

        mock_runtime = MagicMock()
        state: dict = {}

        result = middleware.before_agent(state, mock_runtime)

        assert result is not None
        assert "skills_metadata" in result
        assert len(result["skills_metadata"]) == 1
        assert result["skills_metadata"][0]["name"] == "test-skill"

    def test_before_agent_empty_directory(self, tmp_path: Path) -> None:
        """Test before_agent with empty skills directory."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="agent",
        )

        mock_runtime = MagicMock()
        state: dict = {}

        result = middleware.before_agent(state, mock_runtime)

        assert result is not None
        assert result["skills_metadata"] == []


class TestSkillsMiddlewareWrapModelCall:
    """Test wrap_model_call and awrap_model_call methods."""

    def test_wrap_model_call_injects_skills(self, tmp_path: Path) -> None:
        """Test that wrap_model_call injects skills into prompt."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        mock_request = MagicMock()
        mock_request.state = {
            "skills_metadata": [
                {
                    "name": "test-skill",
                    "description": "Test description",
                    "path": "/path/to/SKILL.md",
                    "source": "user",
                },
            ]
        }
        mock_request.system_prompt = "Original prompt"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        result = middleware.wrap_model_call(mock_request, mock_handler)

        mock_handler.assert_called_once_with(modified_request)
        mock_request.override.assert_called_once()

        # Verify system prompt was modified
        call_kwargs = mock_request.override.call_args[1]
        new_prompt = call_kwargs["system_prompt"]
        assert "Original prompt" in new_prompt
        assert "Skills System" in new_prompt
        assert "test-skill" in new_prompt

    def test_wrap_model_call_no_existing_prompt(self, tmp_path: Path) -> None:
        """Test wrap_model_call when no existing system prompt."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        mock_request = MagicMock()
        mock_request.state = {"skills_metadata": []}
        mock_request.system_prompt = None

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        middleware.wrap_model_call(mock_request, mock_handler)

        call_kwargs = mock_request.override.call_args[1]
        new_prompt = call_kwargs["system_prompt"]
        assert "Skills System" in new_prompt

    @pytest.mark.asyncio
    async def test_awrap_model_call_injects_skills(self, tmp_path: Path) -> None:
        """Test that awrap_model_call injects skills into prompt."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="agent",
        )

        mock_request = MagicMock()
        mock_request.state = {
            "skills_metadata": [
                {
                    "name": "async-skill",
                    "description": "Async test",
                    "path": "/async/SKILL.md",
                    "source": "project",
                },
            ]
        }
        mock_request.system_prompt = "Base prompt"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = AsyncMock(return_value="async response")

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result == "async response"
        mock_handler.assert_called_once_with(modified_request)

        call_kwargs = mock_request.override.call_args[1]
        new_prompt = call_kwargs["system_prompt"]
        assert "async-skill" in new_prompt


class TestSkillsMiddlewareIntegration:
    """Integration tests for SkillsMiddleware."""

    def test_full_workflow(self, tmp_path: Path) -> None:
        """Test complete workflow: before_agent -> wrap_model_call."""
        # Setup skills directory
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "integration-test"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: integration-test
description: Integration test skill
---

# Integration Test

Test instructions.
""")

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="test-agent",
        )

        # Step 1: before_agent loads skills
        mock_runtime = MagicMock()
        state: dict = {}
        state_update = middleware.before_agent(state, mock_runtime)
        state.update(state_update or {})

        # Step 2: wrap_model_call uses loaded skills
        mock_request = MagicMock()
        mock_request.state = state
        mock_request.system_prompt = "You are a helpful assistant."

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        middleware.wrap_model_call(mock_request, mock_handler)

        # Verify the full prompt contains skill info
        call_kwargs = mock_request.override.call_args[1]
        prompt = call_kwargs["system_prompt"]

        assert "You are a helpful assistant." in prompt
        assert "integration-test" in prompt
        assert "Integration test skill" in prompt

    def test_project_skills_override_user_skills(self, tmp_path: Path) -> None:
        """Test that project skills override user skills with same name."""
        user_skills = tmp_path / "user" / "skills"
        project_skills = tmp_path / "project" / ".Nova" / "skills"
        user_skills.mkdir(parents=True)
        project_skills.mkdir(parents=True)

        # Create user skill
        user_skill = user_skills / "shared-skill"
        user_skill.mkdir()
        (user_skill / "SKILL.md").write_text("""---
name: shared-skill
description: User version
---
""")

        # Create project skill with same name
        project_skill = project_skills / "shared-skill"
        project_skill.mkdir()
        (project_skill / "SKILL.md").write_text("""---
name: shared-skill
description: Project version (should override)
---
""")

        middleware = SkillsMiddleware(
            skills_dir=user_skills,
            assistant_id="agent",
            project_skills_dir=project_skills,
        )

        mock_runtime = MagicMock()
        result = middleware.before_agent({}, mock_runtime)

        # Should only have one skill (project version)
        assert len(result["skills_metadata"]) == 1
        assert result["skills_metadata"][0]["description"] == "Project version (should override)"
        assert result["skills_metadata"][0]["source"] == "project"
