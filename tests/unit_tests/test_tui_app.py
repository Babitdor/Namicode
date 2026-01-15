"""Unit tests for TUI application components.

Tests for the Textual-based TUI including:
- NamiCodeApp initialization and command handling
- StatusBar widget plan mode indicator
- Session management integration
- Subagent invocation routing
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from namicode_cli.states.Session import SessionState


class TestStatusBarPlanMode:
    """Tests for StatusBar plan mode indicator."""

    def test_status_bar_initialization(self):
        """Test StatusBar initializes with plan_mode=False."""
        from namicode_cli.widgets.status import StatusBar

        status_bar = StatusBar()
        assert status_bar.plan_mode is False

    def test_set_plan_mode_enabled(self):
        """Test setting plan mode to enabled."""
        from namicode_cli.widgets.status import StatusBar

        status_bar = StatusBar()
        status_bar.set_plan_mode(enabled=True)
        assert status_bar.plan_mode is True

    def test_set_plan_mode_disabled(self):
        """Test setting plan mode to disabled."""
        from namicode_cli.widgets.status import StatusBar

        status_bar = StatusBar()
        status_bar.set_plan_mode(enabled=True)
        status_bar.set_plan_mode(enabled=False)
        assert status_bar.plan_mode is False

    def test_status_bar_auto_approve_toggle(self):
        """Test auto-approve toggle in status bar."""
        from namicode_cli.widgets.status import StatusBar

        status_bar = StatusBar()
        assert status_bar.auto_approve is False

        status_bar.set_auto_approve(enabled=True)
        assert status_bar.auto_approve is True

        status_bar.set_auto_approve(enabled=False)
        assert status_bar.auto_approve is False

    def test_status_bar_mode_setting(self):
        """Test mode setting in status bar."""
        from namicode_cli.widgets.status import StatusBar

        status_bar = StatusBar()
        assert status_bar.mode == "normal"

        status_bar.set_mode("bash")
        assert status_bar.mode == "bash"

        status_bar.set_mode("command")
        assert status_bar.mode == "command"

    def test_status_bar_token_setting(self):
        """Test token count setting in status bar."""
        from namicode_cli.widgets.status import StatusBar

        status_bar = StatusBar()
        assert status_bar.tokens == 0

        status_bar.set_tokens(1000)
        assert status_bar.tokens == 1000

        status_bar.set_tokens(50000)
        assert status_bar.tokens == 50000


class TestSessionStatePlanMode:
    """Tests for SessionState plan mode integration."""

    def test_session_state_has_plan_mode_field(self):
        """Test SessionState initializes with plan_mode_enabled=False."""
        state = SessionState()
        assert hasattr(state, "plan_mode_enabled")
        assert state.plan_mode_enabled is False

    def test_session_state_toggle_plan_mode(self):
        """Test toggle_plan_mode method."""
        state = SessionState()
        assert state.plan_mode_enabled is False

        result = state.toggle_plan_mode()
        assert result is True
        assert state.plan_mode_enabled is True

        result = state.toggle_plan_mode()
        assert result is False
        assert state.plan_mode_enabled is False


class TestTUICommandParsing:
    """Tests for TUI command parsing logic."""

    def test_parse_command_slash(self):
        """Test parsing slash commands."""
        test_cases = [
            ("/help", "help", ""),
            ("/plan", "plan", ""),
            ("/plan on", "plan", "on"),
            ("/model gpt-4", "model", "gpt-4"),
            ("/init", "init", ""),
        ]

        for user_input, expected_cmd, expected_args in test_cases:
            stripped = user_input.strip()
            if stripped.startswith("/"):
                parts = stripped[1:].split(maxsplit=1)
                cmd = parts[0] if parts else ""
                args = parts[1] if len(parts) > 1 else ""
                assert cmd == expected_cmd, f"Failed for input: {user_input}"
                assert args == expected_args, f"Failed for input: {user_input}"

    def test_parse_agent_mention(self):
        """Test parsing @agent mentions."""
        from namicode_cli.input import parse_agent_mentions

        result = parse_agent_mentions("@code-reviewer review this code")
        assert result is not None
        agent_name, query = result
        assert agent_name == "code-reviewer"
        assert query == "review this code"

    def test_parse_agent_mention_no_match(self):
        """Test that non-mentions return tuple with None agent."""
        from namicode_cli.input import parse_agent_mentions

        result = parse_agent_mentions("hello world")
        # When no @agent mention, returns (None, original_input)
        assert result == (None, "hello world")

    def test_parse_bash_command(self):
        """Test parsing !bash commands."""
        user_input = "!ls -la"
        if user_input.startswith("!"):
            bash_cmd = user_input[1:].strip()
            assert bash_cmd == "ls -la"


class TestTokenTracker:
    """Tests for TokenTracker from ui_elements."""

    def test_token_tracker_initialization(self):
        """Test TokenTracker initializes correctly."""
        from namicode_cli.ui.ui_elements import TokenTracker

        tracker = TokenTracker()
        # Check that baseline_context is initialized
        assert hasattr(tracker, "baseline_context")
        assert tracker.baseline_context == 0
        assert tracker.current_context == 0

    def test_token_tracker_set_baseline(self):
        """Test setting baseline tokens."""
        from namicode_cli.ui.ui_elements import TokenTracker

        tracker = TokenTracker()
        tracker.set_baseline(1000)
        assert tracker.baseline_context == 1000
        assert tracker.current_context == 1000

    def test_token_tracker_set_model(self):
        """Test setting model name."""
        from namicode_cli.ui.ui_elements import TokenTracker

        tracker = TokenTracker()
        tracker.set_model("gpt-4")
        assert tracker.model_name == "gpt-4"

    def test_token_tracker_add_tokens(self):
        """Test adding tokens updates current context."""
        from namicode_cli.ui.ui_elements import TokenTracker

        tracker = TokenTracker()
        tracker.set_baseline(1000)
        # add() sets current_context to input_tokens (the new context size)
        tracker.add(input_tokens=1500, output_tokens=200)
        assert tracker.current_context == 1500
        assert tracker.last_output == 200


class TestAppImports:
    """Tests for TUI app imports and dependencies."""

    def test_namicode_app_import(self):
        """Test that NamiCodeApp can be imported."""
        from namicode_cli.app import NamiCodeApp

        assert NamiCodeApp is not None

    def test_run_textual_app_import(self):
        """Test that run_textual_app can be imported."""
        from namicode_cli.app import run_textual_app

        assert run_textual_app is not None

    def test_status_bar_import(self):
        """Test that StatusBar can be imported."""
        from namicode_cli.widgets.status import StatusBar

        assert StatusBar is not None

    def test_chat_input_import(self):
        """Test that ChatInput can be imported."""
        from namicode_cli.widgets.chat_input import ChatInput

        assert ChatInput is not None

    def test_message_widgets_import(self):
        """Test that message widgets can be imported."""
        from namicode_cli.widgets.messages import (
            UserMessage,
            AssistantMessage,
            ToolCallMessage,
            SystemMessage,
        )

        assert UserMessage is not None
        assert AssistantMessage is not None
        assert ToolCallMessage is not None
        assert SystemMessage is not None


class TestMainTUIFunction:
    """Tests for main_tui entry point function."""

    def test_main_tui_import(self):
        """Test that main_tui can be imported."""
        from namicode_cli.main import main_tui

        assert main_tui is not None
        # Verify it's an async function
        import inspect

        assert inspect.iscoroutinefunction(main_tui)

    def test_main_tui_signature(self):
        """Test main_tui has correct parameters."""
        from namicode_cli.main import main_tui
        import inspect

        sig = inspect.signature(main_tui)
        params = list(sig.parameters.keys())

        expected_params = [
            "assistant_id",
            "session_state",
            "sandbox_type",
            "sandbox_id",
            "setup_script_path",
            "continue_session",
        ]
        assert params == expected_params


class TestCommandHandlerStubs:
    """Tests for TUI command handler stubs (verify they exist in NamiCodeApp)."""

    def test_namicode_app_has_command_handlers(self):
        """Test NamiCodeApp has required command handler methods."""
        from namicode_cli.app import NamiCodeApp

        # Get the class methods
        methods = dir(NamiCodeApp)

        expected_handlers = [
            "_show_help",
            "_handle_context_command",
            "_handle_plan_command",
            "_handle_sessions_command",
            "_handle_save_command",
            "_handle_init_command",
            "_handle_skills_command",
            "_handle_agents_command",
            "_handle_servers_command",
            "_handle_tests_command",
            "_handle_kill_command",
            "_handle_compact_command",
            "_handle_trace_command",
        ]

        for handler in expected_handlers:
            assert handler in methods, f"Missing handler: {handler}"

    def test_namicode_app_has_subagent_support(self):
        """Test NamiCodeApp has subagent invocation method."""
        from namicode_cli.app import NamiCodeApp

        methods = dir(NamiCodeApp)
        assert "_invoke_subagent" in methods

    def test_namicode_app_has_session_management(self):
        """Test NamiCodeApp has session management methods."""
        from namicode_cli.app import NamiCodeApp

        methods = dir(NamiCodeApp)
        assert "_save_session" in methods
        assert "_maybe_auto_save" in methods
        assert "_save_session_on_exit" in methods


class TestWidgetComponents:
    """Tests for TUI widget components."""

    def test_chat_input_class_exists(self):
        """Test ChatInput class exists and has expected structure."""
        from namicode_cli.widgets.chat_input import ChatInput

        # Verify ChatInput is a valid class
        assert ChatInput is not None
        # Verify it has BINDINGS as a ClassVar
        assert hasattr(ChatInput, "BINDINGS")

    def test_approval_menu_import(self):
        """Test ApprovalMenu can be imported."""
        from namicode_cli.widgets.approval import ApprovalMenu

        assert ApprovalMenu is not None

    def test_confirmation_modal_import(self):
        """Test ConfirmationModal can be imported."""
        from namicode_cli.widgets.confirmation import ConfirmationModal

        assert ConfirmationModal is not None


class TestAutoSaveConfiguration:
    """Tests for auto-save configuration in TUI."""

    def test_auto_save_constants_in_app(self):
        """Test auto-save constants are defined in app module."""
        from namicode_cli.app import (
            AUTO_SAVE_INTERVAL_SECONDS,
            AUTO_SAVE_MESSAGE_THRESHOLD,
        )

        assert AUTO_SAVE_INTERVAL_SECONDS == 300
        assert AUTO_SAVE_MESSAGE_THRESHOLD == 5

    def test_auto_save_constants_in_main(self):
        """Test auto-save constants are defined in main module."""
        from namicode_cli.main import (
            AUTO_SAVE_INTERVAL_SECONDS,
            AUTO_SAVE_MESSAGE_THRESHOLD,
        )

        assert AUTO_SAVE_INTERVAL_SECONDS == 300
        assert AUTO_SAVE_MESSAGE_THRESHOLD == 5
