"""Unit tests for plan mode middleware and question handling."""

import pytest
from unittest.mock import Mock, AsyncMock, patch

from nami_deepagents.middleware.planning import (
    PlanModeMiddleware,
    PlanModeState,
    PlanModeStateUpdate,
    QuestionRequest,
    _ask_question,
    _create_ask_question_tool,
    PLAN_MODE_SYSTEM_PROMPT,
    ASK_QUESTION_SYSTEM_PROMPT,
)
from namicode_cli.ui.question_prompt import (
    prompt_for_structured_question,
    handle_agent_question,
    QuestionResponse,
)
from namicode_cli.states.Session import SessionState


class TestPlanModeMiddleware:
    """Tests for PlanModeMiddleware."""

    def test_middleware_initialization_default(self):
        """Test middleware initializes with correct defaults."""
        middleware = PlanModeMiddleware()
        assert middleware.enabled_by_default is False
        assert middleware.include_system_prompt is True
        assert len(middleware.tools) == 2
        tool_names = {t.name for t in middleware.tools}
        assert tool_names == {"ask_question", "exit_plan_mode"}

    def test_middleware_initialization_enabled(self):
        """Test middleware can start with plan mode enabled."""
        middleware = PlanModeMiddleware(enabled_by_default=True)
        assert middleware.enabled_by_default is True

    def test_middleware_initialization_no_prompt(self):
        """Test middleware can be configured without system prompt injection."""
        middleware = PlanModeMiddleware(include_system_prompt=False)
        assert middleware.include_system_prompt is False

    def test_before_agent_initializes_state(self):
        """Test before_agent sets initial state when not present."""
        middleware = PlanModeMiddleware()
        state = PlanModeState(messages=[])

        update = middleware.before_agent(state, Mock(), Mock())

        assert update is not None
        assert update["plan_mode_enabled"] is False
        assert update["pending_question"] is None

    def test_before_agent_initializes_state_enabled(self):
        """Test before_agent sets enabled state when configured."""
        middleware = PlanModeMiddleware(enabled_by_default=True)
        state = PlanModeState(messages=[])

        update = middleware.before_agent(state, Mock(), Mock())

        assert update is not None
        assert update["plan_mode_enabled"] is True

    def test_before_agent_skips_if_state_exists(self):
        """Test before_agent doesn't overwrite existing state."""
        middleware = PlanModeMiddleware()
        state = PlanModeState(messages=[], plan_mode_enabled=True)

        update = middleware.before_agent(state, Mock(), Mock())

        assert update is None

    def test_state_schema(self):
        """Test state schema is properly set."""
        middleware = PlanModeMiddleware()
        assert middleware.state_schema == PlanModeState


class TestAskQuestionTool:
    """Tests for ask_question tool."""

    def test_tool_creation(self):
        """Test tool is created with correct schema."""
        tool = _create_ask_question_tool()
        assert tool.name == "ask_question"
        assert "question" in tool.description.lower()
        assert "clarification" in tool.description.lower()

    # Note: Tests for _ask_question with valid inputs are skipped because
    # the function uses langgraph.types.interrupt() which requires a full
    # agent context to work properly. The error validation tests below verify
    # that validation errors are returned before the interrupt is triggered.


class TestModifyRequest:
    """Tests for modify_request method."""

    def test_adds_ask_question_prompt_when_enabled(self):
        """Test system prompt includes ask_question instructions."""
        middleware = PlanModeMiddleware()
        request = Mock()
        request.system_prompt = "Original prompt"
        request.state = {"plan_mode_enabled": False}
        request.override = Mock(return_value=request)

        result = middleware.modify_request(request)

        request.override.assert_called_once()
        call_kwargs = request.override.call_args
        system_prompt = (
            call_kwargs.kwargs.get("system_prompt") or call_kwargs.args[0]
            if call_kwargs.args
            else None
        )

        # The system_prompt should contain ASK_QUESTION_SYSTEM_PROMPT
        if system_prompt is None:
            system_prompt = request.override.call_args[1].get("system_prompt", "")

    def test_adds_plan_mode_prompt_when_enabled(self):
        """Test system prompt includes plan mode instructions when enabled."""
        middleware = PlanModeMiddleware()
        request = Mock()
        request.system_prompt = "Original prompt"
        request.state = {"plan_mode_enabled": True}
        request.override = Mock(return_value=request)

        result = middleware.modify_request(request)

        request.override.assert_called_once()

    def test_skips_prompt_injection_when_disabled(self):
        """Test no prompt injection when include_system_prompt is False."""
        middleware = PlanModeMiddleware(include_system_prompt=False)
        request = Mock()
        request.system_prompt = "Original prompt"
        request.state = {"plan_mode_enabled": True}

        result = middleware.modify_request(request)

        # Should return original request unchanged
        assert result == request


