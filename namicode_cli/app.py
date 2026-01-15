"""Textual UI application for Nami-Code.

This is the main TUI application that provides a full-featured terminal interface
for Nami-Code, matching all functionality from the CLI REPL.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches
from textual.events import MouseUp  # noqa: TC002 - used in type annotation
from textual.widgets import Static  # noqa: TC002 - used at runtime

from namicode_cli.clipboard import copy_selection_to_clipboard
from namicode_cli.textual_adapter import TextualUIAdapter, execute_task_textual
from namicode_cli.widgets.approval import ApprovalMenu
from namicode_cli.widgets.chat_input import ChatInput
from namicode_cli.widgets.loading import LoadingWidget
from namicode_cli.widgets.messages import (
    AssistantMessage,
    ErrorMessage,
    SystemMessage,
    ToolCallMessage,
    UserMessage,
)
from namicode_cli.widgets.status import StatusBar
from namicode_cli.widgets.welcome import WelcomeBanner
from namicode_cli.config.config import Settings
from namicode_cli.states.Session import SessionState
from namicode_cli.input import ImageTracker, parse_agent_mentions

if TYPE_CHECKING:
    from langgraph.pregel import Pregel
    from langgraph.store.memory import InMemoryStore
    from langgraph.checkpoint.memory import InMemorySaver
    from textual.app import ComposeResult
    from textual.worker import Worker


# Auto-save configuration (matching main.py)
AUTO_SAVE_INTERVAL_SECONDS = 300  # Save session every 5 minutes
AUTO_SAVE_MESSAGE_THRESHOLD = 5  # Save after every N new messages


class TextualTokenTracker:
    """Token tracker that updates the status bar."""

    def __init__(self, update_callback: callable) -> None:
        """Initialize with a callback to update the display."""
        self._update_callback = update_callback
        self.current_context = 0
        self._baseline = 0
        self._model_name: str | None = None

    def add(self, input_tokens: int, output_tokens: int) -> None:  # noqa: ARG002
        """Update token count from a response."""
        self.current_context = input_tokens
        self._update_callback(input_tokens)

    def reset(self) -> None:
        """Reset token count."""
        self.current_context = 0
        self._update_callback(0)

    def set_baseline(self, tokens: int) -> None:
        """Set baseline token count."""
        self._baseline = tokens

    def set_model(self, model_name: str) -> None:
        """Set model name for context window calculation."""
        self._model_name = model_name


class NamiCodeApp(App):
    """Main Textual application for Nami-Code."""

    TITLE = "Nami-Code"
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False

    # Slow down scroll speed (default is 3 lines per scroll event)
    # Using 0.25 to require 4 scroll events per line - very smooth
    SCROLL_SENSITIVITY_Y = 0.25

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "interrupt", "Interrupt", show=False, priority=True),
        Binding("ctrl+c", "quit_or_interrupt", "Quit/Interrupt", show=False),
        Binding("ctrl+d", "quit_app", "Quit", show=False, priority=True),
        Binding("ctrl+t", "toggle_auto_approve", "Toggle Auto-Approve", show=False),
        Binding(
            "shift+tab", "toggle_auto_approve", "Toggle Auto-Approve", show=False, priority=True
        ),
        Binding("ctrl+o", "toggle_tool_output", "Toggle Tool Output", show=False),
        # Approval menu keys (handled at App level for reliability)
        Binding("up", "approval_up", "Up", show=False),
        Binding("k", "approval_up", "Up", show=False),
        Binding("down", "approval_down", "Down", show=False),
        Binding("j", "approval_down", "Down", show=False),
        Binding("enter", "approval_select", "Select", show=False),
        Binding("y", "approval_yes", "Yes", show=False),
        Binding("1", "approval_yes", "Yes", show=False),
        Binding("n", "approval_no", "No", show=False),
        Binding("2", "approval_no", "No", show=False),
        Binding("a", "approval_auto", "Auto", show=False),
        Binding("3", "approval_auto", "Auto", show=False),
    ]

    def __init__(
        self,
        *,
        agent: Pregel | None = None,
        assistant_id: str | None = None,
        backend: Any = None,  # noqa: ANN401  # CompositeBackend
        auto_approve: bool = False,
        cwd: str | Path | None = None,
        thread_id: str | None = None,
        session_state: SessionState | None = None,
        session_manager: Any = None,
        store: InMemoryStore | None = None,
        checkpointer: InMemorySaver | None = None,
        model_name: str | None = None,
        settings: Settings | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Nami-Code application.

        Args:
            agent: Pre-configured LangGraph agent
            assistant_id: Agent identifier for memory storage
            backend: Backend for file operations
            auto_approve: Whether to start with auto-approve enabled
            cwd: Current working directory to display
            thread_id: Optional thread ID for session persistence
            session_state: Session state instance
            session_manager: SessionManager for persistence
            store: InMemoryStore for shared memory
            checkpointer: InMemorySaver for state persistence
            model_name: Name of the model being used
            settings: Settings instance
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._agent = agent
        self._assistant_id = assistant_id
        self._backend = backend
        self._auto_approve = auto_approve
        self._cwd = str(cwd) if cwd else str(Path.cwd())
        # Avoid collision with App._thread_id
        self._lc_thread_id = thread_id
        self._session_manager = session_manager
        self._store = store
        self._checkpointer = checkpointer
        self._model_name = model_name
        self._settings = settings or Settings.from_environment()

        # Initialize session state if not provided
        if session_state:
            self._session_state = session_state
        else:
            self._session_state = SessionState(auto_approve=auto_approve)
            if thread_id:
                self._session_state.thread_id = thread_id

        # UI state
        self._status_bar: StatusBar | None = None
        self._chat_input: ChatInput | None = None
        self._quit_pending = False
        self._ui_adapter: TextualUIAdapter | None = None
        self._pending_approval: asyncio.Future | None = None
        self._pending_approval_widget: Any = None
        # Agent task tracking for interruption
        self._agent_worker: Worker[None] | None = None
        self._agent_running = False
        self._loading_widget: LoadingWidget | None = None
        self._token_tracker: TextualTokenTracker | None = None
        self._image_tracker = ImageTracker()

        # Auto-save state
        self._last_save_time = time.time()
        self._messages_since_save = 0

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        # Main chat area with scrollable messages
        with VerticalScroll(id="chat"):
            yield WelcomeBanner(id="welcome-banner")
            yield Container(id="messages")  # Container can have children mounted

        # Bottom app container - holds either ChatInput OR ApprovalMenu (swapped)
        # This is OUTSIDE VerticalScroll so arrow keys work in approval
        with Container(id="bottom-app-container"):
            yield ChatInput(cwd=self._cwd, id="input-area")

        # Status bar at bottom
        yield StatusBar(cwd=self._cwd, id="status-bar")

    async def on_mount(self) -> None:
        """Initialize components after mount."""
        self._status_bar = self.query_one("#status-bar", StatusBar)
        self._chat_input = self.query_one("#input-area", ChatInput)

        # Set initial auto-approve state
        if self._auto_approve:
            self._status_bar.set_auto_approve(enabled=True)

        # Set plan mode indicator if enabled
        if self._session_state and self._session_state.plan_mode_enabled:
            self._status_bar.set_plan_mode(enabled=True)

        # Create token tracker that updates status bar
        self._token_tracker = TextualTokenTracker(self._update_tokens)
        if self._model_name:
            self._token_tracker.set_model(self._model_name)

        # Create UI adapter if agent is provided
        if self._agent:
            self._ui_adapter = TextualUIAdapter(
                mount_message=self._mount_message,
                update_status=self._update_status,
                request_approval=self._request_approval,
                on_auto_approve_enabled=self._on_auto_approve_enabled,
                scroll_to_bottom=self._scroll_chat_to_bottom,
            )
            self._ui_adapter.set_token_tracker(self._token_tracker)

        # Focus the input (autocomplete is now built into ChatInput)
        self._chat_input.focus_input()

    def _update_status(self, message: str) -> None:
        """Update the status bar with a message."""
        if self._status_bar:
            self._status_bar.set_status_message(message)

    def _update_tokens(self, count: int) -> None:
        """Update the token count in status bar."""
        if self._status_bar:
            self._status_bar.set_tokens(count)

    def _scroll_chat_to_bottom(self) -> None:
        """Scroll the chat area to the bottom.

        Uses anchor() for smoother streaming - keeps scroll locked to bottom
        as new content is added without causing visual jumps.
        """
        try:
            chat = self.query_one("#chat", VerticalScroll)
            # anchor() locks scroll to bottom and auto-scrolls as content grows
            # Much smoother than calling scroll_end() on every chunk
            chat.anchor()
        except NoMatches:
            pass

    async def _request_approval(
        self,
        action_request: Any,  # noqa: ANN401
        assistant_id: str | None,
    ) -> asyncio.Future:
        """Request user approval inline in the messages area.

        Returns a Future that resolves to the user's decision.
        Mounts ApprovalMenu in the messages area (inline with chat).
        ChatInput stays visible - user can still see it.

        If another approval is already pending, queue this one.
        """
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future = loop.create_future()

        # If there's already a pending approval, wait for it to complete first
        if self._pending_approval_widget is not None:
            while self._pending_approval_widget is not None:  # noqa: ASYNC110
                await asyncio.sleep(0.1)

        # Create menu with unique ID to avoid conflicts
        unique_id = f"approval-menu-{uuid.uuid4().hex[:8]}"
        menu = ApprovalMenu(action_request, assistant_id, id=unique_id)
        menu.set_future(result_future)

        # Store reference
        self._pending_approval_widget = menu

        # Pause the loading spinner during approval
        if self._loading_widget:
            self._loading_widget.pause("Awaiting decision")

        # Update status to show we're waiting for approval
        self._update_status("Waiting for approval...")

        # Mount approval inline in messages area (not replacing ChatInput)
        try:
            messages = self.query_one("#messages", Container)
            await messages.mount(menu)
            self._scroll_chat_to_bottom()
            # Focus approval menu
            self.call_after_refresh(menu.focus)
        except Exception as e:  # noqa: BLE001
            self._pending_approval_widget = None
            if not result_future.done():
                result_future.set_exception(e)

        return result_future

    def _on_auto_approve_enabled(self) -> None:
        """Callback when auto-approve mode is enabled via HITL."""
        self._auto_approve = True
        if self._status_bar:
            self._status_bar.set_auto_approve(enabled=True)
        if self._session_state:
            self._session_state.auto_approve = True

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle submitted input from ChatInput widget."""
        value = event.value
        mode = event.mode

        # Reset quit pending state on any input
        self._quit_pending = False

        # Handle different modes
        if mode == "bash":
            # Bash command - strip the ! prefix
            await self._handle_bash_command(value.removeprefix("!"))
        elif mode == "command":
            # Slash command
            await self._handle_command(value)
        else:
            # Normal message - will be sent to agent
            await self._handle_user_message(value)

    def on_chat_input_mode_changed(self, event: ChatInput.ModeChanged) -> None:
        """Update status bar when input mode changes."""
        if self._status_bar:
            self._status_bar.set_mode(event.mode)

    async def on_approval_menu_decided(
        self,
        event: Any,  # noqa: ANN401, ARG002
    ) -> None:
        """Handle approval menu decision - remove from messages and refocus input."""
        # Remove ApprovalMenu using stored reference
        if self._pending_approval_widget:
            await self._pending_approval_widget.remove()
            self._pending_approval_widget = None

        # Resume the loading spinner after approval
        if self._loading_widget:
            self._loading_widget.resume()

        # Clear status message
        self._update_status("")

        # Refocus the chat input
        if self._chat_input:
            self.call_after_refresh(self._chat_input.focus_input)

    async def _handle_bash_command(self, command: str) -> None:
        """Handle a bash command (! prefix).

        Args:
            command: The bash command to execute
        """
        # Mount user message showing the bash command
        await self._mount_message(UserMessage(f"!{command}"))

        # Execute the bash command (shell=True is intentional for user-requested bash)
        try:
            result = await asyncio.to_thread(  # noqa: S604
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=60,
            )
            output = result.stdout.strip()
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr.strip()}"

            if output:
                # Display output as assistant message (uses markdown for code blocks)
                msg = AssistantMessage(f"```\n{output}\n```")
                await self._mount_message(msg)
                await msg.write_initial_content()
            else:
                await self._mount_message(SystemMessage("Command completed (no output)"))

            if result.returncode != 0:
                await self._mount_message(ErrorMessage(f"Exit code: {result.returncode}"))

            # Scroll to show the output
            self._scroll_chat_to_bottom()

        except subprocess.TimeoutExpired:
            await self._mount_message(ErrorMessage("Command timed out (60s limit)"))
        except OSError as e:
            await self._mount_message(ErrorMessage(str(e)))

    async def _handle_command(self, command: str) -> None:
        """Handle a slash command.

        Args:
            command: The slash command (including /)
        """
        # Parse command and arguments
        cmd_parts = command.strip().lstrip("/").split(maxsplit=1)
        cmd = cmd_parts[0].lower()
        cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else None

        if cmd in ("quit", "exit", "q"):
            await self._save_session_on_exit()
            self.exit()
            return

        if cmd == "help":
            await self._mount_message(UserMessage(command))
            await self._show_help()
            return

        if cmd == "clear":
            from langgraph.checkpoint.memory import InMemorySaver
            # Reset agent checkpointer if available
            if self._agent and hasattr(self._agent, 'checkpointer'):
                self._agent.checkpointer = InMemorySaver()
            await self._clear_messages()
            # Reset thread to start fresh conversation
            if self._session_state:
                self._session_state.thread_id = uuid.uuid4().hex[:8]
            if self._token_tracker:
                self._token_tracker.reset()
            await self._mount_message(SystemMessage(f"Fresh start! Conversation reset."))
            return

        if cmd in ("threads", "sessions"):
            await self._mount_message(UserMessage(command))
            await self._handle_sessions_command()
            return

        if cmd == "tokens":
            await self._mount_message(UserMessage(command))
            if self._token_tracker and self._token_tracker.current_context > 0:
                count = self._token_tracker.current_context
                if count >= 1000:
                    formatted = f"{count / 1000:.1f}K"
                else:
                    formatted = str(count)
                await self._mount_message(SystemMessage(f"Current context: {formatted} tokens"))
            else:
                await self._mount_message(SystemMessage("No token usage yet"))
            return

        if cmd == "context":
            await self._mount_message(UserMessage(command))
            await self._handle_context_command()
            return

        if cmd == "plan":
            await self._mount_message(UserMessage(command))
            await self._handle_plan_command(cmd_args)
            return

        if cmd == "save":
            await self._mount_message(UserMessage(command))
            await self._handle_save_command()
            return

        if cmd == "init":
            await self._mount_message(UserMessage(command))
            await self._handle_init_command()
            return

        if cmd == "mcp":
            await self._mount_message(UserMessage(command))
            await self._mount_message(SystemMessage("MCP management: Use the CLI for full MCP configuration (`nami` then `/mcp`)"))
            return

        if cmd == "model":
            await self._mount_message(UserMessage(command))
            await self._mount_message(SystemMessage("Model management: Use the CLI for model switching (`nami` then `/model`)"))
            return

        if cmd == "skills":
            await self._mount_message(UserMessage(command))
            await self._handle_skills_command(cmd_args)
            return

        if cmd == "agents":
            await self._mount_message(UserMessage(command))
            await self._handle_agents_command(cmd_args)
            return

        if cmd == "servers":
            await self._mount_message(UserMessage(command))
            await self._handle_servers_command()
            return

        if cmd == "tests":
            await self._mount_message(UserMessage(command))
            await self._handle_tests_command(cmd_args)
            return

        if cmd == "kill":
            await self._mount_message(UserMessage(command))
            await self._handle_kill_command(cmd_args)
            return

        if cmd == "compact":
            await self._mount_message(UserMessage(command))
            await self._handle_compact_command(cmd_args)
            return

        if cmd == "trace":
            await self._mount_message(UserMessage(command))
            await self._handle_trace_command(cmd_args)
            return

        # Unknown command
        await self._mount_message(UserMessage(command))
        await self._mount_message(SystemMessage(f"Unknown command: /{cmd}. Type /help for available commands."))

    async def _handle_user_message(self, message: str) -> None:
        """Handle a user message to send to the agent.

        Args:
            message: The user's message
        """
        # Check for @agent mentions
        agent_name, query = parse_agent_mentions(message, self._settings)

        if agent_name and self._store and self._checkpointer:
            # Handle subagent invocation
            await self._mount_message(UserMessage(message))
            await self._invoke_subagent(agent_name, query)
            return

        # Mount the user message
        await self._mount_message(UserMessage(message))

        # Check if agent is available
        if self._agent and self._ui_adapter and self._session_state:
            # Show loading widget
            self._loading_widget = LoadingWidget("Thinking")
            await self._mount_message(self._loading_widget)
            self._agent_running = True

            # Disable cursor blink while agent is working
            if self._chat_input:
                self._chat_input.set_cursor_active(active=False)

            # Use run_worker to avoid blocking the main event loop
            # This allows the UI to remain responsive during agent execution
            self._agent_worker = self.run_worker(
                self._run_agent_task(message),
                exclusive=False,
            )
        else:
            await self._mount_message(
                SystemMessage("Agent not configured. Run with --agent flag or use standalone mode.")
            )

    async def _invoke_subagent(self, agent_name: str, query: str) -> None:
        """Invoke a named subagent.

        Args:
            agent_name: Name of the agent to invoke
            query: The query to send to the agent
        """
        from namicode_cli.agents.named_agents import create_subagent
        from namicode_cli.config.model_create import create_model

        try:
            subagent, _ = create_subagent(
                agent_name,
                model=create_model(),
                tools=[],
                settings=self._settings,
                store=self._store,
                checkpointer=self._checkpointer,
            )

            self._loading_widget = LoadingWidget(f"@{agent_name} thinking")
            await self._mount_message(self._loading_widget)
            self._agent_running = True

            if self._chat_input:
                self._chat_input.set_cursor_active(active=False)

            self._agent_worker = self.run_worker(
                self._run_subagent_task(query, subagent, agent_name),
                exclusive=False,
            )
        except Exception as e:
            await self._mount_message(ErrorMessage(f"Failed to invoke @{agent_name}: {e}"))

    async def _run_subagent_task(self, query: str, subagent: Any, agent_name: str) -> None:
        """Run a subagent task.

        Args:
            query: The query to send
            subagent: The subagent instance
            agent_name: Name of the agent
        """
        try:
            await execute_task_textual(
                user_input=query,
                agent=subagent,
                assistant_id=agent_name,
                session_state=self._session_state,
                adapter=self._ui_adapter,
                backend=self._backend,
            )
        except Exception as e:
            await self._mount_message(ErrorMessage(f"Subagent error: {e}"))
        finally:
            await self._cleanup_agent_task()

    async def _run_agent_task(self, message: str) -> None:
        """Run the agent task in a background worker.

        This runs in a worker thread so the main event loop stays responsive.
        """
        try:
            await execute_task_textual(
                user_input=message,
                agent=self._agent,
                assistant_id=self._assistant_id,
                session_state=self._session_state,
                adapter=self._ui_adapter,
                backend=self._backend,
            )
        except Exception as e:  # noqa: BLE001
            await self._mount_message(ErrorMessage(f"Agent error: {e}"))
        finally:
            # Clean up loading widget and agent state
            await self._cleanup_agent_task()
            # Track messages and maybe auto-save
            self._messages_since_save += 1
            await self._maybe_auto_save()

    async def _cleanup_agent_task(self) -> None:
        """Clean up after agent task completes or is cancelled."""
        self._agent_running = False
        self._agent_worker = None

        # Remove loading widget if present
        if self._loading_widget:
            with contextlib.suppress(Exception):
                await self._loading_widget.remove()
            self._loading_widget = None

        # Re-enable cursor blink now that agent is done
        if self._chat_input:
            self._chat_input.set_cursor_active(active=True)

    async def _mount_message(self, widget: Static) -> None:
        """Mount a message widget to the messages area.

        Args:
            widget: The message widget to mount
        """
        try:
            messages = self.query_one("#messages", Container)
            await messages.mount(widget)
            # Scroll to bottom
            chat = self.query_one("#chat", VerticalScroll)
            chat.scroll_end(animate=False)
        except NoMatches:
            pass

    async def _clear_messages(self) -> None:
        """Clear the messages area."""
        try:
            messages = self.query_one("#messages", Container)
            await messages.remove_children()
        except NoMatches:
            # Widget not found - can happen during shutdown
            pass

    def action_quit_or_interrupt(self) -> None:
        """Handle Ctrl+C - interrupt agent, reject approval, or quit on double press.

        Priority order:
        1. If agent is running, interrupt it (preserve input)
        2. If approval menu is active, reject it
        3. If double press (quit_pending), quit
        4. Otherwise show quit hint
        """
        # If agent is running, interrupt it
        if self._agent_running and self._agent_worker:
            self._agent_worker.cancel()
            self._quit_pending = False
            return

        # If approval menu is active, reject it
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()
            self._quit_pending = False
            return

        # Double Ctrl+C to quit
        if self._quit_pending:
            self.exit()
        else:
            self._quit_pending = True
            self.notify("Press Ctrl+C again to quit", timeout=3)

    def action_interrupt(self) -> None:
        """Handle escape key - interrupt agent or reject approval.

        This is the primary way to stop a running agent.
        """
        # If agent is running, interrupt it
        if self._agent_running and self._agent_worker:
            self._agent_worker.cancel()
            return

        # If approval menu is active, reject it
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()

    def action_quit_app(self) -> None:
        """Handle quit action (Ctrl+D)."""
        self.exit()

    def action_toggle_auto_approve(self) -> None:
        """Toggle auto-approve mode."""
        self._auto_approve = not self._auto_approve
        if self._status_bar:
            self._status_bar.set_auto_approve(enabled=self._auto_approve)
        if self._session_state:
            self._session_state.auto_approve = self._auto_approve

    def action_toggle_tool_output(self) -> None:
        """Toggle expand/collapse of the most recent tool output."""
        # Find all tool messages with output, get the most recent one
        try:
            tool_messages = list(self.query(ToolCallMessage))
            # Find ones with output, toggle the most recent
            for tool_msg in reversed(tool_messages):
                if tool_msg.has_output:
                    tool_msg.toggle_output()
                    return
        except Exception:
            pass

    # Approval menu action handlers (delegated from App-level bindings)
    # NOTE: These only activate when approval widget is pending AND input is not focused
    def action_approval_up(self) -> None:
        """Handle up arrow in approval menu."""
        # Only handle if approval is active (input handles its own up for history/completion)
        if self._pending_approval_widget and not self._is_input_focused():
            self._pending_approval_widget.action_move_up()

    def action_approval_down(self) -> None:
        """Handle down arrow in approval menu."""
        if self._pending_approval_widget and not self._is_input_focused():
            self._pending_approval_widget.action_move_down()

    def action_approval_select(self) -> None:
        """Handle enter in approval menu."""
        # Only handle if approval is active AND input is not focused
        if self._pending_approval_widget and not self._is_input_focused():
            self._pending_approval_widget.action_select()

    def _is_input_focused(self) -> bool:
        """Check if the chat input (or its text area) has focus."""
        if not self._chat_input:
            return False
        focused = self.focused
        if focused is None:
            return False
        # Check if focused widget is the text area inside chat input
        return focused.id == "chat-input" or focused in self._chat_input.walk_children()

    def action_approval_yes(self) -> None:
        """Handle yes/1 in approval menu."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_approve()

    def action_approval_no(self) -> None:
        """Handle no/2 in approval menu."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()

    def action_approval_auto(self) -> None:
        """Handle auto/3 in approval menu."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_auto()

    def action_approval_escape(self) -> None:
        """Handle escape in approval menu - reject."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()

    def on_mouse_up(self, event: MouseUp) -> None:  # noqa: ARG002
        """Copy selection to clipboard on mouse release."""
        copy_selection_to_clipboard(self)

    # =========================================================================
    # Command handlers
    # =========================================================================

    async def _show_help(self) -> None:
        """Show help information."""
        help_text = """**Available Commands:**

**General:**
- `/help` - Show this help message
- `/clear` - Clear conversation and start fresh
- `/quit`, `/exit`, `/q` - Exit the application

**Tokens & Context:**
- `/tokens` - Show token usage for this session
- `/context` - Show detailed context window usage
- `/compact [focus]` - Compress conversation history

**Session Management:**
- `/sessions` - List and manage saved sessions
- `/save` - Manually save current session

**Project:**
- `/init` - Initialize project NAMI.md file
- `/skills [create|list]` - Manage skills
- `/agents [list]` - List available agents

**Development:**
- `/servers` - Manage dev servers
- `/tests [command]` - Run project tests
- `/kill [pid|name]` - Kill a running process

**Configuration:**
- `/plan [on|off|status]` - Toggle plan mode
- `/mcp` - MCP server management (use CLI)
- `/model` - Model provider management (use CLI)
- `/trace [on|off]` - Toggle LangSmith tracing

**Special Modes:**
- `!command` - Execute bash command
- `@agent query` - Invoke named subagent

**Keyboard Shortcuts:**
- `Enter` - Submit message
- `Ctrl+J` / `Alt+Enter` - New line
- `Ctrl+T` / `Shift+Tab` - Toggle auto-approve
- `Ctrl+O` - Toggle tool output
- `Ctrl+C` - Interrupt agent / Double press to quit
- `Ctrl+D` - Quit
- `Escape` - Interrupt / Reject approval
"""
        msg = AssistantMessage(help_text)
        await self._mount_message(msg)
        await msg.write_initial_content()

    async def _handle_context_command(self) -> None:
        """Handle /context command."""
        if self._token_tracker:
            count = self._token_tracker.current_context
            baseline = self._token_tracker._baseline
            model = self._token_tracker._model_name or "unknown"

            context_info = f"""**Context Usage:**
- Current context: {count:,} tokens
- Baseline (system + tools): {baseline:,} tokens
- Model: {model}
"""
            msg = AssistantMessage(context_info)
            await self._mount_message(msg)
            await msg.write_initial_content()
        else:
            await self._mount_message(SystemMessage("Token tracking not available"))

    async def _handle_plan_command(self, cmd_args: str | None) -> None:
        """Handle /plan command to toggle plan mode."""
        if cmd_args:
            arg = cmd_args.lower().strip()
            if arg == "on":
                self._session_state.plan_mode_enabled = True
                if self._status_bar:
                    self._status_bar.set_plan_mode(enabled=True)
                await self._mount_message(SystemMessage("Plan mode enabled"))
            elif arg == "off":
                self._session_state.plan_mode_enabled = False
                if self._status_bar:
                    self._status_bar.set_plan_mode(enabled=False)
                await self._mount_message(SystemMessage("Plan mode disabled"))
            elif arg == "status":
                status = "enabled" if self._session_state.plan_mode_enabled else "disabled"
                await self._mount_message(SystemMessage(f"Plan mode is {status}"))
            else:
                await self._mount_message(SystemMessage("Usage: /plan [on|off|status]"))
        else:
            # Toggle
            new_state = self._session_state.toggle_plan_mode()
            if self._status_bar:
                self._status_bar.set_plan_mode(enabled=new_state)
            status = "enabled" if new_state else "disabled"
            await self._mount_message(SystemMessage(f"Plan mode {status}"))

    async def _handle_sessions_command(self) -> None:
        """Handle /sessions command."""
        if not self._session_manager:
            if self._session_state:
                await self._mount_message(SystemMessage(f"Current session: {self._session_state.thread_id}"))
            else:
                await self._mount_message(SystemMessage("No active session"))
            return

        sessions = self._session_manager.list_sessions(limit=10)
        if not sessions:
            await self._mount_message(SystemMessage("No saved sessions found"))
            return

        lines = ["**Saved Sessions:**\n"]
        for meta in sessions:
            project = Path(meta.project_root).name if meta.project_root else "no project"
            model = meta.model_name or "unknown"
            lines.append(f"- `{meta.session_id[:8]}` - {project} ({model}), {meta.message_count} messages")

        msg = AssistantMessage("\n".join(lines))
        await self._mount_message(msg)
        await msg.write_initial_content()

    async def _handle_save_command(self) -> None:
        """Handle /save command."""
        if await self._save_session(silent=False):
            await self._mount_message(SystemMessage("Session saved successfully"))
        else:
            await self._mount_message(ErrorMessage("Failed to save session"))

    async def _handle_init_command(self) -> None:
        """Handle /init command."""
        if not self._agent:
            await self._mount_message(ErrorMessage("Agent not configured"))
            return

        project_root = self._settings.project_root
        if not project_root:
            await self._mount_message(ErrorMessage("Not in a project directory (no .git found)"))
            return

        await self._mount_message(SystemMessage(f"Initializing NAMI.md for {project_root.name}..."))

        # Use the agent to explore and create NAMI.md
        init_prompt = f"""Please explore this codebase at {project_root} and create a comprehensive NAMI.md file.
The file should include: project overview, technology stack, structure, development setup, commands, and architecture.
Save it to {project_root / '.nami' / 'NAMI.md'}"""

        # Temporarily enable auto-approve
        original = self._session_state.auto_approve
        self._session_state.auto_approve = True

        try:
            self._loading_widget = LoadingWidget("Exploring codebase")
            await self._mount_message(self._loading_widget)
            self._agent_running = True

            if self._chat_input:
                self._chat_input.set_cursor_active(active=False)

            self._agent_worker = self.run_worker(
                self._run_agent_task(init_prompt),
                exclusive=False,
            )
        finally:
            self._session_state.auto_approve = original

    async def _handle_skills_command(self, cmd_args: str | None) -> None:
        """Handle /skills command."""
        from namicode_cli.skills.load import list_skills

        user_skills_dir = self._settings.ensure_user_skills_dir(self._assistant_id or "nami-agent")
        project_skills_dir = self._settings.get_project_skills_dir()

        skills = list_skills(
            user_skills_dir=user_skills_dir,
            project_skills_dir=project_skills_dir,
        )

        if not skills:
            await self._mount_message(SystemMessage("No skills found. Use CLI to create skills."))
            return

        lines = ["**Available Skills:**\n"]
        for skill in skills:
            source = "Global" if skill["source"] == "user" else "Project"
            lines.append(f"- **{skill['name']}** ({source}) - {skill['description']}")

        msg = AssistantMessage("\n".join(lines))
        await self._mount_message(msg)
        await msg.write_initial_content()

    async def _handle_agents_command(self, cmd_args: str | None) -> None:
        """Handle /agents command."""
        from namicode_cli.agents.named_agents import get_available_subagents

        agents = get_available_subagents(self._settings)

        if not agents:
            await self._mount_message(SystemMessage("No custom agents found"))
            return

        lines = ["**Available Agents:**\n"]
        for agent_info in agents:
            lines.append(f"- **@{agent_info['name']}** - {agent_info.get('description', 'No description')}")

        msg = AssistantMessage("\n".join(lines))
        await self._mount_message(msg)
        await msg.write_initial_content()

    async def _handle_servers_command(self) -> None:
        """Handle /servers command."""
        from namicode_cli.server_runner.dev_server import list_servers

        servers = list_servers()

        if not servers:
            await self._mount_message(SystemMessage("No dev servers running"))
            return

        lines = ["**Running Dev Servers:**\n"]
        for server in servers:
            status_icon = "Healthy" if server.status.value == "healthy" else "Unknown"
            lines.append(f"- **{server.name}** - {server.url} (PID: {server.pid}, {status_icon})")

        msg = AssistantMessage("\n".join(lines))
        await self._mount_message(msg)
        await msg.write_initial_content()

    async def _handle_tests_command(self, cmd_args: str | None) -> None:
        """Handle /tests command."""
        from namicode_cli.server_runner.test_runner import run_tests, detect_test_framework, get_default_test_command

        working_dir = str(Path.cwd())

        if not cmd_args:
            framework = detect_test_framework(working_dir)
            command = get_default_test_command(framework)
            if not command:
                await self._mount_message(ErrorMessage("Could not detect test framework. Specify command: /tests pytest"))
                return
        else:
            command = cmd_args.strip()

        await self._mount_message(SystemMessage(f"Running: {command}"))

        output_lines: list[str] = []

        def output_callback(line: str) -> None:
            output_lines.append(line)

        result = await run_tests(
            command=command,
            working_dir=working_dir,
            output_callback=output_callback,
        )

        # Show output (last 50 lines)
        if output_lines:
            output_text = "\n".join(output_lines[-50:])
            msg = AssistantMessage(f"```\n{output_text}\n```")
            await self._mount_message(msg)
            await msg.write_initial_content()

        if result.success:
            await self._mount_message(SystemMessage("Tests passed!"))
        else:
            await self._mount_message(ErrorMessage(f"Tests failed: {result.error or 'See output above'}"))

    async def _handle_kill_command(self, cmd_args: str | None) -> None:
        """Handle /kill command."""
        from namicode_cli.process_manager import ProcessManager

        manager = ProcessManager.get_instance()

        if cmd_args:
            arg = cmd_args.strip()
            try:
                pid = int(arg)
                result = await manager.stop_process(pid)
                if result:
                    await self._mount_message(SystemMessage(f"Killed process {pid}"))
                else:
                    await self._mount_message(ErrorMessage(f"No process found with PID {pid}"))
            except ValueError:
                result = await manager.stop_by_name(arg)
                if result:
                    await self._mount_message(SystemMessage(f"Killed process '{arg}'"))
                else:
                    await self._mount_message(ErrorMessage(f"No process found with name '{arg}'"))
        else:
            processes = manager.list_processes(alive_only=True)
            if not processes:
                await self._mount_message(SystemMessage("No managed processes running"))
            else:
                lines = ["**Running Processes:**\n"]
                for info in processes:
                    lines.append(f"- [{info.pid}] {info.name}")
                lines.append("\nUse `/kill <pid>` or `/kill <name>` to stop a process")
                msg = AssistantMessage("\n".join(lines))
                await self._mount_message(msg)
                await msg.write_initial_content()

    async def _handle_compact_command(self, cmd_args: str | None) -> None:
        """Handle /compact command."""
        from namicode_cli.compaction import compact_conversation
        from namicode_cli.config.model_create import create_model

        if not self._agent:
            await self._mount_message(ErrorMessage("Agent not configured"))
            return

        await self._mount_message(SystemMessage("Compacting conversation..."))

        model = create_model()
        result = await compact_conversation(
            agent=self._agent,
            model=model,
            thread_id=self._session_state.thread_id,
            focus_instructions=cmd_args,
        )

        if result.success:
            await self._mount_message(SystemMessage(
                f"Compacted: {result.messages_before} -> {result.messages_after} messages, ~{result.tokens_saved:,} tokens saved"
            ))
            if self._token_tracker:
                self._token_tracker.reset()
        else:
            await self._mount_message(ErrorMessage(f"Compaction failed: {result.error}"))

    async def _handle_trace_command(self, cmd_args: str | None) -> None:
        """Handle /trace command."""
        import os

        if cmd_args:
            arg = cmd_args.lower().strip()
            if arg == "on":
                os.environ["LANGCHAIN_TRACING_V2"] = "true"
                await self._mount_message(SystemMessage("LangSmith tracing enabled"))
            elif arg == "off":
                os.environ["LANGCHAIN_TRACING_V2"] = "false"
                await self._mount_message(SystemMessage("LangSmith tracing disabled"))
            else:
                await self._mount_message(SystemMessage("Usage: /trace [on|off]"))
        else:
            current = os.environ.get("LANGCHAIN_TRACING_V2", "false")
            status = "enabled" if current.lower() == "true" else "disabled"
            await self._mount_message(SystemMessage(f"LangSmith tracing is {status}"))

    # =========================================================================
    # Session management
    # =========================================================================

    async def _save_session(self, *, silent: bool = True) -> bool:
        """Save current session state."""
        if not self._session_manager or not self._assistant_id or not self._agent:
            return False

        try:
            config = {"configurable": {"thread_id": self._session_state.thread_id}}
            state = await self._agent.aget_state(config)
            messages = state.values.get("messages", [])

            if not messages:
                return False

            self._session_manager.save_session(
                session_id=self._session_state.session_id or self._session_state.thread_id,
                thread_id=self._session_state.thread_id,
                messages=messages,
                assistant_id=self._assistant_id,
                todos=self._session_state.todos,
                model_name=self._model_name,
                project_root=Path.cwd(),
            )
            return True
        except Exception:
            return False

    async def _maybe_auto_save(self) -> None:
        """Check if auto-save should run."""
        current_time = time.time()
        time_since_save = current_time - self._last_save_time

        should_save = (
            time_since_save >= AUTO_SAVE_INTERVAL_SECONDS
            or self._messages_since_save >= AUTO_SAVE_MESSAGE_THRESHOLD
        )

        if should_save and self._messages_since_save > 0:
            if await self._save_session(silent=True):
                self._last_save_time = current_time
                self._messages_since_save = 0

    async def _save_session_on_exit(self) -> None:
        """Save session and clean up on exit."""
        from namicode_cli.process_manager import ProcessManager

        # Stop managed processes
        try:
            manager = ProcessManager.get_instance()
            await manager.stop_all()
        except Exception:
            pass

        # Save session
        await self._save_session(silent=True)


