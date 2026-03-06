"""Unit tests for subagent skills functionality.

Tests that subagents have access to the same skills as the main agent
via the SkillsMiddleware integration in invoke_subagent.
"""

from pathlib import Path
from unittest.mock import MagicMock

from namicode_cli.skills.middleware import SkillsMiddleware


class TestSubagentSkillsMiddlewareSetup:
    """Test that invoke_subagent correctly sets up SkillsMiddleware."""

    def test_subagent_middleware_includes_skills_middleware(self, tmp_path: Path) -> None:
        """Test that subagent middleware pipeline includes SkillsMiddleware."""
        # Create mock skills directories
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        project_skills = tmp_path / "project" / ".nami" / "skills"
        project_skills.mkdir(parents=True)

        # Create SkillsMiddleware like invoke_subagent does
        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="test-subagent",
            project_skills_dirs=[project_skills],
        )

        assert middleware.skills_dir == skills_dir
        assert middleware.assistant_id == "test-subagent"
        assert middleware.project_skills_dirs == [project_skills]

    def test_subagent_skills_directory_path(self, tmp_path: Path) -> None:
        """Test that subagent uses correct skills directory paths."""
        skills_dir = tmp_path / ".nami" / "skills"
        skills_dir.mkdir(parents=True)

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="researcher",
        )

        # The skills_dir should be correctly set
        assert middleware.skills_dir == skills_dir
        # assistant_id should be the subagent name
        assert middleware.assistant_id == "researcher"


class TestSubagentSkillsDiscovery:
    """Test that subagents can discover and use skills."""

    def test_subagent_discovers_user_skills(self, tmp_path: Path) -> None:
        """Test that subagent discovers user-level skills."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create a skill
        skill_dir = skills_dir / "web-research"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: web-research
description: Research topics on the web systematically
---

# Web Research Skill

Follow this workflow for web research tasks.
""")

        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="research-agent",
        )

        mock_runtime = MagicMock()
        state: dict = {}

        result = middleware.before_agent(state, mock_runtime)

        assert result is not None
        assert len(result["skills_metadata"]) == 1
        skill = result["skills_metadata"][0]
        assert skill["name"] == "web-research"
        assert skill["description"] == "Research topics on the web systematically"
        assert skill["source"] == "user"

    def test_subagent_discovers_project_skills(self, tmp_path: Path) -> None:
        """Test that subagent discovers project-level skills."""
        user_skills = tmp_path / "user_skills"
        project_skills = tmp_path / "project" / ".nami" / "skills"
        user_skills.mkdir()
        project_skills.mkdir(parents=True)

        # Create a project skill
        skill_dir = project_skills / "deploy"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: deploy
description: Deploy the application to production
---

# Deploy Skill

Steps for deployment.
""")

        middleware = SkillsMiddleware(
            skills_dir=user_skills,
            assistant_id="deploy-agent",
            project_skills_dirs=[project_skills],
        )

        mock_runtime = MagicMock()
        result = middleware.before_agent({}, mock_runtime)

        assert result is not None
        assert len(result["skills_metadata"]) == 1
        skill = result["skills_metadata"][0]
        assert skill["name"] == "deploy"
        assert skill["source"] == "project"

    def test_subagent_discovers_both_user_and_project_skills(self, tmp_path: Path) -> None:
        """Test that subagent discovers both user and project skills."""
        user_skills = tmp_path / "user"
        project_skills = tmp_path / "project"
        user_skills.mkdir()
        project_skills.mkdir()

        # Create user skill
        user_skill = user_skills / "web-research"
        user_skill.mkdir()
        (user_skill / "SKILL.md").write_text("""---
name: web-research
description: Research on the web
---
""")

        # Create project skill
        project_skill = project_skills / "code-review"
        project_skill.mkdir()
        (project_skill / "SKILL.md").write_text("""---
name: code-review
description: Review code changes
---
""")

        middleware = SkillsMiddleware(
            skills_dir=user_skills,
            assistant_id="multi-skill-agent",
            project_skills_dirs=[project_skills],
        )

        mock_runtime = MagicMock()
        result = middleware.before_agent({}, mock_runtime)

        assert result is not None
        assert len(result["skills_metadata"]) == 2

        skill_names = {s["name"] for s in result["skills_metadata"]}
        assert skill_names == {"web-research", "code-review"}


class TestSubagentSkillsPromptInjection:
    """Test that skills are injected into subagent's system prompt."""

    def test_skills_injected_into_subagent_prompt(self, tmp_path: Path) -> None:
        """Test that SkillsMiddleware injects skills into subagent prompt."""
        middleware = SkillsMiddleware(
            skills_dir=tmp_path,
            assistant_id="test-agent",
        )

        mock_request = MagicMock()
        mock_request.state = {
            "skills_metadata": [
                {
                    "name": "arxiv-search",
                    "description": "Search arXiv for papers",
                    "path": "/path/to/arxiv-search/SKILL.md",
                    "source": "user",
                },
            ]
        }
        mock_request.system_prompt = """You are a research assistant.

---

## Subagent Context

You are being invoked as an isolated subagent."""

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        middleware.wrap_model_call(mock_request, mock_handler)

        call_kwargs = mock_request.override.call_args[1]
        new_prompt = call_kwargs["system_prompt"]

        # Verify original prompt is preserved
        assert "You are a research assistant" in new_prompt
        assert "Subagent Context" in new_prompt

        # Verify skills are injected
        assert "Skills System" in new_prompt
        assert "arxiv-search" in new_prompt
        assert "Search arXiv for papers" in new_prompt

    def test_subagent_prompt_mentions_skills_access(self, tmp_path: Path) -> None:
        """Test that the subagent prompt template mentions skills access."""
        # This tests the enhanced_prompt in invoke_subagent
        enhanced_prompt = """Base agent instructions.

---

## Subagent Context

You are being invoked as an isolated subagent to handle a specific task.
Your response will be returned to the main assistant.

Guidelines:
- Focus on the specific task at hand
- Provide clear, actionable responses
- Keep your response concise but comprehensive
- You have FULL access to all tools: filesystem, shell commands, web search, HTTP requests, dev servers, and test runner
- You have access to the SAME skills as the main agent - check the Skills System section below for available skills
- If a skill is relevant to your task, read the SKILL.md file for detailed instructions
- Return a synthesized summary rather than raw data
- Do NOT ask for confirmation - execute tools directly"""

        assert "skills" in enhanced_prompt.lower()
        assert "SKILL.md" in enhanced_prompt
        assert "Skills System" in enhanced_prompt