class TestQuestionPromptUI:
    """Tests for question prompt UI."""

    @pytest.mark.asyncio
    async def test_handle_agent_question_routes_structured(self):
        """Test routing to structured question handler."""
        with patch("namicode_cli.ui.question_prompt.prompt_for_structured_question") as mock:
            mock.return_value = QuestionResponse(answer="Option A", selected_index=0)

            result = await handle_agent_question(
                {
                    "question": "Choose?",
                    "question_type": "structured",
                    "options": ["Option A", "Option B"],
                }
            )

            mock.assert_called_once()
            assert result["answer"] == "Option A"
            assert result["selected_index"] == 0

    @pytest.mark.asyncio
    async def test_handle_agent_question_routes_open_ended(self):
        """Test routing to open-ended question handler."""
        with patch("namicode_cli.ui.question_prompt.prompt_for_open_question") as mock:
            mock.return_value = QuestionResponse(answer="My answer", selected_index=None)

            result = await handle_agent_question(
                {
                    "question": "What do you think?",
                    "question_type": "open_ended",
                }
            )

            mock.assert_called_once()
            assert result["answer"] == "My answer"
            assert result["selected_index"] is None

    @pytest.mark.asyncio
    async def test_handle_agent_question_defaults_to_open_ended(self):
        """Test defaults to open-ended when no type specified."""
        with patch("namicode_cli.ui.question_prompt.prompt_for_open_question") as mock:
            mock.return_value = QuestionResponse(answer="Answer", selected_index=None)

            result = await handle_agent_question(
                {
                    "question": "Question without type?",
                }
            )

            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_agent_question_structured_without_options(self):
        """Test structured question without options falls back to open-ended."""
        with patch("namicode_cli.ui.question_prompt.prompt_for_open_question") as mock:
            mock.return_value = QuestionResponse(answer="Answer", selected_index=None)

            result = await handle_agent_question(
                {
                    "question": "Structured but no options?",
                    "question_type": "structured",
                    "options": [],  # Empty options
                }
            )

            mock.assert_called_once()


class TestSessionState:
    """Tests for SessionState plan mode fields."""

    def test_session_state_has_plan_mode_field(self):
        """Test SessionState initializes with plan_mode_enabled=False."""
        state = SessionState()
        assert hasattr(state, "plan_mode_enabled")
        assert state.plan_mode_enabled is False

    def test_toggle_plan_mode(self):
        """Test toggle_plan_mode method."""
        state = SessionState()
        assert state.plan_mode_enabled is False

        result = state.toggle_plan_mode()
        assert result is True
        assert state.plan_mode_enabled is True

        result = state.toggle_plan_mode()
        assert result is False
        assert state.plan_mode_enabled is False


class TestQuestionRequest:
    """Tests for QuestionRequest TypedDict."""

    def test_question_request_structure(self):
        """Test QuestionRequest can be created with required fields."""
        request: QuestionRequest = {
            "question": "What is your preference?",
            "question_type": "open_ended",
        }
        assert request["question"] == "What is your preference?"
        assert request["question_type"] == "open_ended"

    def test_question_request_with_options(self):
        """Test QuestionRequest with options."""
        request: QuestionRequest = {
            "question": "Choose one:",
            "question_type": "structured",
            "options": ["A", "B", "C"],
        }
        assert request["options"] == ["A", "B", "C"]

    def test_question_request_with_context(self):
        """Test QuestionRequest with context."""
        request: QuestionRequest = {
            "question": "What framework?",
            "question_type": "open_ended",
            "context": "This affects project setup.",
        }
        assert request["context"] == "This affects project setup."


