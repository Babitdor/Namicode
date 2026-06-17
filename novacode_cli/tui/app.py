"""Textual chat application (Phase 1).

A scrollable transcript + input + status line. The agent runs in a Textual
worker that iterates :func:`novacode_cli.agent_stream.run_agent_stream` and
renders each :mod:`novacode_cli.ui_events` event. HITL interrupts are shown as
modal screens.

Existing ``rich`` renderers are reused by capturing their output to a ``Text``
(``_capture``), so the visual style matches the legacy UI without duplicating
rendering code.

Animations
----------
All animated effects (entrance slide/fade/zoom, pulsing borders, shimmer,
thinking dots) are defined in :mod:`novacode_cli.tui.animations` and called
from ``on_mount`` handlers via Python's ``animate()`` API.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.markup import escape as _esc
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import (
    Button,
    Collapsible,
    Input,
    OptionList,
    Select,
    Static,
    RichLog,
)
from textual.widgets.option_list import Option

from novacode_cli.tui.animations import (
    animate_entrance,
    animate_modal_screen,
    shimmer_bar,
)


# ---------------------------------------------------------------------------
# Matrix rain — animated home screen banner
# ---------------------------------------------------------------------------


class MatrixRain(Static):
    """A matrix-style digital rain with the NOVA ASCII logo composited on top.

    Columns of falling half-width katakana/hex characters cascade down with a
    fading trail (bright head, dimmer green tail). The ASCII banner is stamped
    over the rain each frame: its solid cells occlude the rain (logo in front),
    while regular-space gaps stay transparent so the rain shows *through* the
    art — "rain behind the banner". The logo is tinted with the active TUI
    theme's primary color, so it recolors live when the theme changes.

    Half-width katakana (U+FF66–FF9D) are single-cell, so they align exactly
    with the width-1 ASCII art — full-width katakana would drift the columns.
    """

    KATAKANA = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅ"

    def __init__(self, art: str = "", width: int | None = None) -> None:
        super().__init__("", id="matrix-rain")
        self._columns: list[dict] = []
        self._chars = list(MatrixRain.KATAKANA)
        self._width: int | None = None
        self._timer: Any = None  # set_interval handle for pause/resume
        self._configure(art, width)

    def _configure(self, art: str, width: int | None) -> None:
        """(Re)compute the grid + logo placement for the given art and width."""
        # Trim blank top/bottom lines so the logo sits tightly in the rain.
        art_lines = art.splitlines() if art else []
        while art_lines and not art_lines[0].strip():
            art_lines.pop(0)
        while art_lines and not art_lines[-1].strip():
            art_lines.pop()
        self._art_lines = art_lines

        art_w = max((len(ln) for ln in art_lines), default=0)
        art_h = len(art_lines)
        # Fill (most of) the terminal width so the rain spans the whole row and
        # the logo is centered within it. Leave a small margin for the transcript
        # padding + scrollbar (avoids wrapping) and cap very wide terminals so
        # the per-frame build stays cheap.
        usable = (width or 80) - 6
        self._col_count = min(max(usable, art_w, 60), 200)
        self._row_count = max(art_h + 6, 18)
        self._art_left = max(0, (self._col_count - art_w) // 2)
        self._art_top = 2  # a couple rows of rain above the logo
        self._width = width

    def reflow(self, art: str, width: int | None) -> None:
        """Re-grid for a new terminal width (called on resize). No-op if same."""
        if width == self._width:
            return
        self._configure(art, width)
        if self.is_mounted:
            self._init_columns()  # rebuild rain columns for the new width

    def _theme_base_color(self):
        """The active theme's primary color as a Textual ``Color`` object.

        Handles ANSI theme names (``ansi_blue`` → ``blue``) and falls back to
        matrix green if the theme color can't be parsed.
        """
        from textual.color import Color

        raw = None
        try:
            raw = self.app.current_theme.primary
        except Exception:  # noqa: BLE001
            try:
                raw = self.app.theme_variables.get("primary")
            except Exception:  # noqa: BLE001
                raw = None
        raw = (raw or "#00ff88").strip()
        if raw.startswith("ansi_"):
            raw = raw[len("ansi_") :]
        try:
            return Color.parse(raw)
        except Exception:  # noqa: BLE001
            return Color.parse("#00ff88")

    def _art_style(self) -> str:
        """Bold style for the logo — the theme's primary color at full strength."""
        return f"bold {self._theme_base_color().hex}"

    def _rain_palette(self) -> tuple[str, str, str, str]:
        """(head, near, mid, tail) hex colors — a *dimmed* theme-tinted gradient.

        Derived from the theme color and darkened progressively so the rain reads
        as a subtle backdrop (no bright white head) and recolors with the theme.
        """
        base = self._theme_base_color()
        return (
            base.darken(0.15).hex,  # head — muted, not white
            base.darken(0.40).hex,  # near head
            base.darken(0.60).hex,  # mid trail
            base.darken(0.78).hex,  # tail — barely there
        )

    def on_mount(self) -> None:
        self._init_columns()
        # ~25 fps: smooth fluid rain. Previous optimizations (buffer reuse,
        # RichText.assemble) ensure this stays cheap.
        self._timer = self.set_interval(0.04, self._tick)

    def pause(self) -> None:
        """Pause the rain timer (called when the app loses OS focus or rain is
        scrolled out of view)."""
        if self._timer is not None:
            self._timer.pause()

    def resume(self) -> None:
        """Resume the rain timer (called when the app regains OS focus)."""
        if self._timer is not None:
            self._timer.resume()

    def _init_columns(self) -> None:
        self._columns = []
        span = self._row_count + 5
        for _ in range(self._col_count):
            self._columns.append(
                {
                    "pos": random.uniform(-span, 0),
                    "speed": random.uniform(0.04, 0.11),  # adjusted for 25fps
                    "trail": random.randint(5, 14),
                }
            )
        # Pre-allocate frame buffers (reused in _tick to avoid GC churn)
        self._frame_lines = [[" "] * self._col_count for _ in range(self._row_count)]
        self._frame_styles = [[""] * self._col_count for _ in range(self._row_count)]

    def _tick(self) -> None:
        """Advance one frame of the rain, then stamp the logo over it.

        Early-returns (no work) when the widget is scrolled out of the visible
        viewport, so transcript messages push the rain off-screen cheaply.
        """
        # Skip the (expensive) frame build when the banner is scrolled out of the
        # transcript viewport. Both regions are in SCREEN coordinates, so they're
        # directly comparable: if the widget sits entirely above or below the
        # parent scroll-container's visible area, there's nothing to draw.
        import sys

        is_testing = "pytest" in sys.modules or getattr(self.app, "_driving", False)
        try:
            if not is_testing:
                p = self.parent
                visible = getattr(p, "region", None)
                if visible is not None:
                    r = self.region
                    if r.height == 0 or r.bottom <= visible.y or r.y >= visible.bottom:
                        return
        except Exception:  # noqa: BLE001
            pass

        cols = self._col_count
        rows = self._row_count
        lines = self._frame_lines
        styles = self._frame_styles

        # Clear buffers for the new frame.
        for y in range(rows):
            for x in range(cols):
                lines[y][x] = " "
                styles[y][x] = ""

        head_c, near_c, mid_c, tail_c = self._rain_palette()
        choice = random.choice
        chars = self._chars

        for col, d in enumerate(self._columns):
            d["pos"] += d["speed"]
            if d["pos"] > rows + d["trail"]:  # reset when fully off-screen
                d["pos"] = random.uniform(-rows, -3)
                d["speed"] = random.uniform(0.05, 0.14)
                d["trail"] = random.randint(5, 14)

            tail_start = max(0, int(d["pos"]) - d["trail"])
            head = min(rows - 1, int(d["pos"]))
            for y in range(tail_start, head + 1):
                dist = head - y
                lines[y][col] = choice(chars)
                if dist == 0:
                    styles[y][col] = head_c
                elif dist <= 2:
                    styles[y][col] = near_c
                elif dist <= 5:
                    styles[y][col] = mid_c
                else:
                    styles[y][col] = tail_c

        # Composite the logo on top. Solid art cells occlude the rain; regular
        # spaces stay transparent so the rain shows through the gaps.
        if self._art_lines:
            art_style = self._art_style()
            for ay, art_line in enumerate(self._art_lines):
                gy = self._art_top + ay
                if not 0 <= gy < rows:
                    continue
                row_l = lines[gy]
                row_s = styles[gy]
                left = self._art_left
                for ax, ch in enumerate(art_line):
                    if ch == " ":
                        continue
                    gx = left + ax
                    if 0 <= gx < cols:
                        row_l[gx] = ch
                        row_s[gx] = art_style

        # Build the frame with run-length coalescing: collect (segment, style)
        # tuples and build the final RichText in one shot via assemble(). This
        # is significantly faster than repeated append() calls.
        from rich.text import Text as RichText

        segments: list[tuple[str, str | None]] = []
        for y in range(rows):
            line = lines[y]
            st = styles[y]
            x = 0
            while x < cols:
                s = st[x]
                j = x + 1
                while j < cols and st[j] == s:
                    j += 1
                segment = "".join(line[x:j]) if s else " " * (j - x)
                segments.append((segment, s or None))
                x = j
            if y < rows - 1:
                segments.append(("\n", None))

        self.update(RichText.assemble(*segments))


# Transcript is pruned from the top once it exceeds this many widgets, down to
# _TRANSCRIPT_LOW_WATER — keeps Textual's layout/scroll/repaint fast in long
# sessions (the DOM would otherwise grow without bound).
_MAX_TRANSCRIPT_WIDGETS = 400
_TRANSCRIPT_LOW_WATER = 320

# Tools whose result is a code change worth seeing in full: these keep their own
# Collapsible with a colored diff body so the user can review what the agent
# changed. Every other tool (reads, search, exec, MCP, …) condenses into the
# shared tool group. Keep in sync with the file-write tools that emit a FileOp
# record with a diff (see tracking/file_tracker.py).
_DETAILED_TOOL_NAMES = frozenset(
    {
        "write_file",
        "edit_file",
        "create_file",
        "multi_edit",
        "str_replace",
        "apply_patch",
    }
)


# Slash commands routed through the legacy handle_command via console capture.
# Restricted to commands that only print or toggle state — never read stdin or
# use a Live spinner (those would hang or garble inside Textual).
# Rare subcommands still delegated to handle_command (captured) from within the
# native handlers (e.g. `/trace enable`, `/log show <id>`). Common forms native.
_PASSTHROUGH_SLASH: set[str] = set()

# The @mention token immediately before the cursor (start-of-line or after
# whitespace, so emails like user@host don't match). Used to drive @file/@agent
# autocomplete *anywhere* in the line, not just at the very start.
_AT_FRAGMENT_RE = re.compile(r"(?:^|(?<=\s))@([^\s@]*)$")

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
    "/copy",
    "/plugins",
    "/steer",
    "/notifications",
    "/research",
    "/dream",
    "/evolution",
    "/reindex",
    "/images",
    "/files",
    "/tests",
    "/servers",
    "/kill",
    "/restore",
    "/hooks",
    "/browser-use",
    "/ralph",
    "/trello",
    "/create",
    "/council",
    "/clear",
    "/tokens",
    "/context",
    "/cost",
    "/verbose",
    "/trace",
    "/log",
    "/theme",
    "/quit",
    "/exit",
    # Wiki commands
    "/ingest",
    "/ask",
    "/file",
    "/wiki",
    "/effort",
    "/goal",
    "/btw",
]

from novacode_cli import ui_events as ev
from novacode_cli.agent_stream import run_agent_stream
from novacode_cli.config.config import console as _rich_console
from novacode_cli.input import (
    PASTE_MIN_CHARS,
    PASTE_MIN_NEWLINES,
    PasteTracker,
    format_paste_placeholder,
    resolve_paste_placeholders,
)

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


class SessionHeader(Horizontal):
    """A structured header showing session metadata as pills.

    Pills include: Model, Sandbox, Memory, and CWD breadcrumbs.
    """

    DEFAULT_CSS = """
    SessionHeader {
        classes: "session-header";
    }
    """

    def __init__(self, model: str, sandbox: str, cwd: str, memory: str) -> None:
        super().__init__()
        self.model = model
        self.sandbox = sandbox
        self.cwd = cwd
        self.memory = memory

    def compose(self) -> ComposeResult:
        yield Static(f"🤖 {self.model}", classes="session-pill pill-model")
        yield Static(f"📦 {self.sandbox}", classes="session-pill pill-sandbox")
        yield Static(f"🧠 {self.memory}", classes="session-pill pill-memory")
        yield Static(f"📁 {self.cwd}", classes="breadcrumb")

    def update_info(self, model: str, sandbox: str, cwd: str, memory: str) -> None:
        self.model = model
        self.sandbox = sandbox
        self.cwd = cwd
        self.memory = memory
        self.refresh()


