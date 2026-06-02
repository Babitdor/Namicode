"""Textual chat application (Phase 1).

A scrollable transcript + input + status line. The agent runs in a Textual
worker that iterates :func:`novacode_cli.agent_stream.run_agent_stream` and
renders each :mod:`novacode_cli.ui_events` event. HITL interrupts are shown as
modal screens.

Existing ``rich`` renderers are reused by capturing their output to a ``Text``
(``_capture``), so the visual style matches the legacy UI without duplicating
rendering code.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from rich.markdown import Markdown
from rich.markup import escape as _esc
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme

from textual.widgets import (
    Button,
    Collapsible,
    Input,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option

# Slash commands routed through the legacy handle_command via console capture.
# Restricted to commands that only print or toggle state — never read stdin or
# use a Live spinner (those would hang or garble inside Textual).
# Rare subcommands still delegated to handle_command (captured) from within the
# native handlers (e.g. `/trace enable`, `/log show <id>`). Common forms native.
_PASSTHROUGH_SLASH: set[str] = set()

# Slash commands offered by the autocomplete dropdown.
_TUI_SLASH_COMMANDS = [
    "/help",
    "/init",
    "/model",
    "/sessions",
    "/mcp",
    "/skills",
    "/agents",
    "/plan",
    "/remote",
    "/compact",
    "/save",
    "/steer",
    "/notifications",
    "/research",
    "/dream",
    "/reindex",
    "/images",
    "/vision",
    "/files",
    "/tests",
    "/servers",
    "/kill",
    "/restore",
    "/hooks",
    "/browser-use",
    "/ralph",
    "/trello",
    "/clear",
    "/tokens",
    "/context",
    "/cost",
    "/verbose",
    "/decompose",
    "/trace",
    "/log",
    "/theme",
    "/quit",
    "/exit",
]

from novacode_cli import ui_events as ev
from novacode_cli.agent_stream import run_agent_stream
from novacode_cli.config.config import console as _rich_console
from novacode_cli.config.config import get_responsive_ascii

# Nova's default palette, registered as a real Textual theme so /theme can swap
# it for any other theme. Previously these colors were hardcoded as CSS
# variables ($primary: …) at the top of NovaApp.CSS, which *overrode* the active
# theme and made theme switching a no-op. Defining them here instead lets the
# active theme drive every $variable, so /theme actually changes the UI.
NOVA_TOKYO_NIGHT = Theme(
    name="tokyo-night",
    primary="#7aa2f7",
    secondary="#9ece6a",
    accent="#bb9af7",
    success="#73daca",
    warning="#e0af68",
    error="#f7768e",
    surface="#1a1b26",
    panel="#24283b",
    background="#13141d",
    foreground="#c0caf5",
    boost="#2f3346",
    dark=True,
    variables={
        "text-muted": "#565f89",
        "border": "#3b4261",
    },
)
DEFAULT_THEME = "tokyo-night"


class ChatMessage(Vertical):
    """A single transcript entry: a left accent bar, a role header, and a body.

    role_class selects the accent color (user / nova / reason). The body is set
    via :meth:`update_body` with any rich renderable (plain Text while streaming,
    Markdown once committed)."""

    DEFAULT_CSS = """
    /* Even, consistent cards: a colored left accent bar + padding. Only the
       accent color and header differ between roles (minimal accent-bar style). */
    ChatMessage {
        height: auto;
        margin: 1 0;
        padding: 1 3;
        background: $surface;
    }
    ChatMessage > .role { text-style: bold; }
    ChatMessage > .body { height: auto; }
    ChatMessage.user { border-left: thick $primary; }
    ChatMessage.nova { border-left: thick $success; }
    ChatMessage.reason { border-left: thick $panel; color: $text-muted; }
    """

    def __init__(self, header: Text, role_class: str) -> None:
        super().__init__(classes=role_class)
        self._header = header

    def compose(self) -> ComposeResult:
        yield Static(self._header, classes="role")
        yield Static("", classes="body")

    def update_body(self, renderable: Any) -> None:
        self.query_one(".body", Static).update(renderable)


def _capture(fn, *args, **kwargs) -> Text:
    """Render an existing ``console.print``-based helper into a ``Text``.

    Lets the TUI reuse the legacy rich renderers (tool panels, todos, file ops)
    without printing to the real terminal — capture redirects the global
    console to an in-memory buffer.
    """
    with _rich_console.capture() as cap:
        fn(*args, **kwargs)
    return Text.from_ansi(cap.get())


class _TuiSink:
    """File-like sink that streams a rich Console's output into the TUI live.

    Used so long-running pipelines (e.g. ``/init``) that print progress via a
    rich ``Console`` render line-by-line in the transcript. Safe to call from
    worker threads (uses ``call_from_thread``); falls back to a direct call when
    already on the app thread."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._emit(self._buf)
            self._buf = ""

    def _emit(self, line: str) -> None:
        try:
            self._app.call_from_thread(self._app._init_emit, line)
        except Exception:  # noqa: BLE001 — already on the app thread, emit directly
            try:
                self._app._init_emit(line)
            except Exception:  # noqa: BLE001, S110
                pass


def _approval_details(action_requests: list[dict]) -> Text:
    """Detailed, multi-line view of the actions awaiting approval."""
    from novacode_cli.ui.ui_elements import format_tool_display

    t = Text()
    t.append("⚠ The agent wants to run:\n\n", style="yellow")
    for ar in action_requests:
        name = ar.get("name", "?")
        args = ar.get("args", {}) or {}
        try:
            disp = format_tool_display(name, args)
        except Exception:  # noqa: BLE001
            disp = name
        t.append(f"  • {disp}\n", style="bold")
        if isinstance(args, dict):
            for k, v in args.items():
                sval = str(v).replace("\n", " ")
                if len(sval) > 160:
                    sval = sval[:160] + "…"
                t.append(f"      {k}: {sval}\n", style="dim")
    return t


class ConfirmModal(ModalScreen[bool]):
    """Simple yes/no confirmation (e.g. delete actions)."""

    BINDINGS = [
        ("y", "yes", "Yes"),
        ("n", "no", "No"),
        ("escape", "no", "No"),
    ]

    def __init__(self, title: str, body: Any) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text(self._title, style="bold"), id="modal-title")
            yield Static(self._body, id="modal-body")
            with Horizontal(id="modal-buttons"):
                yield Button("Yes (y)", id="yes", variant="error")
                yield Button("No (n)", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class ApprovalModal(ModalScreen[str]):
    """Rich approval dialog. Returns 'approve', 'auto', or 'reject'.

    Shows the action details and a keyboard-navigable choice list (arrows +
    Enter, or y/a/n quick keys, Esc to reject)."""

    BINDINGS = [
        ("y", "approve", "Approve"),
        ("a", "auto", "Auto-approve"),
        ("n", "reject", "Reject"),
        ("escape", "reject", "Reject"),
    ]

    def __init__(self, title: str, body: Any, *, allow_auto: bool = True) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._allow_auto = allow_auto

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text(f">>> {self._title} <<<", style="bold yellow"), id="modal-title")
            # Bound + scroll the body so a long plan can't push the choices
            # off-screen — the options must always stay visible.
            with VerticalScroll(id="modal-body-scroll"):
                yield Static(self._body, id="modal-body")
            yield OptionList(id="choices")
            yield Static(
                Text(
                    "↑/↓ navigate · Enter select · y/a/n quick keys · Esc reject",
                    style="dim",
                ),
                id="modal-hint",
            )

    def on_mount(self) -> None:
        ol = self.query_one("#choices", OptionList)
        ol.add_option(Option("Approve (y)"))
        if self._allow_auto:
            ol.add_option(Option("Auto-approve for this thread (a)"))
        ol.add_option(Option("Reject (n)"))
        ol.highlighted = 0
        ol.focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        label = str(event.option.prompt)
        if label.startswith("Approve"):
            self.dismiss("approve")
        elif label.startswith("Auto"):
            self.dismiss("auto")
        else:
            self.dismiss("reject")

    def action_approve(self) -> None:
        self.dismiss("approve")

    def action_auto(self) -> None:
        self.dismiss("auto" if self._allow_auto else "approve")

    def action_reject(self) -> None:
        self.dismiss("reject")


class QuestionModal(ModalScreen[dict]):
    """Answer an ``ask_question`` interrupt (open-ended or option select)."""

    def __init__(self, question_request: dict) -> None:
        super().__init__()
        self._q = question_request or {}

    def compose(self) -> ComposeResult:
        prompt = (
            self._q.get("question")
            or self._q.get("prompt")
            or "The agent has a question:"
        )
        opts = self._q.get("options") or []
        with Vertical(id="modal-box"):
            yield Static(Text(str(prompt), style="bold"), id="modal-title")
            if opts:
                # Use Text (not a raw markup string) so an option containing
                # '[' can't be parsed as markup and crash the render.
                lines = "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(opts))
                yield Static(Text(lines), id="modal-body")
            yield Input(
                placeholder="Type your answer (or option number)…", id="answer"
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        from novacode_cli.ui.question_prompt import QuestionResponse

        text = event.value.strip()
        opts = self._q.get("options") or []
        selected = None
        answer = text
        if text.isdigit() and opts:
            idx = int(text) - 1
            if 0 <= idx < len(opts):
                selected = idx
                answer = opts[idx]
        self.dismiss(
            {"response": QuestionResponse(answer=answer, selected_index=selected)}
        )


class ModelScreen(ModalScreen[dict | None]):
    """Native ``/model`` screen: pick a provider, optionally enter an API key,
    and choose (or free-type) a model. Returns the selection; the app performs
    the actual switch."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current_provider: str | None, configured: set[str]) -> None:
        super().__init__()
        self._current = current_provider
        self._configured = configured

    def compose(self) -> ComposeResult:
        from novacode_cli.config.model_manager import MODEL_PRESETS

        options = []
        for pid, preset in MODEL_PRESETS.items():
            mark = "" if pid in self._configured else "  (needs key)"
            options.append((f"{preset['name']}{mark}", pid))

        default_value = (
            self._current if self._current in MODEL_PRESETS else Select.BLANK
        )
        with Vertical(id="modal-box"):
            yield Static(Text("Switch model", style="bold"), id="modal-title")
            yield Select(options, value=default_value, id="provider", allow_blank=True)
            yield Static("", id="modelinfo")
            yield Input(
                placeholder="API key (blank = use saved)", password=True, id="apikey"
            )
            yield Input(
                placeholder="Model (blank = default, or type any slug)", id="model"
            )
            with Horizontal(id="modal-buttons"):
                yield Button("Switch", id="switch", variant="success")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        if self._current:
            self._refresh_info(self._current)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider" and event.value is not Select.BLANK:
            self._refresh_info(str(event.value))

    def _refresh_info(self, pid: str) -> None:
        from novacode_cli.config.model_manager import MODEL_PRESETS

        preset = MODEL_PRESETS.get(pid)
        if not preset:
            return
        info = Text()
        info.append(f"default: {preset['default_model']}\n", style="dim")
        models = preset.get("models", [])
        if models:
            info.append("suggestions: " + ", ".join(models[:6]), style="dim")
        self.query_one("#modelinfo", Static).update(info)
        self.query_one("#model", Input).placeholder = (
            f"Model (blank = {preset['default_model']})"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        provider = self.query_one("#provider", Select).value
        if provider is Select.BLANK:
            self.dismiss(None)
            return
        self.dismiss(
            {
                "provider": str(provider),
                "model": self.query_one("#model", Input).value.strip(),
                "api_key": self.query_one("#apikey", Input).value.strip(),
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class SessionsScreen(ModalScreen[None]):
    """List and delete saved sessions (resume is via ``nova --continue <id>``)."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, session_manager, current_id: str | None) -> None:
        super().__init__()
        self._sm = session_manager
        self._current = current_id
        self._sessions: list = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Saved sessions", style="bold"), id="modal-title")
            yield OptionList(id="sessions")
            yield Static("", id="sessions-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Delete", id="delete", variant="error")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self._reload()

    def _reload(self) -> None:
        from pathlib import Path

        from novacode_cli.session.session_restore import format_session_age

        self._sessions = self._sm.list_sessions(limit=20)
        ol = self.query_one("#sessions", OptionList)
        ol.clear_options()
        hint = self.query_one("#sessions-hint", Static)
        if not self._sessions:
            hint.update(Text("No saved sessions.", style="dim"))
            return
        for meta in self._sessions:
            age = format_session_age(meta.last_active)
            project = (
                Path(meta.project_root).name if meta.project_root else "no project"
            )
            model = meta.model_name or "unknown"
            marker = " ← current" if meta.session_id == self._current else ""
            ol.add_option(
                Option(
                    f"{meta.session_id[:8]}{marker}  ·  {project} ({model})  ·  "
                    f"{meta.message_count} msgs  ·  {age}"
                )
            )
        hint.update(
            Text("Resume with:  nova --continue <id>", style="dim")
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "delete":
            self._delete_highlighted()

    @work
    async def _delete_highlighted(self) -> None:
        ol = self.query_one("#sessions", OptionList)
        idx = ol.highlighted
        if idx is None or not (0 <= idx < len(self._sessions)):
            return
        meta = self._sessions[idx]
        ok = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete session {meta.session_id[:8]}?",
                Text("This cannot be undone."),
            )
        )
        if ok:
            try:
                self._sm.delete_session(meta.session_id)
            except Exception:  # noqa: BLE001
                pass
            self._reload()

    def action_close(self) -> None:
        self.dismiss(None)


