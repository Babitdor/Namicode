"""Tests for project-specific memory and dual agent.md loading."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from namicode_cli.memory.agent_memory import AgentMemoryMiddleware
from namicode_cli.config import Settings
from namicode_cli.skills import SkillsMiddleware


class TestAgentMemoryMiddleware:
    """Test dual memory loading in AgentMemoryMiddleware."""

    def test_load_user_memory_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading user agent.md when no project memory exists."""
        # Mock Path.home() to return tmp_path
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # Create user agent directory at ~/.nami/agents/{agent_name}/
        agent_dir = tmp_path / ".nami" / "agents" / "test_agent"
        agent_dir.mkdir(parents=True)
        user_md = agent_dir / "agent.md"
        user_md.write_text("User instructions")

        # Create a directory without .git to avoid project detection
        non_project_dir = tmp_path / "not-a-project"
        non_project_dir.mkdir()

        # Change to non-project directory for test
        original_cwd = Path.cwd()
        try:
            os.chdir(non_project_dir)

            # Create settings (no project detected from non_project_dir)
            test_settings = Settings.from_environment(start_path=non_project_dir)

            # Create middleware
            middleware = AgentMemoryMiddleware(settings=test_settings, assistant_id="test_agent")

            # Simulate before_agent call with no project root
            state = {}
            result = middleware.before_agent(state, None)

            assert result["user_memory"] == "User instructions"
            assert "project_memory" not in result
        finally:
            os.chdir(original_cwd)

    def test_load_both_memories(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading both user and project agent.md."""
        # Mock Path.home() to return tmp_path
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # Create user agent directory at ~/.nami/agents/{agent_name}/
        agent_dir = tmp_path / ".nami" / "agents" / "test_agent"
        agent_dir.mkdir(parents=True)
        user_md = agent_dir / "agent.md"
        user_md.write_text("User instructions")

        # Create project with .git and agent.md in .nami/
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        (project_root / ".nami").mkdir()
        project_md = project_root / ".nami" / "agent.md"
        project_md.write_text("Project instructions")

        original_cwd = Path.cwd()
        try:
            os.chdir(project_root)

            # Create settings (project detected from project_root)
            test_settings = Settings.from_environment(start_path=project_root)

            # Create middleware
            middleware = AgentMemoryMiddleware(settings=test_settings, assistant_id="test_agent")

            # Simulate before_agent call
            state = {}
            result = middleware.before_agent(state, None)

            assert result["user_memory"] == "User instructions"
            assert result["project_memory"] == "Project instructions"
        finally:
            os.chdir(original_cwd)

    def test_memory_not_reloaded_if_already_in_state(self, tmp_path: Path) -> None:
        """Test that memory is not reloaded if already in state."""
        agent_dir = tmp_path / ".deepagents" / "test_agent"
        agent_dir.mkdir(parents=True)

        # Create settings
        test_settings = Settings.from_environment(start_path=tmp_path)

        middleware = AgentMemoryMiddleware(settings=test_settings, assistant_id="test_agent")

        # State already has memory
        state = {"user_memory": "Existing memory", "project_memory": "Existing project"}
        result = middleware.before_agent(state, None)

        # Should return empty dict (no updates)
        assert result == {}


class TestSkillsPathResolution:
    """Test skills path resolution with per-agent structure."""

    def test_skills_middleware_paths(self, tmp_path: Path) -> None:
        """Test that skills middleware uses correct per-agent paths."""
        agent_dir = tmp_path / ".deepagents" / "test_agent"
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(parents=True)

        middleware = SkillsMiddleware(skills_dir=skills_dir, assistant_id="test_agent")

        # Check paths are correctly set
        assert middleware.skills_dir == skills_dir
        assert middleware.skills_dir_display == "~/.deepagents/test_agent/skills"
        assert middleware.skills_dir_absolute == str(skills_dir)

    def test_skills_dir_per_agent(self, tmp_path: Path) -> None:
        """Test that different agents have separate skills directories."""
        from namicode_cli.skills import SkillsMiddleware

        # Agent 1
        agent1_skills = tmp_path / ".deepagents" / "agent1" / "skills"
        agent1_skills.mkdir(parents=True)
        middleware1 = SkillsMiddleware(skills_dir=agent1_skills, assistant_id="agent1")

        # Agent 2
        agent2_skills = tmp_path / ".deepagents" / "agent2" / "skills"
        agent2_skills.mkdir(parents=True)
        middleware2 = SkillsMiddleware(skills_dir=agent2_skills, assistant_id="agent2")

        # Should have different paths
        assert middleware1.skills_dir != middleware2.skills_dir
        assert "agent1" in middleware1.skills_dir_display
        assert "agent2" in middleware2.skills_dir_display


class TestAgentMemoryBuildSystemPrompt:
    """Test _build_system_prompt method of AgentMemoryMiddleware."""

    def test_build_system_prompt_with_both_memories(self, tmp_path: Path) -> None:
        """Test building system prompt with both user and project memory."""
        test_settings = Settings.from_environment(start_path=tmp_path)

        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="test-agent",
        )

        mock_request = MagicMock()
        mock_request.state = {
            "user_memory": "User preferences here",
            "project_memory": "Project context here",
        }
        mock_request.system_prompt = "Base system prompt"

        result = middleware._build_system_prompt(mock_request)

        # Should contain user memory
        assert "User preferences here" in result
        # Should contain project memory
        assert "Project context here" in result
        # Should contain base prompt
        assert "Base system prompt" in result
        # Should contain long-term memory documentation
        assert "Long-term Memory" in result

    def test_build_system_prompt_with_user_memory_only(self, tmp_path: Path) -> None:
        """Test building system prompt with only user memory."""
        test_settings = Settings.from_environment(start_path=tmp_path)

        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="test-agent",
        )

        mock_request = MagicMock()
        mock_request.state = {
            "user_memory": "User memory content",
        }
        mock_request.system_prompt = None

        result = middleware._build_system_prompt(mock_request)

        assert "User memory content" in result
        assert "(No project agent.md)" in result

    def test_build_system_prompt_with_no_memory(self, tmp_path: Path) -> None:
        """Test building system prompt with no memory loaded."""
        test_settings = Settings.from_environment(start_path=tmp_path)

        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="test-agent",
        )

        mock_request = MagicMock()
        mock_request.state = {}
        mock_request.system_prompt = "Just the base prompt"

        result = middleware._build_system_prompt(mock_request)

        assert "(No user agent.md)" in result
        assert "(No project agent.md)" in result
        assert "Just the base prompt" in result

    def test_build_system_prompt_project_memory_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test project_memory_info formatting in system prompt."""
        # Create a project with .git
        project_root = tmp_path / "my-project"
        project_root.mkdir()
        (project_root / ".git").mkdir()

        original_cwd = Path.cwd()
        try:
            os.chdir(project_root)

            test_settings = Settings.from_environment(start_path=project_root)

            middleware = AgentMemoryMiddleware(
                settings=test_settings,
                assistant_id="test-agent",
            )

            mock_request = MagicMock()
            mock_request.state = {"project_memory": "Project content"}
            mock_request.system_prompt = None

            result = middleware._build_system_prompt(mock_request)

            # Should show project is detected
            assert "(detected)" in result or str(project_root) in result
        finally:
            os.chdir(original_cwd)


class TestAgentMemoryWrapModelCall:
    """Test wrap_model_call and awrap_model_call methods."""

    def test_wrap_model_call_injects_memory(self, tmp_path: Path) -> None:
        """Test that wrap_model_call injects memory into system prompt."""
        test_settings = Settings.from_environment(start_path=tmp_path)

        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="agent",
        )

        mock_request = MagicMock()
        mock_request.state = {"user_memory": "Remember this"}
        mock_request.system_prompt = "Original"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        result = middleware.wrap_model_call(mock_request, mock_handler)

        mock_handler.assert_called_once_with(modified_request)
        mock_request.override.assert_called_once()

        # Verify memory was injected
        call_kwargs = mock_request.override.call_args[1]
        assert "Remember this" in call_kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_awrap_model_call_injects_memory(self, tmp_path: Path) -> None:
        """Test that awrap_model_call injects memory into system prompt."""
        test_settings = Settings.from_environment(start_path=tmp_path)

        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="agent",
        )

        mock_request = MagicMock()
        mock_request.state = {"user_memory": "Async memory"}
        mock_request.system_prompt = "Base"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = AsyncMock(return_value="async response")

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result == "async response"
        mock_handler.assert_called_once_with(modified_request)

        call_kwargs = mock_request.override.call_args[1]
        assert "Async memory" in call_kwargs["system_prompt"]


class TestAgentMemoryEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_agent_md_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test handling of empty agent.md files."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # Create empty agent.md at ~/.nami/agents/{agent_name}/
        agent_dir = tmp_path / ".nami" / "agents" / "test_agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.md").write_text("")

        test_settings = Settings.from_environment(start_path=tmp_path)
        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="test_agent",
        )

        state: dict = {}
        result = middleware.before_agent(state, None)

        # Empty string is still valid memory
        assert result.get("user_memory") == ""

    def test_malformed_unicode_in_agent_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test handling of files with unicode errors (should skip gracefully).

        On some systems, certain byte sequences may be decoded with replacement
        characters rather than raising UnicodeDecodeError. The important thing
        is that the middleware handles this gracefully without crashing.
        """
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        # Create agent.md at ~/.nami/agents/{agent_name}/
        agent_dir = tmp_path / ".nami" / "agents" / "test_agent"
        agent_dir.mkdir(parents=True)

        # Write binary data with invalid UTF-8 sequences
        # These sequences are invalid in UTF-8: 0x80-0xBF as first byte
        (agent_dir / "agent.md").write_bytes(b"\x80\x81\x82 invalid utf-8 bytes")

        test_settings = Settings.from_environment(start_path=tmp_path)
        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="test_agent",
        )

        state: dict = {}
        # Should not raise - the middleware catches UnicodeDecodeError
        result = middleware.before_agent(state, None)

        # The behavior depends on the system's default encoding:
        # - On strict UTF-8 systems: file is skipped (UnicodeDecodeError)
        # - On systems with fallback encoding: file may be read with replacement chars
        # Either outcome is acceptable - the key is no exception is raised
        # We just verify the middleware completes without crashing
        assert isinstance(result, dict)

    def test_custom_system_prompt_template(self, tmp_path: Path) -> None:
        """Test using a custom system prompt template."""
        test_settings = Settings.from_environment(start_path=tmp_path)

        custom_template = """### Custom Memory Format ###
User: {user_memory}
Project: {project_memory}"""

        middleware = AgentMemoryMiddleware(
            settings=test_settings,
            assistant_id="agent",
            system_prompt_template=custom_template,
        )

        mock_request = MagicMock()
        mock_request.state = {
            "user_memory": "Custom user data",
            "project_memory": "Custom project data",
        }
        mock_request.system_prompt = None

        result = middleware._build_system_prompt(mock_request)

        assert "### Custom Memory Format ###" in result
        assert "User: Custom user data" in result
        assert "Project: Custom project data" in result