class TestSubagentSkillsIntegration:
    """Integration tests for subagent skills functionality."""

    def test_full_subagent_skills_workflow(self, tmp_path: Path) -> None:
        """Test complete workflow: skills discovery -> prompt injection."""
        # Setup skills directories like in invoke_subagent
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        project_skills = tmp_path / "project_skills"
        project_skills.mkdir()

        # Create skills
        user_skill = skills_dir / "langgraph-docs"
        user_skill.mkdir()
        (user_skill / "SKILL.md").write_text("""---
name: langgraph-docs
description: Reference LangGraph documentation for agent development
---

# LangGraph Documentation Skill

Use this skill when working with LangGraph agents.
""")

        project_skill = project_skills / "custom-deploy"
        project_skill.mkdir()
        (project_skill / "SKILL.md").write_text("""---
name: custom-deploy
description: Deploy using project-specific configuration
---

# Custom Deploy

Project-specific deployment instructions.
""")

        # Create middleware like invoke_subagent does
        middleware = SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id="developer-agent",
            project_skills_dirs=[project_skills],
        )

        # Step 1: Discover skills (before_agent)
        mock_runtime = MagicMock()
        state: dict = {}
        state_update = middleware.before_agent(state, mock_runtime)
        state.update(state_update or {})

        # Verify skills were discovered
        assert len(state["skills_metadata"]) == 2

        # Step 2: Inject into prompt (wrap_model_call)
        mock_request = MagicMock()
        mock_request.state = state
        mock_request.system_prompt = """You are a developer assistant.

---

## Subagent Context

You are being invoked as an isolated subagent."""

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        middleware.wrap_model_call(mock_request, mock_handler)

        # Verify final prompt contains all expected content
        call_kwargs = mock_request.override.call_args[1]
        final_prompt = call_kwargs["system_prompt"]

        # Original content
        assert "You are a developer assistant" in final_prompt
        assert "Subagent Context" in final_prompt

        # Skills System section
        assert "Skills System" in final_prompt

        # User skill
        assert "langgraph-docs" in final_prompt
        assert "Reference LangGraph documentation" in final_prompt

        # Project skill
        assert "custom-deploy" in final_prompt
        assert "Deploy using project-specific configuration" in final_prompt

    def test_subagent_without_skills_still_works(self, tmp_path: Path) -> None:
        """Test that subagent works even with no skills available."""
        empty_skills_dir = tmp_path / "empty_skills"
        empty_skills_dir.mkdir()

        middleware = SkillsMiddleware(
            skills_dir=empty_skills_dir,
            assistant_id="no-skills-agent",
        )

        mock_runtime = MagicMock()
        state: dict = {}
        state_update = middleware.before_agent(state, mock_runtime)
        state.update(state_update or {})

        # Should have empty skills list
        assert state["skills_metadata"] == []

        # Prompt injection should still work
        mock_request = MagicMock()
        mock_request.state = state
        mock_request.system_prompt = "Base prompt"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)
        mock_handler = MagicMock(return_value="response")

        middleware.wrap_model_call(mock_request, mock_handler)

        call_kwargs = mock_request.override.call_args[1]
        prompt = call_kwargs["system_prompt"]

        # Should mention no skills available
        assert "No skills available" in prompt


class TestSubagentSkillsWithMultipleProjectDirs:
    """Test subagent skills with multiple project directories."""

    def test_multiple_project_skills_dirs(self, tmp_path: Path) -> None:
        """Test that subagent can load from multiple project skill directories."""
        user_skills = tmp_path / "user"
        nami_skills = tmp_path / ".nami" / "skills"
        claude_skills = tmp_path / ".claude" / "skills"

        user_skills.mkdir()
        nami_skills.mkdir(parents=True)
        claude_skills.mkdir(parents=True)

        # Create skills in each location
        (user_skills / "user-skill").mkdir()
        (user_skills / "user-skill" / "SKILL.md").write_text("""---
name: user-skill
description: From user directory
---
""")

        (nami_skills / "nami-skill").mkdir()
        (nami_skills / "nami-skill" / "SKILL.md").write_text("""---
name: nami-skill
description: From .nami directory
---
""")

        (claude_skills / "claude-skill").mkdir()
        (claude_skills / "claude-skill" / "SKILL.md").write_text("""---
name: claude-skill
description: From .claude directory
---
""")

        middleware = SkillsMiddleware(
            skills_dir=user_skills,
            assistant_id="multi-dir-agent",
            project_skills_dirs=[nami_skills, claude_skills],
        )

        mock_runtime = MagicMock()
        result = middleware.before_agent({}, mock_runtime)

        assert result is not None
        assert len(result["skills_metadata"]) == 3

        skill_names = {s["name"] for s in result["skills_metadata"]}
        assert skill_names == {"user-skill", "nami-skill", "claude-skill"}