class McpScreen(ModalScreen[None]):
    """Browse configured MCP servers and install presets.

    Shows configured servers with active/inactive status, the full catalog of
    available presets, and lets users install presets (collecting API keys
    when needed) or remove configured servers — all in the TUI."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._config_names: list[str] = []
        self._preset_ids: list[str] = []
        self._presets: dict[str, dict] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("MCP Management", style="bold"), id="modal-title")
            yield Static(Text("Configured Servers:", style="bold cyan"), id="mcp-section")
            yield OptionList(id="mcp-configured")
            yield Static(Text("Available Presets:", style="bold yellow"), id="preset-section")
            yield OptionList(id="mcp-presets")
            yield Static("", id="mcp-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Install", id="install", variant="primary")
                yield Button("Add Custom", id="add-custom")
                yield Button("Remove", id="remove", variant="error")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self._reload()
        # Discover live MCP servers OFF the UI thread (it can connect to stdio
        # servers and block/hang). Repaint active status when it finishes.
        try:
            from novacode_cli.mcp import get_shared_mcp_middleware

            if not get_shared_mcp_middleware()._tools_discovered:
                self._discover_then_refresh()
        except Exception:  # noqa: BLE001
            pass

    @work(thread=True, exclusive=True)
    def _discover_then_refresh(self) -> None:
        """Run MCP discovery in a worker thread, then repaint on the UI thread."""
        try:
            from novacode_cli.mcp import get_shared_mcp_middleware

            get_shared_mcp_middleware()._discover_tools_sync()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.app.call_from_thread(self._reload)
        except Exception:  # noqa: BLE001
            pass

    def _reload(self) -> None:
        """Refresh both configured servers and presets lists (non-blocking)."""
        # Configured servers
        configured = self.query_one("#mcp-configured", OptionList)
        configured.clear_options()
        self._config_names = []
        try:
            from novacode_cli.mcp.config import MCPConfig

            servers = MCPConfig().list_servers()
        except Exception:  # noqa: BLE001
            servers = {}

        # Active servers from whatever has ALREADY been discovered (no blocking
        # discovery here — _discover_then_refresh fills this in asynchronously).
        active_servers: set[str] = set()
        try:
            from novacode_cli.mcp import get_shared_mcp_middleware

            middleware = get_shared_mcp_middleware()
            for tool_meta in middleware._tools_cache:
                sn = tool_meta.get("server")
                if sn:
                    active_servers.add(sn)
        except Exception:  # noqa: BLE001
            pass

        if servers:
            for name, sc in servers.items():
                self._config_names.append(name)
                is_active = name in active_servers
                status_mark = "\u25cf" if is_active else "\u25cb"
                status_style = "#73daca" if is_active else "#565f89"
                transport = getattr(sc, "transport", "?")
                loc = getattr(sc, "url", None) or getattr(sc, "command", None) or ""
                label = Text.assemble(
                    (f"{status_mark}  {name}  \u00b7  ", status_style),
                    (f"{transport}  \u00b7  {loc}", "dim"),
                )
                configured.add_option(Option(label))

            # Show active tool count
            active_section = self.query_one("#mcp-section", Static)
            active_count = sum(1 for n in active_servers if n in self._config_names)
            inactive_count = len(self._config_names) - active_count
            active_section.update(
                Text(
                    f"Configured Servers: {len(self._config_names)} total"
                    + (f" ({active_count} active, {inactive_count} inactive)" if inactive_count or active_count else ""),
                    style="bold cyan",
                )
            )
        else:
            configured.add_option(Option("(no MCP servers configured)"))
            self.query_one("#mcp-section", Static).update(
                Text("Configured Servers: (none)", style="bold cyan")
            )

        # Available presets
        presets_list = self.query_one("#mcp-presets", OptionList)
        presets_list.clear_options()
        self._preset_ids = []
        self._presets = {}
        try:
            from novacode_cli.mcp.presets import list_presets

            self._presets = list_presets()
        except Exception:  # noqa: BLE001
            pass

        for pid, preset in self._presets.items():
            self._preset_ids.append(pid)
            already_configured = pid in self._config_names
            marker = "[\u2713]" if already_configured else "[ ]"
            needs_key = "\U0001f511" if preset.get("setup_key") else ""
            label = Text.assemble(
                (f"{marker}  {pid}  ", "bold #e0af68"),
                (f"{preset['name']}", ""),
                (f"  {needs_key}", "dim") if needs_key else ("", ""),
                (f"\n     {preset['description']}", "dim"),
            )
            presets_list.add_option(Option(label))

        hint = self.query_one("#mcp-hint", Static)
        hint.update(
            Text(
                f"{len(self._presets)} presets \u00b7 "
                "\U0001f511 = needs API key \u00b7 [\u2713] = already configured \u00b7 "
                "restart session after installing",
                style="dim",
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "remove":
            self._remove_highlighted()
        elif event.button.id == "install":
            self._install_highlighted()
        elif event.button.id == "add-custom":
            self._add_custom()

    @work
    async def _remove_highlighted(self) -> None:
        if not self._config_names:
            return
        ol = self.query_one("#mcp-configured", OptionList)
        idx = ol.highlighted
        if idx is None or not (0 <= idx < len(self._config_names)):
            return
        name = self._config_names[idx]
        ok = await self.app.push_screen_wait(
            ConfirmModal(
                f"Remove MCP server '{name}'?",
                Text("This edits ~/.nova/mcp.json."),
            )
        )
        if ok:
            try:
                from novacode_cli.mcp.config import MCPConfig

                MCPConfig().remove_server(name)
            except Exception:  # noqa: BLE001
                pass
            self._reload()

    @work
    async def _install_highlighted(self) -> None:
        """Install the highlighted preset, collecting API keys when needed."""
        ol = self.query_one("#mcp-presets", OptionList)
        idx = ol.highlighted
        if idx is None or not (0 <= idx < len(self._preset_ids)):
            return
        preset_id = self._preset_ids[idx]
        preset = self._presets.get(preset_id)
        if preset is None:
            return

        # Already configured?
        if preset_id in self._config_names:
            ok = await self.app.push_screen_wait(
                ConfirmModal(
                    f"'{preset['name']}' is already configured.",
                    Text("Re-install with new configuration?"),
                )
            )
            if not ok:
                return

        # Collect API keys / user inputs
        user_inputs: dict[str, str] = {}
        if preset.get("setup_key"):
            result = await self.app.push_screen_wait(
                McpInstallModal(preset, preset_id)
            )
            if result is None:  # cancelled
                return
            user_inputs = result

        # Create and save config
        try:
            from novacode_cli.mcp.presets import create_config_from_preset
            from novacode_cli.mcp.config import MCPConfig

            config = create_config_from_preset(preset_id, user_inputs)
            if config:
                MCPConfig().add_server(preset_id, config)
                self.app.query_one("#transcript", VerticalScroll).mount(
                    Static(
                        Text(
                            f"\u2713 MCP preset '{preset['name']}' installed! Restart session to activate.",
                            style="green",
                        ),
                        classes="logline",
                    )
                )
        except Exception as ex:  # noqa: BLE001
            self.app.query_one("#transcript", VerticalScroll).mount(
                Static(
                    Text(f"Install failed: {ex}", style="red"),
                    classes="logline",
                )
            )
        self._reload()
        self.dismiss(None)

    @work
    async def _add_custom(self) -> None:
        """Show a two-step modal for adding a custom MCP server."""
        result = await self.app.push_screen_wait(McpCustomModal())
        if result is not None:
            try:
                from novacode_cli.mcp.config import MCPConfig, MCPServerConfig

                name = result["name"]
                if result["transport"] == "http":
                    config = MCPServerConfig(
                        transport="http",
                        url=result["url"],
                        description=result.get("description") or None,
                    )
                else:
                    config = MCPServerConfig(
                        transport="stdio",
                        command=result["command"],
                        args=result.get("args") or [],
                        env=result.get("env") or {},
                        description=result.get("description") or None,
                    )
                MCPConfig().add_server(name, config)
                self.app.query_one("#transcript", VerticalScroll).mount(
                    Static(
                        Text(
                            f"\u2713 Custom MCP '{name}' added! Restart session to activate.",
                            style="green",
                        ),
                        classes="logline",
                    )
                )
            except Exception as ex:  # noqa: BLE001
                self.app.query_one("#transcript", VerticalScroll).mount(
                    Static(
                        Text(f"Add custom MCP failed: {ex}", style="red"),
                        classes="logline",
                    )
                )
            self._reload()
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class McpInstallModal(ModalScreen[dict | None]):
    """Collect API keys / configuration values for an MCP preset before installing."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, preset: dict, preset_id: str) -> None:
        super().__init__()
        self._preset = preset
        self._preset_id = preset_id

    def compose(self) -> ComposeResult:
        preset = self._preset
        with Vertical(id="modal-box"):
            yield Static(
                Text(f"Install: {preset['name']}", style="bold #e0af68"),
                id="modal-title",
            )
            yield Static(
                Text(f"{preset.get('description', '')}\nPackage: {preset.get('package', 'N/A')}", style="dim"),
                id="modal-body",
            )
            if preset.get("setup_prompt"):
                yield Static(Text(preset["setup_prompt"], style="bold"), id="mcp-key-label")
                yield Input(placeholder="Enter value\u2026", id="mcp-key-value", password=True)
            yield Static("", id="mcp-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Install", id="do-install", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        if self._preset.get("setup_prompt"):
            self.query_one("#mcp-key-value", Input).focus()
        else:
            self.query_one("#do-install", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "do-install":
            self._do_install()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mcp-key-value":
            self._do_install()

    def _do_install(self) -> None:
        result: dict[str, str] = {}
        key = self._preset.get("setup_key")
        if key:
            try:
                val = self.query_one("#mcp-key-value", Input).value.strip()
            except Exception:  # noqa: BLE001
                val = ""
            if not val:
                return  # don't install without required key
            result[key] = val
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)


class McpCustomModal(ModalScreen[dict | None]):
    """Two-step modal to add a custom MCP server (name + transport + connection details)."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Add Custom MCP Server", style="bold"), id="modal-title")
            yield Static(Text("Server name:", style="bold"), id="mcp-name-label")
            yield Input(placeholder="e.g., my-custom-mcp", id="mcp-name")
            yield Static(Text("Transport:", style="bold"), id="mcp-transport-label")
            yield Select(
                [("stdio (local command)", "stdio"), ("HTTP (remote server)", "http")],
                id="mcp-transport",
                value="stdio",
            )
            yield Static(Text("Connection:", style="bold"), id="mcp-conn-label")
            yield Input(placeholder="npx -y @scope/package  OR  https://example.com/mcp", id="mcp-conn")
            yield Input(placeholder="Description (optional)", id="mcp-desc")
            with Horizontal(id="modal-buttons"):
                yield Button("Add", id="do-add", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#mcp-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "do-add":
            self._do_add()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mcp-name":
            self.query_one("#mcp-conn", Input).focus()
        elif event.input.id == "mcp-conn":
            self._do_add()

    def _do_add(self) -> None:
        try:
            name = self.query_one("#mcp-name", Input).value.strip()
        except Exception:  # noqa: BLE001
            return
        if not name:
            return
        try:
            transport = self.query_one("#mcp-transport", Select).value
        except Exception:  # noqa: BLE001
            transport = "stdio"
        try:
            conn = self.query_one("#mcp-conn", Input).value.strip()
        except Exception:  # noqa: BLE001
            conn = ""
        if not conn:
            return
        try:
            desc = self.query_one("#mcp-desc", Input).value.strip()
        except Exception:  # noqa: BLE001
            desc = ""

        if str(transport) == "http":
            result: dict = {"name": name, "transport": "http", "url": conn}
        else:
            # stdio: split command into executable + args
            parts = conn.split()
            result = {
                "name": name,
                "transport": "stdio",
                "command": parts[0] if parts else conn,
                "args": parts[1:] if len(parts) > 1 else [],
            }
        if desc:
            result["description"] = desc
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)

class InfoListScreen(ModalScreen[None]):
    """A simple read-only list modal (used by /skills and /agents)."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str, lines: list[str], hint: str | None = None) -> None:
        super().__init__()
        self._title = title
        self._lines = lines
        self._hint = hint

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text(self._title, style="bold"), id="modal-title")
            yield OptionList(id="infolist")
            if self._hint:
                yield Static(Text(self._hint, style="dim"), id="info-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        ol = self.query_one("#infolist", OptionList)
        for line in self._lines:
            ol.add_option(Option(line))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class PickScreen(ModalScreen[int]):
    """A reusable selection modal: choose one item, returns its index (-1 = cancel)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[str], hint: str | None = None) -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._hint = hint

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text(self._title, style="bold"), id="modal-title")
            yield OptionList(id="pick-list")
            if self._hint:
                yield Static(Text(self._hint, style="dim"), id="pick-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Select", id="select", variant="success")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        ol = self.query_one("#pick-list", OptionList)
        for line in self._options:
            ol.add_option(Option(line))
        if self._options:
            ol.highlighted = 0
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(-1)
        elif event.button.id == "select":
            ol = self.query_one("#pick-list", OptionList)
            self.dismiss(ol.highlighted if ol.highlighted is not None else -1)

    def action_cancel(self) -> None:
        self.dismiss(-1)


class ThemeScreen(ModalScreen[None]):
    """Browse and apply Textual themes with live preview."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._theme_names: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Choose Theme", style="bold"), id="modal-title")
            yield OptionList(id="theme-list")
            yield Static("", id="theme-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self._reload()

    def _reload(self) -> None:
        # available_themes includes builtins *and* Nova's registered tokyo-night.
        themes = self.app.available_themes

        ol = self.query_one("#theme-list", OptionList)
        ol.clear_options()
        self._theme_names = sorted(themes.keys())
        current = self.app.theme if hasattr(self.app, "theme") else DEFAULT_THEME
        for name in self._theme_names:
            # Just the theme name, with a dot marking the active one.
            is_current = name == current
            marker = "\u25cf" if is_current else "\u25cb"
            label = Text(
                f"{marker}  {name}",
                style="bold" if is_current else "",
            )
            ol.add_option(Option(label))

        # Highlight current theme
        try:
            idx = self._theme_names.index(current)
            ol.highlighted = idx
        except ValueError:
            pass

        hint = self.query_one("#theme-hint", Static)
        hint.update(
            Text(
                f"{len(self._theme_names)} themes \u00b7 changes apply instantly \u00b7 persist across restarts",
                style="dim",
            )
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "theme-list":
            self._do_apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "apply":
            self._do_apply()

    def _do_apply(self) -> None:
        ol = self.query_one("#theme-list", OptionList)
        idx = ol.highlighted
        if idx is None or not (0 <= idx < len(self._theme_names)):
            return
        name = self._theme_names[idx]
        # Apply instantly — setting App.theme re-renders all themed CSS.
        self.app.theme = name
        # Persist to the same config the app reads on startup (Nova.config.json).
        try:
            from novacode_cli.config.nova_config import NovaConfig

            NovaConfig().set("theme", name)
        except Exception:  # noqa: BLE001
            pass
        self._reload()

    def action_close(self) -> None:
        self.dismiss(None)


class RemoteScreen(ModalScreen[None]):
    """Native /remote screen: bridge status + start/stop/test, rendered as TUI
    components (the underlying logic is reused, but its output stays in-modal)."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, session_state) -> None:
        super().__init__()
        self._ss = session_state

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Remote bridges", style="bold"), id="modal-title")
            yield Static("", id="remote-status")
            yield Input(
                placeholder="Bot token (blank = use saved)",
                password=True,
                id="remote-token",
            )
            yield Input(
                placeholder="Channel/Chat ID (blank = saved/auto)", id="remote-chat"
            )
            with Horizontal(id="modal-buttons"):
                yield Button("Start Discord", id="start-discord", variant="success")
                yield Button("Start Telegram", id="start-telegram", variant="success")
                yield Button("Test", id="test")
                yield Button("Stop All", id="stop", variant="error")
                yield Button("Close", id="close")
            yield Static("", id="remote-result")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        from novacode_cli.remote.config import load_remote_config

        mgr = getattr(self._ss, "_remote_bridge_manager", None)
        bridges = mgr.active_bridges if mgr is not None else []
        t = Text()
        if bridges:
            t.append(f"{len(bridges)} active:\n", style="cyan")
            for b in bridges:
                status = b.get("status", "")
                icon = (
                    "🟢"
                    if status == "running"
                    else ("🔴" if "error" in status.lower() else "🟡")
                )
                bot = f" (@{b['bot_user']})" if b.get("bot_user") else ""
                t.append(
                    f"  {icon} {b['platform']}{bot} — chat {b['chat_id']} — {status}\n",
                    style="dim",
                )
        else:
            t.append("No bridges active.\n", style="dim")
        try:
            saved = load_remote_config()
        except Exception:  # noqa: BLE001
            saved = {}
        if saved:
            t.append("\nSaved config:\n", style="dim")
            if "discord" in saved:
                d = saved["discord"]
                tok = "✓" if d.get("token") else "✗"
                t.append(
                    f"  Discord: token {tok} · channel {d.get('channel_id', '—')}\n",
                    style="dim",
                )
            if "telegram" in saved:
                tg = saved["telegram"]
                tok = "✓" if tg.get("token") else "✗"
                t.append(
                    f"  Telegram: token {tok} · chat {tg.get('chat_id', '—')}\n",
                    style="dim",
                )
        self.query_one("#remote-status", Static).update(t)

    def _build_args(self, platform: str) -> str:
        token = self.query_one("#remote-token", Input).value.strip()
        chat = self.query_one("#remote-chat", Input).value.strip()
        args = f"start {platform}"
        if token:
            args += f" --token {token}"
        if chat:
            args += f" --channel {chat}" if platform == "discord" else f" --chat {chat}"
        return args

    @work
    async def _run_remote(self, args: str) -> None:
        from novacode_cli.commands.commands import handle_command
        from novacode_cli.config.config import console as _c

        self.query_one("#remote-result", Static).update(Text("Working…", style="dim"))
        app = self.app
        try:
            with _c.capture() as cap:
                await handle_command(
                    f"/remote {args}",
                    app.agent,
                    app.token_tracker,
                    self._ss,
                    app.assistant_id,
                    model_name=app.model_name,
                    image_tracker=app.image_tracker,
                )
            out = cap.get().strip()
        except Exception as ex:  # noqa: BLE001
            out = f"Error: {ex}"
        # Native one-line result: take the last meaningful line, color by outcome.
        plain = Text.from_ansi(out).plain.strip()
        last = next(
            (ln.strip() for ln in reversed(plain.splitlines()) if ln.strip()),
            "Done",
        )
        errored = any(x in plain for x in ("❌", "✗", "Error", "error", "No "))
        self.query_one("#remote-result", Static).update(
            Text(last, style="red" if errored else "green")
        )
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close":
            self.dismiss(None)
        elif bid == "start-discord":
            self._run_remote(self._build_args("discord"))
        elif bid == "start-telegram":
            self._run_remote(self._build_args("telegram"))
        elif bid == "test":
            self._run_remote("test")
        elif bid == "stop":
            self._run_remote("stop")

    def action_close(self) -> None:
        self.dismiss(None)


class NovaApp(App):
    """Phase-1 Nova chat TUI."""

    # Colors come from the active Textual theme (default: tokyo-night, registered
    # in on_mount). Do NOT redefine $primary/$surface/etc. here — CSS variable
    # definitions override the theme and break /theme switching.
    CSS = """
    /* --- App chrome --- */
    Screen { background: $background; }

    #transcript { height: 1fr; padding: 1 2; }
    #transcript > .subagent {
        border-left: thick $accent; padding: 0 1;
        margin: 1 0; background: $surface;
    }
    #transcript > .tool { color: $warning; padding: 0 1; margin: 1 0; }
    .toolbody { color: $text-muted; margin: 0; }
    #transcript > .todos {
        border-left: thick $secondary; padding: 0 1;
        margin: 1 0; background: $surface;
    }
    #transcript > .initlog {
        height: auto; border-left: thick $accent;
        padding: 0 1; margin: 1 0; background: $surface;
    }
    #transcript > .logline {
        height: auto; padding: 0 1;
        background: $surface; margin: 1 0;
    }
    #cmdpalette {
        width: 100%;
        height: auto; max-height: 10;
        border: thick $accent; background: $panel;
        padding: 0 1;
        display: none; layer: overlay; dock: bottom;
    }
    #status {
        height: 1; color: $text-muted;
        padding: 0 2; background: $surface;
    }
    #prompt {
        dock: bottom; border: none;
        background: $panel; color: $text;
        padding: 1 3; min-height: 5;
        /* Smooth fade when switching into/out of a mode. */
        transition: background 300ms in_out_cubic;
    }
    #prompt:focus {
        background: $boost;
        border: none;
    }
    /* BASH mode — magenta, thick left bar, urgent. */
    #prompt.bash-mode {
        background: #2a1a2e; color: #d7c4ff;
        border-left: thick #bb9af7;
        border-title-color: #bb9af7;
    }
    #prompt:focus.bash-mode {
        background: #2f1e35;
        border-left: thick #bb9af7;
    }
    /* PLAN mode — blue, thick left bar, calm. */
    #prompt.plan-mode {
        background: #161f33; color: #b4c6ef;
        border-left: thick #7aa2f7;
        border-title-color: #7aa2f7;
    }
    #prompt:focus.plan-mode {
        background: #1b2540;
        border-left: thick #7aa2f7;
    }
    #mode-badge {
        dock: bottom; height: 1;
        padding: 0 3; background: $panel;
        color: $text-muted;
    }
    Screen > .modal-backdrop { background: $surface 50%; }
    /* Every modal centers its box and dims the backdrop. */
    ModalScreen { align: center middle; background: $surface 50%; }
    /* Approval body scrolls within bounds so the choices never get clipped. */
    #modal-body-scroll { height: auto; max-height: 55%; scrollbar-gutter: stable; }
    #choices {
        height: auto; max-height: 8; margin-top: 1;
        border: round $accent; background: $boost;
    }
    #choices:focus { border: round $warning; }
    #modal-box {
        width: 80%; max-width: 110; height: auto; max-height: 90%;
        border: thick $accent; background: $surface;
        padding: 1 2; layer: overlay;
    }
    #modal-title { margin-bottom: 1; padding: 0 1; }
    #modal-body { padding: 0 1; }
    /* Long lists scroll inside the box instead of overflowing the screen. */
    #sessions, #pick-list, #infolist, #mcp-configured, #mcp-presets {
        height: auto; max-height: 60%;
    }
    #modal-buttons {
        height: auto; align: center middle;
        margin-top: 1; padding: 0 0;
    }
    #modal-buttons Button { margin: 0 1; }
    #modal-hint { padding: 0 1; color: $text-muted; }
    Collapsible { margin: 0; }
    Collapsible > .collapsible--title { padding: 0 1; background: $surface; }
    VerticalScroll { scrollbar-gutter: stable; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("escape", "cancel_turn", "Cancel"),
    ]

    def __init__(
        self,
        *,
        agent,
        assistant_id,
        session_state,
        backend,
        token_tracker,
        image_tracker,
        model_name,
        session_manager=None,
        restored_messages=None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.assistant_id = assistant_id
        self.session_state = session_state
        self.backend = backend
        self.token_tracker = token_tracker
        self.image_tracker = image_tracker
        self.model_name = model_name or "unknown"
        self.session_manager = session_manager
        # Prior conversation turns to replay into the transcript on resume.
        self._restored_messages = list(restored_messages or [])
        self._seen: set[str] = set()
        self._live_buf = ""  # accumulating streamed answer prose
        self._reasoning_buf = ""  # accumulating reasoning trace
        self._stream_msg: ChatMessage | None = None  # in-progress Nova answer widget
        self._reason_msg: ChatMessage | None = None  # in-progress reasoning widget
        # call_id -> (collapsible, body Static, base title) for open tool calls
        self._tool_components: dict[str, tuple[Collapsible, Static, str]] = {}
        # fallback for tool calls that arrive without an id
        self._last_tool: tuple[Collapsible, Static, str] | None = None
        # subagent tracking: call_id -> (collapsible, body Static, type, start_time)
        self._subagent_widgets: dict[str, tuple[Collapsible, Static, str, float]] = {}
        self._subagent_count: int = 0  # running total for display
        self._remote_msg: Any = None  # current RemoteMessage during remote turn
        self._todo_widget: Static | None = None  # updated in place per turn
        self._init_widget: Static | None = None  # live /init step tracker widget
        self._init_steps: list[dict] = []
        self._skill_names_cache: list[str] | None = None
        self._agent_names_cache: list[str] | None = None
        # Live status state (animated spinner + elapsed while a turn runs).
        self._activity = "ready"
        self._turn_active = False
        self._turn_start = 0.0
        self._spinner_frame = 0
        # Input mode pulse animation (plan / bash) — see _set_input_pulse.
        self._input_pulse_mode: str | None = None
        self._input_pulse_timer: Any = None
        self._pulse_on = False
        # Notification badge: last seen unread count (drives status refresh).
        self._last_notif_count = 0
        # Context-window management: warn once per crossing; auto-compact at critical.
        self._ctx_warned = False
        self._auto_compact = True
        # Live steering: SteeringInstructions added mid-turn, removed when it ends.
        self._live_steers: list = []

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="transcript")
        yield Static("", id="status")
        yield Static("", id="mode-badge")
        yield Input(
            placeholder="Ask Nova…  (/help · !cmd · @agent · /quit to exit)",
            id="prompt",
        )
        yield OptionList(id="cmdpalette")

    def _apply_saved_theme(self) -> None:
        """Register Nova's palette and apply the persisted theme (or default)."""
        try:
            self.register_theme(NOVA_TOKYO_NIGHT)
        except Exception:  # noqa: BLE001
            pass
        name = DEFAULT_THEME
        try:
            from novacode_cli.config.nova_config import NovaConfig

            saved = NovaConfig().get("theme")
            if saved and saved in self.available_themes:
                name = saved
        except Exception:  # noqa: BLE001
            pass
        try:
            self.theme = name
        except Exception:  # noqa: BLE001
            pass

    def on_mount(self) -> None:
        # Register Nova's palette and apply the saved (or default) theme first,
        # so the whole UI renders with the right colors from the first frame.
        self._apply_saved_theme()
        self.query_one("#cmdpalette", OptionList).display = False
        self._set_status("ready")
        self._update_mode_badge()
        # Animate the live status (~5 fps) while a turn is active.
        self.set_interval(0.2, self._tick)
        self.query_one("#prompt", Input).focus()
        # Show ASCII art banner on home screen
        try:
            art = get_responsive_ascii(_rich_console)
            if art.strip():
                self._log(Text(art, style="bold #7aa2f7"))
        except Exception:  # noqa: BLE001
            pass
        # Native startup panel (model / cwd / sandbox / memory / web-search).
        self._render_startup_info()
        # Replay prior conversation when resuming a session.
        self._replay_history()
        # Route remote bridge status messages into the transcript (not stdout).
        mgr = getattr(self.session_state, "_remote_bridge_manager", None)
        if mgr is not None:
            async def _status_cb(m: str) -> None:
                self._log(Text(f"🔗 Remote: {m}", style="dim"))

            try:
                mgr.set_status_callback(_status_cb)
            except Exception:  # noqa: BLE001
                pass
        # Consume remote (Discord/Telegram) messages and render them in the TUI.
        if getattr(self.session_state, "_remote_message_queue", None) is not None:
            self._remote_consumer()
        self._log(Text(f"Nova TUI · model: {self.model_name}", style="dim"))
        if not self.session_state.auto_approve:
            self._log(
                Text(
                    "Tool actions will prompt for approval. Run with --auto-approve "
                    "to skip prompts.",
                    style="dim",
                )
            )

    # -- helpers --------------------------------------------------------------
    def _scroll_end(self) -> None:
        self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)

    async def _mount(self, widget) -> None:
        await self.query_one("#transcript", VerticalScroll).mount(widget)
        self._scroll_end()

    def _remote_send(self, text: str) -> None:
        """Send a status update to the remote platform during a remote turn."""
        msg = self._remote_msg
        if msg is None:
            return
        try:
            import asyncio
            asyncio.create_task(msg.reply_fn(f"{text}"))
        except Exception:  # noqa: BLE001
            pass

    def _log(self, renderable: Any) -> None:
        """Mount an ancillary line (errors, command output, notices)."""
        self.query_one("#transcript", VerticalScroll).mount(
            Static(renderable, classes="logline")
        )
        self._scroll_end()

    _INIT_STEP_GLYPH = {
        "done": ("✓", "green"),
        "active": ("▶", "yellow"),
        "pending": ("☐", "dim"),
        "fail": ("✗", "red"),
    }

    def _init_render_steps(self) -> None:
        if self._init_widget is None:
            return
        t = Text()
        t.append("NOVA.md initialization\n", style="bold")
        for st in self._init_steps:
            glyph, color = self._INIT_STEP_GLYPH[st["status"]]
            t.append(f"  {glyph} {st['label']}", style=color)
            if st["detail"]:
                t.append(f"  — {st['detail']}", style="dim")
            t.append("\n")
        self._init_widget.update(t)
        self._scroll_end()

    def _init_finish(self) -> None:
        """Mark any remaining steps done (called when the pipeline returns)."""
        for st in self._init_steps:
            if st["status"] in ("active", "pending"):
                st["status"] = "done"
        self._init_render_steps()

    def _init_emit(self, line: str) -> None:
        """Parse a pipeline progress line into the native step tracker."""
        if self._init_widget is None:
            return
        import re

        plain = Text.from_ansi(line).plain.strip()
        if not plain:
            return
        m = re.match(r"Step\s+(\d+)\s*/\s*\d+\s*:?\s*(.*)", plain)
        if m:
            n = int(m.group(1))
            title = m.group(2).strip().rstrip(".")
            for i, st in enumerate(self._init_steps):
                if i < n - 1:
                    st["status"] = "done"
                elif i == n - 1:
                    st["status"] = "active"
                    if title:
                        st["label"] = title
                    st["detail"] = ""
            self._init_render_steps()
            return
        # Non-step line: attach as detail of the active step (or flag a failure).
        active = next((s for s in self._init_steps if s["status"] == "active"), None)
        if active is not None:
            if any(x in plain for x in ("❌", "✗")) or "failed" in plain.lower():
                active["status"] = "fail"
            active["detail"] = plain[:80]
            self._init_render_steps()

    async def _add_message(self, label: Text, role_class: str, body: Any) -> ChatMessage:
        msg = ChatMessage(label, role_class)
        await self._mount(msg)
        msg.update_body(body)
        return msg

    @staticmethod
    def _message_text(msg: Any) -> str:
        """Extract displayable text from a LangChain message's content."""
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts)
        return str(content)

    def _render_startup_info(self) -> None:
        """Render a compact native session-info panel (replaces the legacy
        pre-TUI Rich panels, which never appeared in TUI mode)."""
        from pathlib import Path

        try:
            from novacode_cli.config.config import settings
        except Exception:  # noqa: BLE001
            return

        t = Text()
        t.append("session\n", style="bold")
        t.append("  model: ", style="dim")
        t.append(f"{self.model_name}\n", style="cyan")

        sandbox_type = getattr(self.session_state, "_sandbox_type", None)
        if sandbox_type:
            try:
                from novacode_cli.integrations.sandbox_factory import (
                    get_default_working_dir,
                )

                wd = get_default_working_dir(sandbox_type)
            except Exception:  # noqa: BLE001
                wd = "?"
            t.append("  sandbox: ", style="dim")
            t.append(f"{sandbox_type} ({wd})\n", style="yellow")
            t.append(f"  local dir: {Path.cwd()}\n", style="dim")
        else:
            t.append("  sandbox: ", style="dim")
            t.append("local\n", style="dim")
            t.append(f"  cwd: {Path.cwd()}\n", style="dim")

        # Memory status (agent.md / project memory).
        try:
            aid = self.assistant_id
            has_user = bool(aid) and settings.get_user_agent_md_path(aid).exists()
            proj = settings.get_project_agent_md_paths()
            if has_user or proj:
                parts = []
                if has_user:
                    parts.append(f"~/.nova/agents/{aid}/agent.md")
                if proj:
                    parts.append("project: " + ", ".join(p.name for p in proj))
                t.append(f"  memory: {' · '.join(parts)}\n", style="dim")
            else:
                t.append("  memory: none (use /init to create project memory)\n", style="dim")
        except Exception:  # noqa: BLE001
            pass

        # Web search availability.
        try:
            if not settings.has_tavily:
                t.append(
                    "  ⚠ web search disabled — set TAVILY_API_KEY to enable\n",
                    style="#e0af68",
                )
        except Exception:  # noqa: BLE001
            pass

        self._log(t)

    @work
    async def _replay_history(self) -> None:
        """Replay restored conversation turns into the transcript on resume.

        Renders the prior Human/AI turns (skipping system + tool noise) so a
        resumed session *shows* its history. The agent's own state is restored
        separately via the checkpointer / continuation prompt.
        """
        msgs = self._restored_messages
        if not msgs:
            return
        # Only render real conversation turns, oldest first.
        shown = 0
        for m in msgs:
            role = getattr(m, "type", "") or ""
            text = self._message_text(m).strip()
            if not text:
                continue
            if role == "human":
                await self._add_message(
                    Text("You", style="bold cyan"), "user", Markdown(text)
                )
                shown += 1
            elif role == "ai":
                await self._add_message(
                    Text("Nova", style="green"), "nova", Markdown(text)
                )
                shown += 1
        if shown:
            self._log(
                Text(
                    f"⟲ Resumed — {shown} earlier message(s) restored above",
                    style="dim",
                )
            )

    def _reset_streaming(self) -> None:
        """Drop any in-progress streaming/reasoning widgets at a turn boundary."""
        for ref in (self._stream_msg, self._reason_msg):
            if ref is not None:
                try:
                    ref.remove()  # fire-and-forget
                except Exception:  # noqa: BLE001
                    pass
        self._stream_msg = None
        self._reason_msg = None
        self._live_buf = ""
        self._reasoning_buf = ""
        self._tool_components.clear()
        self._last_tool = None
        self._subagent_widgets.clear()
        self._subagent_count = 0
        self._todo_widget = None  # next turn starts a fresh todo block

    @staticmethod
    def _render_todos(todos: list, agent_name: str | None) -> Text:
        """Native todo list: status glyphs + content (no legacy panel)."""
        glyphs = {
            "completed": ("☑", "green"),
            "in_progress": ("▶", "yellow"),
            "pending": ("☐", "dim"),
        }
        t = Text()
        header = f"{agent_name} · Todos" if agent_name else "Todos"
        t.append(f"{header}\n", style="bold")
        for td in todos or []:
            if isinstance(td, dict):
                content = td.get("content", "")
                status = td.get("status", "pending")
            else:
                content, status = str(td), "pending"
            glyph, color = glyphs.get(status, ("☐", "dim"))
            t.append(f"  {glyph} ", style=color)
            t.append(
                f"{content}\n",
                style="strike dim" if status == "completed" else "",
            )
        return t

    def _pop_tool(
        self, call_id: str | None
    ) -> "tuple[Collapsible, Static, str] | None":
        """Find (and stop tracking) the tool component for a result."""
        entry = None
        if call_id and call_id in self._tool_components:
            entry = self._tool_components.pop(call_id)
        elif self._last_tool is not None:
            entry = self._last_tool
        if entry is not None and entry is self._last_tool:
            self._last_tool = None
        return entry

    @staticmethod
    def _render_diff_text(diff: str, max_lines: int = 500) -> Text:
        """Render a unified diff natively with +/- coloring (no legacy capture)."""
        t = Text()
        lines = diff.splitlines()
        for line in lines[:max_lines]:
            if line.startswith(("+++", "---")):
                t.append(line + "\n", style="dim")
            elif line.startswith("@@"):
                t.append(line + "\n", style="cyan")
            elif line.startswith("+"):
                t.append(line + "\n", style="green")
            elif line.startswith("-"):
                t.append(line + "\n", style="red")
            else:
                t.append(line + "\n", style="dim")
        if len(lines) > max_lines:
            t.append(f"… {len(lines) - max_lines} more lines\n", style="dim italic")
        return t

    def _fileop_body(self, rec, full_output: str) -> Text:
        """Native body for a file-op component: diff for writes/edits, content for reads."""
        diff = getattr(rec, "diff", None) if rec is not None else None
        if diff:
            return self._render_diff_text(diff)
        after = getattr(rec, "after_content", None) if rec is not None else None
        if after:  # write with no diff — show the new content as additions
            return self._render_diff_text(
                "\n".join("+" + ln for ln in after.splitlines())
            )
        out = (
            full_output
            or (getattr(rec, "read_output", None) if rec is not None else None)
            or "(no output)"
        )
        if len(out) > 6000:
            out = out[:6000] + "\n… (truncated)"
        return Text(out)

    def _fileop_summary(self, rec) -> str:
        """A concise '+A / -D' (or 'Read N lines') summary for a file-op title."""
        if rec is None:
            return ""
        tn = getattr(rec, "tool_name", "")
        m = getattr(rec, "metrics", None)
        added = getattr(m, "lines_added", 0) or 0
        removed = getattr(m, "lines_removed", 0) or 0
        if tn == "read_file":
            n = getattr(m, "lines_written", 0) or added
            return f"Read {n} lines" if n else "Read"
        return f"+{added} / -{removed}"

    def _finalize_tool(
        self, call_id: str | None, preview: str, full_output: str, *, is_error: bool
    ) -> None:
        entry = self._pop_tool(call_id)
        if entry is None:
            self._log(Text(f"  ⎿  {preview}", style="red" if is_error else "dim"))
            return
        comp, body, base = entry
        mark = "✗" if is_error else "✓"
        comp.title = f"{base}  {mark} {_esc(preview)}"
        out = full_output or "(no output)"
        if len(out) > 6000:
            out = out[:6000] + "\n… (truncated)"
        body.update(Text(out, style="red" if is_error else ""))

    async def _handle_subagent(self, e: ev.SubagentActivity) -> None:
        """Render subagent dispatch and completion with collapsible widgets."""
        import time

        cid = e.call_id or ""
        color = e.color or "#bb9af7"

        if e.kind == "dispatched" and cid:
            self._subagent_count += 1
            label = f"⟐ {e.subagent_type or 'subagent'}"
            title = Text.assemble(
                (label, f"bold {color}"),
                (f"  · #{self._subagent_count} dispatched", "dim"),
            )
            body_text = Text(e.detail or "", style="dim") if e.detail else Text("")
            body = Static(body_text, classes="toolbody")
            comp = Collapsible(body, title=title, collapsed=False)
            comp.add_class("subagent")
            await self._mount(comp)
            self._subagent_widgets[cid] = (comp, body, e.subagent_type or "subagent", time.time())
            # Stream to remote
            desc = f" — {e.detail}" if e.detail else ""
            self._remote_send(f"🔍 {e.subagent_type or 'subagent'} dispatched{desc}")

        elif e.kind == "completed":
            # Try matching by call_id first, then fallback to subagent_type
            entry = None
            matched_cid = cid
            if cid and cid in self._subagent_widgets:
                entry = self._subagent_widgets.pop(cid)
            else:
                # Fallback: find first matching by subagent type
                for key, val in list(self._subagent_widgets.items()):
                    if val[2] == (e.subagent_type or ""):
                        entry = self._subagent_widgets.pop(key)
                        matched_cid = key
                        break

            if entry is not None:
                comp, body, stype, start_time = entry
                elapsed = time.time() - start_time
                dur = f"{elapsed:.1f}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
                icon = e.message or f"{e.subagent_type}"
                count = len(self._subagent_widgets)
                remaining = f" · {count} active" if count > 0 else ""
                comp.title = f"{_esc(str(icon))}  ({dur}){remaining}"
                if e.detail:
                    body.update(Text(e.detail, style="dim"))
                else:
                    body.update(Text(""))
                comp.collapsed = True
                # Stream to remote
                detail_str = f" — {e.detail}" if e.detail else ""
                self._remote_send(f"✅ {icon} completed ({dur}){detail_str}")
            else:
                # No matching widget — log as a simple line
                dur_part = ""
                if e.detail:
                    dur_part = f" — {e.detail}"
                self._log(Text(f"{e.message}{dur_part}", style=color))

        elif e.kind == "status" and e.message:
            self._log(Text(f"  ⟐ {e.message}", style=color))

    async def _remove_reasoning(self) -> None:
        if self._reason_msg is not None:
            try:
                await self._reason_msg.remove()
            except Exception:  # noqa: BLE001
                pass
            self._reason_msg = None
        self._reasoning_buf = ""

    _SPINNER = "▖▘▙▚▛▜▝▞▟"

    def _set_status(self, activity: str) -> None:
        self._activity = activity
        self._refresh_status()

    def _refresh_status(self) -> None:
        pct = ""
        if self.token_tracker is not None:
            try:
                bd = self.token_tracker.get_breakdown()
                if bd:
                    pct = f" · ctx {bd.usage_percentage:.0f}%"
            except Exception:  # noqa: BLE001
                pass
        if self._turn_active:
            frame = self._SPINNER[self._spinner_frame % len(self._SPINNER)]
            elapsed = time.monotonic() - self._turn_start
            activity = f"{frame} {self._activity} · {elapsed:0.1f}s"
        else:
            activity = self._activity
        line = Text(f"[{self.model_name}]{pct} · {activity}", style="dim")
        notif = self._unread_count()
        if notif:
            line.append("  🔔 ", style="bold #e0af68")
            line.append(str(notif), style="bold #e0af68")
        self.query_one("#status", Static).update(line)

    def _unread_count(self) -> int:
        """Unread notification count (0 on any error)."""
        try:
            return self.session_state.unread_notification_count()
        except Exception:  # noqa: BLE001
            return 0

    def _tick(self) -> None:
        refresh = False
        if self._turn_active:
            self._spinner_frame += 1
            refresh = True
        # Surface notifications raised by background tasks within ~200ms.
        cur = self._unread_count()
        if cur != self._last_notif_count:
            self._last_notif_count = cur
            refresh = True
        if refresh:
            self._refresh_status()

    # -- input ----------------------------------------------------------------
    def _update_mode_badge(self, input_value: str = "") -> None:
        """Show a mode badge and restyle/animate the input for plan/bash modes.

        Bash takes visual precedence over plan when both apply (you can be in
        plan mode and still type a ``!command``). Styling is driven by CSS
        classes (``bash-mode`` / ``plan-mode``) plus a per-mode pulse so each
        mode has a distinct look *and* a distinct animation.
        """
        badge = self.query_one("#mode-badge", Static)
        prompt = self.query_one("#prompt", Input)
        plan = getattr(self.session_state, "plan_mode_enabled", False)
        bash = input_value.startswith("!")

        if plan and bash:
            t = Text()
            t.append("  ⏸ PLAN  ", style="bold #7aa2f7")
            t.append("$ BASH — runs in your shell", style="bold #bb9af7")
            badge.update(t)
        elif plan:
            badge.update(
                Text("  ⏸ PLAN MODE — proposing, not editing", style="bold #7aa2f7")
            )
        elif bash:
            badge.update(Text("  $ BASH — runs in your shell", style="bold #bb9af7"))
        else:
            badge.update("")

        # Drive the input look from CSS classes (bash wins over plan visually).
        prompt.set_class(bash, "bash-mode")
        prompt.set_class(plan and not bash, "plan-mode")
        prompt.border_title = "BASH" if bash else ("PLAN" if plan else "")

        # Distinct animation per mode.
        self._set_input_pulse("bash" if bash else ("plan" if plan else None))

    def _set_input_pulse(self, mode: str | None) -> None:
        """Animate the input's tint with a per-mode pulse (no-op if unchanged).

        - bash: quick, urgent magenta pulse
        - plan: slow, calm blue "breathing"
        - None: stop and clear the tint
        """
        if mode == self._input_pulse_mode:
            return
        self._input_pulse_mode = mode

        if self._input_pulse_timer is not None:
            self._input_pulse_timer.stop()
            self._input_pulse_timer = None

        try:
            prompt = self.query_one("#prompt", Input)
        except Exception:  # noqa: BLE001
            return

        if mode is None:
            # Smoothly fade the tint away.
            prompt.styles.animate(
                "tint", value=Color(0, 0, 0, 0.0), duration=0.3
            )
            return

        if mode == "bash":
            glow = Color.parse("#bb9af7")
            period = 0.55  # fast, alert
            peak = 0.22
        else:  # plan
            glow = Color.parse("#7aa2f7")
            period = 1.1  # slow, calm
            peak = 0.16

        self._pulse_on = False

        def _tick() -> None:
            self._pulse_on = not self._pulse_on
            alpha = peak if self._pulse_on else 0.02
            try:
                prompt.styles.animate(
                    "tint", value=glow.with_alpha(alpha), duration=period * 0.85
                )
            except Exception:  # noqa: BLE001
                pass

        _tick()  # kick off immediately
        self._input_pulse_timer = self.set_interval(period, _tick)

    # -- autocomplete dropdown ------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        self._update_palette(event.value)
        self._update_mode_badge(event.value)

    def _palette_candidates(self, value: str) -> list[str]:
        """Completion candidates for the current input, by trigger context."""
        if " " in value or not value:
            return []
        v = value.lower()
        # /skill:<name> — invoke a skill
        if value.startswith("/skill:"):
            return [
                f"/skill:{n}"
                for n in self._get_skill_names()
                if f"/skill:{n}".lower().startswith(v)
            ]
        # @<agent> — delegate to a subagent
        if value.startswith("@"):
            return [
                f"@{n}"
                for n in self._get_agent_names()
                if f"@{n}".lower().startswith(v)
            ]
        # /<command>
        if value.startswith("/"):
            return [c for c in _TUI_SLASH_COMMANDS if c.startswith(v)]
        return []

    def _update_palette(self, value: str) -> None:
        palette = self.query_one("#cmdpalette", OptionList)
        matches = self._palette_candidates(value)
        if matches and not (len(matches) == 1 and matches[0] == value.lower()):
            palette.clear_options()
            for c in matches:
                palette.add_option(Option(c))
            palette.display = True
            try:
                palette.highlighted = 0
            except Exception:  # noqa: BLE001
                pass
        else:
            self._hide_palette()

    def _hide_palette(self) -> None:
        palette = self.query_one("#cmdpalette", OptionList)
        palette.clear_options()
        palette.display = False

    def _accept_palette(self, command: str) -> None:
        inp = self.query_one("#prompt", Input)
        inp.value = f"{command} "
        inp.cursor_position = len(inp.value)
        self._hide_palette()
        inp.focus()

    def on_key(self, event) -> None:
        palette = self.query_one("#cmdpalette", OptionList)
        if not palette.display:
            return
        if event.key == "down":
            palette.action_cursor_down()
        elif event.key == "up":
            palette.action_cursor_up()
        elif event.key == "escape":
            self._hide_palette()
            event.stop()
            event.prevent_default()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        # Mouse-click accept from the command palette (other lists handle their own).
        if event.option_list.id == "cmdpalette":
            self._accept_palette(str(event.option.prompt))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Only react to the main prompt (modals have their own inputs).
        if event.input.id != "prompt":
            return
        # If the palette is open, Enter accepts the highlighted command.
        palette = self.query_one("#cmdpalette", OptionList)
        if (
            palette.display
            and palette.option_count
            and palette.highlighted is not None
        ):
            opt = palette.get_option_at_index(palette.highlighted)
            self._accept_palette(str(opt.prompt))
            return
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self._hide_palette()
        # While the agent is working, a submitted prompt steers the current run
        # (injected for its next step) instead of cancelling it or starting a new
        # turn. Esc still cancels. Empty turns route normally.
        if self._turn_active:
            self._add_live_steer(text)
            return
        self._dispatch(text)

    def _add_live_steer(self, text: str) -> None:
        """Inject a transient steering instruction into the in-flight turn.

        The agent's SteeringMiddleware reads ``session_state.steering_instructions``
        on every model call, so appending here makes the running agent pick this
        up at its next step. The instruction is removed when the turn ends
        (one-turn lifetime) so it doesn't leak into later turns.
        """
        from novacode_cli.bootstrap.steering import SteeringInstruction

        if getattr(self.session_state, "steering_instructions", None) is None:
            self.session_state.steering_instructions = []
        si = SteeringInstruction(label="steer", instruction=text)
        self.session_state.steering_instructions.append(si)
        self._live_steers.append(si)
        self._log(
            Text(f"↗ Steering (applies on the next step): {text}", style="italic #7aa2f7")
        )

    def action_cancel_turn(self) -> None:
        self.workers.cancel_all()
        self._set_status("cancelling…")

    async def action_quit(self) -> None:
        """Persist the session (so --continue works) then exit."""
        await self._save_session()
        self.exit()

    async def _save_session(self) -> None:
        """Save the conversation to disk via the session manager (best effort)."""
        if self.session_manager is None:
            return
        try:
            from pathlib import Path

            config = {"configurable": {"thread_id": self.session_state.thread_id}}
            # Bound the checkpointer read so a slow/contended DB can't hang /quit.
            state = await asyncio.wait_for(self.agent.aget_state(config), timeout=5.0)
            messages = state.values.get("messages", [])
            if not messages:
                return
            todos = state.values.get("todos") or getattr(
                self.session_state, "todos", None
            )
            # save_session does several synchronous file writes — run it off the
            # event loop so /save, /clear, and quit don't freeze the UI.
            await asyncio.to_thread(
                self.session_manager.save_session,
                session_id=self.session_state.session_id,
                thread_id=self.session_state.thread_id,
                messages=messages,
                assistant_id=self.assistant_id,
                todos=todos,
                model_name=self.model_name,
                project_root=Path.cwd(),
            )
        except Exception:  # noqa: BLE001
            pass  # never block exit on a save failure

    # -- input routing --------------------------------------------------------
    @work(exclusive=True, group="turn")
    async def _dispatch(self, text: str) -> None:
        """Route input: quit / !bash / slash command / @agent / agent prompt."""
        low = text.lower()
        if low in ("/quit", "/exit", "quit", "exit", "q"):
            await self.action_quit()
            return

        if text.startswith("!"):
            await self._run_bash(text)
            return

        if text.startswith("/"):
            await self._run_slash(text)
            return

        # @agent mention -> route through the main agent's task tool.
        try:
            from novacode_cli.config.config import settings
            from novacode_cli.input import parse_agent_mentions

            agent_name, query = parse_agent_mentions(text, settings)
        except Exception:  # noqa: BLE001
            agent_name, query = None, text
        if agent_name:
            await self._add_message(
                Text(f"You → @{agent_name}", style="bold cyan"), "user", Text(query)
            )
            await self._stream_prompt(
                f"Call the '{agent_name}' subagent to do the following:\n\n{query}"
            )
            return

        # Plain prompt. Decompose multi-intent requests into sequential turns.
        await self._add_message(Text("You", style="bold cyan"), "user", Text(text))
        sub_prompts = [text]
        try:
            from novacode_cli.prompt_decomposer import decompose_prompt

            if getattr(self.session_state, "prompt_decomposition_enabled", True):
                decomp = decompose_prompt(text)
                if decomp.decomposed:
                    sub_prompts = decomp.sub_prompts
                    self._log(
                        Text(
                            f"Split into {len(sub_prompts)} steps.", style="dim"
                        )
                    )
        except Exception:  # noqa: BLE001
            pass

        for sub_prompt in sub_prompts:
            await self._stream_prompt(sub_prompt)
        # If a plan was approved during this turn, hand off to the main agent.
        await self._maybe_run_approved_plan()

    async def _stream_prompt(self, text: str) -> None:
        """Run a single prompt through the agent and render its events.

        Serialized on the shared remote lock so local and remote turns never
        interleave on the same checkpointer thread.
        """
        lock = getattr(self.session_state, "_remote_message_lock", None)
        self._reset_streaming()
        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status("thinking…")
        try:
            if lock is not None:
                async with lock:
                    await self._do_stream(text)
            else:
                await self._do_stream(text)
        except asyncio.CancelledError:
            self._reset_streaming()
            self._log(Text("Cancelled.", style="yellow"))
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Error: {ex}", style="red"))
        finally:
            self._turn_active = False
            self._set_status("ready")
            self._clear_live_steers()
        # Proactively manage the context window once the turn has settled.
        await self._check_context()

    def _clear_live_steers(self) -> None:
        """Drop transient live-steer instructions added during the turn."""
        if not self._live_steers:
            return
        instrs = getattr(self.session_state, "steering_instructions", None) or []
        for si in self._live_steers:
            try:
                instrs.remove(si)
            except ValueError:
                pass
        self._live_steers.clear()

    async def _check_context(self) -> None:
        """Warn (and optionally auto-compact) as the context window fills up.

        The TUI previously showed ctx% passively but never nudged — so a long
        session could silently approach the model's limit and then error. Here we
        warn once at the warning threshold and, at critical, auto-compact to
        avoid a hard overflow on the next turn.
        """
        if self.token_tracker is None:
            return
        try:
            bd = self.token_tracker.get_breakdown()
        except Exception:  # noqa: BLE001
            return
        if not bd:
            return
        pct = getattr(bd, "usage_percentage", 0.0)
        if getattr(bd, "is_critical", False):
            if self._auto_compact:
                self._log(
                    Text(
                        f"⚠ Context {pct:.0f}% — auto-compacting to free space…",
                        style="bold #f7768e",
                    )
                )
                await self._run_compact("")
            else:
                self._log(
                    Text(
                        f"⚠ Context critical: {pct:.0f}% — run /compact now to avoid errors.",
                        style="bold #f7768e",
                    )
                )
            self._ctx_warned = True
        elif getattr(bd, "is_warning", False):
            if not self._ctx_warned:
                self._ctx_warned = True
                self._log(
                    Text(
                        f"⚠ Context usage high: {pct:.0f}% — consider /compact soon.",
                        style="#e0af68",
                    )
                )
        else:
            # Dropped back below the warning line (e.g. after /compact) — re-arm.
            self._ctx_warned = False

    async def _do_stream(self, text: str) -> None:
        ag, backend = self._active_agent()
        async for e in run_agent_stream(
            text,
            ag,
            self.assistant_id,
            self.session_state,
            backend=backend,
            image_tracker=self.image_tracker,
            seen_message_ids=self._seen,
        ):
            await self._render(e)

    @work(group="remote")
    async def _remote_consumer(self) -> None:
        """Render remote (Discord/Telegram) prompts in the TUI and reply back.

        Mirrors the legacy remote processor but streams through the TUI instead
        of the console. Turn serialization is handled by ``_stream_prompt``'s
        lock (shared with local input)."""
        import asyncio

        from novacode_cli.remote.processor import _extract_response

        queue = self.session_state._remote_message_queue
        while True:
            try:
                msg = await queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._add_message(
                    Text(
                        f"📡 {msg.user_name} ({msg.platform.value})",
                        style="bold cyan",
                    ),
                    "user",
                    Text(msg.text),
                )
                # Remote turns auto-approve tools (no local prompt to answer).
                prev_auto = getattr(self.session_state, "auto_approve", False)
                self.session_state.auto_approve = True
                config = {"configurable": {"thread_id": self.session_state.thread_id}}
                try:
                    # Trigger typing indicator on the remote platform
                    if msg.typing_fn is not None:
                        try:
                            import asyncio
                            asyncio.create_task(msg.typing_fn())
                        except Exception:  # noqa: BLE001
                            pass
                    self._remote_msg = msg
                    pre = await self.agent.aget_state(config)
                    pre_count = len(pre.values.get("messages", [])) if pre else 0
                    await self._stream_prompt(msg.text)
                    post = await self.agent.aget_state(config)
                    reply = _extract_response(post, pre_count) or "✅ Task completed."
                    try:
                        await msg.reply_fn(reply)
                    except Exception:  # noqa: BLE001
                        pass
                finally:
                    self._remote_msg = None
                    self.session_state.auto_approve = prev_auto
            except asyncio.CancelledError:
                self._log(Text("Remote turn cancelled.", style="yellow"))
            except Exception as ex:  # noqa: BLE001
                self._log(Text(f"Remote error: {ex}", style="red"))
            finally:
                queue.task_done()

    async def _run_bash(self, text: str) -> None:
        """Run a ``!`` shell command and show output in the transcript."""
        import asyncio
        from pathlib import Path

        cmd = text[1:].strip()
        if not cmd:
            return

        # Show the command being run
        self._log(Text(f"$ {cmd}", style="bold #e0af68"))

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.cwd(),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=30
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self._log(Text("Command timed out after 30 seconds.", style="red"))
                self.query_one("#prompt", Input).focus()
                return

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            # Build output, limit total size to avoid rendering issues
            lines: list[str] = []
            if stdout.strip():
                lines.append(stdout.rstrip())
            if stderr.strip():
                lines.append(stderr.rstrip())
            out_text = "\n".join(lines)
            if len(out_text) > 10000:
                out_text = out_text[:10000] + "\n… (output truncated)"

            if out_text:
                style = "red" if proc.returncode != 0 else ""
                self._log(Text(out_text, style=style))
            elif proc.returncode != 0:
                self._log(Text(f"Exit code: {proc.returncode}", style="red"))
        except asyncio.CancelledError:
            self._log(Text("Bash command cancelled.", style="yellow"))
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Error: {ex}", style="red"))
        finally:
            self.query_one("#prompt", Input).focus()

    async def _run_slash(self, text: str) -> None:
        """Handle the TUI-native slash command subset."""
        cmd = text[1:].split(maxsplit=1)[0].lower() if len(text) > 1 else ""
        if cmd.startswith("skill:"):
            # /skill:<name> — invoke via the legacy handler (returns a prompt).
            await self._passthrough_command(text)
        elif cmd in ("help", "?"):
            self._log(self._help_text())
        elif cmd == "model":
            await self._run_model()
        elif cmd == "sessions":
            await self._run_sessions()
        elif cmd == "mcp":
            await self._run_mcp()
        elif cmd == "init":
            await self._run_init(text)
        elif cmd == "remote":
            await self.push_screen_wait(RemoteScreen(self.session_state))
        elif cmd == "agents":
            await self._run_agents()
        elif cmd == "skills":
            await self._run_skills()
        elif cmd == "clear":
            await self._run_clear()
        elif cmd == "theme":
            await self.push_screen_wait(ThemeScreen())
        elif cmd == "tokens" or cmd == "context" or cmd == "cost":
            self._log(self._token_text())
        elif cmd == "verbose":
            new = self.session_state.toggle_verbose()
            self._log(
                Text(
                    f"Verbose mode {'on' if new else 'off'} — internal context "
                    f"{'shown' if new else 'collapsed'}.",
                    style="green" if new else "dim",
                )
            )
        elif cmd == "decompose":
            cur = getattr(self.session_state, "prompt_decomposition_enabled", True)
            self.session_state.prompt_decomposition_enabled = not cur
            new = self.session_state.prompt_decomposition_enabled
            self._log(
                Text(
                    f"Prompt decomposition {'on' if new else 'off'}.",
                    style="green" if new else "dim",
                )
            )
        elif cmd == "trace":
            await self._run_trace(text)
        elif cmd == "log":
            await self._run_log(text)
        elif cmd == "plan":
            await self._run_plan(text)
        elif cmd == "compact":
            await self._run_compact(text)
        elif cmd == "save":
            await self._run_save()
        elif cmd == "steer":
            await self._run_steer(text)
        elif cmd == "notifications":
            await self._run_notifications(text)
        elif cmd == "research":
            await self._run_research(text)
        elif cmd == "dream":
            await self._run_dream()
        elif cmd == "reindex":
            await self._run_reindex()
        elif cmd == "images":
            await self._run_images(text)
        elif cmd == "vision":
            await self._run_vision(text)
        elif cmd == "files":
            await self._run_files()
        elif cmd == "tests":
            await self._run_tests(text)
        elif cmd == "servers":
            await self._run_servers()
        elif cmd == "kill":
            await self._run_kill(text)
        elif cmd == "restore":
            await self._run_restore(text)
        elif cmd == "hooks":
            await self._run_hooks(text)
        elif cmd == "browser-use":
            await self._run_browser_use(text)
        elif cmd == "ralph":
            await self._run_ralph(text)
        elif cmd == "trello":
            await self._run_trello(text)
        elif cmd in _PASSTHROUGH_SLASH:
            await self._passthrough_command(text)
        else:
            self._log(
                Text(
                    f"/{cmd} isn't available in --tui yet. "
                    "Use --legacy-ui for the full command set.",
                    style="yellow",
                )
            )

    async def _passthrough_command(self, text: str) -> None:
        """Run a print/toggle-only legacy slash command and show its output.

        Captures the global console so the existing handler's ``console.print``
        calls render into the transcript instead of the real terminal.
        """
        from novacode_cli.commands.commands import handle_command

        try:
            with _rich_console.capture() as cap:
                result = await handle_command(
                    text,
                    self.agent,
                    self.token_tracker,
                    self.session_state,
                    self.assistant_id,
                    model_name=self.model_name,
                    image_tracker=self.image_tracker,
                )
            out = cap.get()
            if out.strip():
                self._log(Text.from_ansi(out))
            # Some handlers return a prompt string to feed back to the agent.
            if isinstance(result, str):
                await self._stream_prompt(result)
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"/{text[1:].split()[0]} failed: {ex}", style="red"))

    async def _run_model(self) -> None:
        """Native /model: choose provider + model, store key, hot-swap the agent."""
        import os

        from novacode_cli.config.model_manager import MODEL_PRESETS, ModelManager

        mm = ModelManager()
        configured = {pid for pid, _ in mm.get_available_providers()}
        current = mm.get_current_provider()  # (display_name, model) | None
        current_id = None
        if current:
            for pid, preset in MODEL_PRESETS.items():
                if preset["name"] == current[0]:
                    current_id = pid
                    break

        result = await self.push_screen_wait(ModelScreen(current_id, configured))
        if not result:
            return

        provider = result["provider"]
        preset = MODEL_PRESETS[provider]
        model = result["model"] or preset["default_model"]
        key = result["api_key"]

        # Ensure the API key is present in the environment (model creation reads
        # os.environ). Store a newly entered key in the keychain.
        if preset["requires_api_key"]:
            from novacode_cli.onboarding import SecretManager

            sm = SecretManager()
            key_name = preset["api_key_var"].lower()
            existing = sm.get_secret(key_name) or os.environ.get(preset["api_key_var"])
            if key:
                sm.store_secret(key_name, key)
                os.environ[preset["api_key_var"]] = key
            elif existing:
                os.environ[preset["api_key_var"]] = existing
            else:
                self._log(
                    Text(f"{preset['name']} requires an API key.", style="red")
                )
                return

        mm.set_provider(provider, model)
        try:
            from novacode_cli.config.model_create import create_model

            new_model = create_model()
            new_agent, new_backend = await self.session_state.switch_model(new_model)
            self.agent = new_agent
            self.backend = new_backend
            self.model_name = getattr(new_model, "model_name", None) or getattr(
                new_model, "model", "unknown"
            )
            if self.token_tracker is not None:
                try:
                    self.token_tracker.set_model(self.model_name)
                except Exception:  # noqa: BLE001
                    pass
            self._set_status("ready")
            self._log(
                Text(
                    f"✓ Switched to {preset['name']} · {self.model_name}",
                    style="green",
                )
            )
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Model switch failed: {ex}", style="red"))

    async def _run_sessions(self) -> None:
        """Open the saved-sessions screen (list + delete)."""
        from novacode_cli.session.session_persistence import SessionManager

        sm = self.session_manager or SessionManager()
        await self.push_screen_wait(
            SessionsScreen(sm, getattr(self.session_state, "session_id", None))
        )

    async def _run_mcp(self) -> None:
        """Open the MCP servers screen (view + remove)."""
        await self.push_screen_wait(McpScreen())

    async def _run_init(self, text: str) -> None:
        """Generate NOVA.md natively: graphify pipeline (captured) or stream the
        fallback exploration through the TUI."""
        from pathlib import Path

        from novacode_cli.config.config import settings

        cmd_args = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else None
        project_root = settings.project_root
        if not project_root:
            self._log(
                Text("/init requires a project with a .git directory.", style="yellow")
            )
            return
        nova_dir = Path(project_root) / ".nova"
        nova_md_path = nova_dir / "NOVA.md"
        self._log(
            Text(f"🔍 Initializing NOVA.md for {Path(project_root).name}…", style="bold")
        )

        from novacode_cli.init.detect import is_graphify_available

        if is_graphify_available():
            from rich.console import Console as _Console

            from novacode_cli.commands.init_handler import (
                InitFlags,
                _run_graphify_pipeline,
            )

            # Drive the multi-step pipeline into a NATIVE step tracker. A quiet
            # console feeds progress lines to _init_emit, which advances the
            # step list (Detect → Extract → Build → Analyze → Generate).
            self._init_steps = [
                {"label": name, "status": "pending", "detail": ""}
                for name in (
                    "Detect files",
                    "Extract entities",
                    "Build & cluster graph",
                    "Analyze structure",
                    "Generate docs",
                )
            ]
            self._init_widget = Static("", classes="initlog")
            await self._mount(self._init_widget)
            self._init_render_steps()
            tui_console = _Console(
                file=_TuiSink(self),
                force_terminal=True,
                color_system="standard",
                width=100,
            )
            self._turn_active = True
            self._turn_start = time.monotonic()
            self._set_status("indexing codebase…")
            try:
                await _run_graphify_pipeline(
                    project_root=Path(project_root),
                    nova_dir=nova_dir,
                    nova_md_path=nova_md_path,
                    agents_md_path=nova_dir / "AGENTS.md",
                    flags=InitFlags(cmd_args),
                    console=tui_console,
                )
                self._init_finish()
            except Exception as ex:  # noqa: BLE001
                self._log(Text(f"/init failed: {ex}", style="red"))
            finally:
                self._turn_active = False
                self._set_status("ready")
                self._init_widget = None
                self._init_steps = []
        else:
            # Fallback: stream the agent's codebase exploration through the TUI.
            from novacode_cli.prompts import render_template

            prompt = render_template(
                "init_exploration.jinja",
                project_root=str(project_root),
                Nova_md_path=str(nova_md_path),
            )
            prev = self.session_state.auto_approve
            self.session_state.auto_approve = True
            try:
                await self._stream_prompt(prompt)
            finally:
                self.session_state.auto_approve = prev

        if nova_md_path.exists():
            self._log(Text(f"✓ NOVA.md ready → {nova_md_path}", style="green"))

    async def _run_trace(self, text: str) -> None:
        """Native LangSmith tracing: status / enable / disable / projects / traces."""
        import os

        parts = text.split()
        args = parts[1:]
        sub = parts[1].lower() if len(parts) > 1 else "status"
        from novacode_cli.tracking.tracing import (
            configure_tracing,
            get_traces,
            get_tracing_config,
            get_tracing_status,
            list_projects,
        )

        if sub in ("enable", "on"):
            api_key = args[1] if len(args) > 1 and not args[1].startswith("-") else None
            project_name = None
            for i, a in enumerate(args):
                if a == "--project" and i + 1 < len(args):
                    project_name = args[i + 1]
                    break
            cfg = configure_tracing(api_key=api_key, project_name=project_name, enable=True)
            if cfg.is_configured():
                t = Text()
                t.append("✓ LangSmith tracing enabled\n", style="green")
                t.append(f"  project: {cfg.project_name}\n", style="dim")
                t.append("  set LANGSMITH_API_KEY in .env to persist\n", style="dim")
                self._log(t)
            else:
                self._log(
                    Text(
                        "Failed to enable tracing — LANGSMITH_API_KEY is required.",
                        style="red",
                    )
                )
            return
        if sub in ("disable", "off"):
            os.environ["LANGSMITH_TRACING"] = "false"
            self._log(
                Text(
                    "✓ LangSmith tracing disabled for this session "
                    "(set LANGSMITH_TRACING=false in .env to persist).",
                    style="green",
                )
            )
            return
        if sub == "projects":
            projects = list_projects()
            t = Text()
            t.append("LangSmith projects\n", style="bold")
            if projects:
                for p in projects[:20]:
                    t.append(f"  {p['name']}", style="cyan")
                    t.append(f"  {p['url']}\n", style="dim")
            else:
                t.append("  (none found or tracing not configured)\n", style="dim")
            self._log(t)
            return
        if sub in ("traces", "recent"):
            limit = 10
            for i, a in enumerate(args):
                if a in ("-n", "--limit") and i + 1 < len(args):
                    try:
                        limit = int(args[i + 1])
                    except ValueError:
                        pass
            traces = get_traces(limit=limit)
            t = Text()
            t.append(f"Recent traces (last {limit})\n", style="bold")
            if traces:
                for tr in traces[:limit]:
                    created = (tr.get("created_at", "") or "")[:19] or "unknown"
                    inputs = str(tr.get("inputs", {}))[:40]
                    t.append(f"  {tr['name']}", style="cyan")
                    t.append(f"  {created}  {inputs}\n", style="dim")
            else:
                t.append("  (none — make a request with tracing enabled first)\n", style="dim")
            self._log(t)
            return
        if sub in ("-h", "--help", "help"):
            t = Text()
            t.append("/trace — LangSmith tracing\n", style="bold")
            for name, desc in (
                ("status", "show current tracing configuration"),
                ("enable [KEY] [--project P]", "enable tracing"),
                ("disable", "disable tracing for this session"),
                ("projects", "list LangSmith projects"),
                ("traces [--limit N]", "show recent traces"),
            ):
                t.append(f"  /trace {name}\n", style="cyan")
                t.append(f"      {desc}\n", style="dim")
            self._log(t)
            return
        if sub not in ("status", ""):
            self._log(Text(f"Unknown trace subcommand: {sub} (try /trace help)", style="yellow"))
            return

        st = get_tracing_status()
        t = Text()
        t.append("LangSmith tracing\n", style="bold")
        if not st.get("available"):
            t.append("  langsmith not installed\n", style="dim")
        elif st.get("configured"):
            cfg = get_tracing_config()
            t.append("  ● enabled\n", style="green")
            t.append(f"  project: {cfg.project_name}\n", style="dim")
            if getattr(cfg, "workspace_id", None):
                t.append(f"  workspace: {cfg.workspace_id}\n", style="dim")
            t.append("  view: https://smith.langchain.com\n", style="dim")
        else:
            t.append("  ○ not configured\n", style="yellow")
            t.append(
                "  set LANGSMITH_API_KEY and LANGSMITH_TRACING=true\n", style="dim"
            )
        self._log(t)

    async def _run_log(self, text: str) -> None:
        """Native recent-runs list and `/log show <id>` detail."""
        from novacode_cli.commands.log_commands import (
            _list_runs,
            _load_json,
            _run_summary_line,
            _runs_dir,
        )

        parts = text.split()
        sub = parts[1].lower() if len(parts) > 1 else "list"
        ws = str(getattr(self.session_state, "workspace_root", "") or "") or None
        runs_dir = _runs_dir(ws)

        if sub == "show" and len(parts) > 2:
            run_id = parts[2]
            matches = [p for p in _list_runs(runs_dir) if p.name.startswith(run_id)]
            if not matches:
                self._log(Text(f"No run matching '{run_id}'", style="red"))
                return
            run_dir = matches[0]
            t = Text()
            t.append(f"Run: {run_dir.name}\n", style="bold")
            for label, fname in (
                ("Meta", "meta.json"),
                ("Summary", "summary.json"),
                ("Verdict", "user_verdict.json"),
            ):
                data = _load_json(run_dir / fname)
                if data:
                    t.append(f"\n{label}\n", style="bold")
                    for k, v in data.items():
                        t.append(f"  {k}: {v}\n", style="dim")
            self._log(t)
            return

        if sub == "grep":
            import re as _re

            if len(parts) < 3:
                self._log(Text("Usage: /log grep <pattern>", style="red"))
                return
            pattern = parts[2]
            limit = 50
            for i, a in enumerate(parts):
                if a == "--limit" and i + 1 < len(parts):
                    try:
                        limit = int(parts[i + 1])
                    except ValueError:
                        pass
            try:
                rx = _re.compile(pattern, _re.IGNORECASE)
            except _re.error as e:
                self._log(Text(f"Invalid pattern: {e}", style="red"))
                return
            t = Text()
            t.append(f"grep '{pattern}'\n", style="bold")
            hits = 0
            for run_dir in _list_runs(runs_dir):
                turns_dir = run_dir / "turns"
                if not turns_dir.exists():
                    continue
                for turn in sorted(turns_dir.iterdir()):
                    for fname in ("prompt.txt", "response.json"):
                        fpath = turn / fname
                        if not fpath.exists():
                            continue
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                        for lineno, line in enumerate(content.splitlines(), 1):
                            if rx.search(line):
                                t.append(
                                    f"  {run_dir.name[:16]}/{turn.name}/{fname}:{lineno}  ",
                                    style="dim",
                                )
                                t.append(f"{line.strip()[:120]}\n")
                                hits += 1
                                if hits >= limit:
                                    t.append(f"  … stopped at {limit} hits\n", style="dim")
                                    self._log(t)
                                    return
            if hits == 0:
                t.append(f"  (no matches for '{pattern}')\n", style="dim")
            self._log(t)
            return

        if sub not in ("list", ""):  # diff / verdict / frontier
            await self._passthrough_command(text)
            return

        runs = _list_runs(runs_dir)[:20]
        t = Text()
        t.append("Recent runs\n", style="bold")
        if not runs:
            t.append("  (no runs yet — start a session to generate logs)\n", style="dim")
        else:
            for r in runs:
                t.append(f"  {_run_summary_line(r)}\n", style="dim")
        self._log(t)

    # -- plan mode ------------------------------------------------------------
    def _active_agent(self) -> tuple[Any, Any]:
        """Route to the plan agent while plan mode is active, else the main agent."""
        if getattr(self.session_state, "plan_mode_enabled", False) and (
            getattr(self.session_state, "plan_agent", None) is not None
        ):
            return self.session_state.plan_agent, getattr(
                self.session_state, "plan_backend", None
            )
        return self.agent, self.backend

    async def _enable_plan_mode(self) -> bool:
        try:
            from novacode_cli.agents.plan_agent import create_plan_agent_with_config
            from novacode_cli.tools.plan_mode_tools import (
                ask_user_question,
                enter_plan_mode,
                exit_plan_mode,
            )

            model = getattr(self.session_state, "_model", None)
            if model is None:
                self._log(Text("Plan mode needs a model; none configured.", style="red"))
                return False
            plan_agent, plan_backend = create_plan_agent_with_config(
                model=model,
                assistant_id=getattr(self.session_state, "_assistant_id", None)
                or "nova",
                tools=[ask_user_question, enter_plan_mode, exit_plan_mode],
                steering_instructions=getattr(
                    self.session_state, "steering_instructions", None
                ),
            )
            self.session_state.plan_mode_enabled = True
            self._update_mode_badge()
            self.session_state.plan_content = None
            self.session_state.plan_agent = plan_agent
            self.session_state.plan_backend = plan_backend
            return True
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Plan mode failed: {ex}", style="red"))
            self.session_state.plan_mode_enabled = False
            self._update_mode_badge()
            return False

    async def _maybe_run_approved_plan(self) -> None:
        """After a plan-mode turn, execute an approved plan via the main agent."""
        try:
            approved = self.session_state.consume_approved_plan()
        except Exception:  # noqa: BLE001
            approved = None
        if not approved:
            return
        try:
            self.session_state.clear_plan_agent()
        except Exception:  # noqa: BLE001
            pass
        self._log(Text("✓ Plan approved — executing with Nova…", style="cyan"))
        await self._stream_prompt(
            "The user has approved the following plan. Execute it step by step, "
            "marking each step complete as you go:\n\n" + approved
        )

    async def _run_plan(self, text: str) -> None:
        """Native /plan: status / off / enable (+ optional prompt)."""
        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        low = args.lower()
        if low == "status":
            enabled = getattr(self.session_state, "plan_mode_enabled", False)
            self._log(
                Text(
                    f"Plan mode: {'enabled' if enabled else 'disabled'}",
                    style="cyan" if enabled else "dim",
                )
            )
            return
        if low == "off":
            self.session_state.plan_mode_enabled = False
            self._update_mode_badge()
            try:
                self.session_state.clear_plan_agent()
            except Exception:  # noqa: BLE001
                pass
            self._log(Text("Plan mode disabled.", style="yellow"))
            return
        if not await self._enable_plan_mode():
            return
        self._log(
            Text(
                "▌ Plan mode — investigation only (read-only tools); "
                "you'll approve the plan before execution.",
                style="cyan",
            )
        )
        if args:
            await self._stream_prompt(args)
            await self._maybe_run_approved_plan()

    async def _run_compact(self, text: str) -> None:
        """Compact the conversation natively (spinner + result component)."""
        from novacode_cli.compaction import compact_conversation
        from novacode_cli.config.model_create import create_model

        parts = text.split(maxsplit=1)
        focus = parts[1].strip() if len(parts) > 1 else None
        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status("compacting…")
        try:
            model = create_model()
            result = await compact_conversation(
                agent=self.agent,
                model=model,
                thread_id=self.session_state.thread_id,
                focus_instructions=focus,
            )
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"/compact failed: {ex}", style="red"))
            return
        finally:
            self._turn_active = False
            self._set_status("ready")
        if getattr(result, "success", False):
            if self.token_tracker is not None:
                try:
                    self.token_tracker.reset()
                except Exception:  # noqa: BLE001
                    pass
            t = Text()
            t.append("✓ Conversation compacted\n", style="green")
            t.append(
                f"  messages: {result.messages_before} → {result.messages_after}\n",
                style="dim",
            )
            t.append(f"  tokens saved: ~{result.tokens_saved:,}\n", style="dim")
            summary = getattr(result, "summary", "") or ""
            if summary:
                t.append(
                    "\n" + summary[:400] + ("…" if len(summary) > 400 else ""),
                    style="dim italic",
                )
            self._log(t)
        else:
            self._log(
                Text(
                    f"Compaction skipped: {getattr(result, 'error', '') or 'unknown'}",
                    style="yellow",
                )
            )

    async def _run_save(self) -> None:
        """Manually persist the session (native confirmation)."""
        if self.session_manager is None:
            self._log(Text("Session saving is unavailable.", style="yellow"))
            return
        await self._save_session()
        sid = str(getattr(self.session_state, "session_id", "") or "")[:8]
        self._log(
            Text(
                f"✓ Session saved — resume with:  nova --continue {sid}",
                style="green",
            )
        )

    async def _run_clear(self) -> None:
        """Start a fresh chat: save the current conversation, then reset it.

        Clearing only the transcript would leave the agent's full history in the
        checkpointer (same thread_id), so it would still "remember" everything.
        A real reset assigns a new thread_id + session_id (fresh checkpointer
        state), drops per-conversation tracking, and re-baselines token usage —
        the previous conversation is saved first so nothing is lost.
        """
        import uuid

        saved = self.session_manager is not None
        # Preserve the current conversation under its existing id before resetting.
        await self._save_session()

        # New conversation thread (empty checkpointer state) + new session id.
        self.session_state.thread_id = str(uuid.uuid4())
        self.session_state.session_id = str(uuid.uuid4())
        self.session_state.is_continued = False
        self.session_state.todos = None

        # Drop per-conversation UI/tracking state.
        self._reset_streaming()
        self._seen.clear()
        self._restored_messages = []

        await self.query_one("#transcript", VerticalScroll).remove_children()

        # Re-baseline context/token accounting for the fresh chat.
        if self.token_tracker is not None:
            try:
                self.token_tracker.reset()
            except Exception:  # noqa: BLE001
                pass
        self._refresh_status()

        self._log(
            Text(
                "✓ Started a new chat"
                + (" — previous conversation saved." if saved else "."),
                style="green",
            )
        )

    async def _run_steer(self, text: str) -> None:
        """Manage persistent steering instructions natively (add/list/clear/remove)."""
        import re

        from novacode_cli.bootstrap.steering import (
            SteeringInstruction,
            classify_instruction,
        )

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        if getattr(self.session_state, "steering_instructions", None) is None:
            self.session_state.steering_instructions = []
        instr = self.session_state.steering_instructions
        low = args.lower()

        if not args or low in ("list", "ls", "show"):
            t = Text()
            t.append("Steering instructions\n", style="bold")
            if not instr:
                t.append("  (none — /steer <instruction> to add)\n", style="dim")
            else:
                for i, si in enumerate(instr, 1):
                    t.append(f"  {i}. ", style="cyan")
                    t.append(f"{si.label}: {si.instruction}\n", style="dim")
            self._log(t)
            return
        if low in ("clear", "reset"):
            n = len(instr)
            instr.clear()
            self._log(Text(f"Cleared {n} steering instruction(s).", style="green"))
            return
        m = re.match(r"(?:remove|rm|del|delete)\s+(\d+)", args, re.IGNORECASE)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(instr):
                removed = instr.pop(idx)
                self._log(Text(f"Removed: {removed.label}", style="green"))
            else:
                self._log(Text(f"Invalid index {idx + 1}.", style="yellow"))
            return
        label = classify_instruction(args)
        instr.append(SteeringInstruction(label=label, instruction=args))
        self._log(
            Text(
                f"✓ Added steering [{label}]: {args}\n"
                f"  {len(instr)} active — injected into every turn.",
                style="green",
            )
        )

    async def _run_notifications(self, text: str) -> None:
        """Native /notifications: list, dismiss <id>, or clear."""
        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        ap = args.split(maxsplit=1)
        sub = ap[0].lower() if ap else ""
        ss = self.session_state

        if sub in ("clear", "reset"):
            n = ss.clear_notifications()
            self._log(Text(f"Cleared {n} notification(s).", style="green"))
            self._refresh_status()
            return
        if sub in ("dismiss", "rm", "ack") and len(ap) > 1:
            nid = ap[1].strip()
            ok = ss.dismiss_notification(nid)
            self._log(
                Text(
                    f"Dismissed {nid}" if ok else f"Notification {nid} not found",
                    style="green" if ok else "yellow",
                )
            )
            self._refresh_status()
            return

        notes = list(ss.notifications)
        colors = {"info": "cyan", "success": "green", "warning": "yellow", "error": "red"}
        t = Text()
        t.append(f"Notifications ({ss.unread_notification_count()} unread)\n", style="bold")
        if not notes:
            t.append("  (none yet — long-running tasks notify here)\n", style="dim")
        else:
            for n in notes:
                c = colors.get(n.level, "white")
                t.append(f"  {'●' if not n.dismissed else '○'} ", style=c)
                t.append(f"{n.id} ", style="dim")
                t.append(f"{n.timestamp.strftime('%H:%M:%S')} ", style="dim")
                t.append(f"[{n.source}] ", style="dim")
                t.append(f"{n.title}", style=c)
                if n.message:
                    t.append(f" — {n.message[:60]}", style="dim")
                t.append("\n")
            t.append(
                "  /notifications dismiss <id> · /notifications clear\n", style="dim"
            )
        self._log(t)

    async def _tui_execute_fn(
        self,
        user_input,
        agent=None,
        assistant_id=None,
        session_state=None,
        token_tracker=None,
        backend=None,
        is_subagent=False,
        image_tracker=None,
        seen_message_ids=None,
        *,
        skip_file_mentions=False,
    ) -> None:
        """Drop-in replacement for ``execute_task`` that streams natively.

        Signature mirrors ``execute_task`` so handlers (e.g. /research,
        /browser-use, /ralph) can call it positionally or by keyword and have
        the agent run render as native TUI widgets instead of rich prints.
        """
        await self._stream_prompt(user_input)

    async def _run_research(self, text: str) -> None:
        """Launch the research swarm, streaming the run as native widgets."""
        from novacode_cli.commands.research_handler import handle_research_command

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        if not args:
            # No query → let the handler emit its usage block, surface natively.
            with _rich_console.capture() as cap:
                await handle_research_command(
                    self.agent, self.session_state, self.token_tracker, cmd_args=None
                )
            out = Text.from_ansi(cap.get()).plain.strip()
            self._log(Text(out or "Usage: /research <query>", style="dim"))
            return
        self._log(Text(f"🔬 Research: {args}", style="bold"))
        # Capture (and discard) the handler's setup prints; the agent run itself
        # streams natively through _tui_execute_fn → _stream_prompt.
        with _rich_console.capture():
            await handle_research_command(
                self.agent,
                self.session_state,
                self.token_tracker,
                cmd_args=args,
                execute_fn=self._tui_execute_fn,
            )

    async def _run_dream(self) -> None:
        """Run /dream: build the dream prompt from memories and stream it."""
        from novacode_cli.commands.dream_handler import handle_dream_command

        with _rich_console.capture() as cap:
            result = await handle_dream_command(self.session_state)
        notice = Text.from_ansi(cap.get()).plain.strip()
        if isinstance(result, str) and result.strip():
            self._log(Text("💭 Dreaming over memories…", style="bold"))
            await self._stream_prompt(result)
        elif notice:
            self._log(Text(notice, style="dim"))
        else:
            self._log(Text("Nothing to dream about (no memories found).", style="dim"))

    async def _run_reindex(self) -> None:
        """Rebuild the semantic code-search index, with a native status."""
        try:
            from novacode_cli.tools.code_search_tools import (
                _get_index,
                _is_semble_available,
                _reset_index,
            )
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Code search unavailable: {ex}", style="yellow"))
            return
        if not _is_semble_available():
            self._log(
                Text(
                    "Code search is not available. Install 'semble' to enable "
                    "semantic code search (pip install semble).",
                    style="yellow",
                )
            )
            return

        from pathlib import Path

        from novacode_cli.config.config import settings as _settings

        workspace = _settings.project_root or Path.cwd()
        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status("re-indexing…")
        try:
            _reset_index()
            idx = await asyncio.to_thread(_get_index, workspace)
            if idx is not None:
                self._log(Text(f"✓ Code search index rebuilt for {workspace}", style="green"))
            else:
                self._log(Text("Failed to build code search index.", style="red"))
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Reindex failed: {ex}", style="red"))
        finally:
            self._turn_active = False
            self._set_status("ready")

    async def _run_images(self, text: str) -> None:
        """Native /images: list, remove, or clear conversation images."""
        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        it = self.image_tracker
        if it is None:
            self._log(Text("Image tracking not available.", style="yellow"))
            return
        arg_parts = args.split(maxsplit=1)
        sub = arg_parts[0].lower() if arg_parts else ""

        if not args or sub == "list":
            images = it.list_images()
            t = Text()
            t.append("Images in conversation\n", style="bold")
            if not images:
                t.append(
                    "  (none — paste with Ctrl+V or reference @path/to/image.png)\n",
                    style="dim",
                )
            else:
                for img in images:
                    t.append(f"  {img['id']}", style="cyan")
                    t.append(
                        f"  {img['format'].upper()}  {img['size_kb']:.1f} KB  "
                        f"{img['placeholder']}\n",
                        style="dim",
                    )
                t.append(
                    f"  Total: {len(images)} — /images remove <id> · /images clear\n",
                    style="dim",
                )
            self._log(t)
            return
        if sub == "remove":
            if len(arg_parts) < 2:
                self._log(Text("Usage: /images remove <id>", style="red"))
                return
            image_id = arg_parts[1].strip()
            if not image_id.startswith("image-"):
                image_id = f"image-{image_id}"
            if it.remove_image(image_id):
                self._log(Text(f"Removed {image_id}", style="green"))
            else:
                avail = ", ".join(i["id"] for i in it.list_images())
                msg = f"Image not found: {image_id}"
                if avail:
                    msg += f" (available: {avail})"
                self._log(Text(msg, style="red"))
            return
        if sub == "clear":
            count = it.count
            if count == 0:
                self._log(Text("No images to clear.", style="dim"))
            else:
                it.clear()
                self._log(Text(f"Cleared {count} image(s) from conversation.", style="green"))
            return
        self._log(Text("Usage: /images [list | remove <id> | clear]", style="red"))

    async def _run_vision(self, text: str) -> None:
        """Native /vision: load @image refs and describe them via a vision model."""
        from langchain_core.messages import HumanMessage

        from novacode_cli.commands.vision_handler import parse_image_references
        from novacode_cli.config.model_create import (
            create_model,
            get_current_model_name,
            get_vision_model_suggestion,
            model_supports_vision,
        )
        from novacode_cli.image_utils import load_image_from_path

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        refs = parse_image_references(args)
        if not refs:
            self._log(
                Text(
                    "Usage: /vision @path/to/image.png [optional prompt]",
                    style="yellow",
                )
            )
            return

        images = []
        for original, path in refs:
            if path is None:
                self._log(Text(f"✗ {original}: invalid path", style="red"))
                continue
            if not path.exists():
                self._log(Text(f"✗ {path}: file not found", style="red"))
                continue
            try:
                images.append(load_image_from_path(path))
                self._log(Text(f"✓ Loaded {path.name}", style="green"))
            except (OSError, ValueError, RuntimeError) as ex:
                self._log(Text(f"✗ {path}: {ex}", style="red"))
        if not images:
            self._log(Text("No valid images to process.", style="red"))
            return

        current_model = get_current_model_name()
        if not model_supports_vision(current_model):
            sug = get_vision_model_suggestion(current_model)
            msg = f"⚠ Model '{current_model}' may not support vision."
            if sug:
                msg += f"  Try /model {sug}."
            self._log(Text(msg, style="yellow"))

        prompt_text = "Describe this image in detail."
        remaining = args
        for original, _ in refs:
            remaining = remaining.replace(original, "", 1)
        remaining = remaining.strip()
        if remaining:
            prompt_text = remaining

        content_blocks = [{"type": "text", "text": prompt_text}]
        content_blocks.extend(img.to_message_content() for img in images)

        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status(f"analyzing {len(images)} image(s)…")
        try:
            model = create_model()
            resp = await model.ainvoke([HumanMessage(content=content_blocks)])
            content = resp.content
            desc = content if isinstance(content, str) else str(content)
            await self._add_message(
                Text("Vision", style="bold magenta"), "nova", Markdown(desc)
            )
            if self.image_tracker and hasattr(self.image_tracker, "add_vision_result"):
                self.image_tracker.add_vision_result(images, desc)
        except (OSError, ValueError, RuntimeError) as ex:
            self._log(Text(f"Error analyzing image: {ex}", style="red"))
        finally:
            self._turn_active = False
            self._set_status("ready")

    async def _run_files(self) -> None:
        """Native /files: session read/write summary from the file tracker."""
        from novacode_cli.tracking.file_tracker import get_session_tracker

        tr = get_session_tracker()
        t = Text()
        t.append("Session file operations\n", style="bold")
        t.append(f"  read: {len(tr.files_read)} files / {tr.total_reads} ops\n", style="dim")
        t.append(
            f"  modified: {len(tr.files_written)} files / {tr.total_writes} ops\n",
            style="dim",
        )
        if getattr(tr, "rejected_edits", 0):
            t.append(f"  rejected edits (unread files): {tr.rejected_edits}\n", style="red")
        if tr.files_read:
            t.append("\nRecently read\n", style="bold")
            for path in tr.read_order[-15:]:
                rec = tr.files_read[path]
                disp = path if len(path) <= 60 else "..." + path[-57:]
                t.append(f"  {disp}", style="cyan")
                t.append(f"  ({rec.line_count} lines)\n", style="dim")
        if tr.files_written:
            t.append("\nRecently modified\n", style="bold")
            for path in tr.write_order[-15:]:
                recs = tr.files_written[path]
                disp = path if len(path) <= 60 else "..." + path[-57:]
                ops = ", ".join(r.operation for r in recs[-3:])
                if len(recs) > 3:
                    ops = f"({len(recs)}x) " + ops
                t.append(f"  {disp}", style="yellow")
                t.append(f"  {ops}\n", style="dim")
        self._log(t)

    async def _run_tests(self, text: str) -> None:
        """Native /tests: detect framework (or use args) and stream results."""
        import threading
        from pathlib import Path

        from novacode_cli.server_runner.test_runner import (
            detect_test_framework,
            get_default_test_command,
            run_tests,
        )

        parts = text.split(maxsplit=1)
        cmd_args = parts[1].strip() if len(parts) > 1 else ""
        working_dir = str(Path.cwd())
        if not cmd_args:
            framework = detect_test_framework(working_dir)
            command = get_default_test_command(framework)
            if not command:
                self._log(
                    Text(
                        "Could not auto-detect test framework. "
                        "Specify one: /tests pytest  or  /tests npm test",
                        style="yellow",
                    )
                )
                return
            self._log(Text(f"Detected {framework.value} — running: {command}", style="dim"))
        else:
            command = cmd_args
            self._log(Text(f"Running: {command}", style="dim"))

        loop_tid = threading.get_ident()

        def _cb(line: str) -> None:
            if threading.get_ident() == loop_tid:
                self._log(Text(line, style="dim"))
            else:
                try:
                    self.call_from_thread(self._log, Text(line, style="dim"))
                except Exception:  # noqa: BLE001
                    pass

        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status("running tests…")
        try:
            result = await run_tests(
                command=command, working_dir=working_dir, output_callback=_cb
            )
            t = Text()
            t.append("✓ Tests passed\n" if result.success else "✗ Tests failed\n",
                     style="green" if result.success else "red")
            stats = []
            if result.tests_run is not None:
                stats.append(f"{result.tests_run} run")
            if result.tests_passed is not None:
                stats.append(f"{result.tests_passed} passed")
            if result.tests_failed is not None:
                stats.append(f"{result.tests_failed} failed")
            if result.duration_seconds is not None:
                stats.append(f"{result.duration_seconds:.2f}s")
            if stats:
                t.append("  " + ", ".join(stats) + "\n", style="dim")
            if result.error:
                t.append(f"  error: {result.error}\n", style="red")
            self._log(t)
            self._notify_test_result(result)
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Test run failed: {ex}", style="red"))
        finally:
            self._turn_active = False
            self._set_status("ready")

    def _notify_test_result(self, result) -> None:
        """Record a notification summarizing a finished test run."""
        try:
            ok = bool(getattr(result, "success", False))
            passed = getattr(result, "tests_passed", None)
            failed = getattr(result, "tests_failed", None)
            total = getattr(result, "tests_run", None)
            dur = getattr(result, "duration_seconds", None)
            if passed is not None and total:
                title = f"Tests: {passed}/{total} passed"
            else:
                title = "Tests passed" if ok else "Tests failed"
            msg = f"{failed} failed" if failed is not None else ("ok" if ok else "failed")
            if dur is not None:
                msg += f" · {dur:.1f}s"
            self.session_state.add_notification(
                level="success" if ok else "error",
                title=title,
                message=msg,
                source="tests",
            )
        except Exception:  # noqa: BLE001
            pass

    async def _run_servers(self) -> None:
        """Native /servers: list dev servers and act on a chosen one."""
        import webbrowser

        from novacode_cli.process_manager import ProcessManager
        from novacode_cli.server_runner.dev_server import list_servers, stop_server

        servers = list_servers(include_external=True)
        t = Text()
        t.append("Dev servers\n", style="bold")
        if not servers:
            t.append("  (none running — use the start_dev_server tool)\n", style="dim")
            self._log(t)
            return
        for s in servers:
            ext = s.pid == 0 and "external" in s.name
            t.append(f"  [{'external' if ext else s.pid}] ", style="dim")
            t.append(f"{s.name}", style="cyan")
            t.append(f"  {s.url}  ", style="dim")
            t.append(f"{s.status.value}\n", style="green" if s.status.value == "healthy" else "yellow")
        self._log(t)

        action = await self.push_screen_wait(
            PickScreen(
                "Servers — choose an action",
                ["Open in browser", "Stop a server (managed)", "Stop all managed", "Cancel"],
            )
        )
        if action in (-1, 3, None):
            return
        if action == 0:
            opts = [f"{s.name} ({s.url})" for s in servers]
            idx = await self.push_screen_wait(PickScreen("Open which server?", opts))
            if 0 <= idx < len(servers):
                webbrowser.open(servers[idx].url)
                self._log(Text(f"✓ Opened {servers[idx].url}", style="green"))
            return
        if action == 1:
            stoppable = [s for s in servers if s.pid > 0]
            if not stoppable:
                self._log(Text("No managed servers to stop.", style="yellow"))
                return
            opts = [f"{s.name} (PID {s.pid})" for s in stoppable]
            idx = await self.push_screen_wait(PickScreen("Stop which server?", opts))
            if 0 <= idx < len(stoppable):
                ok = await stop_server(pid=stoppable[idx].pid)
                self._log(
                    Text(
                        f"✓ Stopped '{stoppable[idx].name}'" if ok else "Failed to stop server",
                        style="green" if ok else "red",
                    )
                )
            return
        if action == 2:
            count = await ProcessManager.get_instance().stop_all()
            self._log(
                Text(
                    f"✓ Stopped {count} managed server(s)" if count else "No managed servers to stop",
                    style="green" if count else "yellow",
                )
            )

    async def _run_kill(self, text: str) -> None:
        """Native /kill: kill a process by PID/name (arg) or via a picker."""
        from novacode_cli.process_manager import ProcessManager

        manager = ProcessManager.get_instance()
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        if arg:
            try:
                pid = int(arg)
                ok = await manager.stop_process(pid)
                self._log(
                    Text(
                        f"✓ Killed process {pid}" if ok else f"No process with PID {pid}",
                        style="green" if ok else "yellow",
                    )
                )
                return
            except ValueError:
                pass
            ok = await manager.stop_by_name(arg)
            self._log(
                Text(
                    f"✓ Killed process '{arg}'" if ok else f"No process named '{arg}'",
                    style="green" if ok else "yellow",
                )
            )
            return

        processes = manager.list_processes(alive_only=True)
        if not processes:
            self._log(Text("No managed processes running.", style="yellow"))
            return
        opts = [
            f"[{p.pid}] {p.name}" + (f" (port {p.port})" if p.port else "")
            for p in processes
        ]
        idx = await self.push_screen_wait(PickScreen("Kill which process?", opts))
        if 0 <= idx < len(processes):
            info = processes[idx]
            ok = await manager.stop_process(info.pid)
            self._log(
                Text(
                    f"✓ Killed '{info.name}' (PID {info.pid})" if ok else "Failed to kill process",
                    style="green" if ok else "red",
                )
            )

    async def _run_restore(self, text: str) -> None:
        """Native /restore: restore a file snapshot by arg or via a picker."""
        from datetime import datetime

        from novacode_cli.recovery import REASON_LABELS, get_recovery_manager

        mgr = get_recovery_manager()
        if mgr is None:
            self._log(Text("No recovery manager active for this session.", style="yellow"))
            return
        snapshots = mgr.list_snapshots(include_past_sessions=True)
        if not snapshots:
            self._log(
                Text(
                    "No file snapshots found. Snapshots are created before "
                    "rm/write_file/edit_file.",
                    style="yellow",
                )
            )
            return

        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        def _restore(idx: int) -> None:
            session_id, entry = snapshots[idx]
            ok = mgr.restore(entry, session_id=session_id)
            self._log(
                Text(
                    f"✓ Restored {entry.original_path}" if ok else f"Failed to restore {entry.original_path}",
                    style="green" if ok else "red",
                )
            )

        if arg:
            if arg.isdigit():
                i = int(arg) - 1
                if 0 <= i < len(snapshots):
                    _restore(i)
                else:
                    self._log(Text(f"No snapshot at index {arg}.", style="red"))
                return
            for i, (_sid, entry) in enumerate(snapshots):
                if arg in entry.original_path or entry.original_path.endswith(arg):
                    _restore(i)
                    return
            self._log(Text(f"No snapshot matching '{arg}'.", style="red"))
            return

        now = datetime.now()
        opts = []
        for _sid, entry in snapshots:
            label = REASON_LABELS.get(entry.reason, entry.reason)
            try:
                secs = int((now - datetime.fromisoformat(entry.timestamp)).total_seconds())
                age = (
                    f"{secs}s ago" if secs < 60
                    else f"{secs // 60}m ago" if secs < 3600
                    else f"{secs // 3600}h ago" if secs < 86400
                    else f"{secs // 86400}d ago"
                )
            except Exception:  # noqa: BLE001
                age = entry.timestamp
            opts.append(f"{entry.original_path}  — {label} ({age})")
        idx = await self.push_screen_wait(PickScreen("Restore which snapshot?", opts))
        if 0 <= idx < len(snapshots):
            _restore(idx)

    async def _run_hooks(self, text: str) -> None:
        """Native /hooks: list, enable/disable/remove/test via args or a picker."""
        from novacode_cli.commands.hooks_handler import _save_hooks
        from novacode_cli.hooks import _load_hooks

        parts = text.split()
        sub = parts[1].lower() if len(parts) > 1 else "list"
        idx_arg = parts[2] if len(parts) > 2 else None

        def _fmt(hooks: list[dict]) -> Text:
            t = Text()
            t.append("Configured hooks\n", style="bold")
            if not hooks:
                t.append("  (none — add with:  nova hooks add)\n", style="dim")
                return t
            for i, h in enumerate(hooks, 1):
                command = " ".join(h.get("command", []))
                events = ", ".join(h.get("events", ["<all>"]))
                status = "✓" if h.get("enabled", True) else "✗"
                t.append(f"  {i}. ", style="dim")
                t.append(f"{status} {command}", style="cyan")
                t.append(f"  [{events}]\n", style="dim")
            return t

        hooks = _load_hooks()
        if sub in ("list", ""):
            self._log(_fmt(hooks))
            return
        if sub == "add":
            self._log(
                Text(
                    "Interactive hook creation isn't available in the TUI yet. "
                    "Add hooks with:  nova hooks add",
                    style="yellow",
                )
            )
            return
        if sub not in ("enable", "disable", "remove", "test"):
            self._log(Text(f"Unknown hooks subcommand: {sub}", style="yellow"))
            return
        if not hooks:
            self._log(Text("No hooks configured.", style="yellow"))
            return

        # Resolve the target hook index (explicit arg or picker).
        index = None
        if idx_arg and idx_arg.isdigit():
            index = int(idx_arg) - 1
        else:
            opts = [
                ("✓ " if h.get("enabled", True) else "✗ ") + " ".join(h.get("command", []))
                for h in hooks
            ]
            picked = await self.push_screen_wait(PickScreen(f"{sub.title()} which hook?", opts))
            if picked is None or picked < 0:
                return
            index = picked
        if index is None or not (0 <= index < len(hooks)):
            self._log(Text(f"Hook {('' if index is None else index + 1)} does not exist.", style="red"))
            return

        if sub == "test":
            self._log(
                Text(
                    "Hook test isn't available in the TUI yet — run:  "
                    f"nova hooks test {index + 1}",
                    style="yellow",
                )
            )
            return
        if sub == "remove":
            removed = hooks.pop(index)
            ok = _save_hooks(hooks)
            self._log(
                Text(
                    f"✓ Removed hook: {' '.join(removed.get('command', []))}" if ok
                    else "Failed to save hook configuration",
                    style="green" if ok else "red",
                )
            )
            return
        # enable / disable
        hooks[index]["enabled"] = sub == "enable"
        ok = _save_hooks(hooks)
        self._log(
            Text(
                f"✓ Hook {index + 1} {'enabled' if sub == 'enable' else 'disabled'}" if ok
                else "Failed to save hook configuration",
                style="green" if ok else "red",
            )
        )

    async def _run_browser_use(self, text: str) -> None:
        """Run /browser-use; the agent analysis streams natively via execute_fn."""
        from novacode_cli.commands.browser_use_handler import handle_browser_use_command

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        self._log(Text(f"🌐 Browser task: {args or '(status)'}", style="bold"))
        # Browser automation + setup prints are captured/discarded; the follow-up
        # agent run renders natively through _tui_execute_fn.
        with _rich_console.capture():
            await handle_browser_use_command(
                self.agent,
                self.session_state,
                self.assistant_id,
                self.token_tracker,
                args or None,
                execute_fn=self._tui_execute_fn,
            )

    async def _run_ralph(self, text: str) -> None:
        """Run /ralph; foreground iterations stream natively via execute_fn."""
        from novacode_cli.commands.ralph_handler import handle_ralph_command

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        self._log(Text(f"🔁 Ralph: {args or '(status)'}", style="bold"))
        with _rich_console.capture():
            await handle_ralph_command(
                self.agent,
                self.session_state,
                self.assistant_id,
                self.token_tracker,
                args or None,
                execute_fn=self._tui_execute_fn,
            )

    async def _run_trello(self, text: str) -> None:
        """Run /trello; start the server inline, then watch for tasks in background."""
        from novacode_cli.commands.trello_handler import (
            _handle_stop,
            _handle_status,
        )
        from novacode_cli.commands.trello_server import TrelloServer

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""

        # Subcommands that don't need the processing loop
        if args == "stop":
            with _rich_console.capture() as cap:
                _handle_stop(self.session_state)
            self._log(Text.from_ansi(cap.get()))
            return
        if args == "status":
            with _rich_console.capture() as cap:
                _handle_status(self.session_state)
            self._log(Text.from_ansi(cap.get()))
            return

        # Check if already running
        existing_server: TrelloServer | None = getattr(
            self.session_state, "trello_server", None
        )
        if existing_server and existing_server.is_running:
            self._log(
                Text(
                    f"Trello board already running at http://localhost:{existing_server.port}",
                    style="yellow",
                )
            )
            return

        # Start the server
        server = TrelloServer()
        port = await server.start()
        self.session_state.trello_server = server
        self._log(
            Text(
                f"📋 Trello board started at http://localhost:{port}",
                style="bold green",
            )
        )
        self._log(
            Text(
                "Add tasks in the browser. The agent will process them one at a time.",
                style="dim",
            )
        )

        # Launch the processing loop as a background task so the TUI stays responsive
        asyncio.create_task(self._trello_watch_loop(server))

    async def _trello_watch_loop(self, server: Any) -> None:
        """Background loop: poll for processing tasks and execute them."""
        try:
            while server.is_running:
                # First check for tasks explicitly moved to "processing" (web UI click)
                task = await server.get_next_processing_task()
                if not task:
                    # Auto-pick the first "loaded" task
                    task = server.pop_next_loaded_task()
                if task:
                    self._log(
                        Text(f"📋 Processing task: {task['description']}", style="bold")
                    )
                    await self._tui_execute_fn(
                        task["description"],
                        self.agent,
                        self.assistant_id,
                        self.session_state,
                        self.token_tracker,
                    )
                    await server.mark_done(task["id"])
                    self._log(
                        Text(
                            f"✓ Task completed: {task['description']}",
                            style="green",
                        )
                    )
                else:
                    await asyncio.sleep(0.5)
        except Exception:
            pass  # Server stopped, loop ends

    async def _run_agents(self) -> None:
        """Show configured subagents (read-only)."""
        lines = []
        try:
            from novacode_cli.config.config import extract_agent_description, settings

            for name, agent_dir, scope in settings.get_all_agents():
                try:
                    desc = extract_agent_description(agent_dir / "agent.md")
                except Exception:  # noqa: BLE001
                    desc = ""
                lines.append(f"{name}  ·  {scope}  ·  {desc}".rstrip(" ·"))
        except Exception as ex:  # noqa: BLE001
            lines = [f"(error listing agents: {ex})"]
        await self.push_screen_wait(
            InfoListScreen(
                "Subagents",
                lines or ["(no agents found)"],
                hint="Create/edit with:  nova agents  ·  or @name in chat",
            )
        )

    async def _run_skills(self) -> None:
        """Show installed skills (read-only)."""
        names = self._get_skill_names()
        await self.push_screen_wait(
            InfoListScreen(
                "Skills",
                names or ["(no skills found)"],
                hint="Run a skill with:  /skill:<name>  ·  manage with:  nova skills",
            )
        )

    def _collect_skill_names(self) -> list[str]:
        from pathlib import Path

        from novacode_cli.config.config import settings

        dirs: list = []
        try:
            dirs.append(settings.ensure_user_skills_dir())
        except Exception:  # noqa: BLE001
            pass
        try:
            dirs.extend(settings.get_project_skills_dirs())
        except Exception:  # noqa: BLE001
            pass

        names: list[str] = []
        seen: set[str] = set()
        for d in dirs:
            if not d:
                continue
            p = Path(d)
            if not p.exists():
                continue
            for sk in sorted(p.iterdir()):
                if sk.is_dir() and (sk / "SKILL.md").exists() and sk.name not in seen:
                    seen.add(sk.name)
                    names.append(sk.name)
        return names

    def _get_skill_names(self) -> list[str]:
        if self._skill_names_cache is None:
            self._skill_names_cache = self._collect_skill_names()
        return self._skill_names_cache

    def _get_agent_names(self) -> list[str]:
        if self._agent_names_cache is None:
            names: list[str] = []
            try:
                from novacode_cli.config.config import settings

                for name, _d, _scope in settings.get_all_agents():
                    names.append(name)
            except Exception:  # noqa: BLE001
                pass
            self._agent_names_cache = names
        return self._agent_names_cache

    # -- slash helpers --------------------------------------------------------
    def _help_text(self) -> Text:
        t = Text()
        t.append("Nova TUI commands\n", style="bold")
        t.append("  /help            ", style="cyan")
        t.append("show this help\n", style="dim")
        t.append("  /init            ", style="cyan")
        t.append("generate NOVA.md from the codebase\n", style="dim")
        t.append("  /model           ", style="cyan")
        t.append("switch provider / model\n", style="dim")
        t.append("  /sessions        ", style="cyan")
        t.append("list / delete saved sessions\n", style="dim")
        t.append("  /mcp             ", style="cyan")
        t.append("view / remove MCP servers\n", style="dim")
        t.append("  /agents /skills  ", style="cyan")
        t.append("list subagents / skills\n", style="dim")
        t.append("  /plan [task]     ", style="cyan")
        t.append("plan mode (status / off)\n", style="dim")
        t.append("  /trace /log      ", style="cyan")
        t.append("tracing status / recent runs\n", style="dim")
        t.append("  /compact         ", style="cyan")
        t.append("summarize conversation to free context\n", style="dim")
        t.append("  /save            ", style="cyan")
        t.append("save the session now\n", style="dim")
        t.append("  /steer           ", style="cyan")
        t.append("add/list/clear steering instructions\n", style="dim")
        t.append("  /notifications   ", style="cyan")
        t.append("review task notifications (dismiss <id> · clear)\n", style="dim")
        t.append("  /research        ", style="cyan")
        t.append("launch a multi-agent research swarm\n", style="dim")
        t.append("  /dream           ", style="cyan")
        t.append("reflect over memories to surface ideas\n", style="dim")
        t.append("  /reindex         ", style="cyan")
        t.append("rebuild the semantic code-search index\n", style="dim")
        t.append("  /images          ", style="cyan")
        t.append("list/remove/clear conversation images\n", style="dim")
        t.append("  /vision          ", style="cyan")
        t.append("describe images with a vision model\n", style="dim")
        t.append("  /files           ", style="cyan")
        t.append("session file read/write summary\n", style="dim")
        t.append("  /tests           ", style="cyan")
        t.append("run project tests (auto-detect or /tests <cmd>)\n", style="dim")
        t.append("  /servers /kill   ", style="cyan")
        t.append("manage dev servers / kill processes\n", style="dim")
        t.append("  /restore         ", style="cyan")
        t.append("restore a file from the snapshot trash\n", style="dim")
        t.append("  /hooks           ", style="cyan")
        t.append("list/enable/disable/remove hooks\n", style="dim")
        t.append("  /browser-use     ", style="cyan")
        t.append("AI browser automation, results analyzed by the agent\n", style="dim")
        t.append("  /ralph           ", style="cyan")
        t.append("autonomous looping mode (/ralph <task>)\n", style="dim")
        t.append("  /remote          ", style="cyan")
        t.append("manage Discord/Telegram bridges\n", style="dim")
        t.append("  /clear           ", style="cyan")
        t.append("clear the transcript\n", style="dim")
        t.append("  /tokens /context ", style="cyan")
        t.append("show token / context usage\n", style="dim")
        t.append("  /verbose         ", style="cyan")
        t.append("toggle internal-context display\n", style="dim")
        t.append("  /decompose       ", style="cyan")
        t.append("toggle multi-step prompt splitting\n", style="dim")
        t.append("  /quit            ", style="cyan")
        t.append("exit the TUI\n", style="dim")
        t.append("  !<command>       ", style="magenta")
        t.append("run a shell command on the host\n", style="dim")
        t.append("  /skill:<name>    ", style="green")
        t.append("invoke a skill (autocompletes)\n", style="dim")
        t.append("  @<agent> <task>  ", style="green")
        t.append("delegate to a named subagent (autocompletes)\n", style="dim")
        t.append("\nEsc cancels the current turn · Ctrl+Q quits", style="dim")
        return t

    def _token_text(self) -> Text:
        if self.token_tracker is None:
            return Text("No token data available.", style="dim")
        try:
            bd = self.token_tracker.get_breakdown()
        except Exception:  # noqa: BLE001
            bd = None
        if not bd:
            return Text("No token usage captured yet.", style="dim")
        return Text(
            f"Context: {bd.usage_percentage:.1f}% used "
            f"({getattr(bd, 'tokens_used', 0):,} tokens)",
            style="dim",
        )

    async def _render(self, e: Any) -> None:
        if isinstance(e, ev.StatusUpdate):
            self._set_status(e.message or "ready")
        elif isinstance(e, ev.ReasoningDelta):
            # Stream the model's reasoning into a dim, transient message widget.
            self._reasoning_buf += e.text
            if self._reason_msg is None:
                self._reason_msg = ChatMessage(
                    Text("💭 reasoning", style="dim italic"), "reason"
                )
                await self._mount(self._reason_msg)
            self._reason_msg.update_body(
                Text(self._reasoning_buf[-2000:], style="dim italic")
            )
            self._scroll_end()
            if self._activity != "thinking…":
                self._set_status("thinking…")
        elif isinstance(e, ev.TextDelta):
            # Stream incremental prose into the in-progress Nova message widget.
            self._live_buf += e.text
            if self._stream_msg is None:
                self._stream_msg = ChatMessage(Text("Nova", style="green"), "nova")
                await self._mount(self._stream_msg)
            self._stream_msg.update_body(Text(self._live_buf))
            self._scroll_end()
            if self._activity != "responding…":
                self._set_status("responding…")
        elif isinstance(e, ev.TextDiscard):
            if self._stream_msg is not None:
                try:
                    await self._stream_msg.remove()
                except Exception:  # noqa: BLE001
                    pass
                self._stream_msg = None
            self._live_buf = ""
        elif isinstance(e, ev.AssistantMessage):
            # Commit: finalize the streaming widget as rendered markdown.
            if self._stream_msg is not None:
                self._stream_msg.update_body(Markdown(e.text))
                self._stream_msg = None
            else:
                await self._add_message(
                    Text(e.agent_name, style=e.agent_color), "nova", Markdown(e.text)
                )
            self._live_buf = ""
            await self._remove_reasoning()
            self._scroll_end()
        elif isinstance(e, ev.ToolCall):
            self._set_status(f"running {e.name}…")
            # Escape markup: tool args can contain '[' which Textual would
            # otherwise parse as console markup and crash the title render.
            base = f"{e.icon} {_esc(e.display_str)}"
            body = Static("", classes="toolbody")
            comp = Collapsible(body, title=f"{base}  · running…", collapsed=True)
            comp.add_class("tool")
            await self._mount(comp)
            entry = (comp, body, base)
            if e.call_id:
                self._tool_components[e.call_id] = entry
            self._last_tool = entry
            # Stream tool call to remote
            self._remote_send(f"🔧 {e.display_str}")
        elif isinstance(e, ev.ToolResult):
            self._finalize_tool(
                e.call_id, e.preview, e.full_output, is_error=e.is_error
            )
            self._scroll_end()
        elif isinstance(e, ev.FileOp):
            # File ops (read/write/edit) ARE the result of their tool call —
            # finalize the matching component with a NATIVE body: a colored diff
            # for writes/edits, file content for reads.
            rec = e.record
            errored = bool(getattr(rec, "error", None)) or (
                getattr(rec, "status", "") == "error"
            )
            body_render = self._fileop_body(rec, e.full_output)
            entry = self._pop_tool(e.call_id)
            if entry is not None:
                comp, body, base = entry
                mark = "✗" if errored else "✓"
                comp.title = f"{base}  {mark} {_esc(self._fileop_summary(rec))}".rstrip()
                if errored:
                    comp.collapsed = False  # surface failures
                body.update(body_render)
            else:
                self._log(body_render)
            self._scroll_end()
        elif isinstance(e, ev.TodoUpdate):
            todo_text = self._render_todos(e.todos, e.agent_name)
            if self._todo_widget is None:
                self._todo_widget = Static(todo_text, classes="todos")
                await self._mount(self._todo_widget)
            else:
                self._todo_widget.update(todo_text)
                self._scroll_end()
            # Stream todo summary to remote
            if e.todos:
                done = sum(1 for t in e.todos if (t.get("status") if isinstance(t, dict) else None) == "completed")
                total = len(e.todos)
                self._remote_send(f"📋 Todos: {done}/{total}")
        elif isinstance(e, ev.ErrorOutput):
            self._log(Text(e.text, style="red"))
        elif isinstance(e, ev.CompactionNotice):
            self._log(Text("⟳ Context compacted", style="dim"))
        elif isinstance(e, ev.SubagentActivity):
            await self._handle_subagent(e)
        elif isinstance(e, ev.UsageUpdate):
            if self.token_tracker is not None:
                try:
                    self.token_tracker.add(
                        e.input_tokens,
                        e.output_tokens,
                        cache_read_tokens=e.cache_read_tokens,
                        cache_creation_tokens=e.cache_creation_tokens,
                    )
                except Exception:  # noqa: BLE001
                    pass
        elif isinstance(e, ev.InterruptRequest):
            await self._handle_interrupt(e)
        elif isinstance(e, ev.Cancelled):
            self._log(Text("Interrupted.", style="yellow"))
        elif isinstance(e, ev.Error):
            self._log(Text(f"Error: {e.message}", style="red"))
        # ev.Done -> nothing to render

    async def _handle_interrupt(self, e: "ev.InterruptRequest") -> None:
        if e.kind == "tool":
            req = e.payload
            from novacode_cli.ui.hitl_approval import check_plan_mode_blocked

            blocked, rejection = check_plan_mode_blocked(
                req, self.session_state.plan_mode_enabled
            )
            if blocked and rejection:
                e.future.set_result(
                    {"decisions": rejection["decisions"], "any_rejected": True}
                )
                return
            action_requests = req["action_requests"]
            if self.session_state.auto_approve:
                e.future.set_result(
                    {
                        "decisions": [{"type": "approve"} for _ in action_requests],
                        "any_rejected": False,
                    }
                )
                return
            choice = await self.push_screen_wait(
                ApprovalModal(
                    "Tool action requires approval",
                    _approval_details(action_requests),
                )
            )
            if choice == "reject":
                e.future.set_result(
                    {
                        "decisions": [
                            {"type": "reject", "message": "Rejected by user"}
                            for _ in action_requests
                        ],
                        "any_rejected": True,
                    }
                )
            else:
                if choice == "auto":
                    # Approve everything for the rest of this session.
                    self.session_state.auto_approve = True
                    self._log(Text("✓ Auto-approve enabled for this session.", style="green"))
                e.future.set_result(
                    {
                        "decisions": [{"type": "approve"} for _ in action_requests],
                        "any_rejected": False,
                    }
                )
        elif e.kind == "question":
            result = await self.push_screen_wait(QuestionModal(e.payload))
            e.future.set_result(result)
        elif e.kind == "plan":
            body: Any = "Review the plan and approve to proceed."
            content = None
            try:
                from novacode_cli.ui.interrupt_handlers import resolve_plan_content

                content, _ = resolve_plan_content(
                    getattr(self.session_state, "todos", None),
                    self.session_state,
                    backend=self.backend,
                )
                if content:
                    body = Markdown(content)
            except Exception:  # noqa: BLE001
                pass
            choice = await self.push_screen_wait(
                ApprovalModal("Plan requires approval", body)
            )
            if choice in ("approve", "auto"):
                self.session_state.plan_mode_enabled = False
                self._update_mode_badge()
                if choice == "auto":
                    self.session_state.auto_approve = True
                # Store the plan for hand-off; _maybe_run_approved_plan executes it.
                if content:
                    try:
                        self.session_state.set_approved_plan(content)
                    except Exception:  # noqa: BLE001
                        pass
                e.future.set_result(
                    {
                        "response": {
                            "approved": True,
                            "mode": "auto" if choice == "auto" else "manual",
                        },
                        "state_update": {"plan_mode_enabled": False},
                    }
                )
            else:
                e.future.set_result(
                    {
                        "response": {
                            "approved": False,
                            "action": "reject",
                            "feedback": "",
                        },
                        "state_update": {},
                    }
                )
        else:
            e.future.set_result(None)


async def run_tui(
    *,
    agent,
    assistant_id,
    session_state,
    backend,
    token_tracker,
    image_tracker,
    model_name,
    session_manager=None,
    restored_messages=None,
) -> None:
    """Launch the Textual chat app and run until the user exits."""
    app = NovaApp(
        agent=agent,
        assistant_id=assistant_id,
        session_state=session_state,
        backend=backend,
        token_tracker=token_tracker,
        image_tracker=image_tracker,
        model_name=model_name,
        session_manager=session_manager,
        restored_messages=restored_messages,
    )
    await app.run_async()
