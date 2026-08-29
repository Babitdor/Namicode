"""Widgets for the Nova TUI.

Extracted verbatim from :mod:`novacode_cli.tui.app` (which re-exports these
names for backward compatibility). This module must not import from app.py.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widget import Widget
from textual.message import Message
from textual.widgets import Input, Static, TextArea

from novacode_cli.input_utils import (
    PASTE_MIN_CHARS,
    PASTE_MIN_NEWLINES,
    PasteTracker,
    format_paste_placeholder,
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
        self._needs_layout = True  # one layout pass after mount/reflow
        # Theme-derived render values, recomputed only when the theme changes
        # (keyed by _theme_key) instead of every frame.
        self._palette: tuple[str, str, str, str] | None = None
        self._art_style_str: str = ""
        self._palette_key: str | None = None
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
            self._needs_layout = True  # next frame must re-layout (size changed)

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

    def _theme_key(self) -> str:
        """The active theme's primary color string — the palette cache key."""
        raw = None
        try:
            raw = self.app.current_theme.primary
        except Exception:  # noqa: BLE001
            try:
                raw = self.app.theme_variables.get("primary")
            except Exception:  # noqa: BLE001
                raw = None
        return (raw or "#00ff88").strip()

    def _ensure_theme_cache(self) -> None:
        """Recompute the palette + art style only when the theme color changes."""
        key = self._theme_key()
        if key != self._palette_key:
            self._palette = self._rain_palette()
            self._art_style_str = self._art_style()
            self._palette_key = key

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
        self._needs_layout = True  # first frame must establish the widget size
        # ~15 fps: column speeds are scaled so the fall rate looks the same as
        # the old 25 fps, but each second costs 40% fewer frame builds and —
        # more importantly — 40% fewer Textual repaints on the main thread.
        self._timer = self.set_interval(0.066, self._tick)

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
                    "speed": random.uniform(0.07, 0.18),  # adjusted for 15fps
                    "trail": random.randint(5, 14),
                }
            )
        # Pre-allocate frame buffers (reused per frame to avoid GC churn).
        self._frame_lines = [[" "] * self._col_count for _ in range(self._row_count)]
        self._frame_styles = [[""] * self._col_count for _ in range(self._row_count)]
        # Prebuilt blank rows copied in (slice-assign) to clear buffers at C speed.
        self._blank_line = [" "] * self._col_count
        self._blank_style = [""] * self._col_count
        # Precomputed random-char pool: strided per frame from a random offset so
        # the look stays random without a random.choice() call per cell.
        self._char_pool = [random.choice(self._chars) for _ in range(512)]

    def _tick(self) -> None:
        """Advance one frame of the rain, then stamp the logo over it.

        Early-returns (no work) when the widget is scrolled out of the visible
        viewport, so transcript messages push the rain off-screen cheaply.
        """
        # Pause animation updates while TTS is playing to prevent audio stuttering
        # due to thread / GIL contention on the main loop.
        try:
            vp = getattr(self.app, "_voice_pipeline", None)
            if vp is not None and vp.tts_active:
                return
        except Exception:  # noqa: BLE001
            pass

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

        # layout=False: the frame's row/col count is constant between reflows,
        # so a repaint suffices. The default layout=True re-laid-out the WHOLE
        # screen DOM (up to ~400 transcript widgets) on every frame — the
        # single biggest source of TUI jank while the rain was visible. A
        # one-shot layout pass still runs after mount/reflow (size changes).
        needs_layout = self._needs_layout
        self._needs_layout = False
        self.update(self._build_frame(), layout=needs_layout)

    def _build_frame(self) -> Text:
        """Build one rain frame as a Rich ``Text`` (no side effects)."""
        cols = self._col_count
        rows = self._row_count
        lines = self._frame_lines
        styles = self._frame_styles

        # Clear buffers for the new frame (C-level slice copy of prebuilt rows).
        blank_l = self._blank_line
        blank_s = self._blank_style
        for y in range(rows):
            lines[y][:] = blank_l
            styles[y][:] = blank_s

        self._ensure_theme_cache()
        head_c, near_c, mid_c, tail_c = self._palette
        pool = self._char_pool
        pool_len = len(pool)
        idx = random.randrange(pool_len)  # one RNG call per frame

        for col, d in enumerate(self._columns):
            d["pos"] += d["speed"]
            if d["pos"] > rows + d["trail"]:  # reset when fully off-screen
                d["pos"] = random.uniform(-rows, -3)
                d["speed"] = random.uniform(0.08, 0.23)  # adjusted for 15fps
                d["trail"] = random.randint(5, 14)

            tail_start = max(0, int(d["pos"]) - d["trail"])
            head = min(rows - 1, int(d["pos"]))
            for y in range(tail_start, head + 1):
                dist = head - y
                lines[y][col] = pool[idx]
                idx += 1
                if idx == pool_len:
                    idx = 0
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
            art_style = self._art_style_str
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

        text = Text()
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
                text.append(segment, s or None)
                x = j
            if y < rows - 1:
                text.append("\n")
        return text


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