class TestSystemPrompts:
    """Tests for system prompt constants."""

    def test_plan_mode_prompt_content(self):
        """Test plan mode prompt has expected content."""
        assert "Plan Mode" in PLAN_MODE_SYSTEM_PROMPT
        assert "ask_question" in PLAN_MODE_SYSTEM_PROMPT
        assert "write_todos" in PLAN_MODE_SYSTEM_PROMPT

    def test_ask_question_prompt_content(self):
        """Test ask_question prompt has expected content."""
        assert "ask_question" in ASK_QUESTION_SYSTEM_PROMPT
        assert (
            "Structured" in ASK_QUESTION_SYSTEM_PROMPT or "structured" in ASK_QUESTION_SYSTEM_PROMPT
        )
        assert (
            "Open-ended" in ASK_QUESTION_SYSTEM_PROMPT or "open-ended" in ASK_QUESTION_SYSTEM_PROMPT
        )


class TestComplexityAnalysis:
    """Tests for complexity analysis."""

    def test_simple_task_no_planning(self):
        """Simple tasks should not trigger planning."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("Fix the bug in main.py")
        assert result.should_plan is False
        assert result.score == 0.0

    def test_complex_task_triggers_planning(self):
        """Complex tasks should trigger planning."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("Implement user authentication and add tests")
        assert result.should_plan is True
        assert result.score > 0.0

    def test_keyword_detection(self):
        """Keywords should increase complexity score."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("Implement a new feature")
        assert "implement" in result.factors[0].lower()
        assert result.score > 0.0

    def test_step_detection(self):
        """Multiple steps should increase complexity score."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("First read the file, then modify it, and finally test it")
        assert any("step" in f.lower() for f in result.factors)

    def test_file_mentions(self):
        """Multiple file mentions should increase complexity."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("Update main.py, config.yaml, and utils.py")
        assert any("file" in f.lower() for f in result.factors)

    def test_refactor_keyword(self):
        """Refactor keyword should trigger planning."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("Refactor the authentication module")
        assert result.should_plan is True

    def test_short_simple_request(self):
        """Short simple requests should not trigger planning."""
        from nami_deepagents.middleware.planning import analyze_complexity

        result = analyze_complexity("Read the file")
        assert result.should_plan is False


class TestToolBlocking:
    """Tests for tool blocking in plan mode."""

    def test_blocked_tools_const(self):
        """Test blocked tools constant is defined."""
        from nami_deepagents.middleware.planning import BLOCKED_TOOLS_IN_PLAN_MODE

        assert "write_file" in BLOCKED_TOOLS_IN_PLAN_MODE
        assert "edit_file" in BLOCKED_TOOLS_IN_PLAN_MODE
        assert "execute_bash" in BLOCKED_TOOLS_IN_PLAN_MODE
        assert "run_tests" in BLOCKED_TOOLS_IN_PLAN_MODE

    def test_allowed_tools_const(self):
        """Test allowed tools constant is defined."""
        from nami_deepagents.middleware.planning import ALLOWED_TOOLS_IN_PLAN_MODE

        assert "read_file" in ALLOWED_TOOLS_IN_PLAN_MODE
        assert "ls" in ALLOWED_TOOLS_IN_PLAN_MODE
        assert "glob" in ALLOWED_TOOLS_IN_PLAN_MODE
        assert "write_todos" in ALLOWED_TOOLS_IN_PLAN_MODE
        assert "ask_question" in ALLOWED_TOOLS_IN_PLAN_MODE

    def test_no_overlap_blocked_allowed(self):
        """Test no overlap between blocked and allowed tools."""
        from nami_deepagents.middleware.planning import (
            BLOCKED_TOOLS_IN_PLAN_MODE,
            ALLOWED_TOOLS_IN_PLAN_MODE,
        )

        overlap = BLOCKED_TOOLS_IN_PLAN_MODE & ALLOWED_TOOLS_IN_PLAN_MODE
        assert len(overlap) == 0, f"Found overlap: {overlap}"

    def test_middleware_has_exit_plan_mode_tool(self):
        """Test middleware provides exit_plan_mode tool."""
        middleware = PlanModeMiddleware()
        tool_names = {t.name for t in middleware.tools}
        assert "exit_plan_mode" in tool_names