class NovaStatusBar:
    """Legacy dummy class preserved for tests compatibility."""

    pass


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
        padding: 1 2;
        background: $surface;
    }
    /* Subtle hover cue that a message is clickable (click = copy it). */
    ChatMessage:hover { background: $boost; }
    ChatMessage > .role { text-style: bold; }
    ChatMessage > .body { height: auto; }
    ChatMessage.user { border-left: thick $primary; }
    ChatMessage.nova { border-left: thick $success; }
    ChatMessage.reason { border-left: thick $panel; color: $text-muted; }
    """

    def __init__(self, header: Text, role_class: str) -> None:
        super().__init__(classes=role_class)
        self._header = header
        # Plain-text form of the body, kept in sync by update_body so the message
        # can be copied verbatim (click-to-copy / the /copy command) without
        # re-deriving it from the rendered markdown.
        self.raw_text: str = ""
        # Body renderable received before compose() finished mounting the `.body`
        # child. Applied in on_mount so a fast first stream chunk isn't lost.
        self._pending_body: Any = None
        self.tooltip = "Click to copy this message"

        # Parse and store custom border color if specified
        self._custom_color = None
        if header.style:
            from rich.style import Style
            if isinstance(header.style, Style) and header.style.color:
                self._custom_color = header.style.color.name
            else:
                style_str = str(header.style)
                import re
                m = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}\b", style_str)
                if m:
                    self._custom_color = m.group(0)
                elif "green" in style_str:
                    self._custom_color = "#10b981"

    def compose(self) -> ComposeResult:
        yield Static(self._header, classes="role")
        if isinstance(self._pending_body, Widget):
            self._pending_body.add_class("body")
            yield self._pending_body
        else:
            yield Static(self._pending_body or "", classes="body")

    def on_mount(self) -> None:
        # Apply custom border color if set
        if self._custom_color:
            self.styles.border_left = ("thick", self._custom_color)

        # If update_body ran before the `.body` child existed, apply the stashed
        # renderable now that the children are mounted.
        if self._pending_body is not None:
            if not isinstance(self._pending_body, Widget):
                try:
                    self.query_one(".body", Static).update(self._pending_body)
                except NoMatches:
                    pass
            self._pending_body = None

    def update_header(self, header: Text) -> None:
        self._header = header
        try:
            role_static = self.query_one(".role", Static)
            role_static.update(header)
        except Exception:
            pass

        # Parse and store custom border color if specified
        self._custom_color = None
        if header.style:
            from rich.style import Style
            if isinstance(header.style, Style) and header.style.color:
                self._custom_color = header.style.color.name
            else:
                style_str = str(header.style)
                import re
                m = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}\b", style_str)
                if m:
                    self._custom_color = m.group(0)
                elif "green" in style_str:
                    self._custom_color = "#10b981"

        if self._custom_color:
            self.styles.border_left = ("thick", self._custom_color)

    def update_body(self, renderable: Any) -> None:
        self.raw_text = self._renderable_text(renderable)
        try:
            body = self.query_one(".body")
        except NoMatches:
            # Children not mounted yet (Textual composes asynchronously). Stash
            # the renderable; on_mount/compose will apply it. Prevents the
            # "No nodes match '.body'" crash on a fast first stream chunk.
            self._pending_body = renderable
            return

        if isinstance(renderable, Widget):
            if body is not renderable:
                body.remove()
                renderable.add_class("body")
                self.mount(renderable)
        else:
            if isinstance(body, Static):
                body.update(renderable)
            else:
                body.remove()
                new_body = Static(renderable, classes="body")
                self.mount(new_body)

    @staticmethod
    def _renderable_text(renderable: Any) -> str:
        """Best-effort plain text for a body renderable (Markdown/Text/other)."""
        if isinstance(renderable, Markdown):
            return renderable.markup
        if isinstance(renderable, Text):
            return renderable.plain
        if hasattr(renderable, "initial_cmd"):
            return f"$ {renderable.initial_cmd}"
        return str(renderable)

    def on_click(self, event: events.Click) -> None:
        """Click a message to copy its full text to the clipboard.

        This is deterministic and terminal-independent — unlike mouse
        drag-selection, which a captured-mouse TUI can't reliably support.
        Drag-selection still works: Textual only fires Click when there was no
        drag, and an explicit selection takes precedence here.
        """
        body = (self.raw_text or "").strip()
        if not body:
            return
        app = self.app
        try:
            if app.screen.get_selected_text():
                return  # honor an explicit selection — ctrl+c will copy it
        except Exception:  # noqa: BLE001
            pass
        try:
            app.copy_to_clipboard(body)
            app._log(  # type: ignore[attr-defined]
                Text(f"📋 Copied message ({len(body):,} chars)", style="dim")
            )
            event.stop()
        except Exception:  # noqa: BLE001
            pass


def _capture(fn, *args, **kwargs) -> Text:
    """Render an existing ``console.print``-based helper into a ``Text``.

    Lets the TUI reuse the legacy rich renderers (tool panels, todos, file ops)
    without printing to the real terminal — capture redirects the global
    console to an in-memory buffer.
    """
    with _rich_console.capture() as cap:
        fn(*args, **kwargs)
    return Text.from_ansi(cap.get())


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

    def on_mount(self) -> None:
        animate_modal_screen(self)

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
        animate_modal_screen(self)
        ol = self.query_one("#choices", OptionList)
        ol.add_option(Option("Approve (y)"))
        if self._allow_auto:
            ol.add_option(Option("Auto-approve for this thread (a)"))
        ol.add_option(Option("Reject (n)"))
        ol.highlighted = 0
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
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
        prompt = self._q.get("question") or self._q.get("prompt") or "The agent has a question:"
        opts = self._q.get("options") or []
        with Vertical(id="modal-box"):
            yield Static(Text(str(prompt), style="bold"), id="modal-title")
            if opts:
                # Use Text (not a raw markup string) so an option containing
                # '[' can't be parsed as markup and crash the render.
                lines = "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(opts))
                yield Static(Text(lines), id="modal-body")
            yield Input(placeholder="Type your answer (or option number)…", id="answer")

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
        self.dismiss({"response": QuestionResponse(answer=answer, selected_index=selected)})


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

        default_value = self._current if self._current in MODEL_PRESETS else Select.BLANK
        with Vertical(id="modal-box"):
            yield Static(Text("Switch model", style="bold"), id="modal-title")
            yield Select(options, value=default_value, id="provider", allow_blank=True)
            yield Static("", id="modelinfo")
            # For Ollama: a live list of installed models (from `ollama list`).
            # Hidden for other providers (shown via _refresh_info).
            yield OptionList(id="modellist")
            yield Input(placeholder="API key (blank = use saved)", password=True, id="apikey")
            yield Input(placeholder="Model (blank = default, or type any slug)", id="model")
            with Horizontal(id="modal-buttons"):
                yield Button("Switch", id="switch", variant="success")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        # List is shown only for Ollama; hide until a provider is chosen.
        self.query_one("#modellist", OptionList).display = False
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
        model_list = self.query_one("#modellist", OptionList)

        if pid == "ollama":
            # Populate the list from `ollama list` (off the event loop).
            info.append("loading installed models (ollama list)…", style="dim")
            model_list.display = True
            self._load_ollama_models()
        else:
            models = preset.get("models", [])
            if models:
                info.append("suggestions: " + ", ".join(models[:6]), style="dim")
            model_list.display = False
            model_list.clear_options()

        self.query_one("#modelinfo", Static).update(info)
        self.query_one("#model", Input).placeholder = f"Model (blank = {preset['default_model']})"

    @work(exclusive=True)
    async def _load_ollama_models(self) -> None:
        """Populate the Ollama model list from `ollama list` without blocking."""
        import asyncio

        from novacode_cli.config.model_manager import get_ollama_models

        try:
            models = await asyncio.to_thread(get_ollama_models)
        except Exception:  # noqa: BLE001
            models = []

        try:
            model_list = self.query_one("#modellist", OptionList)
        except Exception:  # noqa: BLE001
            return  # screen dismissed before load finished
        model_list.clear_options()

        if not models:
            model_list.add_option(
                Option(
                    "No Ollama models found — is `ollama` installed/running?",
                    id="__none__",
                )
            )
            return

        for name in models:
            model_list.add_option(Option(name, id=name))

        info = Text()
        info.append(
            f"{len(models)} installed model(s) — select one or type a slug below\n",
            style="dim",
        )
        try:
            self.query_one("#modelinfo", Static).update(info)
        except Exception:  # noqa: BLE001
            pass

    def on_option_list_option_selected(self, event: "OptionList.OptionSelected") -> None:
        # Only the Ollama model list lives on this screen.
        if event.option_list.id != "modellist":
            return
        chosen = event.option.id
        if chosen and chosen != "__none__":
            self.query_one("#model", Input).value = chosen

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter in the API-key / model field applies the switch (same as the
        # Switch button) — a keyboard path so the user is never blocked when the
        # button is scrolled off a short terminal (e.g. behind the Ollama list).
        self._submit()

    def _submit(self) -> None:
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
            project = Path(meta.project_root).name if meta.project_root else "no project"
            model = meta.model_name or "unknown"
            marker = " ← current" if meta.session_id == self._current else ""
            ol.add_option(
                Option(
                    f"{meta.session_id[:8]}{marker}  ·  {project} ({model})  ·  "
                    f"{meta.message_count} msgs  ·  {age}"
                )
            )
        hint.update(Text("Resume with:  nova --continue <id>", style="dim"))

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
                yield Button("Toggle Active", id="toggle-enable")
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
                is_disabled = getattr(sc, "disabled", False)
                is_active = name in active_servers and not is_disabled
                transport = getattr(sc, "transport", "?")
                loc = getattr(sc, "url", None) or getattr(sc, "command", None) or ""
                if is_disabled:
                    status_mark = "\u25cb"
                    status_style = "#f7768e"
                    label = Text.assemble(
                        (f"{status_mark}  {name} (disabled)  \u00b7  ", status_style),
                        (f"{transport}  \u00b7  {loc}", "dim strike"),
                    )
                else:
                    status_mark = "\u25cf" if is_active else "\u25cb"
                    status_style = "#73daca" if is_active else "#565f89"
                    label = Text.assemble(
                        (f"{status_mark}  {name}  \u00b7  ", status_style),
                        (f"{transport}  \u00b7  {loc}", "dim"),
                    )
                configured.add_option(Option(label))

            # Show active tool count
            active_section = self.query_one("#mcp-section", Static)
            active_count = sum(1 for n in active_servers if n in self._config_names and not getattr(servers[n], "disabled", False))
            disabled_count = sum(1 for n in self._config_names if getattr(servers[n], "disabled", False))
            inactive_count = len(self._config_names) - active_count - disabled_count

            counts_str = []
            if active_count:
                counts_str.append(f"{active_count} active")
            if inactive_count:
                counts_str.append(f"{inactive_count} inactive")
            if disabled_count:
                counts_str.append(f"{disabled_count} disabled")

            counts_text = f" ({', '.join(counts_str)})" if counts_str else ""
            active_section.update(
                Text(
                    f"Configured Servers: {len(self._config_names)} total" + counts_text,
                    style="bold cyan",
                )
            )
        else:
            configured.add_option(Option("(no MCP servers configured)"))
            self.query_one("#mcp-section", Static).update(
                Text("Configured Servers: (none)", style="bold cyan")
            )

        # Update toggle button dynamically based on reload
        self._update_toggle_button(configured.highlighted)

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
        elif event.button.id == "toggle-enable":
            self._toggle_highlighted()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "mcp-configured":
            self._update_toggle_button(event.option_index)

    def _update_toggle_button(self, idx: int | None) -> None:
        try:
            btn = self.query_one("#toggle-enable", Button)
            if idx is None or not (0 <= idx < len(self._config_names)):
                btn.label = "Toggle Active"
                btn.disabled = True
                return

            btn.disabled = False
            name = self._config_names[idx]
            from novacode_cli.mcp.config import MCPConfig
            sc = MCPConfig().get_server(name)
            if sc and getattr(sc, "disabled", False):
                btn.label = "Activate"
            else:
                btn.label = "Deactivate"
        except Exception:
            pass

    @work
    async def _toggle_highlighted(self) -> None:
        if not self._config_names:
            return
        ol = self.query_one("#mcp-configured", OptionList)
        idx = ol.highlighted
        if idx is None or not (0 <= idx < len(self._config_names)):
            return
        name = self._config_names[idx]
        try:
            from novacode_cli.mcp.config import MCPConfig

            config_mgr = MCPConfig()
            sc = config_mgr.get_server(name)
            if sc:
                sc.disabled = not getattr(sc, "disabled", False)
                await config_mgr.add_server_async(name, sc)

                # Show status message
                state_str = "deactivated" if sc.disabled else "activated"
                self.app._log(
                    Text(
                        f"\u2713 MCP '{name}' {state_str}!",
                        style="green",
                    )
                )
                if hasattr(self.app, "session_state") and hasattr(self.app.session_state, "reload_mcp_servers"):
                    new_agent, new_backend = await self.app.session_state.reload_mcp_servers()
                    self.app.agent = new_agent
                    self.app.backend = new_backend
        except Exception as ex:  # noqa: BLE001
            self.app._log(Text(f"Toggle failed: {ex}", style="red"))
        self._reload()

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
                self.app._log(
                    Text(
                        f"\u2713 MCP '{name}' removed!",
                        style="green",
                    )
                )
                if hasattr(self.app, "session_state") and hasattr(self.app.session_state, "reload_mcp_servers"):
                    new_agent, new_backend = await self.app.session_state.reload_mcp_servers()
                    self.app.agent = new_agent
                    self.app.backend = new_backend
            except Exception as ex:  # noqa: BLE001
                self.app._log(Text(f"Remove failed: {ex}", style="red"))
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
            result = await self.app.push_screen_wait(McpInstallModal(preset, preset_id))
            if result is None:  # cancelled
                return
            user_inputs = result

        # Create and save config
        try:
            from novacode_cli.mcp.config import MCPConfig
            from novacode_cli.mcp.presets import create_config_from_preset

            config = create_config_from_preset(preset_id, user_inputs)
            if config:
                MCPConfig().add_server(preset_id, config)
                self.app._log(
                    Text(
                        f"\u2713 MCP preset '{preset['name']}' installed!",
                        style="green",
                    )
                )
                if hasattr(self.app, "session_state") and hasattr(self.app.session_state, "reload_mcp_servers"):
                    new_agent, new_backend = await self.app.session_state.reload_mcp_servers()
                    self.app.agent = new_agent
                    self.app.backend = new_backend
        except Exception as ex:  # noqa: BLE001
            self.app._log(Text(f"Install failed: {ex}", style="red"))
        self._reload()

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
                self.app._log(
                    Text(
                        f"\u2713 Custom MCP '{name}' added!",
                        style="green",
                    )
                )
                if hasattr(self.app, "session_state") and hasattr(self.app.session_state, "reload_mcp_servers"):
                    new_agent, new_backend = await self.app.session_state.reload_mcp_servers()
                    self.app.agent = new_agent
                    self.app.backend = new_backend
            except Exception as ex:  # noqa: BLE001
                self.app._log(Text(f"Add custom MCP failed: {ex}", style="red"))
            self._reload()

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
                Text(
                    f"{preset.get('description', '')}\nPackage: {preset.get('package', 'N/A')}",
                    style="dim",
                ),
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
            yield Input(
                placeholder="npx -y @scope/package  OR  https://example.com/mcp",
                id="mcp-conn",
            )
            yield Input(placeholder="Description (optional)", id="mcp-desc")
            yield Static("", id="mcp-custom-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Add", id="do-add", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        animate_modal_screen(self)
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
        hint = self.query_one("#mcp-custom-hint", Static)
        try:
            name = self.query_one("#mcp-name", Input).value.strip()
        except Exception:  # noqa: BLE001
            name = ""
        if not name:
            hint.update(Text("Server name is required", style="red"))
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
            hint.update(Text("Connection string/URL is required", style="red"))
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
            cmd = parts[0] if parts else conn
            # Validate command locally first to show immediate feedback in modal!
            try:
                from novacode_cli.mcp.config import MCPServerConfig
                MCPServerConfig.validate_command(cmd)
            except ValueError as ex:
                hint.update(Text(f"Validation failed: {ex}", style="red"))
                return

            result = {
                "name": name,
                "transport": "stdio",
                "command": cmd,
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


class PluginsScreen(ModalScreen[None]):
    """Native ``/plugins`` manager: list installed plugins and toggle them.

    Enable/disable writes ``~/.nova/plugins/manifest.json``; the agent reads it
    at build time, so a session restart is needed for changes to take effect.
    """

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._plugins: list = []  # list of (name, spec)

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Plugins", style="bold"), id="modal-title")
            yield OptionList(id="plugins")
            yield Static("", id="plugins-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Enable / Disable", id="toggle", variant="success")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._reload()

    @staticmethod
    def _counts(spec: Any) -> str:
        if not isinstance(spec, dict):
            return ""
        parts = []
        for key, label in (
            ("middleware", "mw"),
            ("tools", "t"),
            ("subagents", "sa"),
            ("commands", "cmd"),
        ):
            n = len(spec.get(key, []) or [])
            if n:
                parts.append(f"{n}{label}")
        return " · ".join(parts)

    def _reload(self) -> None:
        from novacode_cli.plugins.loader import (
            discover_plugins,
            list_enabled_plugins,
        )

        try:
            self._plugins = discover_plugins()
        except Exception:  # noqa: BLE001
            self._plugins = []
        enabled = set(list_enabled_plugins())

        ol = self.query_one("#plugins", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        hint = self.query_one("#plugins-hint", Static)

        if not self._plugins:
            hint.update(
                Text(
                    "No plugins installed.  pip install one (it registers a "
                    "'nova.plugins' entry point), then reopen /plugins.",
                    style="dim",
                )
            )
            return

        for name, spec in self._plugins:
            on = name in enabled
            opt = Text()
            opt.append("✓ enabled  " if on else "○ disabled ", style="green" if on else "dim")
            opt.append(str(name), style="bold")
            desc = spec.get("description", "") if isinstance(spec, dict) else ""
            if desc:
                opt.append(f"  — {desc}")
            counts = self._counts(spec)
            if counts:
                opt.append(f"   [{counts}]", style="dim")
            ol.add_option(Option(opt))

        if keep is not None and 0 <= keep < len(self._plugins):
            ol.highlighted = keep
        else:
            ol.highlighted = 0
        ol.focus()
        hint.update(
            Text(
                "Enter or Enable/Disable to toggle · restart the session to apply",
                style="dim",
            )
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._toggle(event.option_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "toggle":
            ol = self.query_one("#plugins", OptionList)
            if ol.highlighted is not None:
                self._toggle(ol.highlighted)

    def _toggle(self, idx: int) -> None:
        if not 0 <= idx < len(self._plugins):
            return
        from novacode_cli.plugins.loader import (
            disable_plugin,
            enable_plugin,
            list_enabled_plugins,
        )

        name = self._plugins[idx][0]
        if name in set(list_enabled_plugins()):
            disable_plugin(name)
        else:
            enable_plugin(name)
        self._reload()

    def action_close(self) -> None:
        self.dismiss(None)


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
        animate_modal_screen(self)
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


class AgentCreateModal(ModalScreen[dict | None]):
    """Modal dialog to collect inputs for creating a new custom subagent."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        from novacode_cli.config.config import settings
        
        scope_options = [("Global (all projects)", "global")]
        if settings.project_root is not None:
            scope_options.append(("Project (current project only)", "project"))

        with Vertical(id="modal-box"):
            yield Static(Text("Create Custom Subagent", style="bold"), id="modal-title")
            yield Static(Text("Agent Name (e.g. code-reviewer):", style="bold"), id="agent-name-label")
            yield Input(placeholder="Name (letters, numbers, hyphens, underscores)", id="agent-name")
            
            yield Static(Text("Specialization / Description:", style="bold"), id="agent-desc-label")
            yield Input(placeholder="e.g. Reviews python code for security vulnerabilities", id="agent-desc")
            
            yield Static(Text("Storage Scope:", style="bold"), id="agent-scope-label")
            yield Select(scope_options, id="agent-scope", value="global")
            
            yield Static(Text("Color Theme:", style="bold"), id="agent-color-label")
            yield Select(
                [
                    ("Sky Blue", "#0ea5e9"),
                    ("Teal", "#14b8a6"),
                    ("Green", "#22c55e"),
                    ("Blue", "#3b82f6"),
                    ("Orange", "#f97316"),
                    ("Red", "#ef4444"),
                    ("Purple", "#a855f7"),
                    ("Pink", "#ec4899"),
                    ("Gray", "#6b7280"),
                ],
                id="agent-color",
                value="#0ea5e9",
            )
            yield Static("", id="agent-create-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Create", id="do-create", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self.query_one("#agent-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "do-create":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "agent-name":
            self.query_one("#agent-desc", Input).focus()
        elif event.input.id == "agent-desc":
            self._submit()

    def _submit(self) -> None:
        hint = self.query_one("#agent-create-hint", Static)
        try:
            name = self.query_one("#agent-name", Input).value.strip()
        except Exception:
            name = ""
        if not name:
            hint.update(Text("Agent name is required", style="red"))
            return

        from novacode_cli.config.config import settings
        if not settings._is_valid_agent_name(name):
            hint.update(Text("Invalid name (use letters, numbers, hyphens, underscores)", style="red"))
            return

        try:
            desc = self.query_one("#agent-desc", Input).value.strip()
        except Exception:
            desc = ""
        if not desc:
            hint.update(Text("Description is required", style="red"))
            return

        try:
            scope = self.query_one("#agent-scope", Select).value
        except Exception:
            scope = "global"

        try:
            color = self.query_one("#agent-color", Select).value
        except Exception:
            color = "#0ea5e9"

        self.dismiss({
            "name": name,
            "description": desc,
            "scope": scope,
            "color": color,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class AgentsScreen(ModalScreen[None]):
    """Native subagents manager: list configured agents, view details, create or delete them."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._agents: list[tuple[str, Path, str]] = []  # list of (name, path, scope)
        self._generating = False

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Subagents Manager", style="bold"), id="modal-title")
            yield Static(Text("Configured Subagents:", style="bold cyan"), id="agents-section")
            yield OptionList(id="agents-list")
            yield Static(Text("Subagent Details:", style="bold yellow"), id="agent-detail-header")
            yield Static("", id="agent-detail-preview", classes="preview-box")
            yield Static("", id="agents-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Create", id="create", variant="primary")
                yield Button("Delete", id="delete", variant="error")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._reload()

    def _reload(self) -> None:
        from novacode_cli.config.config import settings

        try:
            self._agents = sorted(settings.get_all_agents(), key=lambda x: x[0].lower())
        except Exception:
            self._agents = []

        ol = self.query_one("#agents-list", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        hint = self.query_one("#agents-hint", Static)

        if not self._agents:
            ol.add_option(Option("(no custom subagents found)"))
            self.query_one("#agent-detail-preview", Static).update(Text("No subagents are currently configured.", style="dim"))
            self.query_one("#delete", Button).disabled = True
            hint.update(Text("Create one with the Create button", style="dim"))
            return

        self.query_one("#delete", Button).disabled = False
        for name, path, scope in self._agents:
            from novacode_cli.commands.agents_commands import extract_agent_description
            desc = ""
            try:
                desc = extract_agent_description(path / "agent.md")
            except Exception:
                pass
            label = Text.assemble(
                (f"@{name} ", "bold #73daca"),
                (f" · {scope} · ", "dim"),
                (desc, "dim")
            )
            ol.add_option(Option(label))

        if keep is not None and 0 <= keep < len(self._agents):
            ol.highlighted = keep
        else:
            ol.highlighted = 0
        ol.focus()
        
        self._update_preview(ol.highlighted)
        hint.update(Text("Select an agent to see details · Create/Delete custom agents", style="dim"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "agents-list":
            self._update_preview(event.option_index)

    def _update_preview(self, idx: int | None) -> None:
        preview = self.query_one("#agent-detail-preview", Static)
        if idx is None or not self._agents or not (0 <= idx < len(self._agents)):
            preview.update("")
            return

        name, path, scope = self._agents[idx]
        from novacode_cli.commands.agents_commands import extract_agent_description
        desc = ""
        system_prompt = ""
        color = ""
        agent_md = path / "agent.md"
        try:
            desc = extract_agent_description(agent_md)
            content = agent_md.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    system_prompt = parts[2].strip()
                    for line in parts[1].splitlines():
                        if line.strip().startswith("color:"):
                            color = line.split(":", 1)[1].strip()
            else:
                system_prompt = content.strip()
        except Exception as e:
            system_prompt = f"(error reading system prompt: {e})"

        preview_text = Text()
        preview_text.append(f"Name: ", style="bold")
        preview_text.append(f"@{name}\n", style="bold #73daca")
        preview_text.append(f"Scope: ", style="bold")
        preview_text.append(f"{scope}\n", style="bold yellow" if scope == "project" else "bold blue")
        if color:
            preview_text.append(f"Color: ", style="bold")
            preview_text.append(f"{color}\n", style=f"bold {color}")
        if desc:
            preview_text.append(f"Description: ", style="bold")
            preview_text.append(f"{desc}\n\n", style="dim")
        preview_text.append(f"System Prompt:\n", style="bold")
        preview_text.append(system_prompt, style="italic dim")

        preview.update(preview_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "create":
            if not self._generating:
                self.app.run_worker(self._create_agent(), group="create_agent", exclusive=True)
        elif event.button.id == "delete":
            if not self._generating:
                self._delete_agent()

    async def _create_agent(self) -> None:
        result = await self.app.push_screen_wait(AgentCreateModal())
        if result is not None:
            name = result["name"]
            desc = result["description"]
            scope = result["scope"]
            color = result["color"]

            from novacode_cli.config.config import settings
            from pathlib import Path
            if scope == "project":
                agents_dir = settings.ensure_project_agents_dir()
                agent_dir = agents_dir / name
            else:
                agent_dir = settings.get_agents_root_dir() / name

            if agent_dir.exists():
                if self.is_mounted:
                    try:
                        hint = self.query_one("#agents-hint", Static)
                        hint.update(Text(f"Agent '{name}' already exists in that scope.", style="yellow"))
                    except Exception:
                        pass
                self.app._log(Text(f"Agent '{name}' already exists in that scope.", style="yellow"))
                return

            self._generating = True
            if self.is_mounted:
                try:
                    self.query_one("#create", Button).disabled = True
                    self.query_one("#delete", Button).disabled = True
                except Exception:
                    pass

                try:
                    hint = self.query_one("#agents-hint", Static)
                    hint.update(Text(f"Generating system prompt for @{name} using AI... Please wait.", style="bold cyan"))
                except Exception:
                    pass
            self.app._log(Text(f"Generating system prompt for @{name} using AI...", style="cyan"))

            try:
                from novacode_cli.commands.agents_commands import _generate_agent_system_prompt
                system_prompt = await _generate_agent_system_prompt(name, desc)
                if not system_prompt:
                    raise RuntimeError("AI generation of system prompt returned empty response.")

                final_content = f"""---
color: {color}
description: {desc}
---

{system_prompt}"""

                agent_dir.mkdir(parents=True, exist_ok=True)
                agent_md = agent_dir / "agent.md"
                agent_md.write_text(final_content, encoding="utf-8")

                if self.is_mounted:
                    try:
                        hint = self.query_one("#agents-hint", Static)
                        hint.update(Text(f"✓ Custom subagent '@{name}' created successfully!", style="green"))
                    except Exception:
                        pass
                self.app._log(Text(f"✓ Custom subagent '@{name}' created successfully!", style="green"))
                self.app._agent_names_cache = None
            except Exception as e:
                if self.is_mounted:
                    try:
                        hint = self.query_one("#agents-hint", Static)
                        hint.update(Text(f"Failed to create agent: {e}", style="red"))
                    except Exception:
                        pass
                self.app._log(Text(f"Failed to create agent: {e}", style="red"))
            
            self._generating = False
            if self.is_mounted:
                try:
                    self.query_one("#create", Button).disabled = False
                    self.query_one("#delete", Button).disabled = False
                except Exception:
                    pass
                self._reload()

    @work
    async def _delete_agent(self) -> None:
        if self._generating:
            return
        ol = self.query_one("#agents-list", OptionList)
        idx = ol.highlighted
        if idx is None or not self._agents or not (0 <= idx < len(self._agents)):
            return

        name, path, scope = self._agents[idx]
        ok = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete custom subagent '@{name}'?",
                Text("This will delete the agent's folder and prompt config. This cannot be undone."),
            )
        )
        if ok:
            import shutil
            try:
                shutil.rmtree(path)
                self.app._log(Text(f"✓ Deleted subagent '@{name}'!", style="green"))
                self.app._agent_names_cache = None
            except Exception as e:
                self.app._log(Text(f"Failed to delete subagent: {e}", style="red"))
            self._reload()

    def action_close(self) -> None:
        if self._generating:
            return
        self.dismiss(None)


class SkillCreateModal(ModalScreen[dict | None]):
    """Modal dialog to collect inputs for creating a new custom skill."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        from novacode_cli.config.config import settings
        
        scope_options = [("Global (all projects)", "global")]
        if settings.project_root is not None:
            scope_options.append(("Project (current project only)", "project"))

        with Vertical(id="modal-box"):
            yield Static(Text("Create Custom Skill", style="bold"), id="modal-title")
            yield Static(Text("Skill Name (e.g. docker-deploy):", style="bold"), id="skill-name-label")
            yield Input(placeholder="Name (letters, numbers, hyphens, underscores)", id="skill-name")
            
            yield Static(Text("Specialization / Description:", style="bold"), id="skill-desc-label")
            yield Input(placeholder="Description (optional)", id="skill-desc")
            
            yield Static(Text("Storage Scope:", style="bold"), id="skill-scope-label")
            yield Select(scope_options, id="skill-scope", value="global")
            
            yield Static("", id="skill-create-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Create", id="do-create", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self.query_one("#skill-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "do-create":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "skill-name":
            self.query_one("#skill-desc", Input).focus()
        elif event.input.id == "skill-desc":
            self._submit()

    def _submit(self) -> None:
        hint = self.query_one("#skill-create-hint", Static)
        try:
            name = self.query_one("#skill-name", Input).value.strip()
        except Exception:
            name = ""
        if not name:
            hint.update(Text("Skill name is required", style="red"))
            return

        from novacode_cli.skills.skill_creation import _validate_name
        is_valid, err = _validate_name(name)
        if not is_valid:
            hint.update(Text(f"Invalid name: {err}", style="red"))
            return

        try:
            desc = self.query_one("#skill-desc", Input).value.strip()
        except Exception:
            desc = ""

        try:
            scope = self.query_one("#skill-scope", Select).value
        except Exception:
            scope = "global"

        self.dismiss({
            "name": name,
            "description": desc,
            "scope": scope,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class SkillsScreen(ModalScreen[None]):
    """Native skills manager: list installed skills, view details, create new skills."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._generating = False

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Skills Manager", style="bold"), id="modal-title")
            yield Static(Text("Installed Skills:", style="bold cyan"), id="skills-section")
            yield OptionList(id="skills-list")
            yield Static(Text("Skill Details:", style="bold yellow"), id="skill-detail-header")
            yield Static("", id="skill-detail-preview", classes="preview-box")
            yield Static("", id="skills-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Create", id="create", variant="primary")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._reload()

    def _reload(self) -> None:
        self.app._skill_names_cache = None
        names = self.app._get_skill_names()

        ol = self.query_one("#skills-list", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        hint = self.query_one("#skills-hint", Static)

        if not names:
            ol.add_option(Option("(no skills found)"))
            self.query_one("#skill-detail-preview", Static).update(Text("No skills are currently installed.", style="dim"))
            hint.update(Text("Create one with the Create button", style="dim"))
            return

        for name in names:
            ol.add_option(Option(Text(name, style="bold #e0af68")))

        if keep is not None and 0 <= keep < len(names):
            ol.highlighted = keep
        else:
            ol.highlighted = 0
        ol.focus()

        self._update_preview(ol.highlighted)
        hint.update(Text("Select a skill to see details · Create custom skills", style="dim"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "skills-list":
            self._update_preview(event.option_index)

    def _update_preview(self, idx: int | None) -> None:
        preview = self.query_one("#skill-detail-preview", Static)
        names = self.app._get_skill_names()
        if idx is None or not names or not (0 <= idx < len(names)):
            preview.update("")
            return

        skill_name = names[idx]
        
        from pathlib import Path
        from novacode_cli.config.config import Settings, settings

        skill_path = None
        scope = "unknown"
        
        search_dirs = []
        try:
            search_dirs.append((settings.ensure_user_skills_dir(), "global"))
        except Exception:
            pass
        try:
            claude_dir = Settings.get_global_claude_skills_dir()
            if claude_dir.exists():
                search_dirs.append((claude_dir, "global"))
        except Exception:
            pass
        try:
            for d in settings.get_project_skills_dirs():
                search_dirs.append((Path(d), "project"))
        except Exception:
            pass

        for d, sc in search_dirs:
            if d and (d / skill_name / "SKILL.md").exists():
                skill_path = d / skill_name / "SKILL.md"
                scope = sc
                break

        desc = ""
        instructions = ""
        if skill_path:
            try:
                content = skill_path.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        instructions = parts[2].strip()
                        for line in parts[1].splitlines():
                            if line.strip().startswith("description:"):
                                desc = line.split(":", 1)[1].strip()
                else:
                    instructions = content.strip()
            except Exception as e:
                instructions = f"(error reading skill: {e})"
        else:
            instructions = "(SKILL.md file not found)"

        preview_text = Text()
        preview_text.append(f"Name: ", style="bold")
        preview_text.append(f"{skill_name}\n", style="bold #e0af68")
        preview_text.append(f"Scope: ", style="bold")
        preview_text.append(f"{scope}\n", style="bold yellow" if scope == "project" else "bold blue")
        if desc:
            preview_text.append(f"Description: ", style="bold")
            preview_text.append(f"{desc}\n\n", style="dim")
        preview_text.append(f"Instructions / Content:\n", style="bold")
        preview_text.append(instructions[:1000] + "..." if len(instructions) > 1000 else instructions, style="italic dim")

        preview.update(preview_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "create":
            if not self._generating:
                self.app.run_worker(self._create_skill(), group="create_skill", exclusive=True)

    async def _create_skill(self) -> None:
        result = await self.app.push_screen_wait(SkillCreateModal())
        if result is not None:
            name = result["name"]
            desc = result["description"]
            scope = result["scope"]

            from novacode_cli.config.config import settings
            if scope == "project":
                base_dir = settings.ensure_project_skills_dir()
            else:
                base_dir = settings.ensure_user_skills_dir(self.app.assistant_id)

            skill_dir = base_dir / name
            if skill_dir.exists():
                if self.is_mounted:
                    try:
                        hint = self.query_one("#skills-hint", Static)
                        hint.update(Text(f"Skill '{name}' already exists.", style="yellow"))
                    except Exception:
                        pass
                self.app._log(Text(f"Skill '{name}' already exists.", style="yellow"))
                return

            self._generating = True
            if self.is_mounted:
                try:
                    self.query_one("#create", Button).disabled = True
                except Exception:
                    pass

                try:
                    hint = self.query_one("#skills-hint", Static)
                    hint.update(Text(f"Generating skill '{name}' using AI... Please wait.", style="bold cyan"))
                except Exception:
                    pass
            self.app._log(Text(f"Generating skill '{name}' using AI...", style="cyan"))

            try:
                skill_dir.mkdir(parents=True, exist_ok=True)
                
                from novacode_cli.skills.skill_creation import _generate_skill
                content = await _generate_skill(
                    name,
                    base_dir=base_dir,
                    description=desc if desc else None,
                )

                if content is None:
                    raise RuntimeError("AI generation returned empty response.")

                if self.is_mounted:
                    try:
                        hint = self.query_one("#skills-hint", Static)
                        hint.update(Text(f"✓ Skill '{name}' created successfully!", style="green"))
                    except Exception:
                        pass
                self.app._log(Text(f"✓ Skill '{name}' created successfully!", style="green"))
            except Exception as e:
                if self.is_mounted:
                    try:
                        hint = self.query_one("#skills-hint", Static)
                        hint.update(Text(f"Failed to create skill: {e}", style="red"))
                    except Exception:
                        pass
                self.app._log(Text(f"Failed to create skill: {e}", style="red"))
            
            self._generating = False
            if self.is_mounted:
                try:
                    self.query_one("#create", Button).disabled = False
                except Exception:
                    pass
                self._reload()

    def action_close(self) -> None:
        self.dismiss(None)


class WikiScreen(ModalScreen[None]):
    """Native wiki manager: browse synthesized wiki pages, view details, ingest raw sources."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._pages: list[tuple[str, str, str]] = []  # list of (topic, path, summary)
        self._sources: list[str] = []  # list of raw source paths
        self._active_tab = "pages"  # "pages" or "inbox"

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Obsidian LLM Wiki Browser", style="bold"), id="modal-title")
            
            with Horizontal(id="wiki-tab-buttons"):
                yield Button("Synthesized Pages", id="tab-pages", variant="primary")
                yield Button("Web Clipper Inbox", id="tab-inbox")
            
            with Vertical(id="pages-container"):
                yield Static(Text("Synthesized Pages:", style="bold cyan"), id="pages-header")
                yield OptionList(id="wiki-pages-list")
            
            with Vertical(id="inbox-container"):
                yield Static(Text("Clipper Inbox / raw:", style="bold cyan"), id="inbox-header")
                yield OptionList(id="wiki-inbox-list")
                
            yield Static(Text("Preview:", style="bold yellow"), id="wiki-detail-header")
            yield Static("", id="wiki-detail-preview", classes="preview-box")
            yield Static("", id="wiki-hint")
            
            with Horizontal(id="modal-buttons"):
                yield Button("Ask About Page", id="ask-btn", variant="primary")
                yield Button("Ingest Selected", id="ingest-btn", variant="primary")
                yield Button("Refresh", id="refresh-btn")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._reload()
        self._switch_tab("pages")

    def _reload(self) -> None:
        from novacode_cli.wiki.manager import WikiManager
        from novacode_cli.wiki.ingest import IngestEngine

        # Synthesized Pages
        try:
            mgr = WikiManager()
            mgr.ensure_structure()
            entries = mgr.read_index()
            self._pages = sorted(
                [(topic, info["path"], info.get("summary", "")) for topic, info in entries.items()],
                key=lambda x: x[0].lower()
            )
        except Exception:
            self._pages = []

        # Clipper Inbox / raw sources
        try:
            engine = IngestEngine()
            self._sources = engine.list_raw_sources()
        except Exception:
            self._sources = []

        # Update lists
        ol_pages = self.query_one("#wiki-pages-list", OptionList)
        ol_pages.clear_options()
        for topic, path, summary in self._pages:
            label = Text.assemble(
                (f"{topic} ", "bold #7bb6ec"),
                (f"({path}) ", "dim"),
                (f"— {summary}" if summary else "", "dim")
            )
            ol_pages.add_option(Option(label))
        if self._pages:
            ol_pages.highlighted = 0

        ol_inbox = self.query_one("#wiki-inbox-list", OptionList)
        ol_inbox.clear_options()
        for s in self._sources:
            label = Text(s, style="bold #a6e3a1")
            ol_inbox.add_option(Option(label))
        if self._sources:
            ol_inbox.highlighted = 0

        # Reset preview
        self._update_preview()

    def _switch_tab(self, tab: str) -> None:
        self._active_tab = tab
        if tab == "pages":
            self.query_one("#tab-pages", Button).variant = "primary"
            self.query_one("#tab-inbox", Button).variant = "default"
            self.query_one("#pages-container").display = True
            self.query_one("#inbox-container").display = False
            self.query_one("#ask-btn", Button).display = True
            self.query_one("#ingest-btn", Button).display = False
            try:
                self.query_one("#wiki-pages-list", OptionList).focus()
            except Exception:
                pass
        else:
            self.query_one("#tab-pages", Button).variant = "default"
            self.query_one("#tab-inbox", Button).variant = "primary"
            self.query_one("#pages-container").display = False
            self.query_one("#inbox-container").display = True
            self.query_one("#ask-btn", Button).display = False
            self.query_one("#ingest-btn", Button).display = True
            try:
                self.query_one("#wiki-inbox-list", OptionList).focus()
            except Exception:
                pass

        self._update_preview()

    def _update_preview(self) -> None:
        preview = self.query_one("#wiki-detail-preview", Static)
        hint = self.query_one("#wiki-hint", Static)

        if self._active_tab == "pages":
            ol = self.query_one("#wiki-pages-list", OptionList)
            idx = ol.highlighted
            if idx is None and self._pages:
                idx = 0
            if idx is not None and 0 <= idx < len(self._pages):
                topic, path, summary = self._pages[idx]
                from novacode_cli.wiki.manager import WikiManager
                try:
                    mgr = WikiManager()
                    content = mgr.read_page(path)
                    if content:
                        preview.update(Text(content))
                    else:
                        preview.update(Text("Could not load page content.", style="red"))
                except Exception as ex:
                    preview.update(Text(f"Error loading page: {ex}", style="red"))
                hint.update(Text("Press Ask About Page to query this page.", style="dim"))
            else:
                preview.update(Text("Select a page from the list to preview.", style="dim"))
                hint.update(Text(""))
        else:
            ol = self.query_one("#wiki-inbox-list", OptionList)
            idx = ol.highlighted
            if idx is None and self._sources:
                idx = 0
            if idx is not None and 0 <= idx < len(self._sources):
                source_path = self._sources[idx]
                from novacode_cli.wiki.ingest import IngestEngine
                try:
                    engine = IngestEngine()
                    source_full = engine.resolve_source(source_path)
                    content = source_full.read_text(encoding="utf-8")
                    preview.update(Text(content))
                except Exception as ex:
                    preview.update(Text(f"Error loading source: {ex}", style="red"))
                hint.update(Text("Press Ingest Selected to parse this source.", style="dim"))
            else:
                preview.update(Text("Select a source file to preview.", style="dim"))
                hint.update(Text(""))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self._active_tab == "pages":
            self._ask_about_selected()
        else:
            self._ingest_selected()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "tab-pages":
            self._switch_tab("pages")
        elif event.button.id == "tab-inbox":
            self._switch_tab("inbox")
        elif event.button.id == "refresh-btn":
            self._reload()
        elif event.button.id == "ingest-btn":
            self._ingest_selected()
        elif event.button.id == "ask-btn":
            self._ask_about_selected()

    def _ingest_selected(self) -> None:
        ol = self.query_one("#wiki-inbox-list", OptionList)
        if ol.highlighted is not None and 0 <= ol.highlighted < len(self._sources):
            source_path = self._sources[ol.highlighted]
            self.dismiss(None)
            self.app._dispatch(f"/ingest {source_path}")

    def _ask_about_selected(self) -> None:
        ol = self.query_one("#wiki-pages-list", OptionList)
        if ol.highlighted is not None and 0 <= ol.highlighted < len(self._pages):
            topic, path, summary = self._pages[ol.highlighted]
            self.dismiss(None)
            inp = self.app.query_one("#prompt", Input)
            inp.value = f"/ask regarding [[{topic}]]: "
            inp.cursor_position = len(inp.value)
            inp.focus()

    def action_close(self) -> None:
        self.dismiss(None)


class HookCreateModal(ModalScreen[dict | None]):
    """Modal dialog to collect inputs for creating a new hook."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Add New Hook", style="bold"), id="modal-title")
            yield Static(Text("Command to execute (e.g. python script.py):", style="bold"), id="hook-command-label")
            yield Input(placeholder="e.g. python /path/to/script.py", id="hook-command")

            yield Static(Text("Events to subscribe to (comma-separated, blank for all):", style="bold"), id="hook-events-label")
            yield Input(placeholder="e.g. session.start, tool.call", id="hook-events")
            yield Static(
                "Valid events: session.start, session.end, session.save, session.continue, "
                "model.switch, tool.call, tool.result, agent.message, user.message, error, "
                "remote.message, context.warning, compact, init.complete, notification",
                classes="modal-hint",
                id="events-help-text"
            )
            yield Static("", id="hook-create-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Save", id="do-save", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self.query_one("#hook-command", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "do-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "hook-command":
            self.query_one("#hook-events", Input).focus()
        elif event.input.id == "hook-events":
            self._submit()

    def _submit(self) -> None:
        hint = self.query_one("#hook-create-hint", Static)
        try:
            cmd_str = self.query_one("#hook-command", Input).value.strip()
        except Exception:
            cmd_str = ""
        if not cmd_str:
            hint.update(Text("Command is required", style="red"))
            return

        # Check shell metacharacters
        _SHELL_METACHARACTERS = set("`$|;&")
        for c in _SHELL_METACHARACTERS:
            if c in cmd_str:
                hint.update(Text(f"Shell metacharacter '{c}' not allowed in command", style="red"))
                return

        try:
            events_str = self.query_one("#hook-events", Input).value.strip()
        except Exception:
            events_str = ""
        events = []
        if events_str:
            events = [e.strip() for e in events_str.split(",") if e.strip()]
            # Validate events
            from novacode_cli.hooks import HookEvent
            valid_events = {getattr(HookEvent, attr) for attr in dir(HookEvent) if not attr.startswith("_") and isinstance(getattr(HookEvent, attr), str)}
            valid_events.add("notification")
            invalid_events = [e for e in events if e not in valid_events]
            if invalid_events:
                hint.update(Text(f"Invalid events: {', '.join(invalid_events)}", style="red"))
                return

        self.dismiss({
            "command": cmd_str.split(),
            "events": events,
            "enabled": True
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class HooksScreen(ModalScreen[None]):
    """Native hooks manager: list, toggle, remove, test, add and reload hooks."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._hooks: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Hook Management", style="bold"), id="modal-title")
            yield Static(Text("Configured Hooks:", style="bold cyan"), id="hooks-section")
            yield OptionList(id="hooks-list")
            yield Static(Text("Hook Details:", style="bold yellow"), id="hook-detail-header")
            yield Static("", id="hook-detail-preview", classes="preview-box")
            yield Static("", id="hooks-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Add Hook", id="add", variant="primary")
                yield Button("Toggle Enable", id="toggle", variant="default")
                yield Button("Test Hook", id="test", variant="default")
                yield Button("Remove", id="remove", variant="error")
                yield Button("Reload", id="reload", variant="default")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._reload()

    def _reload(self) -> None:
        from novacode_cli.hooks import _load_hooks
        try:
            self._hooks = _load_hooks()
        except Exception:
            self._hooks = []

        ol = self.query_one("#hooks-list", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        hint = self.query_one("#hooks-hint", Static)

        if not self._hooks:
            ol.add_option(Option("(no hooks configured)"))
            self.query_one("#hook-detail-preview", Static).update(Text("No hooks are currently configured.", style="dim"))
            self.query_one("#toggle", Button).disabled = True
            self.query_one("#test", Button).disabled = True
            self.query_one("#remove", Button).disabled = True
            hint.update(Text("Create a hook with the Add Hook button", style="dim"))
            return

        self.query_one("#toggle", Button).disabled = False
        self.query_one("#test", Button).disabled = False
        self.query_one("#remove", Button).disabled = False

        for h in self._hooks:
            command = " ".join(h.get("command", []))
            events = ", ".join(h.get("events", ["<all>"]))
            enabled = h.get("enabled", True)
            status = "✓" if enabled else "✗"
            status_style = "bold green" if enabled else "bold red"
            label = Text.assemble(
                (f"{status} ", status_style),
                (f"{command} ", "bold #73daca"),
                (f"· {events}", "dim"),
            )
            ol.add_option(Option(label))

        if keep is not None and 0 <= keep < len(self._hooks):
            ol.highlighted = keep
        else:
            ol.highlighted = 0
        ol.focus()

        self._update_preview(ol.highlighted)
        hint.update(Text("Select a hook to see details · Add/Toggle/Test/Remove hooks", style="dim"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "hooks-list":
            self._update_preview(event.option_index)

    def _update_preview(self, idx: int | None) -> None:
        preview = self.query_one("#hook-detail-preview", Static)
        if idx is None or not self._hooks or not (0 <= idx < len(self._hooks)):
            preview.update("")
            return

        h = self._hooks[idx]
        command = " ".join(h.get("command", []))
        events = ", ".join(h.get("events", ["<all>"]))
        enabled = h.get("enabled", True)

        preview_text = Text()
        preview_text.append("Command: ", style="bold")
        preview_text.append(f"{command}\n", style="bold #73daca")
        preview_text.append("Events: ", style="bold")
        preview_text.append(f"{events}\n", style="cyan")
        preview_text.append("Status: ", style="bold")
        preview_text.append("Enabled\n" if enabled else "Disabled\n", style="bold green" if enabled else "bold red")

        preview.update(preview_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "add":
            self._add_hook()
        elif event.button.id == "toggle":
            self._toggle_hook()
        elif event.button.id == "test":
            self._test_hook()
        elif event.button.id == "remove":
            self._remove_hook()
        elif event.button.id == "reload":
            self._reload_hooks()

    @work
    async def _add_hook(self) -> None:
        result = await self.app.push_screen_wait(HookCreateModal())
        if result is not None:
            from novacode_cli.commands.hooks_handler import _save_hooks
            self._hooks.append(result)
            ok = _save_hooks(self._hooks)
            self.app._log(Text(f"✓ Hook added: {' '.join(result['command'])}" if ok else "Failed to save hook configuration", style="green" if ok else "red"))
            self._reload()

    @work
    async def _toggle_hook(self) -> None:
        ol = self.query_one("#hooks-list", OptionList)
        idx = ol.highlighted
        if idx is not None and 0 <= idx < len(self._hooks):
            h = self._hooks[idx]
            from novacode_cli.commands.hooks_handler import _save_hooks
            h["enabled"] = not h.get("enabled", True)
            ok = _save_hooks(self._hooks)
            action = "enabled" if h["enabled"] else "disabled"
            self.app._log(Text(f"✓ Hook {action}: {' '.join(h['command'])}" if ok else "Failed to save hook configuration", style="green" if ok else "red"))
            self._reload()

    @work
    async def _test_hook(self) -> None:
        ol = self.query_one("#hooks-list", OptionList)
        idx = ol.highlighted
        if idx is not None and 0 <= idx < len(self._hooks):
            h = self._hooks[idx]
            command = h.get("command", [])
            self.app._log(Text(f"Testing hook: {' '.join(command)}...", style="cyan"))
            import time
            from novacode_cli.hooks import dispatch_hook
            test_payload = {
                "test": True,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "message": "This is a test event"
            }
            try:
                await dispatch_hook("test", test_payload)
                self.app._log(Text("✓ Test event fired successfully! Check hook logs.", style="green"))
            except Exception as e:
                self.app._log(Text(f"✗ Test failed: {e}", style="red"))

    @work
    async def _remove_hook(self) -> None:
        ol = self.query_one("#hooks-list", OptionList)
        idx = ol.highlighted
        if idx is not None and 0 <= idx < len(self._hooks):
            h = self._hooks[idx]
            ok = await self.app.push_screen_wait(
                ConfirmModal(
                    f"Remove hook: {' '.join(h.get('command', []))}?",
                    Text("This will remove the hook from configuration. This cannot be undone."),
                )
            )
            if ok:
                from novacode_cli.commands.hooks_handler import _save_hooks
                removed = self._hooks.pop(idx)
                saved = _save_hooks(self._hooks)
                self.app._log(Text(f"✓ Removed hook: {' '.join(removed.get('command', []))}" if saved else "Failed to save hook configuration", style="green" if saved else "red"))
                self._reload()

    def _reload_hooks(self) -> None:
        from novacode_cli.hooks import reload_hooks
        reload_hooks()
        self.app._log(Text("✓ Hooks configuration reloaded from disk", style="green"))
        self._reload()

    def action_close(self) -> None:
        self.dismiss(None)


class ServersScreen(ModalScreen[None]):
    """Native dev servers manager: list servers, open in browser, stop them."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._servers: list[Any] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text("Dev Server Management", style="bold"), id="modal-title")
            yield Static(Text("Running Dev Servers:", style="bold cyan"), id="servers-section")
            yield OptionList(id="servers-list")
            yield Static(Text("Server Details:", style="bold yellow"), id="server-detail-header")
            yield Static("", id="server-detail-preview", classes="preview-box")
            yield Static("", id="servers-hint")
            with Horizontal(id="modal-buttons"):
                yield Button("Open in Browser", id="open-browser", variant="primary")
                yield Button("Stop Server", id="stop-server", variant="error")
                yield Button("Stop All Managed", id="stop-all", variant="error")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._reload()

    def _reload(self) -> None:
        from novacode_cli.server_runner.dev_server import list_servers
        try:
            self._servers = list_servers(include_external=True)
        except Exception:
            self._servers = []

        ol = self.query_one("#servers-list", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        hint = self.query_one("#servers-hint", Static)

        if not self._servers:
            ol.add_option(Option("(no dev servers running)"))
            self.query_one("#server-detail-preview", Static).update(Text("No dev servers are currently running.", style="dim"))
            self.query_one("#open-browser", Button).disabled = True
            self.query_one("#stop-server", Button).disabled = True
            self.query_one("#stop-all", Button).disabled = True
            hint.update(Text("Start a dev server via start_dev_server tool", style="dim"))
            return

        self.query_one("#open-browser", Button).disabled = False
        self.query_one("#stop-all", Button).disabled = False
        self.query_one("#stop-server", Button).disabled = False

        for s in self._servers:
            ext = s.pid == 0 and "external" in s.name
            status_style = "bold green" if s.status.value == "healthy" else "bold yellow"
            pid_label = f"external" if ext else f"PID {s.pid}"
            label = Text.assemble(
                (f"{s.name} ", "bold #73daca"),
                (f" · {pid_label} · ", "dim"),
                (s.url, "cyan"),
                (f" · {s.status.value}", status_style),
            )
            ol.add_option(Option(label))

        if keep is not None and 0 <= keep < len(self._servers):
            ol.highlighted = keep
        else:
            ol.highlighted = 0
        ol.focus()

        self._update_preview(ol.highlighted)
        hint.update(Text("Select a server to view details or perform actions", style="dim"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "servers-list":
            self._update_preview(event.option_index)

    def _update_preview(self, idx: int | None) -> None:
        preview = self.query_one("#server-detail-preview", Static)
        if idx is None or not self._servers or not (0 <= idx < len(self._servers)):
            preview.update("")
            return

        s = self._servers[idx]
        ext = s.pid == 0 and "external" in s.name

        preview_text = Text()
        preview_text.append("Name: ", style="bold")
        preview_text.append(f"{s.name}\n", style="bold #73daca")
        preview_text.append("URL: ", style="bold")
        preview_text.append(f"{s.url}\n", style="cyan")
        preview_text.append("Status: ", style="bold")
        status_style = "bold green" if s.status.value == "healthy" else "bold yellow"
        preview_text.append(f"{s.status.value}\n", style=status_style)
        preview_text.append("PID: ", style="bold")
        preview_text.append(f"{'external' if ext else s.pid}\n", style="dim")
        preview_text.append("Command:\n", style="bold")
        preview_text.append(s.command if s.command else "(external server, command unknown)", style="italic dim")

        preview.update(preview_text)
        # Disable stop server button for external servers
        self.query_one("#stop-server", Button).disabled = ext

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "open-browser":
            self._open_in_browser()
        elif event.button.id == "stop-server":
            self._stop_server()
        elif event.button.id == "stop-all":
            self._stop_all()

    def _open_in_browser(self) -> None:
        ol = self.query_one("#servers-list", OptionList)
        idx = ol.highlighted
        if idx is not None and 0 <= idx < len(self._servers):
            import webbrowser
            webbrowser.open(self._servers[idx].url)
            self.app._log(Text(f"✓ Opened {self._servers[idx].url}", style="green"))

    @work
    async def _stop_server(self) -> None:
        ol = self.query_one("#servers-list", OptionList)
        idx = ol.highlighted
        if idx is not None and 0 <= idx < len(self._servers):
            s = self._servers[idx]
            if s.pid == 0 and "external" in s.name:
                return
            from novacode_cli.server_runner.dev_server import stop_server
            ok = await stop_server(pid=s.pid)
            self.app._log(Text(f"✓ Stopped '{s.name}' (PID {s.pid})" if ok else f"Failed to stop server '{s.name}'", style="green" if ok else "red"))
            self._reload()

    @work
    async def _stop_all(self) -> None:
        from novacode_cli.process_manager import ProcessManager
        count = await ProcessManager.get_instance().stop_all()
        self.app._log(Text(f"✓ Stopped {count} managed server(s)" if count else "No managed servers to stop", style="green" if count else "yellow"))
        self._reload()

    def action_close(self) -> None:
        self.dismiss(None)


class RemoteScreen(ModalScreen[None]):
    """Native /remote screen: bridge status + start/stop/test, rendered as TUI
    components (the underlying logic is reused, but its output stays in-modal)."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(
        self,
        session_state,
        sandbox_id: str | None = None,
        sandbox_type: str | None = None,
    ) -> None:
        super().__init__()
        self._ss = session_state
        self._sandbox_id = sandbox_id
        self._sandbox_type = sandbox_type

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(
                Text("🔗 Remote Bridges Status & Config", style="bold cyan"), id="modal-title"
            )
            with VerticalScroll(id="remote-status-container"):
                yield Static("", id="remote-status")
            yield Static(Text("Start / Connect Bridge", style="bold"), id="remote-section-title")
            yield Input(
                placeholder="Bot token (blank = use saved config)",
                password=True,
                id="remote-token",
            )
            yield Input(placeholder="Channel/Chat ID (blank = saved/auto)", id="remote-chat")
            with Horizontal(id="modal-buttons"):
                yield Button("Start Discord", id="start-discord", variant="success")
                yield Button("Start Telegram", id="start-telegram", variant="success")
                yield Button("Test", id="test")
                yield Button("Stop All", id="stop", variant="error")
                yield Button("Close", id="close")
            yield Static("", id="remote-result")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self._refresh()

    def _refresh(self) -> None:
        from novacode_cli.remote.config import load_remote_config

        mgr = getattr(self._ss, "_remote_bridge_manager", None)
        bridges = mgr.active_bridges if mgr is not None else []
        t = Text()
        if bridges:
            t.append("⚡ Active Bridges:\n", style="bold cyan")
            for b in bridges:
                status = b.get("status", "")
                icon = (
                    "🟢" if status == "running" else ("🔴" if "error" in status.lower() else "🟡")
                )
                bot = f" (@{b['bot_user']})" if b.get("bot_user") else ""
                platform = str(b["platform"]).capitalize()

                t.append("  ")
                t.append(icon)
                t.append(f" {platform}{bot}", style="bold white")
                t.append(" — Chat: ")
                t.append(str(b["chat_id"]), style="yellow")
                t.append(" — Status: ")
                status_style = (
                    "bold green"
                    if status == "running"
                    else ("bold red" if "error" in status.lower() else "bold yellow")
                )
                t.append(status, style=status_style)
                t.append("\n")
        else:
            t.append("📭 No bridges active.\n", style="dim italic")
        try:
            saved = load_remote_config()
        except Exception:  # noqa: BLE001
            saved = {}
        if saved:
            t.append("\n💾 Saved Configurations:\n", style="bold magenta")
            if "discord" in saved:
                d = saved["discord"]
                tok = "✓ Configured" if d.get("token") else "✗ Missing Token"
                tok_style = "green" if d.get("token") else "red"
                t.append("  Discord", style="bold #5865F2")  # Discord brand color
                t.append(" · Token: ")
                t.append(tok, style=tok_style)
                t.append(" · Channel: ")
                t.append(str(d.get("channel_id", "—")), style="yellow")
                t.append("\n")
            if "telegram" in saved:
                tg = saved["telegram"]
                tok = "✓ Configured" if tg.get("token") else "✗ Missing Token"
                tok_style = "green" if tg.get("token") else "red"
                t.append("  Telegram", style="bold #24A1DE")  # Telegram brand color
                t.append(" · Token: ")
                t.append(tok, style=tok_style)
                t.append(" · Chat: ")
                t.append(str(tg.get("chat_id", "—")), style="yellow")
                t.append("\n")
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
                    app.agent,  # type: ignore
                    app.token_tracker,  # type: ignore
                    self._ss,
                    app.assistant_id,  # type: ignore
                    model_name=app.model_name,  # type: ignore
                    image_tracker=app.image_tracker,  # type: ignore
                    sandbox_id=self._sandbox_id,
                    sandbox_type=self._sandbox_type,
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


class RalphScreen(ModalScreen[None]):
    """Native /ralph modal: a live dashboard for Ralph autonomous runs.

    Shows a header with task info, a scrollable list of iteration cards
    that update in real time, action buttons (Stop / Checkpoint / Close),
    and a summary when the run finishes.  Background ``--status`` is also
    rendered inside this modal instead of inline in the transcript.
    """

    BINDINGS = [("escape", "close", "Close")]

    _ITER_GLYPH = {
        "running": ("▶", "yellow"),
        "done": ("✓", "green"),
        "failed": ("✗", "red"),
    }

    DEFAULT_CSS = """
    RalphScreen {
        align: center middle;
    }
    RalphScreen #modal-box {
        width: 80%; max-width: 110; height: auto; max-height: 90%;
        border: thick $accent; background: $surface;
        padding: 1 4; layer: overlay;
    }
    RalphScreen #ralph-header {
        margin-bottom: 1; padding: 0 0;
    }
    RalphScreen #ralph-iters {
        height: auto; max-height: 60%;
        padding: 0 1;
    }
    RalphScreen .ralph-iter-card {
        height: auto; padding: 0 1; margin: 0 0;
        border-left: thick $accent;
    }
    RalphScreen .ralph-iter-card.done {
        border-left: thick $success;
    }
    RalphScreen .ralph-iter-card.failed {
        border-left: thick $error;
    }
    RalphScreen .ralph-iter-card.running {
        border-left: thick $warning;
    }
    RalphScreen #ralph-summary {
        margin-top: 1; padding: 0 0;
    }
    RalphScreen #ralph-status-table {
        margin-top: 1; padding: 0 0;
    }
    RalphScreen #modal-buttons {
        height: auto; align: center middle;
        margin-top: 1; padding: 0 0;
    }
    RalphScreen #modal-buttons Button { margin: 0 1; }
    """

    def __init__(
        self,
        session_state: Any,
        agent: Any,
        assistant_id: str,
        token_tracker: Any,
        args: str,
        execute_fn: Any,
    ) -> None:
        super().__init__()
        self._ss = session_state
        self._agent = agent
        self._assistant_id = assistant_id
        self._token_tracker = token_tracker
        self._args = args
        self._execute_fn = execute_fn
        self._iter_cards: dict[int, Static] = {}
        self._finished = False
        self._stop_requested = False

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(
                Text("🔁 Ralph — Autonomous Mode", style="bold cyan"),
                id="modal-title",
            )
            yield Static("", id="ralph-header")
            with VerticalScroll(id="ralph-iters"):
                pass  # iteration cards mounted dynamically
            yield Static("", id="ralph-summary")
            yield Static("", id="ralph-status-table")
            with Horizontal(id="modal-buttons"):
                yield Button("⏹ Stop", id="ralph-stop", variant="error")
                yield Button("💾 Checkpoint", id="ralph-checkpoint", variant="warning")
                yield Button("Close", id="ralph-close")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self.query_one("#ralph-header", Static).update(
            Text("Starting Ralph run…", style="dim italic")
        )
        self.app.run_worker(self._run_ralph(), group="ralph", exclusive=True)

    # ── Event handlers ─────────────────────────────────────────────

    def _on_ralph_event(self, event: Any) -> None:
        """Drive modal widgets from structured Ralph events."""
        if not self.is_mounted:
            return
        from novacode_cli.commands import ralph_events as rev

        if isinstance(event, rev.RalphStarted):
            self._iter_cards.clear()
            iters = (
                "unlimited"
                if event.max_iterations == 0
                else str(event.max_iterations)
            )
            title = (
                "🔁 Ralph Mode (Resumed)"
                if event.resumed_from
                else "🔁 Ralph Mode"
            )
            t = Text()
            t.append(f"{title}\n", style="bold")
            t.append("Task: ", style="bold")
            t.append(f"{event.task}\n")
            t.append("Max iterations: ", style="bold")
            t.append(f"{iters}\n")
            if event.resumed_from:
                t.append("Resuming from: ", style="bold")
                t.append(f"iteration {event.resumed_from}\n")
            t.append("Mode: ", style="bold")
            t.append(
                "background (non-blocking)"
                if event.background
                else "foreground"
            )
            self.query_one("#ralph-header", Static).update(t)

        elif isinstance(event, rev.IterationStarted):
            text = self._iter_text(
                event.iteration, event.max_iterations, "running"
            )
            card = Static(text, classes="ralph-iter-card running")
            self._iter_cards[event.iteration] = card
            self.query_one("#ralph-iters", VerticalScroll).mount(card)
            card.scroll_visible()

        elif isinstance(event, rev.IterationFinished):
            status = "done" if event.ok else "failed"
            text = self._iter_text(
                event.iteration,
                event.max_iterations,
                status,
                event.elapsed,
                event.error,
            )
            card = self._iter_cards.get(event.iteration)
            if card is not None:
                try:
                    card.set_classes(f"ralph-iter-card {status}")
                    card.update(text)
                except Exception:  # noqa: BLE001
                    pass

        elif isinstance(event, rev.RalphFinished):
            self._finished = True
            t = Text()
            t.append("📊 Ralph finished", style="bold")
            t.append(f" — {event.completed} completed", style="green")
            if event.failed:
                t.append(f", {event.failed} failed", style="red")
            t.append(f" of {event.total} iteration(s)", style="dim")
            t.append(f"\nReason: {event.reason}", style="dim italic")
            self.query_one("#ralph-summary", Static).update(t)
            try:
                self.query_one("#ralph-stop", Button).disabled = True
                self.query_one("#ralph-checkpoint", Button).disabled = True
                self.query_one("#ralph-close", Button).disabled = False
            except Exception:  # noqa: BLE001
                pass

        elif isinstance(event, rev.StatusSnapshot):
            self._render_status(event)

    def _render_status(self, snap: Any) -> None:
        """Render ``--status`` snapshot as a native table inside the modal."""
        from rich.console import Group
        from rich.table import Table

        header = Text("Ralph Background Tasks\n", style="bold")
        if not snap.rows:
            header.append("No background Ralph tasks running.", style="dim")
            self.query_one("#ralph-status-table", Static).update(header)
            return

        table = Table(show_edge=False, pad_edge=False, expand=False)
        table.add_column("", width=2)
        table.add_column("Iter")
        table.add_column("Status")
        table.add_column("Elapsed", justify="right")
        table.add_column("Task")
        glyphs = {
            "running": ("⏳", "yellow"),
            "completed": ("✓", "green"),
            "failed": ("✗", "red"),
        }
        for row in snap.rows:
            g, color = glyphs.get(row.status, ("•", "dim"))
            disp = (
                f"{row.iteration}/{row.max_iterations}"
                if row.max_iterations > 0
                else str(row.iteration)
            )
            desc = row.task if len(row.task) <= 50 else row.task[:50] + "…"  # noqa: PLR2004
            table.add_row(
                Text(g, style=color),
                disp,
                Text(row.status, style=color),
                f"{row.elapsed:.0f}s",
                desc,
            )
        summary = Text()
        summary.append(f"\nTotal {snap.total}", style="dim")
        summary.append(f"  ·  running {snap.running}", style="yellow")
        summary.append(f"  ·  completed {snap.completed}", style="green")
        summary.append(f"  ·  failed {snap.failed}", style="red")
        self.query_one("#ralph-status-table", Static).update(
            Group(header, table, summary)
        )

    def _iter_text(
        self,
        iteration: int,
        max_iterations: int,
        status: str,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> Text:
        """One iteration card, styled by status."""
        glyph, color = self._ITER_GLYPH.get(status, ("•", "dim"))
        disp = (
            f"{iteration}/{max_iterations}"
            if max_iterations > 0
            else str(iteration)
        )
        t = Text()
        t.append(f"{glyph} Iteration {disp}", style=f"bold {color}")
        if status == "running":
            t.append("  — running…", style="dim")
        else:
            t.append(
                f"  — {'done' if status == 'done' else 'failed'}",
                style=color,
            )
            if elapsed is not None:
                t.append(f" ({elapsed:.1f}s)", style="dim")
            if error:
                t.append(f"\n    {error}", style="red")
        return t

    async def _run_ralph(self) -> None:
        """Kick off the Ralph handler with events routed to this modal."""
        import threading

        from novacode_cli.commands.ralph_handler import handle_ralph_command

        loop_tid = threading.get_ident()

        def _emit(message: str = "") -> None:
            """Thread-safe Rich-markup emitter — logs to main transcript."""
            try:
                renderable = (
                    Text.from_markup(message) if message else Text("")
                )
            except Exception:  # noqa: BLE001
                renderable = Text(message)
            app = self.app
            if threading.get_ident() == loop_tid:
                app._log(renderable)  # noqa: SLF001
            else:
                try:
                    app.call_from_thread(app._log, renderable)  # noqa: SLF001
                except Exception:  # noqa: BLE001
                    pass

        def _on_event(event: Any) -> None:
            if threading.get_ident() == loop_tid:
                self._on_ralph_event(event)
            else:
                try:
                    self.app.call_from_thread(self._on_ralph_event, event)
                except Exception:  # noqa: BLE001
                    pass

        try:
            await handle_ralph_command(
                self._agent,
                self._ss,
                self._assistant_id,
                self._token_tracker,
                self._args or None,
                execute_fn=self._execute_fn,
                emit=_emit,
                on_event=_on_event,
            )
        except asyncio.CancelledError:
            self._finished = True
            if self.is_mounted:
                try:
                    self.query_one("#ralph-summary", Static).update(
                        Text("⏹ Ralph run stopped / cancelled by user.", style="yellow bold")
                    )
                    self.query_one("#ralph-stop", Button).disabled = True
                    self.query_one("#ralph-checkpoint", Button).disabled = True
                    self.query_one("#ralph-close", Button).disabled = False
                except Exception:  # noqa: BLE001
                    pass
        except Exception as ex:  # noqa: BLE001
            self._finished = True
            if self.is_mounted:
                try:
                    self.query_one("#ralph-summary", Static).update(
                        Text(f"Error: {ex}", style="red bold")
                    )
                    self.query_one("#ralph-stop", Button).disabled = True
                    self.query_one("#ralph-checkpoint", Button).disabled = True
                    self.query_one("#ralph-close", Button).disabled = False
                except Exception:  # noqa: BLE001
                    pass

    # ── Button handling ────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "ralph-close":
            self.dismiss(None)
        elif bid == "ralph-stop":
            self._ss._ralph_stop_requested = True  # noqa: SLF001
            self._stop_requested = True
            self.app.workers.cancel_group(self.app, "ralph")
            if self.is_mounted:
                try:
                    self.query_one("#ralph-summary", Static).update(
                        Text("⏹ Stop requested…", style="yellow bold")
                    )
                    self.query_one("#ralph-stop", Button).disabled = True
                    self.query_one("#ralph-checkpoint", Button).disabled = True
                except Exception:  # noqa: BLE001
                    pass
        elif bid == "ralph-checkpoint":
            self._ss._ralph_checkpoint_requested = True  # noqa: SLF001
            if self.is_mounted:
                try:
                    self.query_one("#ralph-summary", Static).update(
                        Text("💾 Checkpoint requested…", style="yellow")
                    )
                    self.query_one("#ralph-stop", Button).disabled = True
                    self.query_one("#ralph-checkpoint", Button).disabled = True
                except Exception:  # noqa: BLE001
                    pass

    def action_close(self) -> None:
        self.dismiss(None)


class PromptInput(Input):
    """Main prompt input that collapses large pastes into a compact placeholder.

    Textual's single-line ``Input`` keeps only the *first line* of a paste, so a
    multi-line paste would silently lose everything after the first newline.
    Instead, a large paste (>= ``PASTE_MIN_CHARS`` chars or ``PASTE_MIN_NEWLINES``
    newlines) is stored in the app's :class:`PasteTracker` and shown inline as
    ``[paste #N +M lines]``; the placeholder is resolved back to the full text on
    submit (see :meth:`NovaApp.on_input_submitted`). Small pastes fall through to
    Textual's default behaviour.

    Reuses the same tracker/threshold/format helpers as the legacy prompt_toolkit
    input (:mod:`novacode_cli.input`) so both UIs behave identically.
    """

    # After the last Paste fragment, how long an in-progress paste stays "open"
    # for more fragments to merge into it. A single large paste is often split
    # by the terminal into several Paste events that can arrive hundreds of ms
    # apart, so this is generous — it does NOT block typing (that's the separate
    # key-drop window below) and is also ended early by any real keystroke.
    PASTE_MERGE_WINDOW = 1.5
    # How long stray per-character key events are dropped after a Paste fragment
    # (Windows terminals echo a paste as queued keystrokes). Short, so real
    # typing right after a paste is never swallowed.
    PASTE_KEYDROP_WINDOW = 0.05

    def __init__(self, *args, **kwargs) -> None:
        self._paste_tracker: PasteTracker | None = kwargs.pop("paste_tracker", None)
        self._on_large_paste = kwargs.pop("on_large_paste", None)
        super().__init__(*args, **kwargs)
        # On Windows terminals, pasting fires BOTH a Paste event AND individual
        # key events for each character.  We stop the Paste event, but the
        # keystrokes are already queued.  This flag drops them until the key-drop
        # window expires.
        self._paste_active = False
        self._keydrop_timer: Any = None
        # Identity-merge state for coalescing a fragmented paste: while a paste
        # is "open", later fragments are appended to this SAME paste id (one
        # block, one placeholder) instead of each becoming its own [paste #N].
        self._active_paste_id: str | None = None
        self._active_paste_ph: str = ""
        self._merge_timer: Any = None

    async def _on_key(self, event: events.Key) -> None:
        # Drop ALL key events during the key-drop window. On Windows terminals,
        # pasting fires per-character keystrokes after the Paste event — the old
        # `len(event.key) == 1` filter was too narrow because some terminals send
        # the *entire pasted text* as a single key event (e.g. event.key == "use"),
        # which has len > 1 and was let through, duplicating the paste.
        if self._paste_active:
            return
        # A real keystroke means the paste burst is over — stop merging further
        # fragments into it so the next paste starts fresh.
        self._end_paste_merge()
        await super()._on_key(event)

    def _on_paste(self, event: events.Paste) -> None:
        text = event.text
        # Blank this out before Input._on_paste runs (Textual calls _on_* handlers
        # for every class in the MRO). Without this, the parent inserts the text a
        # second time, producing duplicates like "useuse".
        event.text = ""
        event.stop()

        if not text:
            return
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        tracker = self._paste_tracker

        if self._active_paste_id is not None and tracker is not None:
            # Continuation of a fragmented paste: append to the SAME paste so the
            # whole thing stays one block for the agent, and refresh the inline
            # placeholder's line count in place (same id, updated count).
            old_ph = self._active_paste_ph
            tracker.extend_paste(self._active_paste_id, normalized)
            full = tracker.get_paste(self._active_paste_id) or normalized
            new_ph = format_paste_placeholder(self._active_paste_id, full)
            if new_ph != old_ph and old_ph in self.value:
                self.value = self.value.replace(old_ph, new_ph, 1)
                self.cursor_position = len(self.value)
            self._active_paste_ph = new_ph
        elif tracker is not None and (
            len(normalized) >= PASTE_MIN_CHARS or normalized.count("\n") >= PASTE_MIN_NEWLINES
        ):
            # First fragment of a large paste: create the placeholder and open
            # the merge window so any trailing fragments fold into this one.
            paste_id = tracker.add_paste(normalized)
            placeholder = format_paste_placeholder(paste_id, normalized)
            self.insert_text_at_cursor(placeholder + " ")
            self._active_paste_id = paste_id
            self._active_paste_ph = placeholder
        else:
            # Small paste — won't fragment; insert literally, no merge needed.
            self.insert_text_at_cursor(normalized)

        # Drop the echo keystrokes for a short moment after each fragment.
        self._paste_active = True
        if self._keydrop_timer is not None:
            self._keydrop_timer.stop()
        self._keydrop_timer = self.set_timer(
            self.PASTE_KEYDROP_WINDOW, lambda: setattr(self, "_paste_active", False)
        )
        # Keep the paste "open" for more fragments; close it after a quiet gap.
        if self._merge_timer is not None:
            self._merge_timer.stop()
        self._merge_timer = self.set_timer(self.PASTE_MERGE_WINDOW, self._end_paste_merge)

    def _end_paste_merge(self) -> None:
        """Close the current paste so the next paste/fragment starts fresh.

        Logs the collapsed-paste note to the transcript once, with the FINAL
        merged size, so a fragmented paste shows a single accurate notice.
        """
        if self._merge_timer is not None:
            self._merge_timer.stop()
            self._merge_timer = None
        if self._active_paste_id is None:
            return
        if self._on_large_paste is not None and self._paste_tracker is not None:
            full = self._paste_tracker.get_paste(self._active_paste_id)
            if full is not None:
                self._on_large_paste(self._active_paste_ph, len(full))
        self._active_paste_id = None
        self._active_paste_ph = ""


class TuiInitRenderer:
    """Adapter implementing ``InitRenderer`` for the Textual TUI path.

    Wires the pipeline's emit events into ``NovaApp._init_on_event`` (the
    native step-tracker widget), renders the final result, and streams the
    fallback exploration prompt through the TUI.
    """

    def __init__(self, app: NovaApp) -> None:
        self._app = app

    def emit(self, event) -> None:
        """Forward a pipeline event to the TUI's step-tracker."""
        self._app._init_on_event(event)

    def result(self, result, flags) -> None:
        """Finalise the step tracker and log the outcome."""
        self._app._init_finish()
        if not result.ok and result.message:
            self._app._log(Text(result.message, style="yellow"))

    def graphify_unavailable(self) -> None:
        """Log a notice that graphify is not installed."""
        self._app._log(Text("graphify not installed — using fallback exploration", style="yellow"))

    async def run_fallback(
        self,
        project_root: Path,
        nova_md_path: Path,
        agent,
        session_state,
        assistant_id: str,
        token_tracker,  # noqa: ARG002
    ) -> None:
        """Stream the exploration prompt through the TUI."""
        from novacode_cli.prompts import render_template

        prompt = render_template(
            "init_exploration.jinja",
            project_root=str(project_root),
            Nova_md_path=str(nova_md_path),
        )
        prev = session_state.auto_approve
        session_state.auto_approve = True
        try:
            await self._app._stream_prompt(prompt)
        finally:
            session_state.auto_approve = prev


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
        border-left: thick $accent; padding: 0 2;
        margin: 1 0; background: $surface;
    }
    #transcript > .tool { color: $warning; padding: 0 2; margin: 1 0; background: $surface; }
    .toolbody { color: $text-muted; margin: 0; height: auto; }
    .terminal-log {
        height: 5;
        background: $boost;
        border: round $border;
        margin: 0 0;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    #tool-group-log, #subagent-log {
        display: none;
    }
    #tool-group-log.active, #subagent-log.active {
        display: block;
    }
    #transcript > .todos {
        border-left: thick $secondary; padding: 0 2;
        margin: 1 0; background: $surface;
    }
    #transcript > .initlog {
        height: auto; border-left: thick $accent;
        padding: 0 2; margin: 1 0; background: $surface;
    }
    #transcript > .logline {
        height: auto; padding: 0 2;
        background: $surface; margin: 1 0;
    }
    /* --- /ralph native cards (accent-bar style, like .initlog) --- */
    #transcript > .ralph-run {
        height: auto; border-left: thick $primary;
        padding: 0 2; margin: 1 0; background: $surface;
    }
    #transcript > .ralph-iter {
        height: auto; border-left: thick $accent;
        padding: 0 2; margin: 1 0; background: $surface;
    }
    #transcript > .ralph-iter.done { border-left: thick $success; }
    #transcript > .ralph-iter.failed { border-left: thick $error; }
    #transcript > .ralph-summary {
        height: auto; border-left: thick $success;
        padding: 0 2; margin: 1 0; background: $surface;
    }
    #transcript > .ralph-status {
        height: auto; border-left: thick $secondary;
        padding: 0 2; margin: 1 0; background: $surface;
    }
    #transcript > .nova-event {
        height: auto; padding: 0 2;
        background: $surface; margin: 1 0;
        border-left: thick $accent;
    }
    #transcript > .nova-event.nova-review-start {
        border-left: thick #00d4ff;
    }
    #transcript > .nova-event.nova-review-complete {
        border-left: thick #00ff88;
    }
    #transcript > .nova-event.nova-skill-refinement {
        border-left: thick #ffcc00;
    }
    #cmdpalette {
        width: 100%;
        height: auto; max-height: 10;
        border: thick $accent; background: $panel;
        padding: 0 1;
        display: none; layer: overlay; dock: bottom;
        margin-bottom: 8;
    }
    /* --- Prompt dock: 3-row bottom section --- */
    #prompt-dock {
        dock: bottom;
        height: auto;
        background: $surface;
    }
    #prompt-hint-bar {
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $text-muted;
    }
    #prompt {
        width: 1fr;
        background: $panel; color: $text;
        padding: 0 2; min-height: 3;
        border: none;
        /* Smooth fade when switching into/out of a mode. */
        transition: background 300ms in_out_cubic;
    }
    #prompt:focus {
        background: $boost;
    }
    /* The > chevron prefix for the input. */
    #prompt-prefix {
        width: 3;
        height: 3;
        padding: 0 0 0 1;
        background: $panel;
        color: $accent;
    }
    #prompt-row {
        height: auto;
        background: $panel;
        padding: 0;
        border-top: solid $border 30%;
        border-bottom: solid $border 30%;
    }
    /* BASH mode — magenta, urgent. */
    #prompt.bash-mode {
        background: #2a1a2e; color: #d7c4ff;
    }
    #prompt:focus.bash-mode {
        background: #2f1e35;
    }
    #prompt-row.bash-mode {
        border-top: solid #bb9af7 50%;
        border-bottom: solid #bb9af7 50%;
    }
    #prompt-prefix.bash-mode { color: #bb9af7; background: #2a1a2e; }
    /* PLAN mode — blue, calm. */
    #prompt.plan-mode {
        background: #161f33; color: #b4c6ef;
    }
    #prompt:focus.plan-mode {
        background: #1b2540;
    }
    #prompt-row.plan-mode {
        border-top: solid #7aa2f7 50%;
        border-bottom: solid #7aa2f7 50%;
    }
    #prompt-prefix.plan-mode { color: #7aa2f7; background: #161f33; }
    #mode-badge {
        height: 1;
        padding: 0 2;
        background: $panel;
        color: $text-muted;
    }
    /* --- Info bar: workspace / branch / sandbox / model / quota --- */
    #info-bar {
        height: 2;
        padding: 0 1;
        background: $background;
    }
    .info-col {
        height: 2;
        padding: 0 1;
        width: 1fr;
    }
    .info-label {
        height: 1;
        color: $text-muted;
    }
    .info-value {
        height: 1;
    }
    .session-header {
        height: auto;
        padding: 1 2;
        background: $surface;
        align: left middle;
    }
    .session-pill {
        background: $boost;
        border: round $border;
        padding: 0 2;
        margin: 0 1;
        height: auto;
    }
    .pill-model { color: $primary; }
    .pill-sandbox { color: $success; }
    .pill-memory { color: $accent; }
    .breadcrumb { color: $text-muted; }
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
        padding: 1 4; layer: overlay;
    }
    #modal-title { margin-bottom: 1; padding: 0 0; }
    #modal-body { padding: 0 0; }
    /* Long lists scroll inside the box instead of overflowing the screen. */
    #sessions, #pick-list, #infolist, #mcp-configured, #mcp-presets, #plugins, #agents-list, #skills-list, #servers-list, #hooks-list, #wiki-pages-list, #wiki-inbox-list {
        height: auto; max-height: 40%;
        padding: 0 2;
    }
    #wiki-tab-buttons {
        height: auto;
        margin-bottom: 1;
    }
    #wiki-tab-buttons Button {
        margin-right: 1;
    }
    #pages-container, #inbox-container {
        height: auto;
    }
    #pages-header, #inbox-header {
        margin-bottom: 0;
    }
    .preview-box {
        background: $boost;
        border: round $accent 50%;
        padding: 1 2;
        margin-top: 1;
        margin-bottom: 1;
        height: auto;
        max-height: 12;
        scrollbar-gutter: stable;
        overflow-y: scroll;
    }
    /* The Ollama model list sits ABOVE the inputs + Switch/Cancel buttons, so it
       gets a tighter cap and its own scroll — otherwise a long list pushes the
       buttons out of the modal and they can't be clicked. */
    #modellist {
        height: auto; max-height: 9;
        border: round $accent 50%; margin-bottom: 1;
    }
    #modal-buttons {
        height: auto; align: center middle;
        margin-top: 1; padding: 0 0;
    }
    #modal-buttons Button { margin: 0 1; }
    #modal-hint { padding: 0 1; color: $text-muted; }
    Collapsible { margin: 0; }
    Collapsible > .collapsible--title { padding: 0 1; background: $surface; }
    .btw-card { margin: 1 0; border-left: thick $accent-muted; }
    .btw-card > .collapsible--title { color: $accent-muted; background: $surface; }
    .btw-body { padding: 0 2; color: $text-muted; }
    .bgshell-card { margin: 1 0; border-left: thick $warning-muted; }
    .bgshell-card > .collapsible--title { color: $warning; background: $surface; }
    .bgshell-log { height: 10; max-height: 20; border: none; background: $surface; }
    .bgagent-card { margin: 1 0; border-left: thick $success-muted; }
    .bgagent-card > .collapsible--title { color: $success; background: $surface; }
    .bgagent-done > .collapsible--title { color: $success; }
    .bgagent-failed > .collapsible--title { color: $error; }
    VerticalScroll { scrollbar-gutter: stable; }
    #remote-status-container {
        height: auto; max-height: 12;
        background: $boost;
        border: round $accent;
        padding: 0 1;
        margin-bottom: 1;
    }
    #remote-section-title {
        margin-top: 1;
        margin-bottom: 0;
        color: $text;
        text-style: bold;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        # ctrl+c copies the current text selection if there is one, else quits.
        # Textual captures the mouse, so the terminal's native copy doesn't work
        # in the transcript — this restores select-then-copy while keeping the
        # familiar ctrl+c-to-quit when nothing is selected. ctrl+q always quits.
        ("ctrl+c", "copy_or_quit", "Copy / Quit"),
        ("ctrl+t", "toggle_terminal", "Terminal"),
        ("ctrl+b", "run_background", "Background"),
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
        sandbox_id: str | None = None,
        sandbox_type: str | None = None,
        sandbox_meta: dict | None = None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.assistant_id = assistant_id
        self.session_state = session_state
        self.backend = backend
        self.token_tracker = token_tracker
        self.image_tracker = image_tracker
        # Collapses large pastes into [paste #N +M lines] placeholders; resolved
        # back to full text on submit. Shared helpers with the legacy input.
        self.paste_tracker = PasteTracker()
        self.model_name = model_name or "unknown"
        self.session_manager = session_manager
        # Sandbox identity for session persistence (so --continue can reconnect).
        self._sandbox_id = sandbox_id
        self._sandbox_type = sandbox_type
        self._sandbox_meta = sandbox_meta
        # Prior conversation turns to replay into the transcript on resume.
        self._restored_messages = list(restored_messages or [])
        self._seen: set[str] = set()
        self._live_buf = ""  # accumulating streamed answer prose
        self._reasoning_buf = ""  # accumulating reasoning trace
        self._stream_msg: ChatMessage | None = None  # in-progress Nova answer widget
        self._reason_msg: ChatMessage | None = None  # in-progress reasoning widget
        self._current_assistant_id: str | None = None
        # Streaming coalescing: deltas append to the buffers above, but the widget
        # is only repainted on a ~50ms timer (see _flush_stream) so a fast token
        # stream doesn't trigger a full re-render + scroll per token.
        self._stream_flush_scheduled = False
        # Cached singleton widget refs (resolved once in on_mount) to avoid a
        # query_one DOM walk on every delta / keystroke / status tick.
        self._w_cache: dict[str, Any] = {}
        # call_id -> (collapsible, body Static, base title) for open tool calls
        self._tool_components: dict[str, tuple[Collapsible, Static, str]] = {}
        # fallback for tool calls that arrive without an id
        self._last_tool: tuple[Collapsible, Static, str] | None = None
        # Condensed tool view: a run of consecutive tool calls collapses into a
        # single "tool group" panel (one compact line per tool) instead of one
        # Collapsible per call, so a burst of tools doesn't flood the chat.
        self._tool_group: Collapsible | None = None
        self._tool_group_body: Vertical | None = None
        self._tool_group_entries: list[dict] = []  # per-tool {base, mark, detail, error}
        self._tool_group_lines: dict[str, int] = {}  # call_id -> entry index
        self._tool_group_last_idx: int | None = None  # fallback for id-less results
        # subagent tracking: call_id -> (collapsible, body Static, type, start_time)
        self._subagent_widgets: dict[str, tuple[Collapsible, Static, str, float]] = {}
        self._subagent_count: int = 0  # running total for display
        # Maps running subagent tool call_id -> subagent task call_id
        self._subagent_tool_to_task: dict[str, str] = {}
        self._remote_msg: Any = None  # current RemoteMessage during remote turn
        self._remote_question_future: asyncio.Future | None = None
        # Tool/subagent names used during the current remote turn — collapsed
        # into the compact live status line's condensed counts.
        self._remote_activity: list[str] = []
        # The per-turn live status line (edits one compact message in place).
        self._remote_status: Any = None
        # The MatrixRain animation widget, tracked so it can be removed on clear.
        self._home_banner: Static | None = None
        # name → async (args) -> str  for slash commands contributed by plugins.
        self._plugin_commands: dict[str, Any] = {}
        # Strong refs to fire-and-forget background sends so the event loop
        # doesn't garbage-collect them mid-flight (asyncio only holds weak refs).
        self._bg_tasks: set[Any] = set()
        # One-shot guard for the Ollama CPU-offload advisory (set once the model
        # is loaded and checked, so we don't spawn `ollama ps` every turn).
        self._ollama_offload_checked = False
        self._btw_agent: Any = None  # lazy-init btw side-channel agent (web-search only)
        self._bg_job_count: int = 0  # monotonic counter for background shell jobs
        self._todo_widget: Static | None = None  # updated in place per turn
        self._init_widget: Static | None = None  # live /init step tracker widget
        self._init_steps: list[dict] = []
        # Live per-iteration Ralph cards, keyed by iteration number, so an
        # IterationFinished event can update the card mounted at its start.
        self._ralph_iter_cards: dict[int, Static] = {}
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
        # Per-keystroke de-churn: last (plan, bash) mode state + last palette list.
        self._last_mode_state: tuple[bool, bool, bool] | None = None
        self._last_palette: list[str] | None = None
        # Notification badge: last seen unread count (drives status refresh).
        self._last_notif_count = 0
        # Context-window management: warn once per crossing; auto-compact at critical.
        self._ctx_warned = False
        self._auto_compact = True
        # Live steering: SteeringInstructions added mid-turn, removed when it ends.
        self._live_steers: list = []
        # Deferred prompts: messages sent during an active turn that weren't
        # consumed by the steering middleware are re-dispatched as new turns.
        self._deferred_prompts: list[str] = []
        # Nova learning status (review cycles) shown inline in the #status line
        # beside the context %, so it never overlaps the input. _nova_status is
        # the current message (or None); the timer auto-clears it after a moment.
        self._nova_status: str | None = None
        self._nova_status_style: str = "dim"
        self._nova_indicator_timer: Any = None

    def _current_agent_info(self) -> tuple[str, str]:
        from novacode_cli.ui.input_preparation import get_agent_display_name
        from novacode_cli.config.config import get_agent_color
        aid = self._current_assistant_id or self.assistant_id
        name = get_agent_display_name(aid)
        color = get_agent_color(aid) if name != "Nova" else "#10b981"
        return name, color

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="transcript")
        yield OptionList(id="cmdpalette")
        with Vertical(id="prompt-dock"):
            yield Static("", id="prompt-hint-bar")
            with Horizontal(id="prompt-row"):
                yield Static("> ", id="prompt-prefix")
                yield PromptInput(
                    placeholder="Type your message or @path/to/file",
                    id="prompt",
                    paste_tracker=self.paste_tracker,
                    on_large_paste=self._on_large_paste,
                )
            yield Static("", id="mode-badge")
            with Horizontal(id="info-bar"):
                with Vertical(classes="info-col"):
                    yield Static("workspace (/directory)", classes="info-label")
                    yield Static("", id="info-workspace", classes="info-value")
                with Vertical(classes="info-col"):
                    yield Static("branch", classes="info-label")
                    yield Static("", id="info-branch", classes="info-value")
                with Vertical(classes="info-col"):
                    yield Static("sandbox", classes="info-label")
                    yield Static("", id="info-sandbox", classes="info-value")
                with Vertical(classes="info-col"):
                    yield Static("/model", classes="info-label")
                    yield Static("", id="info-model", classes="info-value")
                with Vertical(classes="info-col"):
                    yield Static("quota", classes="info-label")
                    yield Static("", id="info-quota", classes="info-value")

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
        import threading
        self._thread_id = threading.get_ident()
        # Register Nova's palette and apply the saved (or default) theme first,
        # so the whole UI renders with the right colors from the first frame.
        self._apply_saved_theme()
        # Warm the singleton-widget cache so hot paths (streaming, status ticks,
        # keystrokes) skip the query_one DOM walk. See _w().
        for _sel, _kind in (
            ("#transcript", VerticalScroll),
            ("#prompt", Input),
            ("#mode-badge", Static),
            ("#cmdpalette", OptionList),
            ("#prompt-hint-bar", Static),
            ("#info-workspace", Static),
            ("#info-branch", Static),
            ("#info-sandbox", Static),
            ("#info-model", Static),
            ("#info-quota", Static),
        ):
            try:
                self._w_cache[_sel] = self.query_one(_sel, _kind)
            except NoMatches:
                pass
        self.query_one("#cmdpalette", OptionList).display = False
        self._set_status("ready")
        self._update_mode_badge()
        self._refresh_hint_bar()
        self._refresh_info_bar()
        # Load slash commands contributed by enabled plugins (TUI dispatch).
        self._load_plugin_commands()
        # Animate the live status (~5 fps) while a turn is active.
        self.set_interval(0.05, self._tick)
        self.query_one("#prompt", Input).focus()
        # Show ASCII art banner on home screen
        self._show_home_banner()
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
        # Register tool output callback for live terminal/command execution streaming
        try:
            from novacode_cli.events import register_tool_output_callback

            register_tool_output_callback(self._on_tool_output)
        except Exception:
            pass

    def _on_tool_output(self, call_id: str, text: str) -> None:
        """Schedules a thread-safe update to the terminal log body for a running tool."""

        def update_ui() -> None:
            if call_id in self._tool_components:
                comp, body, base = self._tool_components[call_id]
                if isinstance(body, RichLog):
                    body.write(text)
                    body.scroll_end(animate=False)
            elif call_id in self._subagent_tool_to_task:
                subagent_cid = self._subagent_tool_to_task[call_id]
                if subagent_cid in self._subagent_widgets:
                    comp, body, stype, start_time = self._subagent_widgets[subagent_cid]
                    try:
                        log_widget = body.query_one("#subagent-log", RichLog)
                        if not log_widget.has_class("active"):
                            log_widget.add_class("active")
                        log_widget.write(text)
                        log_widget.scroll_end(animate=False)
                        comp._log_lines = getattr(comp, "_log_lines", 0) + text.count("\n")
                        log_widget.styles.height = min(max(comp._log_lines + 2, 5), 8)
                    except Exception:
                        pass
            elif self._tool_group_body is not None:
                try:
                    log_widget = self._tool_group_body.query_one("#tool-group-log", RichLog)
                    if log_widget.has_class("active"):
                        log_widget.write(text)
                        log_widget.scroll_end(animate=False)
                        self._tool_group_log_lines += text.count("\n")
                        log_widget.styles.height = min(max(self._tool_group_log_lines + 2, 5), 8)
                except Exception:
                    pass

        import threading

        if getattr(self, "_thread_id", None) == threading.get_ident():
            update_ui()
        else:
            try:
                self.call_from_thread(update_ui)
            except RuntimeError:
                update_ui()

    # -- OS focus handlers ----------------------------------------------------
    # Pause/resume the MatrixRain animation when the terminal window gains or
    # loses OS-focus, so the TUI never spins the CPU on an invisible animation.

    def _matrix_rain(self) -> MatrixRain | None:
        """Return the MatrixRain widget if it is mounted, else None."""
        try:
            return self.query_one("#matrix-rain", MatrixRain)
        except NoMatches:
            return None

    def on_app_blur(self) -> None:
        """Pause MatrixRain when the terminal loses OS focus."""
        rain = self._matrix_rain()
        if rain is not None:
            rain.pause()

    def on_app_focus(self) -> None:
        """Resume MatrixRain when the terminal regains OS focus."""
        rain = self._matrix_rain()
        if rain is not None:
            rain.resume()

    # -- helpers --------------------------------------------------------------
    def _w(self, selector: str, kind: Any) -> Any:
        """Return a cached singleton widget, resolving (and caching) on first use.

        Avoids a `query_one` DOM walk on every delta / keystroke / status tick.
        Raises NoMatches (like query_one) if the widget isn't mounted yet — hot
        callers that may run before mount guard with try/except.
        """
        w = self._w_cache.get(selector)
        if w is None:
            try:
                w = self.query_one(selector, kind)
            except NoMatches:
                if self.screen_stack:
                    w = self.screen_stack[0].query_one(selector, kind)
                else:
                    raise
            self._w_cache[selector] = w
        return w

    def _transcript(self) -> VerticalScroll:
        return self._w("#transcript", VerticalScroll)

    def _prune_transcript(self) -> None:
        """Cap the transcript: drop the oldest widgets once it grows too large.

        Skips the in-progress widgets we still hold references to (streaming
        answer/reasoning, open tool/subagent cards, todo, /init tracker) so a
        live turn is never disturbed.
        """
        try:
            tr = self._transcript()
        except NoMatches:
            return
        children = tr.children
        if len(children) <= _MAX_TRANSCRIPT_WIDGETS:
            return
        protected: set[int] = {
            id(w)
            for w in (
                self._stream_msg,
                self._reason_msg,
                self._todo_widget,
                self._init_widget,
                self._tool_group,
                *(t[0] for t in self._tool_components.values()),
                *(s[0] for s in self._subagent_widgets.values()),
            )
            if w is not None
        }
        if self._last_tool is not None:
            protected.add(id(self._last_tool[0]))
        to_remove = []
        # Oldest first; stop once we're back at the low-water mark.
        target = len(children) - _TRANSCRIPT_LOW_WATER
        for w in children:
            if len(to_remove) >= target:
                break
            if id(w) not in protected:
                to_remove.append(w)
        for w in to_remove:
            try:
                w.remove()
            except Exception:  # noqa: BLE001
                pass

    def _scroll_end(self) -> None:
        try:
            self._transcript().scroll_end(animate=False)
        except NoMatches:
            pass

    async def _mount(self, widget) -> None:
        # Any non-tool content closes the current tool group so transcript order
        # stays correct and the next tool burst starts a fresh group.
        self._close_tool_group()
        await self._transcript().mount(widget)
        self._prune_transcript()
        self._scroll_end()

    def _remote_send(self, text: str) -> None:
        """Send a one-off status line to the remote platform during a remote turn.

        Reserved for low-frequency notices. Per-tool / per-subagent activity must
        go through :meth:`_remote_record` instead so it's condensed into a single
        digest rather than flooding the chat.
        """
        msg = self._remote_msg
        if msg is None:
            return
        try:
            import asyncio

            # Track the task so it isn't garbage-collected mid-send and so
            # exceptions surface rather than vanish (fire-and-forget pitfall).
            task = asyncio.create_task(msg.reply_fn(f"{text}"))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    def _remote_record(self, name: str | None) -> None:
        """Record one tool/subagent name for this remote turn's live status line.

        No network call — the name feeds the compact status line (condensed
        counts, edited in place) which the pump flushes on its own timer.
        """
        if self._remote_msg is None or not name:
            return
        self._remote_activity.append(str(name))
        if self._remote_status is not None:
            self._remote_status.note(str(name))

    async def _remote_steer_drain(self, queue: Any) -> None:
        """While a remote turn runs, treat further remote messages as live steers.

        Lets a remote user "add extra stuff to the previous prompt": a message
        (or ``/steer …``) arriving mid-turn is injected as a live steer the
        running agent picks up at its next step, instead of queuing a whole new
        turn behind the current one. Other slash commands get a "busy" note.
        Cancelled when the turn ends.
        """
        while True:
            try:
                m = await queue.get()
            except asyncio.CancelledError:
                return
            try:
                if (
                    self._remote_question_future is not None
                    and not self._remote_question_future.done()
                ):
                    react_fn = getattr(m, "react_fn", None)
                    if react_fn is not None:
                        try:
                            await react_fn("📥")
                        except Exception:  # noqa: BLE001
                            pass
                    self._remote_question_future.set_result(m)
                    continue

                text = (getattr(m, "text", "") or "").strip()
                low = text.lower()
                if low.startswith("/steer"):
                    text = text[len("/steer") :].strip()
                elif text.startswith("/"):
                    reply_fn = getattr(m, "reply_fn", None)
                    if reply_fn is not None:
                        try:
                            await reply_fn(
                                "⏳ Busy with the current task — send "
                                "`/steer <text>` (or just text) to add to it."
                            )
                        except Exception:  # noqa: BLE001
                            pass
                    continue
                if not text:
                    continue
                self._add_live_steer(text)
                react_fn = getattr(m, "react_fn", None)
                reply_fn = getattr(m, "reply_fn", None)
                if react_fn is not None:
                    try:
                        await react_fn("↗")
                    except Exception:  # noqa: BLE001
                        pass
                elif reply_fn is not None:
                    try:
                        await reply_fn(f"↗ Added to the running task: {text}")
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                try:
                    queue.task_done()
                except Exception:  # noqa: BLE001
                    pass

    def _remote_react(self, emoji: str, msg: Any = None) -> None:
        """Add a reaction emoji to the remote user's message (best-effort).

        ``msg`` defaults to the active remote message, but callers can pass it
        explicitly (e.g. the error handler, which runs after ``_remote_msg`` has
        already been cleared).
        """
        msg = msg if msg is not None else self._remote_msg
        if msg is None or getattr(msg, "react_fn", None) is None:
            return
        try:
            import asyncio

            task = asyncio.create_task(msg.react_fn(emoji))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except Exception:  # noqa: BLE001
            pass

    def _log(self, renderable: Any) -> None:
        """Mount an ancillary line (errors, command output, notices)."""
        self._close_tool_group()
        self._transcript().mount(Static(renderable, classes="logline"))
        self._prune_transcript()
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

    def _init_on_event(self, event: Any) -> None:
        """Drive the native step tracker from a structured pipeline event.

        The /init pipeline (``_run_graphify_pipeline``) reports progress through
        UI-agnostic :mod:`novacode_cli.init.events`; this keeps the concise
        pre-set step labels and treats the events as authoritative. Called on the
        app thread from the pipeline coroutine, so it may mutate widgets directly.
        """
        if self._init_widget is None:
            return
        from novacode_cli.init import events as ev

        if isinstance(event, ev.StepStarted):
            for i, st in enumerate(self._init_steps):
                if i < event.index - 1:
                    if st["status"] != "fail":
                        st["status"] = "done"
                elif i == event.index - 1:
                    st["status"] = "active"
                    st["detail"] = ""
            self._init_render_steps()
        elif isinstance(event, ev.StepDetail):
            active = next((s for s in self._init_steps if s["status"] == "active"), None)
            if active is not None:
                active["detail"] = event.text[:80]
                self._init_render_steps()
        elif isinstance(event, ev.Notice):
            if event.level == "error":
                active = next((s for s in self._init_steps if s["status"] == "active"), None)
                if active is not None:
                    active["status"] = "fail"
                    active["detail"] = event.text[:80]
                    self._init_render_steps()
                self._log(Text(event.text, style="red"))
            elif event.level == "warn":
                self._log(Text(event.text, style="yellow"))

    async def _add_message(self, label: Text, role_class: str, body: Any) -> ChatMessage:
        msg = ChatMessage(label, role_class)
        await self._mount(msg)
        msg.update_body(body)
        animate_entrance(msg, "slide")
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

    def _format_breadcrumbs(self, path: Path) -> str:
        """Convert an absolute path into a condensed breadcrumb format.

        Example: B:\\Summer Project 2026\\Nova-Code\\nova-code-cli
                 -> .../Nova-Code/nova-code-cli
        """
        parts = path.parts
        if len(parts) <= 3:
            return str(path)

        # Keep the last 2 segments and prefix with .../
        breadcrumb = "/".join(parts[-2:])
        return f".../{breadcrumb}"

    def _render_startup_info(self) -> None:
        """Render a compact native session-info panel (replaces the legacy
        pre-TUI Rich panels, which never appeared in TUI mode)."""
        from pathlib import Path
        from rich.text import Text

        try:
            from novacode_cli.config.config import settings
        except Exception:  # noqa: BLE001
            return

        sandbox_type = getattr(self.session_state, "_sandbox_type", None)
        meta = self._sandbox_meta

        if sandbox_type and meta:
            # ── Heroku-style TUI list for LangSmith ──
            lines: list[tuple[str, str]] = []

            if snapshot := meta.get("snapshot"):
                lines.append(("snapshot", str(snapshot)))

            specs = []
            if v := meta.get("vcpus"):
                specs.append(f"{v} vCPU")
            if g := meta.get("mem_gb"):
                specs.append(str(g))
            if g := meta.get("fs_capacity_gb"):
                specs.append(str(g))
            if specs:
                lines.append(("specs", " · ".join(specs)))

            if tunnels := meta.get("tunnels"):
                for tn in tunnels:  # type: ignore[union-attr]
                    lines.append(("tunnel", f"localhost:{tn['host']} → sandbox:{tn['container']}"))

            t = Text()
            t.append("● session\n", style="bold yellow")
            t.append("  sandbox : ", style="dim")
            t.append(f"{sandbox_type}", style="yellow")
            t.append(f" ({self._sandbox_id or '?'})\n", style="dim")

            for label, value in lines:
                t.append(f"  {label.ljust(8)}: ", style="dim")
                t.append(f"{value}\n", style="white")

            if t.plain.endswith("\n"):
                t = t[:-1]

            self._log(t)
        else:
            # ── Premium Minimalist Session Details (Pi Coding Agent Style) ──
            t = Text()
            t.append("● session\n", style="bold cyan")

            # model
            t.append("  model   : ", style="dim")
            t.append(f"{self.model_name}\n", style="white")

            # sandbox
            t.append("  sandbox : ", style="dim")
            if sandbox_type:
                try:
                    from novacode_cli.integrations.sandbox_factory import (
                        get_default_working_dir,
                    )

                    wd = get_default_working_dir(sandbox_type)
                except Exception:
                    wd = "?"
                t.append(f"{sandbox_type}", style="yellow")
                t.append(f" (default wd: {wd})\n", style="dim")
            else:
                t.append("local\n", style="green")

            # cwd
            t.append("  cwd     : ", style="dim")
            t.append(f"{Path.cwd()}\n", style="white")

            # memory
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
                    t.append("  memory  : ", style="dim")
                    t.append(f"{' · '.join(parts)}\n", style="white")
                else:
                    t.append("  memory  : ", style="dim")
                    t.append("none (use /init to create project memory)\n", style="dim italic")
            except Exception:
                pass

            # search
            try:
                t.append("  search  : ", style="dim")
                if not settings.has_tavily:
                    t.append("disabled — set TAVILY_API_KEY to enable\n", style="yellow dim")
                else:
                    t.append("enabled via Tavily\n", style="green")
            except Exception:
                pass

            # Strip trailing newline
            if t.plain.endswith("\n"):
                t = t[:-1]

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
                await self._add_message(Text("You", style="bold cyan"), "user", Markdown(text))
                shown += 1
            elif role == "ai":
                await self._add_message(Text("Nova", style="green"), "nova", Markdown(text))
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
        self._stream_flush_scheduled = False
        self._tool_components.clear()
        self._last_tool = None
        self._close_tool_group()
        self._subagent_widgets.clear()
        self._subagent_count = 0
        self._subagent_tool_to_task.clear()
        self._todo_widget = None  # next turn starts a fresh todo block
        self._current_assistant_id = None

    def _flush_stream(self) -> None:
        """Repaint the in-progress stream/reasoning widgets from their buffers.

        Called on a coalescing ~100ms timer (and forced at finalize) so a fast
        token stream triggers ~10 repaints/sec instead of one per token. Updates
        both live widgets in one pass and scrolls once.
        """
        self._stream_flush_scheduled = False
        painted = False
        if self._stream_msg is not None:
            self._stream_msg.update_body(Text(self._live_buf))
            painted = True
        if self._reason_msg is not None:
            self._reason_msg.update_body(Text(self._reasoning_buf[-2000:], style="dim italic"))
            painted = True
        if painted:
            self._scroll_end()

    def _schedule_stream_flush(self) -> None:
        """Ensure a flush happens soon, coalescing bursts of deltas into one."""
        if self._stream_flush_scheduled:
            return
        self._stream_flush_scheduled = True
        self.set_timer(0.1, self._flush_stream)

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

    def _pop_tool(self, call_id: str | None) -> "tuple[Collapsible, Static, str] | None":
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
            return self._render_diff_text("\n".join("+" + ln for ln in after.splitlines()))
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

    # -- condensed tool group -------------------------------------------------

    @staticmethod
    def _oneline(s: str, limit: int = 110) -> str:
        """Collapse whitespace/newlines and truncate to a single short line."""
        s = " ".join((s or "").split())
        return s if len(s) <= limit else s[: limit - 1] + "…"

    async def _ensure_tool_group(self) -> None:
        """Create + mount the condensed tool-group panel if one isn't open."""
        if self._tool_group is not None:
            return
        self._tool_group_entries = []
        self._tool_group_lines = {}
        self._tool_group_last_idx = None
        self._tool_group_log_lines = 0
        body = Vertical(classes="toolbody")
        comp = Collapsible(body, title="⚙ tool calls", collapsed=True)
        comp.add_class("tool")
        animate_entrance(comp, "zoom")
        self._tool_group = comp
        self._tool_group_body = body
        # Mount directly (not via _mount) so we don't immediately close the group
        # we're creating.
        await self._transcript().mount(comp)
        await body.mount(Static("", id="tool-group-list"))
        await body.mount(
            RichLog(id="tool-group-log", classes="terminal-log", highlight=True, markup=True)
        )
        self._prune_transcript()
        self._scroll_end()

    def _close_tool_group(self) -> None:
        """Detach the current tool group so the next burst starts fresh."""
        self._tool_group = None
        self._tool_group_body = None
        self._tool_group_entries = []
        self._tool_group_lines = {}
        self._tool_group_last_idx = None
        self._tool_group_log_lines = 0

    @staticmethod
    def _render_tool_line(entry: dict) -> Text:
        """One compact line for a single tool call in the group body."""
        mark = entry["mark"]
        err = entry["error"]
        mark_style = "red" if err else ("green" if mark == "✓" else "yellow")
        body_style = "red" if err else "dim"
        t = Text()
        t.append(f"{mark} ", style=mark_style)
        t.append(entry["base"], style=body_style)
        if entry["detail"]:
            t.append(f"  — {entry['detail']}", style=body_style)
        return t

    def _refresh_tool_group(self, *, running: str | None = None) -> None:
        """Repaint the group body + title from the current entries."""
        if self._tool_group is None or self._tool_group_body is None:
            return
        body = Text()
        for i, entry in enumerate(self._tool_group_entries[-100:]):
            if i:
                body.append("\n")
            body.append_text(self._render_tool_line(entry))
        try:
            self._tool_group_body.query_one("#tool-group-list", Static).update(body)
        except Exception:
            pass
        n = len(self._tool_group_entries)
        title = f"⚙ {n} tool call" + ("" if n == 1 else "s")
        if running:
            title += f"  · running {running}…"
        self._tool_group.title = title

    def _add_tool_group_call(self, call_id: str | None, base: str, name: str) -> None:
        """Append a 'running' line for a new tool call."""
        entry = {
            "base": self._oneline(base),
            "mark": "⏳",
            "detail": "",
            "error": False,
        }
        idx = len(self._tool_group_entries)
        self._tool_group_entries.append(entry)
        if call_id:
            self._tool_group_lines[call_id] = idx
        self._tool_group_last_idx = idx

        # If running a shell command execution, activate and clear the live log widget
        if name in {
            "shell",
            "bash",
            "execute",
            "execute_bash",
            "run_command",
            "run_tests",
            "start_dev_server",
        }:
            self._tool_group.collapsed = False
            try:
                log_widget = self._tool_group_body.query_one("#tool-group-log", RichLog)
                log_widget.clear()
                log_widget.add_class("active")
                log_widget.write(f"$ {base}\n")
                self._tool_group_log_lines = 1 + base.count("\n")
                log_widget.styles.height = min(max(self._tool_group_log_lines + 2, 5), 8)
            except Exception:
                pass

        self._refresh_tool_group(running=name)

    def _mark_tool_group_result(self, call_id: str | None, *, is_error: bool, detail: str) -> None:
        """Finalize the matching tool line with its status + a short result."""
        idx: int | None = None
        if call_id is not None and call_id in self._tool_group_lines:
            idx = self._tool_group_lines[call_id]
        elif self._tool_group_last_idx is not None:
            idx = self._tool_group_last_idx
        if idx is None or idx >= len(self._tool_group_entries):
            # No open group line (group already closed) — compact fallback line.
            if detail:
                self._log(
                    Text(
                        f"  ⎿  {self._oneline(detail)}",
                        style="red" if is_error else "dim",
                    )
                )
            return
        entry = self._tool_group_entries[idx]
        entry["mark"] = "✗" if is_error else "✓"
        entry["error"] = is_error
        entry["detail"] = self._oneline(detail)
        self._refresh_tool_group()
        # Surface failures: pop the group open so the error isn't hidden.
        if is_error and self._tool_group is not None:
            self._tool_group.collapsed = False

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
        if isinstance(body, RichLog):
            body.clear()
            body.write(Text(out, style="red" if is_error else ""))
            body.scroll_end(animate=False)
        else:
            body.update(Text(out, style="red" if is_error else ""))
        # Animate border to settled state
        from textual.color import Color as TColor

        final_color = "#f7768e" if is_error else "#73daca"  # error / success
        try:
            comp.styles.animate("border_left", f"thick {final_color}", duration=0.35)
        except Exception:  # noqa: BLE001
            pass

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
            # Create a Vertical container as the body
            body = Vertical(classes="toolbody")
            # Start expanded (collapsed=False) so dispatching subagents show live progress
            comp = Collapsible(body, title=title, collapsed=False)  # type: ignore
            comp.add_class("subagent")
            await self._mount(comp)
            animate_entrance(comp, "fade")

            # Mount a Static for status text, a Static for subagent-list, and a RichLog for the progress log
            status_text = Text(e.detail or "", style="dim") if e.detail else Text("")
            await body.mount(Static(status_text, id="subagent-status"))
            await body.mount(Static("", id="subagent-list"))
            await body.mount(
                RichLog(id="subagent-log", classes="terminal-log", highlight=True, markup=True)
            )

            # Initialize dynamic height tracking and entry lists
            comp._log_lines = 0
            comp._log_entries = []
            comp._tool_lines = {}
            try:
                log_widget = body.query_one("#subagent-log", RichLog)
                log_widget.styles.height = 5
            except Exception:
                pass

            self._subagent_widgets[cid] = (
                comp,
                body,
                e.subagent_type or "subagent",
                time.time(),
            )
            # Record the subagent for the end-of-turn remote footer.
            self._remote_record("task")

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
                dur = (
                    f"{elapsed:.1f}s"
                    if elapsed < 60
                    else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
                )
                icon = e.message or f"{e.subagent_type}"
                count = len(self._subagent_widgets)
                remaining = f" · {count} active" if count > 0 else ""
                comp.title = f"{_esc(str(icon))}  ({dur}){remaining}"
                if e.detail:
                    try:
                        body.query_one("#subagent-status", Static).update(
                            Text(e.detail, style="dim")
                        )
                    except Exception:
                        pass
                else:
                    try:
                        body.query_one("#subagent-status", Static).update(Text(""))
                    except Exception:
                        pass
                comp.collapsed = True
                # Clean up tool calls mapping for this subagent
                self._subagent_tool_to_task = {
                    k: v for k, v in self._subagent_tool_to_task.items() if v != matched_cid
                }
                # Subagent completion is already reflected in the digest's task
                # count, so no separate remote message is sent here.
            else:
                # No matching widget — log as a simple line
                dur_part = ""
                if e.detail:
                    dur_part = f" — {e.detail}"
                self._log(Text(f"{e.message}{dur_part}", style=color))

        elif e.kind in ("status", "tool_start", "tool_result") and e.message:
            if e.kind == "tool_start" and e.detail and cid:
                self._subagent_tool_to_task[e.detail] = cid
            elif e.kind == "tool_result" and e.detail:
                self._subagent_tool_to_task.pop(e.detail, None)

            if cid and cid in self._subagent_widgets:
                comp, body, stype, start_time = self._subagent_widgets[cid]
                log_entries = getattr(comp, "_log_entries", [])
                tool_lines = getattr(comp, "_tool_lines", {})

                if e.kind == "tool_start":
                    if e.detail and e.detail in tool_lines:
                        idx = tool_lines[e.detail]
                        entry = log_entries[idx]
                        entry["display"] = e.message
                    else:
                        entry = {
                            "type": "tool",
                            "display": e.message,
                            "mark": "⏳",
                            "detail": "",
                            "error": False,
                        }
                        idx = len(log_entries)
                        log_entries.append(entry)
                        if e.detail:
                            tool_lines[e.detail] = idx
                    comp._log_entries = log_entries
                    comp._tool_lines = tool_lines
                    self._refresh_subagent_list(cid)
                elif e.kind == "tool_result":
                    if e.detail and e.detail in tool_lines:
                        idx = tool_lines[e.detail]
                        entry = log_entries[idx]
                        is_error = e.color == "#f7768e"
                        entry["mark"] = "✗" if is_error else "✓"
                        entry["detail"] = e.message
                        entry["error"] = is_error
                    comp._log_entries = log_entries
                    comp._tool_lines = tool_lines
                    self._refresh_subagent_list(cid)
                else:  # status
                    log_entries.append(
                        {
                            "type": "status",
                            "display": e.message,
                        }
                    )
                    comp._log_entries = log_entries
                    self._refresh_subagent_list(cid)
            else:
                self._log(Text(f"  ⟐ {e.message}", style=color))

    def _refresh_subagent_list(self, cid: str) -> None:
        """Redraw the subagent Static list based on its current entries."""
        if cid not in self._subagent_widgets:
            return
        comp, body, stype, start_time = self._subagent_widgets[cid]
        try:
            list_widget = body.query_one("#subagent-list", Static)
            log_entries = getattr(comp, "_log_entries", [])
            lines = []
            for entry in log_entries:
                if entry.get("type") == "status":
                    lines.append(f"⟐ {entry['display']}")
                else:
                    mark = entry["mark"]
                    display = entry["display"]
                    detail = entry["detail"]
                    error = entry["error"]
                    color = "#f7768e" if error else ("#73daca" if mark == "✓" else "#bb9af7")

                    line = f"[{color}]{mark}[/{color}] {display}"
                    if detail:
                        clean_detail = detail
                        if clean_detail in ("✓", "✗"):
                            clean_detail = ""
                        if clean_detail.startswith("✓ ") or clean_detail.startswith("✗ "):
                            clean_detail = clean_detail[2:]
                        if clean_detail:
                            line += f" [dim]· {clean_detail}[/dim]"
                    lines.append(f"⟐ {line}")
            list_widget.update("\n".join(lines))
        except Exception:
            pass

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

    def _set_nova_indicator(
        self, text: str, *, style: str = "dim", auto_clear: float | None = None
    ) -> None:
        """Show the Nova learning status (review cycle) inline in the status line.

        The status renders beside the context % (see :meth:`_refresh_status`) so
        it never overlaps the input box. Empty ``text`` clears it.

        Args:
            text: Message to display. Empty string clears the status.
            style: Rich style for the text.
            auto_clear: If set, clear the status after this many seconds.
        """
        # Cancel any pending auto-clear so a new message isn't wiped early.
        if self._nova_indicator_timer is not None:
            try:
                self._nova_indicator_timer.stop()
            except Exception:  # noqa: BLE001
                pass
            self._nova_indicator_timer = None

        self._nova_status = text or None
        self._nova_status_style = style
        self._refresh_status()

        if text and auto_clear is not None:
            self._nova_indicator_timer = self.set_timer(
                auto_clear, lambda: self._set_nova_indicator("")
            )

    @staticmethod
    def _ctx_gauge(percent: float, width: int = 10) -> str:
        """A unicode fill gauge like ▕█▉░░░░░░░▏ for *percent* across *width* cells."""
        percent = max(0.0, min(100.0, percent))
        filled = percent / 100.0 * width
        full = int(filled)
        eighths = " ▏▎▍▌▋▊▉█"
        cells = ["█"] * full
        rem = round((filled - full) * 8)
        if full < width and rem > 0:
            cells.append(eighths[min(8, rem)])
        cells += ["░"] * (width - len(cells))
        return "▕" + "".join(cells[:width]) + "▏"

    def _refresh_status(self) -> None:
        line = Text()

        def _divider() -> None:
            line.append("  │  ", style="#3b4261")

        # Activity segment — animated spinner + elapsed while live, else a ● dot.
        if self._turn_active:
            frame = self._SPINNER[self._spinner_frame % len(self._SPINNER)]
            elapsed = time.monotonic() - self._turn_start
            line.append(f"{frame} ", style="bold #bb9af7")
            line.append(str(self._activity), style="#c0caf5")
            line.append(f"  {elapsed:0.1f}s", style="dim")
        else:
            line.append("● ", style="#9ece6a")
            line.append(str(self._activity), style="#9ece6a")

        # Context segment — a filling gauge that recolors green→amber→red.
        if self.token_tracker is not None:
            try:
                bd = self.token_tracker.get_breakdown()
            except Exception:  # noqa: BLE001
                bd = None
            if bd is not None:
                p = bd.usage_percentage
                if p >= 90:
                    ctx_color = "#f7768e"
                elif p >= 75:
                    ctx_color = "#e0af68"
                else:
                    ctx_color = "#9ece6a"
                _divider()
                line.append("ctx ", style="dim")
                line.append(self._ctx_gauge(p), style=ctx_color)
                line.append(f" {p:.0f}%", style=f"bold {ctx_color}")

        # Nova learning status (review cycle).
        if self._nova_status:
            _divider()
            line.append(self._nova_status, style=self._nova_status_style)

        notif = self._unread_count()
        if notif:
            line.append("   🔔 ", style="bold #e0af68")
            line.append(str(notif), style="bold #e0af68")

        pending = self._pending_approval_count()
        if pending:
            line.append("   ⚡", style="bold yellow")
            line.append(str(pending), style="bold yellow")

        # Right-align skill/file counts
        try:
            skills = self._get_skill_names()
            skill_count = len(skills)
        except Exception:  # noqa: BLE001
            skill_count = 0
        try:
            from novacode_cli.config.config import settings

            proj_files = settings.get_project_agent_md_paths()
            file_count = len(proj_files)
        except Exception:  # noqa: BLE001
            file_count = 0

        # Build the right-side info string
        right_parts: list[str] = []
        if file_count:
            right_parts.append(f"{file_count} NOVA.md file{'s' if file_count != 1 else ''}")
        if skill_count:
            right_parts.append(f"{skill_count} skill{'s' if skill_count != 1 else ''}")

        if right_parts:
            # Pad to push the right info to the far right
            right_text = " · ".join(right_parts)
            # Use a large gap to simulate right alignment
            line.append("  ", style="dim")
            # We'll just append it; true right-align isn't possible in Text, but
            # the CSS already handles this if we update the hint bar carefully.
            line.append(right_text, style="dim")

        try:
            self._w("#prompt-hint-bar", Static).update(line)
        except NoMatches:
            pass

    def _unread_count(self) -> int:
        """Unread notification count (0 on any error)."""
        try:
            return self.session_state.unread_notification_count()
        except Exception:  # noqa: BLE001
            return 0

    def _pending_approval_count(self) -> int:
        """Pending approval count (0 on any error)."""
        try:
            return self.session_state.pending_approval_count()
        except Exception:  # noqa: BLE001
            return 0

    def _refresh_hint_bar(self) -> None:
        """Populate the hint bar above the input (delegates to _refresh_status)."""
        self._refresh_status()

    def _refresh_info_bar(self) -> None:
        """Populate the info-bar columns below the input: workspace, branch, sandbox, model, quota."""
        from pathlib import Path
        import subprocess

        # Workspace
        cwd = str(Path.cwd())
        try:
            self._w("#info-workspace", Static).update(Text(cwd, style="bold"))
        except NoMatches:
            pass

        # Branch (git)
        branch = "—"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3,
                cwd=cwd,
            )
            if result.returncode == 0:
                branch = result.stdout.strip() or "—"
        except Exception:  # noqa: BLE001
            pass
        try:
            self._w("#info-branch", Static).update(Text(branch, style="bold #bb9af7"))
        except NoMatches:
            pass

        # Sandbox
        sandbox_type = getattr(self.session_state, "_sandbox_type", None)
        if sandbox_type:
            sandbox_text = Text(str(sandbox_type), style="bold yellow")
        else:
            sandbox_text = Text("no sandbox", style="#e0af68")
        try:
            self._w("#info-sandbox", Static).update(sandbox_text)
        except NoMatches:
            pass

        # Model
        try:
            self._w("#info-model", Static).update(
                Text(str(self.model_name or "—"), style="bold #7aa2f7")
            )
        except NoMatches:
            pass

        # Quota (context usage)
        quota_text = Text("—", style="dim")
        if self.token_tracker is not None:
            try:
                bd = self.token_tracker.get_breakdown()
                if bd is not None:
                    p = bd.usage_percentage
                    if p >= 90:
                        c = "#f7768e"
                    elif p >= 75:
                        c = "#e0af68"
                    else:
                        c = "#9ece6a"
                    quota_text = Text(f"{p:.0f}% used", style=f"bold {c}")
            except Exception:  # noqa: BLE001
                pass
        try:
            self._w("#info-quota", Static).update(quota_text)
        except NoMatches:
            pass

    def _refresh_quota(self) -> None:
        """Lightweight quota-only refresh (called from _tick during active turns)."""
        quota_text = Text("—", style="dim")
        if self.token_tracker is not None:
            try:
                bd = self.token_tracker.get_breakdown()
                if bd is not None:
                    p = bd.usage_percentage
                    if p >= 90:
                        c = "#f7768e"
                    elif p >= 75:
                        c = "#e0af68"
                    else:
                        c = "#9ece6a"
                    quota_text = Text(f"{p:.0f}% used", style=f"bold {c}")
            except Exception:  # noqa: BLE001
                pass
        try:
            self._w("#info-quota", Static).update(quota_text)
        except NoMatches:
            pass

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
            # Also keep the quota column in the info bar current during turns.
            if self._turn_active:
                self._refresh_quota()

    # -- input ----------------------------------------------------------------
    def _update_mode_badge(self, input_value: str = "") -> None:
        """Show a mode badge and restyle/animate the input for plan/bash modes.

        Bash takes visual precedence over plan when both apply (you can be in
        plan mode and still type a ``!command``). Styling is driven by CSS
        classes (``bash-mode`` / ``plan-mode``) plus a per-mode pulse so each
        mode has a distinct look *and* a distinct animation.
        """
        plan = getattr(self.session_state, "plan_mode_enabled", False)
        bash = input_value.startswith("!")
        goal = getattr(self.session_state, "active_goal", None)
        # Skip the badge/class/pulse work entirely when the mode is unchanged —
        # this runs on every keystroke, so the common case (mode didn't change)
        # must be a cheap no-op.
        if self._last_mode_state == (plan, bash, bool(goal)):
            return
        self._last_mode_state = (plan, bash, bool(goal))
        try:
            badge = self._w("#mode-badge", Static)
            prompt = self._w("#prompt", Input)
        except NoMatches:
            return

        if plan and bash:
            t = Text()
            t.append("  ⏸ PLAN  ", style="bold #7aa2f7")
            t.append("$ BASH — runs in your shell", style="bold #bb9af7")
            badge.update(t)
            badge.display = True
        elif plan:
            badge.update(Text("  ⏸ PLAN MODE — proposing, not editing", style="bold #7aa2f7"))
            badge.display = True
        elif bash:
            badge.update(Text("  $ BASH — runs in your shell", style="bold #bb9af7"))
            badge.display = True
        elif goal:
            short = goal if len(goal) <= 60 else goal[:57] + "…"
            badge.update(Text(f"  🎯 GOAL — {short}", style="bold #e0af68"))
            badge.display = True
        else:
            badge.update("")
            badge.display = False

        # Drive the input look from CSS classes (bash wins over plan visually).
        prompt.set_class(bash, "bash-mode")
        prompt.set_class(plan and not bash, "plan-mode")

        # Also style the > prefix chevron and the prompt row to match.
        try:
            prefix = self.query_one("#prompt-prefix", Static)
            prefix.set_class(bash, "bash-mode")
            prefix.set_class(plan and not bash, "plan-mode")
            prefix.update("$ " if bash else "> ")
        except NoMatches:
            pass
        try:
            row = self.query_one("#prompt-row", Horizontal)
            row.set_class(bash, "bash-mode")
            row.set_class(plan and not bash, "plan-mode")
        except NoMatches:
            pass

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
            prompt.styles.animate("tint", value=Color(0, 0, 0, 0.0), duration=0.3)
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
                prompt.styles.animate("tint", value=glow.with_alpha(alpha), duration=period * 0.85)
            except Exception:  # noqa: BLE001
                pass

        _tick()  # kick off immediately
        self._input_pulse_timer = self.set_interval(period, _tick)

    # -- autocomplete dropdown ------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        self._update_palette(event.value, event.input.cursor_position)
        self._update_mode_badge(event.value)

    def _active_at_fragment(self, value: str, cursor: int) -> tuple[int, str] | None:
        """The ``@token`` ending at the cursor, anywhere in the line.

        Returns ``(start_index_of_@, fragment_after_@)`` or ``None``. The token
        must be at the start of the line or preceded by whitespace, so emails
        (``user@host``) and mid-word ``@`` don't trigger completion.
        """
        m = _AT_FRAGMENT_RE.search(value[: max(0, cursor)])
        if not m:
            return None
        return m.start(), m.group(1)

    def _palette_candidates(self, value: str, cursor: int | None = None) -> list[str]:
        """Completion candidates for the current input, by trigger context.

        ``@`` mentions are matched at the **cursor token anywhere** in the line;
        ``/`` commands remain line-level (they only make sense at the start).
        """
        if cursor is None:
            cursor = len(value)

        # @<agent>/<file> — completes the @token under the cursor, ANYWHERE.
        frag = self._active_at_fragment(value, cursor)
        if frag is not None:
            return self._at_candidates(frag[1])

        # Slash contexts are line-level: a space means the token is complete,
        # unless it is a command like `/ingest` or `/file` that takes arguments.
        if " " in value or not value:
            if value.startswith("/ingest "):
                prefix = value[len("/ingest "):].strip()
                try:
                    from novacode_cli.wiki.ingest import IngestEngine
                    from pathlib import Path
                    engine = IngestEngine()
                    sources = engine.list_raw_sources()
                    matches = []
                    for s in sources:
                        if not prefix or prefix.lower() in s.lower() or prefix.lower() in Path(s).name.lower():
                            matches.append(s)
                    return [f"/ingest {s}" for s in matches[:50]]
                except Exception:
                    return []
            elif value.startswith("/file "):
                prefix = value[len("/file "):].strip()
                categories = ["technologies/", "frameworks/", "patterns/", "projects/", "comparisons/"]
                matches = [c for c in categories if not prefix or c.lower().startswith(prefix.lower())]
                return [f"/file {c}" for c in matches]
            return []
        v = value.lower()
        # /skill:<name> — invoke a skill
        if value.startswith("/skill:"):
            return [
                f"/skill:{n}"
                for n in self._get_skill_names()
                if f"/skill:{n}".lower().startswith(v)
            ]
        # /<command>
        if value.startswith("/"):
            return [c for c in _TUI_SLASH_COMMANDS if c.startswith(v)]
        return []

    def _at_candidates(self, fragment: str) -> list[str]:
        """Build @agent + @file completions for an ``@`` fragment (no leading @)."""
        at_prefix = f"@{fragment}".lower()
        candidates: list[str] = []
        # Agent completions
        for n in self._get_agent_names():
            if f"@{n}".lower().startswith(at_prefix):
                candidates.append(f"@{n}")
        # File completions — recursive match across the whole project tree
        if True:
            prefix = fragment
            max_results = 50
            try:
                cwd = Path.cwd()
                # Skip common non-source directories to keep rglob fast
                _SKIP_DIRS = frozenset(
                    {
                        ".git",
                        ".nova",
                        ".venv",
                        ".env",
                        "node_modules",
                        "__pycache__",
                        ".pytest_cache",
                        "build",
                        "dist",
                        ".ruff_cache",
                        ".mypy_cache",
                    }
                )

                def _walk(p: Path, prefix: str, cwd: Path, seen: set[str]) -> None:
                    """Recursively match files starting with prefix, skipping noise dirs."""
                    for child in p.iterdir():
                        is_dir = child.is_dir()
                        # Skip hidden dirs (don't descend into them)
                        if is_dir and (child.name.startswith(".") or child.name in _SKIP_DIRS):
                            continue
                        if child.name.lower().startswith(prefix.lower()):
                            rel = child.relative_to(cwd).as_posix()
                            tag = f"@{rel}"
                            if is_dir:
                                tag += "/"
                            if tag not in seen:
                                seen.add(tag)
                                candidates.append(tag)
                        if is_dir and len(seen) < max_results:
                            _walk(child, prefix, cwd, seen)

                seen: set[str] = set()
                if "/" in prefix:
                    dir_part, _, file_part = prefix.rpartition("/")
                    search_dir = (cwd / dir_part).resolve()
                    if search_dir.is_dir():
                        for p in search_dir.iterdir():
                            name = p.name
                            if name.lower().startswith(file_part.lower()):
                                rel = p.relative_to(cwd).as_posix()
                                tag = f"@{rel}"
                                if p.is_dir():
                                    tag += "/"
                                if tag not in seen:
                                    seen.add(tag)
                                    candidates.append(tag)
                            if len(seen) >= max_results:
                                break
                else:
                    _walk(cwd, prefix, cwd, seen)
            except Exception:
                pass
            return candidates

    @work(group="palette", exclusive=True)
    async def _update_palette(self, value: str, cursor: int | None = None) -> None:
        if cursor is None:
            cursor = len(value)

        # Small debounce for fast typing.
        await asyncio.sleep(0.05)

        # Run the potentially heavy candidate search (which walks the filesystem)
        # in a background thread to keep the main TUI loop responsive.
        matches = await asyncio.to_thread(self._palette_candidates, value, cursor)

        # No-op (don't show) when the only match already equals the current
        # token — the @fragment under the cursor, or the whole line for slashes.
        frag = self._active_at_fragment(value, cursor)
        current_token = f"@{frag[1]}" if frag is not None else value
        show = bool(matches) and not (
            len(matches) == 1 and matches[0].lower() == current_token.lower()
        )
        if not show:
            self._hide_palette()
            return
        # No-op when the candidate list is identical to what's already shown —
        # this runs on every keystroke, and rebuilding the OptionList (clear +
        # re-add) every time is the bulk of typing lag in completion contexts.
        if matches == self._last_palette:
            return
        self._last_palette = list(matches)
        try:
            palette = self._w("#cmdpalette", OptionList)
        except NoMatches:
            return
        palette.clear_options()
        for c in matches:
            palette.add_option(Option(c))
        palette.display = True
        try:
            palette.highlighted = 0
        except Exception:  # noqa: BLE001
            pass

    def _hide_palette(self) -> None:
        self._last_palette = None
        try:
            palette = self._w("#cmdpalette", OptionList)
        except NoMatches:
            return
        palette.clear_options()
        palette.display = False

    def _accept_palette(self, command: str) -> None:
        inp = self.query_one("#prompt", Input)
        value = inp.value
        cursor = inp.cursor_position
        frag = self._active_at_fragment(value, cursor)
        if frag is not None and command.startswith("@"):
            # Replace only the @token under the cursor, preserving the rest of
            # the line. Directories (trailing "/") get no space so the user can
            # keep typing the path; everything else gets a trailing space.
            start, _ = frag
            trailing = "" if command.endswith("/") else " "
            inp.value = value[:start] + command + trailing + value[cursor:]
            inp.cursor_position = start + len(command) + len(trailing)
        else:
            # Slash command (line-level): replace the whole line.
            inp.value = f"{command} "
            inp.cursor_position = len(inp.value)
        self._hide_palette()
        inp.focus()

    def on_key(self, event) -> None:
        # Runs on EVERY keystroke — use the cached ref and bail immediately when
        # the palette is hidden (the common case) to avoid a DOM walk per key.
        try:
            palette = self._w("#cmdpalette", OptionList)
        except NoMatches:
            return
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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Mouse-click accept from the command palette (other lists handle their own).
        if event.option_list.id == "cmdpalette":
            self._accept_palette(str(event.option.prompt))

    def _on_large_paste(self, placeholder: str, char_count: int) -> None:
        """Notify the transcript that a large paste was collapsed."""
        self._log(Text(f"{placeholder} ({char_count:,} chars)", style="dim"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Only react to the main prompt (modals have their own inputs).
        if event.input.id != "prompt":
            return
        # If the palette is open, Enter accepts the highlighted command.
        palette = self.query_one("#cmdpalette", OptionList)
        if palette.display and palette.option_count and palette.highlighted is not None:
            opt = palette.get_option_at_index(palette.highlighted)
            self._accept_palette(str(opt.prompt))
            return
        # The input box holds compact [paste #N +M lines] placeholders for large
        # pastes (so the box stays readable while composing). On submit we expand
        # them back to the full text, which is what both the agent receives AND
        # what the chat shows — the sent message is displayed in full.
        text = resolve_paste_placeholders(event.value, self.paste_tracker).strip()
        # Strip deceptive/invisible Unicode (BiDi overrides, zero-width chars) a
        # paste may smuggle in — a prompt-injection vector. Warn + sanitize.
        text = self._sanitize_user_text(text)
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

    def _sanitize_user_text(self, text: str) -> str:
        """Strip deceptive/invisible Unicode from user input (warn + sanitize).

        Hidden BiDi/zero-width characters in a prompt (often pasted) can hide
        instructions from the human while still reaching the model. We remove
        them and surface a TUI notice. Best-effort — never block input on error.
        """
        try:
            from novacode_cli.security.unicode_security import (
                detect_dangerous_unicode,
                strip_dangerous_unicode,
                summarize_issues,
            )

            issues = detect_dangerous_unicode(text)
            if not issues:
                return text
            cleaned = strip_dangerous_unicode(text)
            self._log(
                Text(
                    f"🛡 Removed {len(issues)} hidden Unicode char(s) from input "
                    f"({summarize_issues(issues)})",
                    style="yellow",
                )
            )
            return cleaned
        except Exception:  # noqa: BLE001
            return text

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
            Text(
                f"↗ Steering (applies on the next step): {text}",
                style="italic #7aa2f7",
            )
        )

    def action_cancel_turn(self) -> None:
        self.workers.cancel_all()
        self._set_status("cancelling…")

    async def action_toggle_terminal(self) -> None:
        """ctrl+t: open a new inline interactive terminal widget in the chat transcript."""
        await self._run_bash("!")

    async def action_run_background(self) -> None:
        """ctrl+b: run the current input in the background without blocking the terminal.

        Mirrors Claude Code's Ctrl+B behaviour:
        - ``!<cmd>`` → background subprocess (output streams into a card).
        - Any other text → background agent turn (full agent, fresh thread_id,
          auto-approved tools so it never blocks waiting for user input).
        """
        try:
            prompt_widget = self._w("#prompt", Input)
        except NoMatches:
            return
        raw = prompt_widget.value.strip()
        if not raw:
            self._log(Text("ctrl+b: type a prompt or !command first", style="dim"))
            return
        prompt_widget.value = ""
        self._update_mode_badge()
        self._bg_job_count += 1
        job_id = self._bg_job_count
        if raw.startswith("!"):
            cmd = raw[1:].strip()
            if not cmd:
                self._log(Text("ctrl+b: empty command after !", style="dim"))
                return
            self._bg_shell_worker(cmd, job_id)
        else:
            self._bg_agent_worker(raw, job_id)

    async def action_copy_or_quit(self) -> None:
        """ctrl+c: copy the active text selection to the clipboard, else quit.

        Lets users select text in the transcript (chat messages, tool output)
        and copy it with ctrl+c. With no selection, behaves like quit.
        """
        try:
            selected = self.screen.get_selected_text()
        except Exception:  # noqa: BLE001
            selected = None
        if selected:
            try:
                self.copy_to_clipboard(selected)
                self._log(Text(f"📋 Copied {len(selected)} chars to clipboard", style="dim"))
                # Clear the highlight now that it's copied.
                self.screen.selections = {}
                self.screen.refresh()
            except Exception:  # noqa: BLE001
                pass
            return
        await self.action_quit()

    async def action_quit(self) -> None:
        """Persist the session (so --continue works) then exit."""
        try:
            from novacode_cli.events import unregister_tool_output_callback

            unregister_tool_output_callback(self._on_tool_output)
        except Exception:
            pass
        await self._save_session()
        self.exit()

    async def _save_session(self, *, cleared: bool = False) -> None:
        """Save the conversation to disk via the session manager (best effort).

        Args:
            cleared: Mark the saved session as cleared (used by /clear) so it is
                excluded from --continue auto-resume — a cleared conversation
                won't come back, but stays on disk for the picker.
        """
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
            todos = state.values.get("todos") or getattr(self.session_state, "todos", None)
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
                sandbox_id=self._sandbox_id,
                sandbox_type=self._sandbox_type,
                cleared=cleared,
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

        # @agent mention(s) -> delegate through the main agent's `task` tool.
        try:
            from novacode_cli.config.config import settings
            from novacode_cli.input import (
                parse_agent_mentions,
                parse_agent_mentions_multi,
            )

            mentioned_agents = parse_agent_mentions_multi(text, settings)
            agent_name, query = parse_agent_mentions(text, settings)
        except Exception:  # noqa: BLE001
            mentioned_agents, agent_name, query = [], None, text

        # Two or more agents (or an agent mentioned mid-message): hand the whole
        # request to the main agent and let it orchestrate the named subagents in
        # order via `task`. @file mentions are expanded by the normal turn path.
        if len(mentioned_agents) >= 2 or (  # noqa: PLR2004
            mentioned_agents and agent_name is None
        ):
            ordered = " → ".join(f"@{a}" for a in mentioned_agents)
            await self._add_message(Text(f"You → {ordered}", style="bold cyan"), "user", Text(text))
            preamble = (
                "This request references specialist subagents by @name. Delegate "
                "each part of the work to the named agent using the `task` tool, "
                "in the order implied by the request, passing results (e.g. edited "
                "files) from one to the next. Referenced agents in order: "
                f"{', '.join(mentioned_agents)}.\n\nRequest:\n{text}"
            )
            await self._stream_prompt(preamble)
            return

        # Single agent at the start: delegate directly to that one subagent.
        if agent_name:
            await self._add_message(
                Text(f"{agent_name}", style="bold cyan"), "user", Text(query)
            )
            await self._stream_prompt(
                f"Call the '{agent_name}' subagent to do the following:\n\n{query}"
            )
            return

        # Plain prompt — send it to the agent as a single turn.
        await self._add_message(Text("You", style="bold cyan"), "user", Text(text))
        await self._stream_prompt(text)
        # If a plan was approved during this turn, hand off to the main agent.
        await self._maybe_run_approved_plan()

    async def _stream_prompt(self, text: str, assistant_id: str | None = None) -> None:
        """Run a single prompt through the agent and render its events.

        Serialized on the shared remote lock so local and remote turns never
        interleave on the same checkpointer thread.
        """
        lock = getattr(self.session_state, "_remote_message_lock", None)
        self._reset_streaming()
        self._current_assistant_id = assistant_id
        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status("thinking…")
        try:
            if lock is not None:
                async with lock:
                    await self._do_stream(text, assistant_id)
            else:
                await self._do_stream(text, assistant_id)
        except asyncio.CancelledError:
            self._reset_streaming()
            self._log(Text("Cancelled.", style="yellow"))
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Error: {ex}", style="red"))
        finally:
            self._turn_active = False
            self._set_status("ready")
            self._clear_live_steers()
            # Safety net: clear the Nova review indicator if it's still showing
            # (e.g. a review triggered on the final turn never drained its
            # completion event).
            self._set_nova_indicator("")
        # Refresh the per-category context breakdown from agent state, then
        # proactively manage the context window once the turn has settled.
        await self._update_context_breakdown()
        await self._check_context()
        # Auto-dispatch any deferred prompts that weren't consumed as steers.
        await self._drain_deferred_prompts()

    async def _update_context_breakdown(self) -> None:
        """Recompute the context breakdown from agent state after a turn.

        The console renderer does this in its finalization step; without it the
        TUI's /context view and context warnings had no per-category detail.
        Best-effort — never blocks the turn on a state read.
        """
        tracker = self.token_tracker
        if tracker is None or not getattr(tracker, "model_name", None):
            return
        try:
            from novacode_cli.context import ContextManager

            ag, _ = self._active_agent()
            config = {"configurable": {"thread_id": self.session_state.thread_id}}
            state = await ag.aget_state(config)
            msgs = state.values.get("messages", []) if state else []
            if msgs:
                tracker.set_breakdown(ContextManager(tracker.model_name).breakdown(msgs))
        except Exception:  # noqa: BLE001
            pass

        await self._maybe_warn_ollama_offload(tracker.model_name)

    async def _maybe_warn_ollama_offload(self, model_name: str | None) -> None:
        """Warn once if the loaded Ollama model is offloaded to CPU (slow).

        Skips cloud API models entirely. Probes `ollama ps` off the event loop;
        stays "unchecked" until the model is actually loaded so the advisory
        still fires on a later turn, then latches off.
        """
        if self._ollama_offload_checked or not model_name:
            return
        from novacode_cli.context._dynamic import is_ollama_cloud_model

        if model_name.lower().startswith(
            ("claude-", "gpt-", "gemini-", "o1", "o3", "o4")
        ) or is_ollama_cloud_model(model_name):
            # Cloud (API or Ollama-cloud) runs remotely — never offloads locally.
            self._ollama_offload_checked = True
            return
        try:
            from novacode_cli.context._dynamic import (
                check_ollama_offloading,
                get_ollama_runtime_info,
            )

            info = await asyncio.to_thread(get_ollama_runtime_info, model_name)
            if info is None:
                return  # not loaded yet — retry on a later turn
            self._ollama_offload_checked = True
            warning = await asyncio.to_thread(check_ollama_offloading, model_name)
            if warning:
                self._log(Text(f"⚠ {warning}", style="bold #e0af68"))
        except Exception:  # noqa: BLE001
            self._ollama_offload_checked = True

    def _clear_live_steers(self) -> None:
        """Drop transient live-steer instructions added during the turn.

        Unconsumed steers (the agent finished before the middleware could
        inject them) are saved to ``_deferred_prompts`` so they can be
        dispatched as a fresh turn rather than silently vanishing.
        """
        if not self._live_steers:
            return
        instrs = getattr(self.session_state, "steering_instructions", None) or []
        for si in self._live_steers:
            # If the middleware never delivered this steer, requeue it.
            if not si.consumed:
                self._deferred_prompts.append(si.instruction)
            try:
                instrs.remove(si)
            except ValueError:
                pass
        self._live_steers.clear()

    async def _drain_deferred_prompts(self) -> None:
        """Dispatch prompts that were queued during the previous turn.

        Called after ``_stream_prompt`` finishes. Each deferred prompt is
        shown as a user message and run through the agent as a new turn,
        giving the user seamless "send while busy" behaviour.
        """
        while self._deferred_prompts:
            prompt = self._deferred_prompts.pop(0)
            self._log(
                Text(
                    f"↗ Processing queued message: {prompt}",
                    style="italic #9ece6a",
                )
            )
            await self._add_message(
                Text("You", style="bold cyan"), "user", Text(prompt)
            )
            await self._stream_prompt(prompt)

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

    async def _do_stream(self, text: str, assistant_id: str | None = None) -> None:
        ag, backend = self._active_agent()
        aid = assistant_id or self.assistant_id
        async for e in run_agent_stream(
            text,
            ag,
            aid,
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
                lock = getattr(self.session_state, "_remote_message_lock", None)
                if self._turn_active or (lock is not None and lock.locked()):
                    try:
                        # Log it in the TUI transcript so the local user sees it
                        await self._add_message(
                            Text(
                                f"📡 {msg.user_name} ({msg.platform.value})",
                                style="bold cyan",
                            ),
                            "user",
                            Text(msg.text),
                        )
                        # Treat as steer / question response
                        if (
                            self._remote_question_future is not None
                            and not self._remote_question_future.done()
                        ):
                            react_fn = getattr(msg, "react_fn", None)
                            if react_fn is not None:
                                try:
                                    await react_fn("📥")
                                except Exception:
                                    pass
                            self._remote_question_future.set_result(msg)
                            continue

                        text = (getattr(msg, "text", "") or "").strip()
                        low = text.lower()
                        if low.startswith("/steer"):
                            text = text[len("/steer") :].strip()
                        elif text.startswith("/"):
                            reply_fn = getattr(msg, "reply_fn", None)
                            if reply_fn is not None:
                                try:
                                    await reply_fn(
                                        "⏳ Busy with the current task — send "
                                        "`/steer <text>` (or just text) to add to it."
                                    )
                                except Exception:
                                    pass
                            continue
                        if not text:
                            continue
                        
                        self._add_live_steer(text)
                        react_fn = getattr(msg, "react_fn", None)
                        reply_fn = getattr(msg, "reply_fn", None)
                        if react_fn is not None:
                            try:
                                await react_fn("↗")
                            except Exception:
                                pass
                        elif reply_fn is not None:
                            try:
                                await reply_fn(f"↗ Added to the running task: {text}")
                            except Exception:
                                pass
                    except Exception as ex:
                        self._log(Text(f"Steer error: {ex}", style="red"))
                    finally:
                        queue.task_done()
                    continue
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
                typing_task: "asyncio.Task | None" = None
                try:
                    self._remote_msg = msg
                    self._remote_activity = []  # tool/subagent names for the status
                    self._remote_status = None
                    self._remote_react("🤔")  # acknowledge: thinking
                    # Keep the "typing…" indicator alive for the whole turn so it
                    # reads like a person typing, then sends a message (the platform
                    # indicator only lasts ~10s, so it must be re-triggered).
                    if msg.typing_fn is not None:

                        async def _typing_loop(typing_fn=msg.typing_fn) -> None:
                            try:
                                while True:
                                    await typing_fn()
                                    await asyncio.sleep(8)
                            except asyncio.CancelledError:
                                return

                        typing_task = asyncio.create_task(_typing_loop())

                    # Slash commands from chat: handle the remote-safe subset
                    # directly (info/toggles/conversation), stream skills as a
                    # turn, and decline interactive/local-only ones.
                    prompt_text = msg.text.strip()
                    slash_reply: str | None = None
                    if prompt_text.startswith("/"):
                        slash_reply, resolved = await self._remote_slash(prompt_text)
                        if resolved is not None:
                            prompt_text = resolved  # e.g. a resolved skill prompt

                    if slash_reply is not None:
                        # Command fully handled — reply directly, no agent turn.
                        try:
                            await msg.reply_fn(slash_reply)
                        except Exception:  # noqa: BLE001
                            pass
                        self._remote_react("✅")
                    else:
                        pre = await self.agent.aget_state(config)
                        pre_count = len(pre.values.get("messages", [])) if pre else 0
                        # A compact status line edits in place to show live tool/
                        # subagent activity (condensed counts) — SEPARATE from the
                        # answer, which is sent as a fresh chat message below.
                        if getattr(msg, "edit_fn", None) is not None:
                            from novacode_cli.remote.status import RemoteStatusLine

                            self._remote_status = RemoteStatusLine(msg.edit_fn)
                            self._remote_status.start()
                        # While the turn runs, drain further remote messages as
                        # live steers so the user can "add to the previous prompt".
                        steer_drain = asyncio.create_task(self._remote_steer_drain(queue))
                        try:
                            if isinstance(prompt_text, str):
                                await self._stream_prompt(prompt_text)
                            elif callable(prompt_text):
                                import inspect
                                if inspect.iscoroutinefunction(prompt_text):
                                    await prompt_text()
                                else:
                                    res = prompt_text()
                                    if inspect.iscoroutine(res):
                                        await res
                        finally:
                            steer_drain.cancel()
                            try:
                                await steer_drain
                            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                                pass
                        # Settle the status line to a done-summary, then send the
                        # answer as its own message (no footer — the status carries
                        # the tool/subagent summary).
                        if self._remote_status is not None:
                            await self._remote_status.finalize()
                        post = await self.agent.aget_state(config)
                        reply = _extract_response(post, pre_count) or "✅ Task completed."
                        try:
                            await msg.reply_fn(reply)
                        except Exception:  # noqa: BLE001
                            pass
                        self._remote_react("✅")
                finally:
                    self._remote_msg = None
                    self._remote_status = None
                    if typing_task is not None:
                        typing_task.cancel()
                        try:
                            await typing_task
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
                    self.session_state.auto_approve = prev_auto
            except asyncio.CancelledError:
                self._log(Text("Remote turn cancelled.", style="yellow"))
            except Exception as ex:  # noqa: BLE001
                self._log(Text(f"Remote error: {ex}", style="red"))
                self._remote_react("❌", msg)
            finally:
                queue.task_done()

    # Slash commands that require the interactive local TUI (modals, pickers,
    # launchers) and can't be driven over a chat bridge.
    _REMOTE_LOCAL_ONLY = frozenset(
        {
            "sessions",
            "mcp",
            "theme",
            "remote",
            "agents",
            "skills",
            "init",
            "trello",
            "browser-use",
            "hooks",
            "servers",
            "files",
            "images",
            "vision",
            "kill",
            "restore",
            "reindex",
            "plan",
            "steer",
            "notifications",
            "trace",
            "log",
            "tests",
            "fast",
        }
    )

    def _remote_help_text(self) -> str:
        """Plain-text help listing the commands that work over a remote chat."""
        return (
            "Remote commands:\n"
            "• /help — this list\n"
            "• /context (/tokens, /cost) — context window usage\n"
            "• /model — show the current model\n"
            "• /clear — reset the conversation\n"
            "• /compact — summarize & free up context\n"
            "• /save — save the session\n"
            "• /verbose — toggle settings\n"
            "• /ingest <path> — ingest a raw source into the wiki\n"
            "• /ask <question> — ask with wiki context\n"
            "• /wiki — show Obsidian LLM Wiki browser\n"
            "• /research <query> — launch multi-agent research swarm\n"
            "• /ralph <task> — run autonomously (looping mode)\n"
            "• /evolution — view self-evolution logs\n"
            "• /dream — consolidate memory from previous sessions\n"
            "• /<skill> (e.g. /graphify) — run a skill\n"
            "Anything without a leading / is sent to the agent. Interactive "
            "panels (/model picker, /sessions, /mcp, /theme…) are local-only."
        )

    async def _remote_slash(self, text: str) -> "tuple[str | None, Any]":
        """Route a slash command arriving from Discord/Telegram.

        Returns ``(reply_text, stream_prompt_or_callable)``:
          * ``(str, None)`` — send this text back; no agent turn.
          * ``(None, str)`` — stream this prompt as an agent turn (skills).
          * ``(None, callable)`` — execute this coroutine/callable in the turn context.
        Interactive / local-only commands return an explanatory reply.
        """
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("help", "?", "commands"):
            return self._remote_help_text(), None
        if cmd in ("tokens", "context", "cost"):
            try:
                return self._token_text().plain, None
            except Exception:  # noqa: BLE001
                return "(token usage unavailable)", None
        if cmd == "model":
            return (
                f"Current model: {self.model_name}\n"
                "Switching models is only available in the local TUI (/model).",
                None,
            )
        if cmd == "verbose":
            new = self.session_state.toggle_verbose()
            return f"Verbose mode {'on' if new else 'off'}.", None
        if cmd == "clear":
            await self._run_clear()
            return "✅ Conversation cleared.", None
        if cmd == "compact":
            await self._run_compact("")
            return "✅ Context compacted.", None
        if cmd == "save":
            await self._run_save()
            return "✅ Session saved.", None
        if cmd == "steer":
            text = arg.strip()
            if text.lower() in ("clear", "reset", "off"):
                self._clear_live_steers()
                return "✅ Steering cleared.", None
            if not text:
                return (
                    "Usage: /steer <instruction> — extra guidance the agent "
                    "follows on its next step (and a running turn picks up now).",
                    None,
                )
            self._add_live_steer(text)
            return f"↗ Steering added: {text}", None

        if cmd == "ingest":
            from novacode_cli.wiki.ingest import IngestEngine

            try:
                engine = IngestEngine()
                if not arg:
                    # Auto-discover the local wiki's Clipping/ + raw/ contents.
                    sources = engine.list_raw_sources()
                    if sources:
                        listing = "\n".join(f"  • {s}" for s in sources)
                        return (
                            "Usage: /ingest <path> (filename found anywhere in "
                            f"Clipping/ or raw/)\nAvailable sources:\n{listing}",
                            None,
                        )
                    return (
                        "No sources yet — save web clips into "
                        f"{engine._mgr.root / 'Clippings'} first.",
                        None,
                    )
                # Resolve the source (Clipping/ or raw/), then stream as a turn.
                source_full = engine.resolve_source(arg)
                rel = source_full.relative_to(engine._mgr.root).as_posix()
                source_content = source_full.read_text(encoding="utf-8")
                prompt = (
                    "Please analyze this source and create a wiki page at "
                    "/.nova/wiki/ for it.\n\n"
                    f"Source ({rel}):\n```\n{source_content[:8000]}\n```"
                )
                return None, prompt
            except (FileNotFoundError, ValueError) as ex:
                return f"Error: {ex}", None
            except Exception as ex:  # noqa: BLE001
                return f"/ingest error: {ex}", None

        if cmd == "ask":
            if not arg:
                return "Usage: /ask <question>", None
            # Search wiki and prepend context
            from novacode_cli.wiki.ask import WikiAskEngine

            try:
                engine = WikiAskEngine()
                prompt = await engine.build_prompt(arg)
                return None, prompt
            except Exception as ex:  # noqa: BLE001
                return f"/ask error: {ex}", None

        if cmd == "research":
            from novacode_cli.commands.research_handler import handle_research_command
            if not arg:
                with _rich_console.capture() as cap:
                    await handle_research_command(
                        self.agent, self.session_state, self.token_tracker, cmd_args=None
                    )
                out = Text.from_ansi(cap.get()).plain.strip()
                return out, None

            from novacode_cli.commands.research_handler import _parse_args, _MODE_AGENTS, _MODE_DESCRIPTIONS
            mode, query, agent_count, fast_mode = _parse_args(arg)
            if not query:
                return f"Error: no research query provided.\nUsage: /research {mode} <your question>", None

            async def run_res(msg_obj=self._remote_msg):
                self._log(
                    Text(
                        f"📡 Remote ({msg_obj.platform.value if msg_obj else 'Remote'}) triggered research swarm: {query}",
                        style="bold cyan"
                    )
                )
                base_agents = _MODE_AGENTS[mode]
                agents = (base_agents * ((agent_count // len(base_agents)) + 1))[:agent_count]
                base_dir = Path(".nova") / "research"
                try:
                    base_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass

                conversation_context = ""
                try:
                    from novacode_cli.context import ContextManager
                    conversation_context = await ContextManager().digest(
                        self.agent, self.session_state.thread_id
                    )
                except Exception:
                    pass

                prompt = render_template(
                    "research_swarm.jinja",
                    research_query=query,
                    mode=mode,
                    mode_description=_MODE_DESCRIPTIONS[mode],
                    agent_count=agent_count,
                    agents=agents,
                    base_dir=base_dir.as_posix(),
                    fast_mode=fast_mode,
                    conversation_context=conversation_context,
                )

                reply_msg = f"🔬 Starting research swarm (mode: {mode}, agents: {agent_count})..."
                if fast_mode:
                    reply_msg += " (fast mode)"
                if msg_obj is not None:
                    try:
                        await msg_obj.reply_fn(reply_msg)
                    except Exception:
                        pass
                await self._tui_execute_fn(
                    prompt,
                    self.agent,
                    "dora",
                    self.session_state,
                    self.token_tracker,
                    self.backend,
                )
            return None, run_res

        if cmd == "evolution":
            async def run_evo(msg_obj=self._remote_msg):
                lines = []
                def _emit(m=""):
                    if m: lines.append(m)
                from novacode_cli.commands.evolution_command import handle_evolution_command
                try:
                    await handle_evolution_command(emit=_emit)
                except ImportError:
                    from novacode_cli.commands.evolution_handler import handle_evolution_command
                    await handle_evolution_command(emit=_emit)
                text_out = "\n".join(lines)
                plain = Text.from_markup(text_out).plain.strip()
                if msg_obj is not None:
                    try:
                        await msg_obj.reply_fn(plain or "No evolution logs yet.")
                    except Exception:
                        pass
            return None, run_evo

        if cmd == "dream":
            async def run_dream(msg_obj=self._remote_msg):
                status_lines = []
                def _emit(m=""):
                    if m: status_lines.append(m)
                from novacode_cli.commands.dream_handler import handle_dream_command
                result = await handle_dream_command(self.session_state, self.assistant_id, emit=_emit)
                if status_lines and msg_obj is not None:
                    plain = Text.from_markup("\n".join(status_lines)).plain.strip()
                    try:
                        await msg_obj.reply_fn(plain)
                    except Exception:
                        pass
                if isinstance(result, str) and result.strip():
                    await self._stream_prompt(result)
            return None, run_dream

        if cmd == "ralph":
            # For --status, it's fast, so return directly
            if arg.strip() == "--status":
                lines = []
                def _emit(m=""):
                    if m: lines.append(m)
                from novacode_cli.commands.ralph_handler import handle_ralph_status
                await handle_ralph_status(self.session_state, emit=_emit)
                text_out = "\n".join(lines)
                plain = Text.from_markup(text_out).plain
                return plain, None

            # For running ralph task, run it in the turn context
            async def run_ralph(msg_obj=self._remote_msg):
                self._log(
                    Text(
                        f"📡 Remote ({msg_obj.platform.value if msg_obj else 'Remote'}) triggered autonomous Ralph run: {arg or '(resume)'}",
                        style="bold cyan"
                    )
                )
                # We want to forward ralph's emit events to both the local TUI and the remote user
                async def _emit_remote(message: str = "") -> None:
                    if not message:
                        return
                    try:
                        renderable = Text.from_markup(message)
                    except Exception:
                        renderable = Text(message)
                    
                    # Log to TUI locally
                    self._log(renderable)
                    
                    # Reply to remote user
                    plain = renderable.plain.strip()
                    if plain and msg_obj is not None:
                        try:
                            await msg_obj.reply_fn(plain)
                        except Exception:
                            pass

                from novacode_cli.commands.ralph_handler import handle_ralph_command
                parts = text.split(maxsplit=1)
                ralph_args = parts[1].strip() if len(parts) > 1 else ""

                await handle_ralph_command(
                    self.agent,
                    self.session_state,
                    self.assistant_id,
                    self.token_tracker,
                    ralph_args or None,
                    execute_fn=self._tui_execute_fn,
                    emit=_emit_remote,
                )
            return None, run_ralph

        if cmd in self._REMOTE_LOCAL_ONLY:
            return f"/{cmd} is only available in the local TUI.", None

        # Otherwise treat it as a skill: /skill:<name> or a bare /<name>.
        skill_name = cmd[len("skill:") :] if cmd.startswith("skill:") else cmd
        if skill_name:
            try:
                from novacode_cli.commands.skill_invoke import _try_skill_invocation

                skill = await _try_skill_invocation(
                    skill_name, arg or None, self.session_state, self.assistant_id
                )
            except Exception as ex:  # noqa: BLE001
                return f"❌ /{cmd} failed: {ex}", None
            if skill is not None:
                return None, skill.prompt

        return (
            f"Unknown command: /{cmd}. Send /help for what works over remote.",
            None,
        )

    async def _run_bash(self, text: str) -> None:
        """Run a ``!`` shell command in the system terminal by suspending the TUI app."""
        cmd = text[1:].strip()
        if not cmd:
            return

        import os
        import sys
        import subprocess
        from pathlib import Path
        from novacode_cli.config.config import settings

        # Log the command in the transcript
        self._log(Text(f"Executing: !{cmd}", style="bold yellow"))

        # Suspend Textual and run the command directly on the system terminal
        from textual.app import SuspendNotSupported

        try:
            with self.suspend():
                cwd = settings.project_root or Path.cwd()
                if sys.stdin.isatty():
                    print(f"\n--- Executing command in {cwd.name} ---")
                    print(f"> {cmd}\n")
                try:
                    res = subprocess.run(cmd, shell=True, cwd=cwd)
                    exit_code = res.returncode
                except Exception as ex:  # noqa: BLE001
                    exit_code = -1
                    print(f"Error executing command: {ex}")

                if sys.stdin.isatty():
                    print("\n--- Command finished. Press Enter to return to TUI ---")
                    try:
                        input()
                    except (KeyboardInterrupt, EOFError):
                        pass
        except SuspendNotSupported:
            # Fallback for non-interactive/headless test environments where suspend is not supported
            cwd = settings.project_root or Path.cwd()
            try:
                res = subprocess.run(
                    cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                exit_code = res.returncode
            except Exception:  # noqa: BLE001
                exit_code = -1

        if exit_code == 0:
            self._log(Text("✓ Command finished successfully.", style="green"))
        else:
            self._log(Text(f"❌ Command exited with code {exit_code}.", style="red"))

    # -- background shell (ctrl+b) --------------------------------------------

    @work(group="bgshell")
    async def _bg_shell_worker(self, cmd: str, job_id: int) -> None:
        """Run *cmd* as a non-blocking background subprocess.

        Each call spawns an independent worker in group ``"bgshell"`` (no
        ``exclusive=True``) so multiple Ctrl+B jobs run in true parallel.
        Output streams line-by-line into a ``RichLog`` inside a ``Collapsible``
        card.  When the process exits the card title flips to ✓/✗ and the
        process is deregistered from ProcessManager.
        """
        import os

        from novacode_cli.config.config import settings
        from novacode_cli.process_manager import ProcessInfo, ProcessManager, ProcessStatus

        cwd = settings.project_root or Path.cwd()
        short = cmd if len(cmd) <= 50 else cmd[:47] + "…"

        # Build the card up-front so output starts streaming immediately.
        log_widget = RichLog(classes="bgshell-log", highlight=True, markup=True)
        body = Vertical(log_widget)
        card = Collapsible(body, title=f"⚙ bg[{job_id}]: {short}  [running]", collapsed=False)
        card.add_class("bgshell-card")
        self._close_tool_group()
        await self._transcript().mount(card)
        self._prune_transcript()
        self._scroll_end()

        # Spawn the subprocess with merged stdout+stderr so the log shows both.
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
                env=os.environ.copy(),
            )
        except Exception as ex:  # noqa: BLE001
            log_widget.write(f"[bold red]Failed to start: {ex}[/bold red]")
            card.title = f"✗ bg[{job_id}]: {short}  [failed to start]"
            return

        # Register with ProcessManager so `/kill bg-<n>` or `/kill <pid>` works.
        info = ProcessInfo(
            pid=process.pid,
            name=f"bg-{job_id}",
            command=cmd,
            status=ProcessStatus.RUNNING,
            working_dir=str(cwd),
            _process=process,
        )
        ProcessManager.get_instance().register_process(info)

        # Stream output line-by-line into the RichLog.
        assert process.stdout is not None  # noqa: S101  — PIPE guarantees this
        try:
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                log_widget.write(line)
                log_widget.scroll_end(animate=False)
        except asyncio.CancelledError:
            process.terminate()
            card.title = f"✗ bg[{job_id}]: {short}  [cancelled]"
            info.status = ProcessStatus.STOPPED
            return

        await process.wait()
        exit_code = process.returncode or 0

        # Update card title and ProcessManager status.
        if exit_code == 0:
            card.title = f"✓ bg[{job_id}]: {short}  [exit 0]"
            card.add_class("bgshell-done")
            info.status = ProcessStatus.STOPPED
        else:
            card.title = f"✗ bg[{job_id}]: {short}  [exit {exit_code}]"
            card.add_class("bgshell-failed")
            info.status = ProcessStatus.FAILED
            log_widget.write(f"[bold red]Exited with code {exit_code}[/bold red]")

        # Collapse finished cards automatically so they don't crowd the transcript.
        card.collapsed = True

    # -- background agent turn (ctrl+b, non-! input) --------------------------

    @work(group="bgagent")
    async def _bg_agent_worker(self, prompt: str, job_id: int) -> None:
        """Run a full agent turn in the background without blocking the main input.

        Uses a fresh thread_id so the background conversation is isolated from the
        main session. All tool approvals are auto-approved (the user opted in by
        pressing Ctrl+B), so the turn never blocks waiting for a decision.
        """
        import uuid

        from novacode_cli.agent_stream import run_agent_stream
        from novacode_cli.ui_events import (
            AssistantMessage,
            Done,
            Error,
            InterruptRequest,
            ToolCall,
            ToolResult,
        )

        thread_id = f"bg-{uuid.uuid4().hex[:12]}"
        p_short = prompt if len(prompt) <= 50 else prompt[:47] + "…"

        # Minimal proxy session state — only the fields iterate_agent_events reads.
        # auto_approve=True makes evaluate_tool_actions return allow for every tool
        # and auto-resolves plan interrupts, so no InterruptRequest is yielded for
        # either. Only ask_user_question (kind="question") can still interrupt; we
        # resolve those below with a canned answer.
        class _BgSession:
            def __init__(self_inner, real_ss: Any) -> None:  # noqa: N805
                self_inner.thread_id = thread_id
                self_inner.auto_approve = True
                self_inner.plan_mode_enabled = False
                self_inner.plan_agent = None
                self_inner.plan_content: Any = None
                self_inner.active_goal: str | None = getattr(real_ss, "active_goal", None)

            def add_notification(self_inner, **_kw: Any) -> None:  # noqa: N805
                return None

            def dismiss_notification(self_inner, _nid: Any) -> None:  # noqa: N805
                pass

            def register_pending_approval(self_inner, _iid: Any, _fut: Any) -> None:  # noqa: N805
                pass

            def set_approved_plan(self_inner, _plan: Any) -> None:  # noqa: N805
                pass

            def clear_plan_agent(self_inner) -> None:  # noqa: N805
                pass

        bg_session = _BgSession(self.session_state)
        ag, backend = self._active_agent()

        log_widget = RichLog(classes="bgshell-log", highlight=True, markup=True)
        card = Collapsible(
            Vertical(log_widget),
            title=f"⟳ bg[{job_id}]: {p_short}  [running]",
            collapsed=False,
        )
        card.add_class("bgagent-card")
        self._close_tool_group()
        await self._transcript().mount(card)
        self._prune_transcript()
        self._scroll_end()

        try:
            async for e in run_agent_stream(
                prompt,
                ag,
                self.assistant_id,
                bg_session,
                backend=backend,
                seen_message_ids=set(),
            ):
                if isinstance(e, AssistantMessage) and e.text:
                    for line in e.text.splitlines():
                        log_widget.write(line)
                    log_widget.scroll_end(animate=False)
                elif isinstance(e, ToolCall):
                    log_widget.write(f"[dim]{e.icon} {e.name}[/dim]")
                    log_widget.scroll_end(animate=False)
                elif isinstance(e, ToolResult) and e.is_error:
                    log_widget.write(f"[red]✗ {e.preview}[/red]")
                    log_widget.scroll_end(animate=False)
                elif isinstance(e, InterruptRequest):
                    # Only ask_user_question reaches here (tools and plans are
                    # auto-approved via auto_approve=True on the session).
                    # Provide a canned answer so the turn continues unblocked.
                    try:
                        if e.kind == "question":
                            e.future.set_result({"answer": "Please continue autonomously."})
                        else:
                            from novacode_cli.core.agent_loop import default_interrupt_response
                            e.future.set_result(default_interrupt_response(e.kind))
                    except Exception:  # noqa: BLE001
                        pass
                elif isinstance(e, (Done, Error)):
                    break
        except asyncio.CancelledError:
            card.title = f"✗ bg[{job_id}]: {p_short}  [cancelled]"
            return
        except Exception as ex:  # noqa: BLE001
            log_widget.write(f"[bold red]Error: {ex}[/bold red]")
            card.title = f"✗ bg[{job_id}]: {p_short}  [error]"
            card.add_class("bgagent-failed")
            card.collapsed = True
            return

        card.title = f"✓ bg[{job_id}]: {p_short}  [done]"
        card.add_class("bgagent-done")
        card.collapsed = True

    async def _run_slash(self, text: str) -> None:
        """Handle the TUI-native slash command subset."""
        cmd = text[1:].split(maxsplit=1)[0].lower() if len(text) > 1 else ""
        if cmd.startswith("skill:"):
            # /skill:<name> — resolve + render natively, then stream the prompt.
            await self._run_skill(text)
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
            await self.push_screen_wait(
                RemoteScreen(
                    self.session_state,
                    sandbox_id=self._sandbox_id,
                    sandbox_type=self._sandbox_type,
                )
            )
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
        elif cmd == "copy":
            await self._run_copy(text)
        elif cmd == "steer":
            await self._run_steer(text)
        elif cmd == "notifications":
            await self._run_notifications(text)
        elif cmd == "research":
            await self._run_research(text)
        elif cmd == "ingest":
            await self._run_ingest(text)
        elif cmd == "ask":
            await self._run_ask(text)
        elif cmd == "file":
            await self._run_file(text)
        elif cmd == "wiki":
            await self._run_wiki()
        elif cmd == "dream":
            await self._run_dream()
        elif cmd == "evolution":
            await self._run_evolution()
        elif cmd == "reindex":
            await self._run_reindex()
        elif cmd == "images":
            await self._run_images(text)
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
            parts = text.split(maxsplit=1)
            args = parts[1].strip() if len(parts) > 1 else ""
            await self.push_screen_wait(
                RalphScreen(
                    session_state=self.session_state,
                    agent=self.agent,
                    assistant_id=self.assistant_id,
                    token_tracker=self.token_tracker,
                    args=args,
                    execute_fn=self._tui_execute_fn,
                )
            )
        elif cmd == "trello":
            await self._run_trello(text)
        elif cmd == "create":
            await self._run_create(text)
        elif cmd == "council":
            await self._run_chat(text)
        elif cmd == "effort":
            await self._run_effort(text)
        elif cmd == "goal":
            await self._run_goal(text)
        elif cmd == "btw":
            await self._run_btw(text)
        elif cmd in ("plugins", "plugin"):
            await self.push_screen_wait(PluginsScreen())
            # Reload plugin commands so newly-enabled command plugins work this
            # session (middleware/subagents still need a restart, as noted).
            self._load_plugin_commands()
        elif cmd in _PASSTHROUGH_SLASH:
            await self._passthrough_command(text)
        # A slash command contributed by an enabled plugin.
        elif await self._run_plugin_command(text):
            pass
        # A bare /<name> may be a skill (e.g. /graphify) — resolve it natively
        # before reporting the command as unavailable.
        elif await self._run_skill(text):
            pass
        else:
            self._log(
                Text(
                    f"/{cmd} isn't available in --tui yet. "
                    "Use --legacy-ui for the full command set.",
                    style="yellow",
                )
            )

    def _load_plugin_commands(self) -> None:
        """Discover slash commands from enabled plugins and register them.

        Populates ``self._plugin_commands`` (name → async handler) and adds the
        names to the autocomplete list. Built-ins are matched first in
        :meth:`_run_slash`, so a plugin can't shadow a core command.
        """
        try:
            from novacode_cli.plugins.loader import (
                collect_plugin_commands,
                discover_enabled_plugins,
            )

            cmds = collect_plugin_commands(discover_enabled_plugins())  # type: ignore
            self._plugin_commands = {
                name: c["handler"] for name, c in cmds.items() if c.get("handler")
            }
            for name in self._plugin_commands:
                slash = f"/{name}"
                if slash not in _TUI_SLASH_COMMANDS:
                    _TUI_SLASH_COMMANDS.append(slash)
        except Exception:  # noqa: BLE001 — a bad plugin must not break startup
            self._plugin_commands = {}

    async def _run_plugin_command(self, text: str) -> bool:
        """Dispatch a plugin-contributed slash command. Returns True if handled.

        Built-ins are matched earlier in :meth:`_run_slash`, so they always win.
        The plugin handler is ``async (args) -> str``; its returned text is logged.
        """
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        handler = self._plugin_commands.get(cmd)
        if handler is None:
            return False
        try:
            result = await handler(args)
            if result:
                self._log(Text(str(result)))
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Plugin command /{cmd} failed: {ex}", style="red"))
        return True

    async def _run_copy(self, text: str) -> None:
        """Copy agent output to the clipboard.

        ``/copy``      — copy the last Nova response.
        ``/copy all``  — copy the whole conversation (You/Nova turns).
        """
        parts = text[1:].split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        msgs = list(self._transcript().query(ChatMessage))
        if not msgs:
            self._log(Text("Nothing to copy yet.", style="dim"))
            return

        if arg == "all":
            blocks: list[str] = []
            for m in msgs:
                body = (m.raw_text or "").strip()
                if not body:
                    continue
                who = "You" if m.has_class("user") else "Nova"
                blocks.append(f"## {who}\n{body}")
            payload = "\n\n".join(blocks)
            label = "conversation"
        else:
            nova = [m for m in msgs if m.has_class("nova")]
            if not nova:
                self._log(Text("No agent response to copy yet.", style="dim"))
                return
            payload = (nova[-1].raw_text or "").strip()
            label = "last response"

        if not payload:
            self._log(Text("Nothing to copy.", style="dim"))
            return
        try:
            self.copy_to_clipboard(payload)
            self._log(
                Text(
                    f"📋 Copied {label} ({len(payload):,} chars) to clipboard",
                    style="dim",
                )
            )
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Copy failed: {ex}", style="red"))

    async def _run_skill(self, text: str) -> bool:
        """Resolve a ``/skill:<name>`` (or bare ``/<name>``) and run it natively.

        Renders the "⚡ Invoking skill" block as native widgets (the resolver is
        presentation-free) and streams the skill prompt. Returns ``True`` when a
        skill matched, ``False`` otherwise so the caller can fall back to the
        "command unavailable" notice.
        """
        raw = text[1:]
        if raw.lower().startswith("skill:"):
            raw = raw[len("skill:") :]
        parts = raw.split(maxsplit=1)
        name = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else None
        if not name:
            self._log(Text("Usage: /skill:<name> [args]", style="yellow"))
            return True

        from novacode_cli.commands.skill_invoke import _try_skill_invocation

        try:
            skill = await _try_skill_invocation(name, args, self.session_state, self.assistant_id)
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"/skill:{name} failed: {ex}", style="red"))
            return True
        if skill is None:
            return False

        t = Text()
        t.append(f"⚡ Invoking skill: {skill.name}", style="bold #7aa2f7")
        if skill.description:
            t.append(f"\n  {skill.description}", style="dim")
        t.append(f"\n  Source: {skill.source}", style="dim")
        if skill.args:
            t.append(f"\n  Arguments: {skill.args}", style="dim")
        if skill.supporting_files:
            t.append(
                f"\n  Supporting files: {', '.join(skill.supporting_files)}",
                style="dim",
            )
        self._log(t)
        await self._stream_prompt(skill.prompt)
        return True

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
                    sandbox_id=self._sandbox_id,
                    sandbox_type=self._sandbox_type,
                )
            out = cap.get()
            if out.strip():
                self._log(Text.from_ansi(out))
            # Sync active TUI agent/backend in case model was switched dynamically
            if self.session_state is not None:
                self.agent = self.session_state.agent
                self.backend = self.session_state.backend
                model = getattr(self.session_state, "model", None)
                if model:
                    self.model_name = getattr(model, "model_name", None) or getattr(model, "model", "unknown")
                    if self.token_tracker is not None:
                        try:
                            self.token_tracker.set_model(self.model_name)
                        except Exception:  # noqa: BLE001
                            pass
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
                self._log(Text(f"{preset['name']} requires an API key.", style="red"))
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

    def _build_init_agent(self) -> tuple[Any, Any]:
        """Build a dedicated **no-HITL, LOCAL-filesystem** agent for /init.

        Two deliberate deviations from the session agent:

        1. ``auto_approve=True`` → ``interrupt_on={}``: the main agent AND every
           subagent (incl. deepagents' auto-injected general-purpose one) run
           tools without approval interrupts. A subagent's HITL interrupt is
           unresolvable (it bubbles out of `task`'s ainvoke as a GraphInterrupt),
           so this is required for /init's `task` workers to run unattended.

        2. ``sandbox=None`` → a LOCAL FilesystemBackend rooted at the project
           (virtual_mode). /init is inherently a local operation: graphify reads
           the local files, and the graph fragments must be written to the local
           ``.nova/graph_fragments/`` so `_read_and_merge_fragments` can read
           them back. Running through the session's *sandbox* backend broke this
           two ways — `/`-prefixed virtual paths resolve to the container root
           (project is at ``/workspace`` → every read_file 404'd), and any
           fragment write would land inside the sandbox, invisible to the local
           merge step. Forcing the local backend fixes both.

        Reuses the session model/tools/store. Raises if no model is configured.
        """
        from novacode_cli.agents.core_agent import create_agent_with_config

        ss = self.session_state
        model = getattr(ss, "_model", None)
        if model is None:
            raise RuntimeError("no model configured")
        return create_agent_with_config(
            model=model,
            assistant_id=getattr(ss, "_assistant_id", None) or self.assistant_id,
            tools=getattr(ss, "_tools", None) or [],
            sandbox=None,  # ← LOCAL filesystem (see docstring #2)
            sandbox_type=None,
            store=getattr(ss, "_store", None),
            checkpointer=getattr(ss, "_checkpointer", None),
            auto_approve=True,  # ← no HITL anywhere (see docstring #1)
            is_continuation=True,
        )

    async def _run_init(self, text: str) -> None:
        """Generate NOVA.md: delegates orchestration to :class:`InitOrchestrator`.

        TUI-specific setup (step tracker widget, agent-building, quiet console,
        turn status) stays here; the pipeline dispatch and fallback routing
        live in the orchestrator.
        """
        from pathlib import Path

        from novacode_cli.commands.init_handler import InitFlags, InitOrchestrator
        from novacode_cli.config.config import settings

        cmd_args = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else None
        project_root = settings.project_root
        if not project_root:
            self._log(Text("/init requires a project with a .git directory.", style="yellow"))
            return
        nova_dir = Path(project_root) / ".nova"
        nova_md_path = nova_dir / "NOVA.md"
        self._log(Text(f"🔍 Initializing NOVA.md for {Path(project_root).name}…", style="bold"))

        # ── TUI-native step tracker setup (renderer concern) ──────────
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
        # Shimmer effect during init
        shimmer_bar(self._init_widget)
        self._init_render_steps()

        # Quiet sink for graphify's internal Rich output (detection/extraction
        # panels, tree-sitter Progress). We surface the real stats as native
        # step detail via the pipeline's emit events instead.
        import io as _io

        from rich.console import Console as _Console

        quiet_console = _Console(
            file=_io.StringIO(),
            force_terminal=False,
            force_interactive=False,
            width=100,
        )

        self._turn_active = True
        self._turn_start = time.monotonic()
        self._set_status("indexing codebase…")
        _prev_auto = self.session_state.auto_approve
        self.session_state.auto_approve = True

        # Build a dedicated no-HITL agent for /init subagents.
        init_agent = init_backend = None
        try:
            init_agent, init_backend = self._build_init_agent()
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"(/init: using shared agent — {ex})", style="dim"))
        self._init_agent = init_agent
        self._init_backend = init_backend

        try:
            renderer = TuiInitRenderer(self)
            orchestrator = InitOrchestrator(
                project_root=Path(project_root),
                nova_dir=nova_dir,
                nova_md_path=nova_md_path,
                agents_md_path=nova_dir / "AGENTS.md",
                flags=InitFlags(cmd_args),
                renderer=renderer,
                agent=init_agent or self.agent,
                session_state=self.session_state,
                assistant_id=self.assistant_id,
                token_tracker=self.token_tracker,
                session_id=getattr(self.session_state, "session_id", ""),
                progress_console=quiet_console,
                execute_fn=self._tui_quiet_execute_fn,
                use_process_pool=True,
            )
            await orchestrator.run()
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"/init failed: {ex}", style="red"))
        finally:
            self._init_agent = None
            self._init_backend = None
            self.session_state.auto_approve = _prev_auto
            self._turn_active = False
            self._set_status("ready")
            if self._init_widget is not None:
                try:
                    await self._init_widget.remove()
                except Exception:  # noqa: BLE001
                    pass
            self._init_widget = None
            self._init_steps = []

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
                t.append(
                    "  (none — make a request with tracing enabled first)\n",
                    style="dim",
                )
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
            t.append("  set LANGSMITH_API_KEY and LANGSMITH_TRACING=true\n", style="dim")
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
        """Route to the plan agent while plan mode is active, else the main agent.

        During /init a dedicated no-HITL agent (``_init_agent``) takes priority so
        the pipeline's `task` subagents can read/write files unattended — the
        shared session agent gates those tools and a subagent's interrupt is
        unresolvable (it bubbles out of `task`'s ainvoke as a GraphInterrupt).
        """
        init_agent = getattr(self, "_init_agent", None)
        if init_agent is not None:
            return init_agent, getattr(self, "_init_backend", None)
        if getattr(self.session_state, "plan_mode_enabled", False) and (
            getattr(self.session_state, "plan_agent", None) is not None
        ):
            return self.session_state.plan_agent, getattr(self.session_state, "plan_backend", None)
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
                assistant_id=getattr(self.session_state, "_assistant_id", None) or "nova",
                tools=[ask_user_question, enter_plan_mode, exit_plan_mode],
                steering_instructions=getattr(self.session_state, "steering_instructions", None),
                auto_approve=getattr(self.session_state, "auto_approve", False),
                # Share the core agent's checkpointer + store so plan mode sees
                # the ongoing conversation (same thread_id) and persists.
                checkpointer=getattr(self.session_state, "_checkpointer", None),
                store=getattr(self.session_state, "_store", None),
            )
            self.session_state.plan_mode_enabled = True
            self._update_mode_badge()
            self.session_state.plan_content = None
            self.session_state.approved_plan_content = None
            if not getattr(self.session_state, "auto_approve", False):
                self.session_state.auto_approve = False
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
                "▌ Plan mode is Active",
                style="cyan",
            )
        )
        if args:
            await self._stream_prompt(args)
            await self._maybe_run_approved_plan()

    async def _run_goal(self, text: str) -> None:
        """Set, show, or clear the active goal for autonomous goal-mode execution.

        Usage:
          /goal <description>   — set the goal and kick off the agent
          /goal status          — show the current goal
          /goal clear           — remove the active goal
        """
        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        low = args.lower()

        if low == "status":
            goal = getattr(self.session_state, "active_goal", None)
            if goal:
                t = Text()
                t.append("🎯 Active goal\n", style="bold #e0af68")
                t.append(goal, style="italic")
                self._log(t)
            else:
                self._log(Text("No active goal. Use /goal <description> to set one.", style="dim"))
            return

        if low in ("clear", "off", "done", "stop"):
            self.session_state.active_goal = None
            self._update_mode_badge()
            self._log(Text("Goal cleared.", style="yellow"))
            return

        if not args:
            self._log(
                Text(
                    "Usage: /goal <description>  ·  /goal status  ·  /goal clear",
                    style="dim",
                )
            )
            return

        self.session_state.active_goal = args
        self._update_mode_badge()

        t = Text()
        t.append("🎯 Goal set\n", style="bold #e0af68")
        t.append(args, style="italic")
        self._log(t)

        kick_off = (
            f"[GOAL] {args}\n\n"
            "You are now in goal mode. Work autonomously to achieve the goal above.\n"
            "1. Analyse what is needed and form a clear execution plan.\n"
            "2. Execute the plan step by step, using your tools as needed.\n"
            "3. After each step verify your progress against the goal.\n"
            "4. When the goal is fully and verifiably achieved, say **GOAL ACHIEVED** "
            "and summarise what was done.\n"
            "Start now."
        )
        await self._stream_prompt(kick_off)

    # -- btw (concurrent side-channel question with web search) ----------------

    def _get_btw_agent(self) -> Any:
        """Return the cached btw agent, creating it on first call."""
        if self._btw_agent is None:
            from novacode_cli.agents.btw_agent import create_btw_agent
            from novacode_cli.config.model_create import create_model

            model = create_model()
            self._btw_agent, _ = create_btw_agent(model)
        return self._btw_agent

    async def _run_btw(self, text: str) -> None:
        """Dispatch a /btw side question — runs concurrently with the main agent."""
        import uuid

        parts = text.split(maxsplit=1)
        question = parts[1].strip() if len(parts) > 1 else ""

        if not question:
            self._log(Text("Usage: /btw <question>", style="dim"))
            return

        try:
            agent = self._get_btw_agent()
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"↩ btw: could not start web-search agent — {ex}", style="red"))
            return

        thread_id = f"btw-{uuid.uuid4().hex[:12]}"
        self._btw_worker(question, agent, thread_id)

    @work(group="btw")
    async def _btw_worker(self, question: str, agent: Any, thread_id: str) -> None:
        """Run the btw question on its own thread, concurrently with the main agent.

        Uses a dedicated ``group="btw"`` work group so it never blocks — or is
        blocked by — the main ``group="turn"`` agent. Multiple /btw calls queue
        within the "btw" group and run one at a time (sequential but not blocking
        the main UI).
        """
        from novacode_cli.agent_stream import run_agent_stream
        from novacode_cli.ui_events import AssistantMessage, Done, Error

        # Minimal session-state shim: only thread_id matters for the btw agent
        # (no checkpointer sharing, no goal/plan injection).
        class _BtwSession:
            def __init__(self) -> None:
                self.thread_id = thread_id
                self.active_goal: str | None = None
                self.plan_mode_enabled: bool = False
                self.auto_approve: bool = True

        btw_state = _BtwSession()

        q_short = question if len(question) <= 55 else question[:52] + "…"
        # Show a transient "btw thinking" note while the request is in flight.
        indicator = Static(
            Text(f"↩ btw: {q_short}…", style="dim italic"),
            classes="logline",
        )
        self._close_tool_group()
        await self._transcript().mount(indicator)
        self._scroll_end()

        answer_parts: list[str] = []
        try:
            async for e in run_agent_stream(
                question,
                agent,
                "btw-agent",
                btw_state,
                backend=None,
                seen_message_ids=set(),
            ):
                if isinstance(e, AssistantMessage):
                    answer_parts.append(e.text)
                elif isinstance(e, (Done, Error)):
                    break
                # ToolCall / ToolResult / StatusUpdate / TextDelta — silently
                # consumed; tool activity is invisible to the user by design.
        except asyncio.CancelledError:
            indicator.remove()
            return
        except Exception as ex:  # noqa: BLE001
            indicator.update(Text(f"↩ btw failed: {ex}", style="red"))
            return

        # Replace the "thinking" indicator with the finished answer card.
        answer = "\n\n".join(answer_parts).strip() or "(no response)"
        title_q = question if len(question) <= 50 else question[:47] + "…"
        body = Static(Markdown(answer), classes="btw-body")
        card = Collapsible(body, title=f"↩ btw: {title_q}", collapsed=False)
        card.add_class("btw-card")
        await indicator.remove()
        self._close_tool_group()
        await self._transcript().mount(card)
        self._prune_transcript()
        self._scroll_end()

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
                    # reset() clears the stale pre-compaction peak; recompute the
                    # breakdown from the actual post-compaction messages so ctx%
                    # is accurate immediately (not just after the next turn).
                    self.token_tracker.reset()
                    await self._update_context_breakdown()
                except Exception:  # noqa: BLE001
                    pass
                self._refresh_status()
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
        """Start a fresh chat — a total reset. Save the current conversation first.

        Clearing only the transcript would leave the agent's full history in the
        checkpointer (same thread_id), so it would still "remember" everything.
        A real reset assigns a new thread_id + session_id (fresh checkpointer
        state) AND clears every piece of carried-over context — todos, steering
        instructions, and plan mode — then drops per-conversation UI/tracking
        state and re-baselines token usage. Long-term memory, the Nova learning
        store, and the agent itself are preserved. The previous conversation is
        saved first so nothing is lost.
        """
        saved = self.session_manager is not None
        # Preserve the current conversation under its existing id, but mark it
        # cleared so neither --continue nor the --resume picker brings it back.
        await self._save_session(cleared=True)
        # Belt-and-suspenders: explicitly mark the session cleared even if the
        # save above early-returned (e.g. the checkpointer read timed out or had
        # no messages) but a prior /save had already written it as not-cleared.
        if self.session_manager is not None:
            try:
                self.session_manager.mark_cleared(self.session_state.session_id)
            except Exception:  # noqa: BLE001
                pass

        # Total reset of session/conversation state: new thread+session id
        # (empty checkpointer state), cleared todos / steering / plan mode.
        self.session_state.reset_conversation()

        # Re-own the live sandbox to the new session so resume reconnects to it
        # and the orphan sweep never reclaims a container the new chat still uses
        # (the container's Docker label is immutable; the registry is the source
        # of truth for ownership).
        if self._sandbox_id:
            try:
                from novacode_cli.integrations import sandbox_registry

                sandbox_registry.retie(self._sandbox_id, self.session_state.session_id)
            except Exception:  # noqa: BLE001
                pass

        # Drop per-conversation UI/tracking state.
        self._reset_streaming()
        self._clear_live_steers()
        self._seen.clear()
        self._restored_messages = []

        await self._transcript().remove_children()

        # Refresh the home screen: re-show the ASCII-art banner so /clear looks
        # like a fresh launch, not just an empty transcript.
        self._show_home_banner()

        # Re-baseline context/token accounting for the fresh chat.
        if self.token_tracker is not None:
            try:
                self.token_tracker.reset()
            except Exception:  # noqa: BLE001
                pass
        # Plan/steer were cleared above — refresh the input badge to match.
        self._update_mode_badge()
        self._refresh_status()

        self._log(
            Text(
                "✓ Started a new chat" + (" — previous conversation saved." if saved else "."),
                style="green",
            )
        )

    def _show_home_banner(self) -> None:
        """Render the home banner: the NOVA ASCII logo composited over the rain.

        The ASCII art (from ``config.get_responsive_ascii``, sized to the live
        terminal width) is stamped on top of the Matrix rain inside a single
        :class:`MatrixRain` widget, so the rain falls *behind* the logo and the
        logo is tinted with the active TUI theme color.
        """
        try:
            from novacode_cli.config.config import get_responsive_ascii

            try:
                width = self.size.width or None
            except Exception:  # noqa: BLE001
                width = None
            art = get_responsive_ascii(width=width)

            rain = MatrixRain(art=art, width=width)
            self._home_banner = rain
            self._transcript().mount(rain)
            self._prune_transcript()
        except Exception:  # noqa: BLE001
            self._home_banner = None

    def on_resize(self, event: events.Resize) -> None:
        """Reflow the home banner to the new terminal width.

        The rain grid width and the ASCII-art size variant are chosen from the
        terminal width, so on resize we re-pick the art variant and re-grid the
        rain. Only acts while the banner is still on screen (home screen).
        """
        rain = self._home_banner
        if not isinstance(rain, MatrixRain) or not rain.is_mounted:
            return
        try:
            from novacode_cli.config.config import get_responsive_ascii

            size = getattr(event, "size", None)
            width = (size.width if size else self.size.width) or None
            rain.reflow(get_responsive_ascii(width=width), width)
        except Exception:  # noqa: BLE001
            pass

    async def _run_effort(self, text: str) -> None:
        """Handle /effort natively: set reasoning effort level."""
        from novacode_cli.config.nova_config import NovaConfig
        from novacode_cli.config.model_create import create_model

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        nova_config = NovaConfig()
        current = nova_config.get("reasoning_effort", "off")

        if not args:
            t = Text()
            t.append("Reasoning Effort Configuration\n", style="bold")
            t.append(f"Current: ", style="dim")
            t.append(f"{current}\n", style="bold cyan")
            t.append("\nUsage: /effort <low|medium|high|off>\n", style="dim")
            self._log(t)
            return

        val = args.strip().lower()
        if val in ("none", "default"):
            val = "off"
        if val not in ("low", "medium", "high", "off"):
            self._log(Text(f"Invalid effort level '{args}'. Choose: low, medium, high, off", style="red"))
            return

        nova_config.set("reasoning_effort", val)
        t = Text(f"✓ Reasoning effort set to '{val}' and saved to config.\n", style="green")

        # Hot-swap the model
        if self.session_state is not None:
            try:
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
                t.append("✓ Model recreated with new reasoning effort dynamically!", style="green")
            except Exception as e:
                t.append(f"⚠ Could not recreate model dynamically: {e}", style="yellow")
                t.append("\nThe change will take effect on next model switch or restart.", style="dim")
        else:
            t.append("The change will take effect on restart.", style="dim")

        self._log(t)

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
        """Native /notifications: list, dismiss <id>, approve <id>, or clear."""
        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        ap = args.split(maxsplit=1)
        sub = ap[0].lower() if ap else ""
        ss = self.session_state

        if sub in ("clear", "reset"):
            # Dismiss all — reject any pending approvals.
            for n in list(ss.notifications):
                if n.action_id and not n.dismissed:
                    ss.resolve_approval(n.action_id, approve=False)
            n = ss.clear_notifications()
            self._log(Text(f"Cleared {n} notification(s).", style="green"))
            self._refresh_status()
            return
        if sub in ("dismiss", "rm", "ack") and len(ap) > 1:
            nid = ap[1].strip()
            n = self._find_notification(ss, nid)
            if n and n.action_id and not n.dismissed:
                ss.resolve_approval(n.action_id, approve=False)
                self._log(Text(f"Dismissed {nid} (rejected approval).", style="green"))
            elif ss.dismiss_notification(nid):
                self._log(Text(f"Dismissed {nid}", style="green"))
            else:
                self._log(Text(f"Notification {nid} not found", style="yellow"))
            self._refresh_status()
            return
        if sub == "approve" and len(ap) > 1:
            nid = ap[1].strip()
            n = self._find_notification(ss, nid)
            if n and n.action_id and not n.dismissed:
                if ss.resolve_approval(n.action_id, approve=True):
                    self._log(Text(f"Approved {nid}.", style="green"))
                else:
                    self._log(Text(f"Approval {nid} already resolved.", style="yellow"))
            else:
                self._log(
                    Text(
                        f"Notification {nid} not found or has no pending approval.",
                        style="yellow",
                    )
                )
            self._refresh_status()
            return

        notes = list(ss.notifications)
        colors = {
            "info": "cyan",
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "approval": "magenta",
        }
        pending = ss.pending_approval_count()
        title = f"Notifications ({ss.unread_notification_count()} unread"
        if pending:
            title += f", {pending} pending approval"
        title += ")"
        t = Text()
        t.append(f"{title}\n", style="bold")
        if not notes:
            t.append("  (none yet — long-running tasks notify here)\n", style="dim")
        else:
            for n in notes:
                c = colors.get(n.level, "white")
                marker = "●" if not n.dismissed else "○"
                if n.action_id and not n.dismissed and n.action_type == "approve":
                    marker = f"⚡{marker}"
                t.append(f"  {marker} ", style=c)
                t.append(f"{n.id} ", style="dim")
                t.append(f"{n.timestamp.strftime('%H:%M:%S')} ", style="dim")
                t.append(f"[{n.source}] ", style="dim")
                t.append(f"{n.title}", style=c)
                if n.message:
                    t.append(f" — {n.message[:60]}", style="dim")
                t.append("\n")
            t.append(
                "  /notifications dismiss <id> · /notifications approve <id>"
                " · /notifications clear\n",
                style="dim",
            )
        self._log(t)

    @staticmethod
    def _find_notification(ss, nid: str) -> object | None:
        """Return the Notification with the given id, or None."""
        for n in ss.notifications:
            if n.id == nid:
                return n
        return None

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
        await self._stream_prompt(user_input, assistant_id=assistant_id)

    async def _tui_quiet_execute_fn(
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
        """Execute the agent run quietly without streaming events to the TUI transcript.

        This avoids event loop flooding and unresponsiveness during intensive
        background operations like /init.
        """
        from novacode_cli.agent_stream import run_agent_stream
        from novacode_cli.ui_events import InterruptRequest, StatusUpdate

        ag = agent or self._init_agent or self.agent
        aid = assistant_id or self.assistant_id

        async for e in run_agent_stream(
            user_input,
            ag,
            aid,
            self.session_state,
            backend=backend or self._init_backend or self.backend,
            image_tracker=self.image_tracker,
            seen_message_ids=self._seen,
        ):
            if isinstance(e, StatusUpdate):
                self._set_status(e.message or "ready")
            elif isinstance(e, InterruptRequest):
                await self._handle_interrupt(e)

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

    async def _run_ingest(self, text: str) -> None:
        """Ingest a raw source into the wiki."""
        from novacode_cli.commands.wiki_commands import handle_ingest

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        if not args:
            # Show usage
            with _rich_console.capture() as cap:
                from novacode_cli.commands import CommandContext

                mock_ctx = CommandContext(
                    cmd="ingest",
                    cmd_args=None,
                    agent=self.agent,
                    token_tracker=self.token_tracker,
                    session_state=self.session_state,
                    assistant_id=self.assistant_id,
                )
                await handle_ingest(mock_ctx)
            out = Text.from_ansi(cap.get()).plain.strip()
            self._log(Text(out or "Usage: /ingest <raw_path>", style="dim"))
            return
        self._log(Text(f"📥 Ingesting: {args}", style="bold"))
        with _rich_console.capture() as cap:
            from novacode_cli.commands import CommandContext

            mock_ctx = CommandContext(
                cmd="ingest",
                cmd_args=args,
                agent=self.agent,
                token_tracker=self.token_tracker,
                session_state=self.session_state,
                assistant_id=self.assistant_id,
            )
            await handle_ingest(mock_ctx, execute_fn=self._tui_execute_fn)
        out = cap.get().strip()
        if out:
            self._log(Text.from_ansi(out))

    async def _run_ask(self, text: str) -> None:
        """Ask a question with wiki context prepended."""
        from novacode_cli.commands.wiki_commands import handle_ask

        parts = text.split(maxsplit=1)
        question = parts[1].strip() if len(parts) > 1 else ""
        if not question:
            with _rich_console.capture() as cap:
                from novacode_cli.commands import CommandContext

                mock_ctx = CommandContext(
                    cmd="ask",
                    cmd_args=None,
                    agent=self.agent,
                    token_tracker=self.token_tracker,
                    session_state=self.session_state,
                    assistant_id=self.assistant_id,
                )
                await handle_ask(mock_ctx)
            out = Text.from_ansi(cap.get()).plain.strip()
            self._log(Text(out or "Usage: /ask <question>", style="dim"))
            return
        self._log(Text(f"📚 Asking: {question}", style="bold"))
        with _rich_console.capture() as cap:
            from novacode_cli.commands import CommandContext

            mock_ctx = CommandContext(
                cmd="ask",
                cmd_args=question,
                agent=self.agent,
                token_tracker=self.token_tracker,
                session_state=self.session_state,
                assistant_id=self.assistant_id,
            )
            await handle_ask(mock_ctx, execute_fn=self._tui_execute_fn)
        out = cap.get().strip()
        if out:
            self._log(Text.from_ansi(out))

    async def _run_file(self, text: str) -> None:
        """File conversation knowledge into the wiki."""
        from novacode_cli.commands.wiki_commands import handle_file

        parts = text.split(maxsplit=1)
        topic = parts[1].strip() if len(parts) > 1 else ""
        if not topic:
            with _rich_console.capture() as cap:
                from novacode_cli.commands import CommandContext

                mock_ctx = CommandContext(
                    cmd="file",
                    cmd_args=None,
                    agent=self.agent,
                    token_tracker=self.token_tracker,
                    session_state=self.session_state,
                    assistant_id=self.assistant_id,
                )
                await handle_file(mock_ctx)
            out = Text.from_ansi(cap.get()).plain.strip()
            self._log(Text(out or "Usage: /file <topic>", style="dim"))
            return
        self._log(Text(f"📝 Filing: {topic}", style="bold"))
        with _rich_console.capture() as cap:
            from novacode_cli.commands import CommandContext

            mock_ctx = CommandContext(
                cmd="file",
                cmd_args=topic,
                agent=self.agent,
                token_tracker=self.token_tracker,
                session_state=self.session_state,
                assistant_id=self.assistant_id,
            )
            await handle_file(mock_ctx, execute_fn=self._tui_execute_fn)
        out = cap.get().strip()
        if out:
            self._log(Text.from_ansi(out))

    async def _run_wiki(self) -> None:
        """Show the Obsidian LLM Wiki browser (interactive)."""
        await self.push_screen_wait(WikiScreen())

    async def _run_dream(self) -> None:
        """Run /dream: show a native memory-consolidation summary, then stream it."""
        from novacode_cli.commands.dream_handler import handle_dream_command

        # Collect the handler's status lines and render them as ONE cohesive
        # native block (blank separators are dropped — no empty log widgets).
        status_lines: list[str] = []

        def _emit(message: str = "") -> None:
            if message:
                status_lines.append(message)

        result = await handle_dream_command(self.session_state, self.assistant_id, emit=_emit)

        if status_lines:
            block = Text()
            for i, line in enumerate(status_lines):
                try:
                    block.append_text(Text.from_markup(line))
                except Exception:  # noqa: BLE001 - bad markup: show literally
                    block.append(line)
                if i < len(status_lines) - 1:
                    block.append("\n")
            self._log(block)

        if isinstance(result, str) and result.strip():
            self._log(Text("💭 Dreaming over memories…", style="bold"))
            await self._stream_prompt(result)

    async def _run_evolution(self) -> None:
        """Run /evolution: show the self-evolution log as a native block."""
        from novacode_cli.commands.evolution_handler import handle_evolution_command

        lines: list[str] = []

        def _emit(message: str = "") -> None:
            if message:
                lines.append(message)

        await handle_evolution_command(emit=_emit)

        if lines:
            block = Text()
            for i, line in enumerate(lines):
                try:
                    block.append_text(Text.from_markup(line))
                except Exception:  # noqa: BLE001 - bad markup: show literally
                    block.append(line)
                if i < len(lines) - 1:
                    block.append("\n")
            self._log(block)

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
            result = await run_tests(command=command, working_dir=working_dir, output_callback=_cb)
            t = Text()
            t.append(
                "✓ Tests passed\n" if result.success else "✗ Tests failed\n",
                style="green" if result.success else "red",
            )
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
        """Show running servers (interactive)."""
        await self.push_screen_wait(ServersScreen())

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
                        (f"✓ Killed process {pid}" if ok else f"No process with PID {pid}"),
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
        opts = [f"[{p.pid}] {p.name}" + (f" (port {p.port})" if p.port else "") for p in processes]
        idx = await self.push_screen_wait(PickScreen("Kill which process?", opts))
        if 0 <= idx < len(processes):
            info = processes[idx]
            ok = await manager.stop_process(info.pid)
            self._log(
                Text(
                    (
                        f"✓ Killed '{info.name}' (PID {info.pid})"
                        if ok
                        else "Failed to kill process"
                    ),
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
                    (
                        f"✓ Restored {entry.original_path}"
                        if ok
                        else f"Failed to restore {entry.original_path}"
                    ),
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
                    f"{secs}s ago"
                    if secs < 60
                    else (
                        f"{secs // 60}m ago"
                        if secs < 3600
                        else (f"{secs // 3600}h ago" if secs < 86400 else f"{secs // 86400}d ago")
                    )
                )
            except Exception:  # noqa: BLE001
                age = entry.timestamp
            opts.append(f"{entry.original_path}  — {label} ({age})")
        idx = await self.push_screen_wait(PickScreen("Restore which snapshot?", opts))
        if 0 <= idx < len(snapshots):
            _restore(idx)

    async def _run_hooks(self, text: str) -> None:
        """Show hooks manager (interactive)."""
        await self.push_screen_wait(HooksScreen())

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

    # --- /ralph native widgets -------------------------------------------
    _RALPH_ITER_GLYPH = {
        "running": ("▶", "yellow"),
        "done": ("✓", "green"),
        "failed": ("✗", "red"),
    }

    def _ralph_mount(self, widget: Widget) -> None:
        """Mount a native Ralph card into the transcript (app thread only)."""
        self._close_tool_group()
        self._transcript().mount(widget)
        self._prune_transcript()
        self._scroll_end()

    def _ralph_run_text(self, event: Any) -> Text:
        """Header card for a Ralph run: task, iteration budget, and mode."""
        iters = "unlimited" if event.max_iterations == 0 else str(event.max_iterations)
        title = "🔁 Ralph Mode (Resumed)" if event.resumed_from else "🔁 Ralph Mode"
        t = Text()
        t.append(f"{title}\n", style="bold")
        t.append("Task: ", style="bold")
        t.append(f"{event.task}\n")
        t.append("Max iterations: ", style="bold")
        t.append(f"{iters}\n")
        if event.resumed_from:
            t.append("Resuming from: ", style="bold")
            t.append(f"iteration {event.resumed_from}\n")
        t.append("Mode: ", style="bold")
        t.append("background (non-blocking)" if event.background else "foreground")
        return t

    def _ralph_iter_text(
        self,
        iteration: int,
        max_iterations: int,
        status: str,
        elapsed: float | None = None,
        error: str | None = None,
    ) -> Text:
        """One iteration card line, styled by ``status`` (running/done/failed)."""
        glyph, color = self._RALPH_ITER_GLYPH.get(status, ("•", "dim"))
        disp = f"{iteration}/{max_iterations}" if max_iterations > 0 else str(iteration)
        t = Text()
        t.append(f"{glyph} Iteration {disp}", style=f"bold {color}")
        if status == "running":
            t.append("  — running…", style="dim")
        else:
            t.append(f"  — {'done' if status == 'done' else 'failed'}", style=color)
            if elapsed is not None:
                t.append(f" ({elapsed:.1f}s)", style="dim")
            if error:
                t.append(f"\n    {error}", style="red")
        return t

    def _ralph_status_renderable(self, snap: Any) -> Any:
        """Render a ``/ralph --status`` snapshot as a native table card."""
        from rich.console import Group
        from rich.table import Table

        header = Text("Ralph Background Tasks\n", style="bold")
        if not snap.rows:
            header.append("No background Ralph tasks running.", style="dim")
            return header

        table = Table(show_edge=False, pad_edge=False, expand=False)
        table.add_column("", width=2)
        table.add_column("Iter")
        table.add_column("Status")
        table.add_column("Elapsed", justify="right")
        table.add_column("Task")
        glyphs = {
            "running": ("⏳", "yellow"),
            "completed": ("✓", "green"),
            "failed": ("✗", "red"),
        }
        for row in snap.rows:
            g, color = glyphs.get(row.status, ("•", "dim"))
            disp = (
                f"{row.iteration}/{row.max_iterations}"
                if row.max_iterations > 0
                else str(row.iteration)
            )
            desc = row.task if len(row.task) <= 50 else row.task[:50] + "…"
            table.add_row(
                Text(g, style=color),
                disp,
                Text(row.status, style=color),
                f"{row.elapsed:.0f}s",
                desc,
            )
        summary = Text()
        summary.append(f"\nTotal {snap.total}", style="dim")
        summary.append(f"  ·  running {snap.running}", style="yellow")
        summary.append(f"  ·  completed {snap.completed}", style="green")
        summary.append(f"  ·  failed {snap.failed}", style="red")
        return Group(header, table, summary)

    def _ralph_on_event(self, event: Any) -> None:
        """Drive native Ralph widgets from a structured handler event (app thread).

        Mirrors :meth:`_init_on_event`: the UI-agnostic handler reports run
        milestones through :mod:`novacode_cli.commands.ralph_events`, and this
        turns each into a native card instead of a flat log line.
        """
        from novacode_cli.commands import ralph_events as rev

        if isinstance(event, rev.RalphStarted):
            self._ralph_iter_cards.clear()
            self._ralph_mount(Static(self._ralph_run_text(event), classes="ralph-run"))
        elif isinstance(event, rev.IterationStarted):
            card = Static(
                self._ralph_iter_text(event.iteration, event.max_iterations, "running"),
                classes="ralph-iter running",
            )
            self._ralph_iter_cards[event.iteration] = card
            self._ralph_mount(card)
        elif isinstance(event, rev.IterationFinished):
            status = "done" if event.ok else "failed"
            text = self._ralph_iter_text(
                event.iteration, event.max_iterations, status, event.elapsed, event.error
            )
            card = self._ralph_iter_cards.get(event.iteration)
            updated = False
            if card is not None:
                try:
                    card.set_classes(f"ralph-iter {status}")
                    card.update(text)
                    updated = True
                except Exception:  # noqa: BLE001 - card may have been pruned
                    updated = False
            if not updated:
                self._ralph_mount(Static(text, classes=f"ralph-iter {status}"))
        elif isinstance(event, rev.RalphFinished):
            t = Text()
            t.append("📊 Ralph finished", style="bold")
            t.append(f" — {event.completed} completed", style="green")
            if event.failed:
                t.append(f", {event.failed} failed", style="red")
            t.append(f" of {event.total} iteration(s)", style="dim")
            self._ralph_mount(Static(t, classes="ralph-summary"))
        elif isinstance(event, rev.StatusSnapshot):
            self._ralph_mount(Static(self._ralph_status_renderable(event), classes="ralph-status"))

    async def _run_ralph(self, text: str) -> None:
        """Run /ralph natively: structured milestones render as native cards via
        ``on_event``, free-form notices via a thread-safe ``emit``, and foreground
        iterations stream through ``_tui_execute_fn``."""
        import threading

        from novacode_cli.commands.ralph_handler import handle_ralph_command

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        self._log(Text(f"🔁 Ralph: {args or '(status)'}", style="bold"))

        loop_tid = threading.get_ident()

        def _emit(message: str = "") -> None:
            try:
                renderable = Text.from_markup(message) if message else Text("")
            except Exception:  # noqa: BLE001 - never let bad markup break the run
                renderable = Text(message)
            if threading.get_ident() == loop_tid:
                self._log(renderable)
            else:
                try:
                    self.call_from_thread(self._log, renderable)
                except Exception:  # noqa: BLE001 - app may be shutting down
                    pass

        def _on_event(event: Any) -> None:
            # Background runs fire events from a worker thread; hop to the app
            # thread before touching widgets (same contract as ``_emit``).
            if threading.get_ident() == loop_tid:
                self._ralph_on_event(event)
            else:
                try:
                    self.call_from_thread(self._ralph_on_event, event)
                except Exception:  # noqa: BLE001 - app may be shutting down
                    pass

        await handle_ralph_command(
            self.agent,
            self.session_state,
            self.assistant_id,
            self.token_tracker,
            args or None,
            execute_fn=self._tui_execute_fn,
            emit=_emit,
            on_event=_on_event,
        )

    async def _run_trello(self, text: str) -> None:
        """Run /trello; start the server inline, then watch for tasks in background."""
        from novacode_cli.commands.trello_handler import (
            _handle_status,
            _handle_stop,
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
        existing_server: TrelloServer | None = getattr(self.session_state, "trello_server", None)
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

    async def _run_create(self, text: str) -> None:
        """Run /create; start the Skills & Agents web UI server."""
        from novacode_cli.commands.create_server import CreateServer

        parts = text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""

        # Subcommand: stop
        if args == "stop":
            server: CreateServer | None = getattr(self.session_state, "create_server", None)
            if server and server.is_running:
                server.stop()
                self.session_state.create_server = None
                self._log(Text("Create UI stopped.", style="green"))
            else:
                self._log(Text("Create UI is not running.", style="yellow"))
            return

        # Check if already running
        existing_server: CreateServer | None = getattr(self.session_state, "create_server", None)
        if existing_server and existing_server.is_running:
            self._log(
                Text(
                    f"Create UI already running at http://localhost:{existing_server.port}",
                    style="yellow",
                )
            )
            return

        # Start the server
        server = CreateServer()
        port = await server.start()
        self.session_state.create_server = server
        self._log(
            Text(
                f"Create UI started at http://localhost:{port}",
                style="bold green",
            )
        )
        self._log(
            Text(
                "Browse, preview, edit, and create skills & agents in the browser.",
                style="dim",
            )
        )

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
                    self._log(Text(f"📋 Processing task: {task['description']}", style="bold"))
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

    async def _run_chat(self, text: str) -> None:
        """Run /council — start or stop the Council web UI in the browser."""
        from novacode_cli.commands.chat_handler import (
            get_server_url,
            is_server_running,
            set_agent_refs,
            start_chat_server,
            stop_chat_server,
        )

        parts = text.split(maxsplit=1)
        sub = parts[1].strip().lower() if len(parts) > 1 else ""

        # Wire agent refs (same as the CLI handler does)
        set_agent_refs(
            self.agent,
            self.assistant_id,
            self.session_state,
            asyncio.get_running_loop(),
        )

        if sub == "stop":
            if not is_server_running():
                self._log(Text("Council server is not running.", style="yellow"))
                return
            stop_chat_server()
            self._log(Text("✓ Council server stopped.", style="green"))
            return

        if is_server_running():
            url = get_server_url()
            self._log(Text(f"Council UI already running at {url}", style="green"))
            return

        url = start_chat_server()
        self._log(
            Text(
                f"Council UI started at {url} — present a topic to convene",
                style="bold green",
            )
        )

    async def _run_agents(self) -> None:
        """Show configured subagents (interactive)."""
        await self.push_screen_wait(AgentsScreen())

    async def _run_skills(self) -> None:
        """Show installed skills (interactive)."""
        await self.push_screen_wait(SkillsScreen())

    def _collect_skill_names(self) -> list[str]:
        from pathlib import Path

        from novacode_cli.config.config import Settings, settings

        dirs: list = []
        try:
            dirs.append(settings.ensure_user_skills_dir())
        except Exception:  # noqa: BLE001
            pass
        try:
            claude_skills_dir = Settings.get_global_claude_skills_dir()
            if claude_skills_dir.exists():
                dirs.append(claude_skills_dir)
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
        t.append("  /goal [text]     ", style="cyan")
        t.append("set a persistent goal (status / clear)\n", style="dim")
        t.append("  /btw <question>  ", style="cyan")
        t.append("ask a side question without touching the main conversation\n", style="dim")
        t.append("  /trace /log      ", style="cyan")
        t.append("tracing status / recent runs\n", style="dim")
        t.append("  /compact         ", style="cyan")
        t.append("summarize conversation to free context\n", style="dim")
        t.append("  /save            ", style="cyan")
        t.append("save the session now\n", style="dim")
        t.append("  /copy [all]      ", style="cyan")
        t.append("copy last response (or whole chat) — or click a message\n", style="dim")
        t.append("  /steer           ", style="cyan")
        t.append("add/list/clear steering instructions\n", style="dim")
        t.append("  /notifications   ", style="cyan")
        t.append("review/pending approvals (dismiss|approve <id> · clear)\n", style="dim")
        t.append("  /research        ", style="cyan")
        t.append("launch a multi-agent research swarm\n", style="dim")
        t.append("  /ingest <path>   ", style="cyan")
        t.append("ingest a raw source into the wiki\n", style="dim")
        t.append("  /ask <question>  ", style="cyan")
        t.append("ask with wiki context prepended\n", style="dim")
        t.append("  /file <topic>    ", style="cyan")
        t.append("file conversation knowledge into the wiki\n", style="dim")
        t.append("  /wiki            ", style="cyan")
        t.append("show Obsidian LLM Wiki browser (interactive)\n", style="dim")
        t.append("  /dream           ", style="cyan")
        t.append("reflect over memories to surface ideas\n", style="dim")
        t.append("  /evolution       ", style="cyan")
        t.append("view skills unlocked / levelled up by complex tasks\n", style="dim")
        t.append("  /reindex         ", style="cyan")
        t.append("rebuild the semantic code-search index\n", style="dim")
        t.append("  /images          ", style="cyan")
        t.append("list/remove/clear conversation images\n", style="dim")
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
            f"Context: {bd.usage_percentage:.1f}% used ({getattr(bd, 'tokens_used', 0):,} tokens)",
            style="dim",
        )

    async def _render(self, e: Any) -> None:
        if isinstance(e, ev.StatusUpdate):
            self._set_status(e.message or "ready")
        elif isinstance(e, ev.ReasoningDelta):
            # Stream the model's reasoning into a dim, transient message widget.
            # The actual repaint is coalesced (~20fps) via _schedule_stream_flush.
            self._reasoning_buf += e.text
            if self._reason_msg is None:
                self._reason_msg = ChatMessage(Text("💭 reasoning", style="dim italic"), "reason")
                await self._mount(self._reason_msg)
            self._schedule_stream_flush()
            if self._activity != "thinking…":
                self._set_status("thinking…")
        elif isinstance(e, ev.TextDelta):
            # Stream incremental prose into the in-progress Nova message widget.
            # Coalesced repaint (~20fps) — see _schedule_stream_flush/_flush_stream.
            self._live_buf += e.text
            if self._stream_msg is None:
                name, color = self._current_agent_info()
                self._stream_msg = ChatMessage(Text(name, style=f"bold {color}"), "nova")
                await self._mount(self._stream_msg)
            self._schedule_stream_flush()
            if self._activity != "responding…":
                self._set_status("responding…")
            # Remote turns don't mirror the answer live — the full answer is sent
            # as a normal chat message when the turn ends (chat-style flow).
        elif isinstance(e, ev.TextDiscard):
            self._stream_flush_scheduled = False
            if self._stream_msg is not None:
                try:
                    await self._stream_msg.remove()
                except Exception:  # noqa: BLE001
                    pass
                self._stream_msg = None
            self._live_buf = ""
        elif isinstance(e, ev.AssistantMessage):
            # Commit: finalize the streaming widget as rendered markdown. Cancel
            # any pending coalesced flush so it can't repaint a finalized widget.
            self._stream_flush_scheduled = False
            if self._stream_msg is not None:
                self._stream_msg.update_header(Text(e.agent_name, style=e.agent_color))
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
            base = f"{e.icon} {_esc(e.display_str)}"
            if e.name in _DETAILED_TOOL_NAMES:
                # Write/edit and execution tools keep a DEDICATED Collapsible.
                # Mounting it (via _mount) closes any open tool group, keeping
                # transcript order correct.
                if e.name in {
                    "shell",
                    "bash",
                    "execute",
                    "execute_bash",
                    "run_command",
                    "run_tests",
                    "start_dev_server",
                }:
                    body = RichLog(classes="terminal-log", highlight=True, markup=True)
                    # Starts expanded (collapsed=False) to show live output!
                    comp = Collapsible(body, title=f"{base}  · running…", collapsed=False)
                else:
                    body = Static("", classes="toolbody")
                    # Starts collapsed for file diffs
                    comp = Collapsible(body, title=f"{base}  · running…", collapsed=True)
                comp.add_class("tool")
                comp.add_class("tool-active")
                animate_entrance(comp, "zoom")
                await self._mount(comp)
                entry = (comp, body, base)
                if e.call_id:
                    self._tool_components[e.call_id] = entry
                self._last_tool = entry
            else:
                # Everything else (reads, search, exec, MCP, …) condenses into
                # the shared tool group — one compact line per call.
                await self._ensure_tool_group()
                self._add_tool_group_call(e.call_id, f"{e.icon} {e.display_str}", e.name)
            # Record for the end-of-turn remote footer (not sent per-event).
            self._remote_record(e.name)
        elif isinstance(e, ev.ToolResult):
            if e.call_id and e.call_id in self._tool_components:
                # Dedicated panel (write/edit) — finalize with full output body.
                self._finalize_tool(e.call_id, e.preview, e.full_output, is_error=e.is_error)
            else:
                self._mark_tool_group_result(e.call_id, is_error=e.is_error, detail=e.preview)
            self._scroll_end()
        elif isinstance(e, ev.FileOp):
            # File ops are the result of their tool call. Write/edit (a dedicated
            # panel was opened at ToolCall) render the full colored diff body so
            # the user can see exactly what changed; reads condense into the
            # group with a concise "Read N lines" summary.
            rec = e.record
            errored = bool(getattr(rec, "error", None)) or (getattr(rec, "status", "") == "error")
            if e.call_id and e.call_id in self._tool_components:
                comp, body, base = self._tool_components.pop(e.call_id)
                if self._last_tool is not None and self._last_tool[0] is comp:
                    self._last_tool = None
                mark = "✗" if errored else "✓"
                comp.title = f"{base}  {mark} {_esc(self._fileop_summary(rec))}".rstrip()
                # Expand on failure (surface the error) AND on a successful change
                # with a diff — these dedicated write/edit panels exist precisely
                # to show what changed, so a collapsed diff defeats the purpose.
                if errored or getattr(rec, "diff", None):
                    comp.collapsed = False
                body.update(self._fileop_body(rec, e.full_output))
            else:
                self._mark_tool_group_result(
                    e.call_id, is_error=errored, detail=self._fileop_summary(rec)
                )
            self._scroll_end()
        elif isinstance(e, ev.TodoUpdate):
            todo_text = self._render_todos(e.todos, e.agent_name)
            if self._todo_widget is None:
                self._todo_widget = Static(todo_text, classes="todos")
                await self._mount(self._todo_widget)
            else:
                self._todo_widget.update(todo_text)
                self._scroll_end()
            # Mirror the plan into the remote status line (one message edited in
            # place, throttled) so the remote user watches the checklist update.
            if self._remote_status is not None:
                self._remote_status.note_todos(e.todos)
        elif isinstance(e, ev.ErrorOutput):
            self._log(Text(e.text, style="red"))
        elif isinstance(e, ev.CompactionNotice):
            self._log(Text("⟳ Context compacted", style="dim"))
            # Context just shrank. The API-sourced current_context is the turn's
            # PEAK (pre-compaction) and would otherwise mask the reduction, so
            # reset() clears has_api_data and lets the recomputed, message-based
            # breakdown show the real post-compaction size. Then refresh the
            # status line so ctx% reflects it immediately.
            if self.token_tracker is not None:
                try:
                    self.token_tracker.reset()
                    await self._update_context_breakdown()
                except Exception:  # noqa: BLE001
                    pass
                self._refresh_status()
        elif isinstance(e, ev.ContextMessage):
            # Review-cycle start/complete are transient status, not log entries:
            # surface them on the live indicator above the input instead of
            # letting them scroll away in the transcript.
            if e.event_type == "nova_review_start":
                self._set_nova_indicator(f"{e.icon} {e.message}", style=e.color)
                return
            if e.event_type == "nova_review_complete":
                # Show briefly, then fade so the indicator doesn't linger.
                self._set_nova_indicator(f"{e.icon} {e.message}", style=e.color, auto_clear=4.0)
                return

            t = Text(e.icon + " ", style=e.color)
            t.append(e.message, style=e.color)
            # Map event_type (e.g. "nova_skill_refinement") to the CSS modifier
            # class ("nova-skill-refinement"): strip the leading "nova_"
            # namespace and convert underscores to hyphens so the per-event
            # border colors defined in the stylesheet actually match.
            css = "nova-event"
            if e.event_type:
                modifier = e.event_type.replace("nova_", "", 1).replace("_", "-")
                css += f" nova-{modifier}"
            # Non-tool content: close any open tool group first to keep order.
            self._close_tool_group()
            self._transcript().mount(Static(t, classes=css))
            self._prune_transcript()
            self._scroll_end()
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

    async def _ask_remote_question(self, question_request: dict) -> dict:
        """Route an agent question to the remote user via Discord/Telegram."""
        prompt = (
            question_request.get("question")
            or question_request.get("prompt")
            or "The agent has a question:"
        )
        opts = question_request.get("options") or []
        context = question_request.get("context")

        lines = []
        if context:
            lines.append(f"ℹ️ *Context:* {context}\n")
        lines.append(f"❓ *Question:* {prompt}")
        if opts:
            lines.append("\n*Options:*")
            for i, opt in enumerate(opts, 1):
                lines.append(f"{i}. {opt}")
            lines.append("\n*(Please reply with the number or the exact option text)*")
        message_text = "\n".join(lines)
        try:
            await self._remote_msg.reply_fn(message_text)
        except Exception as ex:  # noqa: BLE001
            self._log(Text(f"Failed to send remote question: {ex}", style="red"))

        self._remote_question_future = asyncio.Future()
        try:
            m = await self._remote_question_future
        finally:
            self._remote_question_future = None

        text = (getattr(m, "text", "") or "").strip()
        selected = None
        answer = text
        if text.isdigit() and opts:
            idx = int(text) - 1
            if 0 <= idx < len(opts):
                selected = idx
                answer = opts[idx]
        elif opts:
            for i, opt in enumerate(opts):
                if opt.lower() == text.lower():
                    selected = i
                    answer = opt
                    break

        from novacode_cli.ui.question_prompt import QuestionResponse

        return {"response": QuestionResponse(answer=answer, selected_index=selected)}

    async def _handle_interrupt(self, e: "ev.InterruptRequest") -> None:
        # Resolve in a finally so a handler that raises before set_result fails
        # closed (reject) instead of leaving the agent loop awaiting forever.
        try:
            await self._handle_interrupt_inner(e)
        finally:
            if not e.future.done():
                from novacode_cli.core.agent_loop import default_interrupt_response

                e.future.set_result(default_interrupt_response(e.kind))

    async def _handle_interrupt_inner(self, e: "ev.InterruptRequest") -> None:
        if e.kind == "tool":
            req = e.payload
            from novacode_cli.ui.hitl_approval import check_plan_mode_blocked

            blocked, rejection = check_plan_mode_blocked(req, self.session_state.plan_mode_enabled)
            if blocked and rejection:
                e.future.set_result({"decisions": rejection["decisions"], "any_rejected": True})
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
            if self._remote_msg is not None:
                result = await self._ask_remote_question(e.payload)
            else:
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
                    inline_plan=(
                        (e.payload or {}).get("plan") if isinstance(e.payload, dict) else None
                    ),
                )
                if content:
                    body = Markdown(content)
            except Exception:  # noqa: BLE001
                pass
            choice = await self.push_screen_wait(ApprovalModal("Plan requires approval", body))
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
    sandbox_id: str | None = None,
    sandbox_type: str | None = None,
    sandbox_meta: dict | None = None,
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
        sandbox_id=sandbox_id,
        sandbox_type=sandbox_type,
        sandbox_meta=sandbox_meta,
    )
    await app.run_async()