class PromptInput(TextArea):
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

    class Submitted(Message):
        """Posted when the user presses enter to send the prompt.

        ``TextArea`` has no Submitted message of its own (enter inserts a
        newline there), so the prompt defines one to keep the app-side
        contract identical to the old ``Input``-based widget.
        """

        def __init__(self, prompt_input: "PromptInput", value: str) -> None:
            self.input = prompt_input
            self.value = value
            super().__init__()

    @property
    def value(self) -> str:
        """Alias of ``text`` so callers written against ``Input`` still work."""
        return self.text

    @value.setter
    def value(self, new: str) -> None:
        self.text = new

    @property
    def cursor_position(self) -> int:
        """Cursor offset into ``text`` (``Input``-compatible).

        ``TextArea`` exposes a (row, column) ``cursor_location``; the palette
        and @-completion were written against a flat offset, so translate.
        """
        try:
            row, col = self.cursor_location
        except Exception:  # noqa: BLE001
            return len(self.text)
        lines = self.text.split("\n")[:row]
        return sum(len(line) + 1 for line in lines) + col

    @cursor_position.setter
    def cursor_position(self, offset: int) -> None:
        text = self.text
        offset = max(0, min(offset, len(text)))
        before = text[:offset]
        row = before.count("\n")
        col = offset - (before.rfind("\n") + 1)
        self.move_cursor((row, col))

    async def _on_key(self, event: events.Key) -> None:
        # enter sends; shift+enter (and ctrl+j, which some terminals send
        # instead) inserts a real newline. TextArea does the opposite by
        # default, and a chat prompt wants enter to mean "send".
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._end_paste_merge()
            self.post_message(self.Submitted(self, self.text))
            return
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self._end_paste_merge()
            self.insert("\n")
            return
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
            if new_ph != old_ph and old_ph in self.text:
                self.text = self.text.replace(old_ph, new_ph, 1)
                self.move_cursor(self.document.end)
            self._active_paste_ph = new_ph
        elif tracker is not None and (
            len(normalized) >= PASTE_MIN_CHARS or normalized.count("\n") >= PASTE_MIN_NEWLINES
        ):
            # First fragment of a large paste: create the placeholder and open
            # the merge window so any trailing fragments fold into this one.
            paste_id = tracker.add_paste(normalized)
            placeholder = format_paste_placeholder(paste_id, normalized)
            self.insert(placeholder + " ")
            self._active_paste_id = paste_id
            self._active_paste_ph = placeholder
        else:
            # Small paste — won't fragment; insert literally, no merge needed.
            self.insert(normalized)

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

    The exploration prompt streams through the TUI's native chat.
    """

    def __init__(self, app: NovaApp) -> None:
        self._app = app

    def emit(self, event) -> None:
        """Pipeline progress event — no-op."""
        pass

    def result(self, result) -> None:
        """Log the final pipeline outcome."""
        if not result.ok and result.message:
            self._app._log(Text(result.message, style="yellow"))

    async def run_exploration(
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
            nova_md_path=str(nova_md_path),
        )
        prev = session_state.auto_approve
        session_state.auto_approve = True
        try:
            await self._app._stream_prompt(prompt)
        finally:
            session_state.auto_approve = prev