async def run_textual_app(
    *,
    agent: Pregel | None = None,
    assistant_id: str | None = None,
    backend: Any = None,  # noqa: ANN401  # CompositeBackend
    auto_approve: bool = False,
    cwd: str | Path | None = None,
    thread_id: str | None = None,
    session_state: SessionState | None = None,
    session_manager: Any = None,
    store: InMemoryStore | None = None,
    checkpointer: InMemorySaver | None = None,
    model_name: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Run the Textual application.

    Args:
        agent: Pre-configured LangGraph agent
        assistant_id: Agent identifier for memory storage
        backend: Backend for file operations
        auto_approve: Whether to start with auto-approve enabled
        cwd: Current working directory to display
        thread_id: Thread ID for session persistence
        session_state: Session state instance
        session_manager: SessionManager for persistence
        store: InMemoryStore for shared memory
        checkpointer: InMemorySaver for state persistence
        model_name: Name of the model being used
        settings: Settings instance
    """
    app = NamiCodeApp(
        agent=agent,
        assistant_id=assistant_id,
        backend=backend,
        auto_approve=auto_approve,
        cwd=cwd,
        thread_id=thread_id,
        session_state=session_state,
        session_manager=session_manager,
        store=store,
        checkpointer=checkpointer,
        model_name=model_name,
        settings=settings,
    )
    await app.run_async()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_textual_app())
