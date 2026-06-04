"""Input handling, completers, and prompt session for the CLI."""

import asyncio
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import (
    Completer,
    Completion,
    PathCompleter,
    merge_completers,
)
from prompt_toolkit.document import Document
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.selection import PasteMode
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output.vt100 import Vt100_Output

from novacode_cli.config.config import COLORS, COMMANDS, Settings, console
from novacode_cli.image_utils import ImageData, get_clipboard_image
from novacode_cli.states.Session import SessionState

# Regex patterns for context-aware completion
AT_MENTION_RE = re.compile(r"@(?P<path>(?:[^\s@]|(?<=\\)\s)*)$")
SLASH_COMMAND_RE = re.compile(r"^/(?P<command>[a-z][a-z0-9:-]*)$")
# Pattern for @agent_name with optional query at start of input
AGENT_MENTION_RE = re.compile(r"^@([a-zA-Z0-9_-]+)(?:\s+(.+))?$", re.DOTALL)

EXIT_CONFIRM_WINDOW = 3.0


class ImageTracker:
    """Track pasted images in the current conversation with ID-based access."""

    def __init__(self) -> None:
        self._images: dict[str, ImageData] = {}  # id -> ImageData
        self.next_id = 1

    def add_image(self, image_data: ImageData) -> str:
        """Add an image and return its ID.

        Args:
            image_data: The image data to track

        Returns:
            Image ID like "image-1"
        """
        image_id = f"image-{self.next_id}"
        image_data.placeholder = f"[{image_id}]"
        self._images[image_id] = image_data
        self.next_id += 1
        return image_id

    def get_image(self, image_id: str) -> ImageData | None:
        """Get an image by ID.

        Args:
            image_id: The image ID (e.g., "image-1")

        Returns:
            ImageData if found, None otherwise
        """
        return self._images.get(image_id)

    def get_images(self) -> list[ImageData]:
        """Get all tracked images as a list."""
        return list(self._images.values())

    def get_images_dict(self) -> dict[str, ImageData]:
        """Get all tracked images as a dict."""
        return self._images.copy()

    def remove_image(self, image_id: str) -> bool:
        """Remove an image by ID.

        Args:
            image_id: The image ID to remove

        Returns:
            True if removed, False if not found
        """
        return self._images.pop(image_id, None) is not None

    def list_images(self) -> list[dict]:
        """List all images with metadata.

        Returns:
            List of dicts with id, format, size_kb, placeholder
        """
        return [
            {
                "id": image_id,
                "format": img.format,
                "size_kb": img.size_kb,
                "placeholder": img.placeholder,
            }
            for image_id, img in self._images.items()
        ]

    def clear(self) -> None:
        """Clear all tracked images and reset counter."""
        self._images.clear()
        self.next_id = 1

    @property
    def count(self) -> int:
        """Get number of tracked images."""
        return len(self._images)

    @property
    def images(self) -> list[ImageData]:
        """Get all tracked images (backward compatibility)."""
        return list(self._images.values())


class PasteTracker:
    """Track large text pastes in the current conversation with ID-based access.

    When the user pastes a large block of text, it's stored here and replaced
    with a short placeholder like [paste 1 +127 lines] in the input buffer.
    The placeholder is resolved back to the full text before submission.
    """

    def __init__(self) -> None:
        self._pastes: dict[str, str] = {}  # id -> full text
        self.next_id = 1

    def add_paste(self, text: str) -> str:
        """Add a large paste and return its placeholder ID.

        Args:
            text: The pasted text content

        Returns:
            Paste ID like "paste-1"
        """
        paste_id = f"paste-{self.next_id}"
        self._pastes[paste_id] = text
        self.next_id += 1
        return paste_id

    def get_paste(self, paste_id: str) -> str | None:
        """Get the full paste text by ID.

        Args:
            paste_id: The paste ID (e.g., "paste-1")

        Returns:
            Full text if found, None otherwise
        """
        return self._pastes.get(paste_id)

    def remove_paste(self, paste_id: str) -> bool:
        """Remove a paste by ID.

        Args:
            paste_id: The paste ID to remove

        Returns:
            True if removed, False if not found
        """
        return self._pastes.pop(paste_id, None) is not None

    def clear(self) -> None:
        """Clear all tracked pastes and reset counter."""
        self._pastes.clear()
        self.next_id = 1

    @property
    def count(self) -> int:
        """Get number of tracked pastes."""
        return len(self._pastes)

    @property
    def pastes(self) -> dict[str, str]:
        """Get all tracked pastes as dict."""
        return self._pastes.copy()


# Minimum character threshold to trigger paste summarization
PASTE_MIN_CHARS = 200
# Minimum newline threshold (whichever is reached first)
PASTE_MIN_NEWLINES = 5


def format_paste_placeholder(paste_id: str, text: str) -> str:
    """Create a compact placeholder for a large paste.

    Args:
        paste_id: The paste ID (e.g., "paste-1")
        text: The full pasted text

    Returns:
        A placeholder string like "[paste 1 +127 lines]"
    """
    num = paste_id.split("-")[1]
    line_count = text.count("\n")
    return f"[paste #{num} +{line_count} lines]"


_PASTE_PLACEHOLDER_RE = re.compile(r"\[paste #(\d+) \+\d+ lines\]")


def resolve_paste_placeholders(text: str, paste_tracker: PasteTracker) -> str:
    """Replace paste placeholders with the original full text.

    Args:
        text: The input text possibly containing paste placeholders
        paste_tracker: The PasteTracker instance holding the original texts

    Returns:
        The text with all paste placeholders resolved to their full content
    """
    def _replacer(m: re.Match) -> str:
        paste_id = f"paste-{m.group(1)}"
        original = paste_tracker.get_paste(paste_id)
        if original is not None:
            paste_tracker.remove_paste(paste_id)
            return original
        return m.group(0)  # fallback: keep placeholder if paste not found

    return _PASTE_PLACEHOLDER_RE.sub(_replacer, text)


class FilePathCompleter(Completer):
    """Activate filesystem completion only when cursor is after '@'."""

    def __init__(self) -> None:
        self.path_completer = PathCompleter(
            expanduser=True,
            min_input_len=0,
            only_directories=False,
        )

    def get_completions(self, document, complete_event):
        """Get file path completions when @ is detected."""
        text = document.text_before_cursor

        # Use regex to detect @path pattern at end of line
        m = AT_MENTION_RE.search(text)
        if not m:
            return  # Not in an @path context

        path_fragment = m.group("path")

        # Unescape the path for PathCompleter (it doesn't understand escape sequences)
        unescaped_fragment = path_fragment.replace("\\ ", " ")

        # Strip trailing backslash if present (user is in the process of typing an escape)
        unescaped_fragment = unescaped_fragment.removesuffix("\\")

        # Create temporary document for the unescaped path fragment
        temp_doc = Document(text=unescaped_fragment, cursor_position=len(unescaped_fragment))

        # Get completions from PathCompleter and use its start_position
        # PathCompleter returns suffix text with start_position=0 (insert at cursor)
        for comp in self.path_completer.get_completions(temp_doc, complete_event):
            # Add trailing / for directories so users can continue navigating
            completed_path = Path(unescaped_fragment + comp.text).expanduser()
            # Re-escape spaces in the completion text for the command line
            completion_text = comp.text.replace(" ", "\\ ")
            if completed_path.is_dir() and not completion_text.endswith("/"):
                completion_text += "/"

            yield Completion(
                text=completion_text,
                start_position=comp.start_position,  # Use PathCompleter's position (usually 0)
                display=comp.display,
                display_meta=comp.display_meta,
            )


class CommandCompleter(Completer):
    """Activate command completion only when line starts with '/'."""

    def get_completions(self, document, _complete_event):  # type: ignore
        """Get command completions when / is at the start."""
        text = document.text_before_cursor

        # Use regex to detect /command pattern at start of line
        m = SLASH_COMMAND_RE.match(text)
        if not m:
            return  # Not in a /command context

        command_fragment = m.group("command")

        # Match commands that start with the fragment (case-insensitive)
        for cmd_name, cmd_desc in COMMANDS.items():
            if cmd_name.startswith(command_fragment.lower()):
                yield Completion(
                    text=cmd_name,
                    start_position=-len(command_fragment),  # Fixed position for original document
                    display=cmd_name,
                    display_meta=cmd_desc,
                )


class SkillCompleter(Completer):
    """Provide completion for /skill:<name> invocations at the start of input."""

    def __init__(self) -> None:
        self._skills_cache: list[tuple[str, str]] | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 30.0  # seconds

    def _load_skills(self) -> list[tuple[str, str]]:
        """Load available skills with caching."""
        import time
        now = time.time()
        if self._skills_cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._skills_cache

        skills_list: list[tuple[str, str]] = []
        try:
            from novacode_cli.config.config import Settings
            from novacode_cli.skills.load import list_skills

            settings = Settings.from_environment()
            user_skills_dir = settings.ensure_user_skills_dir()
            project_skills_dir = (
                settings.get_project_skills_dir()
                if settings.project_root
                else None
            )
            skills = list_skills(
                user_skills_dir=user_skills_dir,
                project_skills_dir=project_skills_dir,
            )
            for skill in skills:
                name = skill.get("name", "")
                desc = skill.get("description", "")[:60]
                if name:
                    skills_list.append((name, desc))
        except Exception:
            pass

        self._skills_cache = skills_list
        self._cache_time = now
        return skills_list

    def get_completions(self, document, _complete_event):  # type: ignore
        """Get skill name completions when /skill: is at the start."""
        text = document.text_before_cursor

        # Only activate after /skill: prefix
        if not text.startswith("/skill:"):
            return

        # Extract the skill name fragment after /skill:
        skill_fragment = text[len("/skill:"):]

        for skill_name, skill_desc in self._load_skills():
            if skill_name.startswith(skill_fragment.lower()):
                yield Completion(
                    text=skill_name,
                    start_position=-len(skill_fragment),
                    display=skill_name,
                    display_meta=skill_desc,
                )


class AgentCompleter(Completer):
    """Provide completion for @agent mentions at the start of input."""

    def get_completions(self, document, _complete_event):  # type: ignore
        """Get agent completions when @ is at the start of input.

        Shows agents from both project scope (if in a project) and global scope.
        Project agents are shown first and take precedence.
        """
        text = document.text_before_cursor

        # Match @partial_agent_name at start of line (no space yet means still typing agent name)
        match = re.match(r"^@([a-zA-Z0-9_-]*)$", text)
        if not match:
            return

        prefix = match.group(1)
        settings = Settings.from_environment()

        # Get all agents from both scopes
        all_agents = settings.get_all_agents()

        # Track which agent names we've yielded to avoid duplicates
        # (project agents shadow global agents with same name)
        yielded_names: set[str] = set()

        for agent_name, agent_dir, scope in all_agents:
            # Skip if name doesn't match prefix
            if not agent_name.lower().startswith(prefix.lower()):
                continue

            # Skip if we already yielded a project agent with this name
            if agent_name in yielded_names:
                continue

            yielded_names.add(agent_name)

            # Read description from agent.md
            scope_indicator = "[P] " if scope == "project" else ""
            description = f"{scope_indicator}Custom agent"
            try:
                content = (agent_dir / "agent.md").read_text(encoding="utf-8")
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        desc_text = line[:45] if scope == "project" else line[:50]
                        if len(line) > 45:
                            desc_text += "..."
                        description = f"{scope_indicator}{desc_text}"
                        break
            except Exception:
                pass

            yield Completion(
                text=agent_name + " ",  # Add space after agent name
                start_position=-len(prefix),
                display=f"@{agent_name}",
                display_meta=description,
            )


# CSS at-rules and Python/JS decorators that should NOT be treated as file mentions.
# These are commonly misidentified by the @mention regex.
_FALSE_POSITIVE_AT_RULES = frozenset({
    # CSS at-rules
    "keyframes", "media", "import", "charset", "font-face", "supports",
    "layer", "container", "property", "scope", "page", "namespace",
    "document", "viewport",
    # Python/JS decorators and common @-prefixed identifiers
    "dataclass", "abstractmethod", "staticmethod", "classmethod", "property",
    "overload", "cached_property", "final", "override", "deprecated",
    "setter", "getter", "deleter", "register", "injectable", "inject",
    "component", "directive", "service", "module", "pipe",
    "input", "output", "hostbinding", "hostlistener",
})

# File extensions used to distinguish file paths from bare @words.
_FILE_EXTENSIONS = frozenset({
    "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml",
    "md", "txt", "csv", "html", "css", "scss", "less", "svg",
    "xml", "sql", "sh", "bash", "zsh", "fish", "powershell",
    "c", "cpp", "h", "hpp", "rs", "go", "java", "kt", "swift",
    "rb", "php", "r", "R", "lua", "vim", "ex", "exs", "erl",
    "cfg", "ini", "conf", "env", "proto", "graphql", "lock", "wasm",
})


def _is_likely_file_mention(match_str: str) -> bool:
    """Return True if the @-mention looks like a file path, not a CSS at-rule or decorator."""
    if len(match_str) < 2:
        return False

    cleaned = match_str.rstrip(".,;:!?)({")

    # Check for CSS at-rules and known decorators (bare @word before / or \()
    bare_word = cleaned.split("(")[0].split("/")[0].lower()
    if bare_word in _FALSE_POSITIVE_AT_RULES:
        return False

    has_slash = "/" in cleaned
    has_dot = "." in cleaned

    if not has_slash:
        # Bare @word with no path separator
        if not has_dot:
            # No extension, no slash — not a file path
            # (e.g. @keyframes, @decorator, @cache_read_tokens, @e1)
            return False
        else:
            # Has extension but no slash — could be @README.md
            ext = cleaned.rsplit(".", 1)[-1].lower()
            if ext in _FILE_EXTENSIONS:
                return True
            # email@domain.com pattern (no slash, domain-like suffix)
            if re.match(r"^[a-zA-Z0-9._%+-]+\.[a-zA-Z]{2,}$", cleaned):
                return False
            # Unknown extension, no slash — be conservative
            return False

    # Has a slash — likely a path like @src/utils.ts or @app/components/Header.tsx
    # Even @angular/core style scoped packages pass through here;
    # the file-existence check below filters them out silently.
    return True


def parse_file_mentions(text: str) -> tuple[str, list[Path]]:
    """Extract @file mentions and return cleaned text with resolved file paths.

    Filters out false positives like CSS at-rules (@keyframes, @media),
    Python/JS decorators (@dataclass, @property), and email addresses
    (user@domain.com) that the @-mention regex would otherwise match.
    """
    pattern = r"@((?:[^\s@]|(?<=\\\\)\s)+)"
    matches = re.findall(pattern, text)

    files: list[Path] = []
    for match in matches:
        # Skip false positives (CSS at-rules, decorators, email addresses)
        if not _is_likely_file_mention(match):
            continue

        # Remove escape characters
        clean_path = match.replace("\\ ", " ")
        path = Path(clean_path).expanduser()

        # Try to resolve relative to cwd
        if not path.is_absolute():
            path = Path.cwd() / path

        try:
            path = path.resolve()
            if path.exists() and path.is_file():
                files.append(path)
            # Silently skip non-existent files that passed the filter —
            # avoids noise for scoped packages like @angular/core
        except Exception:
            pass  # Silently ignore invalid paths from filtered matches

    return text, files


def parse_agent_mentions(text: str, settings: Settings | None = None) -> tuple[str | None, str]:
    """Parse @agent_name mentions at the start of input.

    Returns:
        Tuple of (agent_name or None, remaining_query)

    Pattern: @agent_name <query>
    Checks project agents first (if in a project), then global agents.
    """
    if settings is None:
        settings = Settings.from_environment()

    match = AGENT_MENTION_RE.match(text.strip())
    if not match:
        return None, text

    agent_name = match.group(1)
    raw_query = match.group(2)
    query = raw_query.strip() if raw_query else "Introduce yourself — describe what you specialise in and how you can help."

    # Core agents have no agent.md on disk — check their names directly.
    from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents
    if agent_name in {s["name"] for s in retrieve_core_subagents()}:
        return agent_name, query

    # User-created agents: verify agent.md exists on disk.
    if settings.find_agent(agent_name) is not None:
        return agent_name, query

    return None, text  # Agent not found, treat as regular input


def get_bottom_toolbar(
    session_state: SessionState, session_ref: dict
) -> Callable[[], list[tuple[str, str]]]:
    """Return toolbar function that shows auto-approve status, BASH MODE, and context usage."""

    def toolbar() -> list[tuple[str, str]]:
        parts = []

        # Check if plan mode is active
        if session_state.plan_mode_enabled:
            parts.append(("bg:#0ea5e9 fg:#ffffff bold", " PLAN MODE "))
            parts.append(("", " | "))

        # Check if we're in BASH mode (input starts with !)
        try:
            session = session_ref.get("session")
            if session:
                current_text = session.default_buffer.text
                if current_text.startswith("!"):
                    parts.append(("bg:#ff1493 fg:#ffffff bold", " BASH MODE "))
                    parts.append(("", " | "))
        except (AttributeError, TypeError):
            # Silently ignore - toolbar is non-critical and called frequently
            pass

        # Check if verbose mode is active
        if session_state.verbose:
            parts.append(("bg:#a855f7 fg:#ffffff bold", " VERBOSE "))
            parts.append(("", " | "))

        # Context usage indicator
        try:
            _tt = session_state.token_tracker
            if _tt and _tt.has_api_data:
                _bd = _tt.get_breakdown()
                _pct = _bd.usage_percentage
                _pct_str = f"{_pct:.0f}%"
                if _bd.is_critical:
                    _ctx_style = "class:toolbar-red"
                    _ctx_msg = f" !CTX {_pct_str} "
                elif _bd.is_warning:
                    _ctx_style = "class:toolbar-orange"
                    _ctx_msg = f" ctx {_pct_str} "
                else:
                    _ctx_style = "class:toolbar-green"
                    _ctx_msg = f" ctx {_pct_str} "
                parts.append((_ctx_style, _ctx_msg))
                parts.append(("", " | "))
        except Exception:
            pass  # Toolbar is non-critical

        # Base status message
        if session_state.auto_approve:
            base_msg = "auto-accept ON (CTRL+T to toggle)"
            base_class = "class:toolbar-green"
        else:
            base_msg = "manual accept (CTRL+T to toggle)"
            base_class = "class:toolbar-orange"

        parts.append((base_class, base_msg))

        # Show exit confirmation hint if active
        hint_until = session_state.exit_hint_until
        if hint_until is not None:
            now = time.monotonic()
            if now < hint_until:
                parts.append(("", " | "))
                parts.append(("class:toolbar-exit", " Ctrl+C again to exit "))
            else:
                session_state.exit_hint_until = None

        return parts

    return toolbar


def create_prompt_session(
    _assistant_id,
    session_state: SessionState,
    image_tracker: ImageTracker | None = None,
    paste_tracker: PasteTracker | None = None,
) -> PromptSession:
    """Create a configured PromptSession with all features."""
    # Set default editor if not already set
    if "EDITOR" not in os.environ:
        os.environ["EDITOR"] = "nano"

    # Create key bindings
    kb = KeyBindings()

    @kb.add("c-c")
    def _(event) -> None:
        """Require double Ctrl+C within a short window to exit."""
        app = event.app
        now = time.monotonic()

        if session_state.exit_hint_until is not None and now < session_state.exit_hint_until:
            handle = session_state.exit_hint_handle
            if handle:
                handle.cancel()
                session_state.exit_hint_handle = None
            session_state.exit_hint_until = None
            app.invalidate()
            app.exit(exception=KeyboardInterrupt())
            return

        session_state.exit_hint_until = now + EXIT_CONFIRM_WINDOW

        handle = session_state.exit_hint_handle
        if handle:
            handle.cancel()

        loop = asyncio.get_running_loop()
        app_ref = app

        def clear_hint() -> None:
            if (
                session_state.exit_hint_until is not None
                and time.monotonic() >= session_state.exit_hint_until
            ):
                session_state.exit_hint_until = None
                session_state.exit_hint_handle = None
                app_ref.invalidate()

        session_state.exit_hint_handle = loop.call_later(EXIT_CONFIRM_WINDOW, clear_hint)  # type: ignore

        app.invalidate()

    # Bind Ctrl+V to paste clipboard image (if available)
    @kb.add("c-v")
    def _(event) -> None:
        """Check for clipboard image, otherwise do normal paste (large text handled by wrapper)."""
        if image_tracker:
            try:
                clipboard_image = get_clipboard_image()
                if clipboard_image:
                    image_id = image_tracker.add_image(clipboard_image)
                    # Insert placeholder text
                    event.current_buffer.insert_text(f"[{image_id}] ")
                    console.print(
                        f"[dim]Image pasted: {image_id} ({clipboard_image.size_kb:.1f} KB)[/dim]"
                    )
                    event.app.invalidate()
                    return
            except Exception:
                pass  # Fall through to normal paste
        # Normal text paste (paste summarisation is handled by the
        # paste_clipboard_data wrapper on the buffer, not here)
        event.current_buffer.paste_clipboard_data(event.app.clipboard.get_data())

    # Bind Ctrl+T to toggle auto-approve
    @kb.add("c-t")
    def _(event) -> None:
        """Toggle auto-approve mode."""
        session_state.toggle_auto_approve()
        # Force UI refresh to update toolbar
        event.app.invalidate()

    # Bind Shift+Tab to toggle plan mode
    @kb.add("s-tab")
    def _(event) -> None:
        """Toggle plan mode on/off."""
        session_state.toggle_plan_mode()
        session_state.pending_plan_mode_sync = True
        # Force UI refresh to update toolbar
        event.app.invalidate()

    # Bind regular Enter to submit (intuitive behavior)
    @kb.add("enter")
    def _(event) -> None:
        """Enter submits the input, unless completion menu is active."""
        buffer = event.current_buffer

        # If completion menu is showing, apply the current completion
        if buffer.complete_state:
            # Get the current completion (the highlighted one)
            current_completion = buffer.complete_state.current_completion

            # If no completion is selected (user hasn't navigated), select and apply the first one
            if not current_completion and buffer.complete_state.completions:
                # Move to the first completion
                buffer.complete_next()
                # Now apply it
                buffer.apply_completion(buffer.complete_state.current_completion)
            elif current_completion:
                # Apply the already-selected completion
                buffer.apply_completion(current_completion)
            else:
                # No completions available, close menu
                buffer.complete_state = None
        # Don't submit if buffer is empty or only whitespace
        elif buffer.text.strip():
            # Normal submit
            buffer.validate_and_handle()
            # If empty, do nothing (don't submit)

    # Alt+Enter for newlines (press ESC then Enter, or Option+Enter on Mac)
    @kb.add("escape", "enter")
    def _(event) -> None:
        """Alt+Enter inserts a newline for multi-line input."""
        event.current_buffer.insert_text("\n")

    # Ctrl+E to open in external editor
    @kb.add("c-e")
    def _(event) -> None:
        """Open the current input in an external editor (nano by default)."""
        event.current_buffer.open_in_editor()

    # Backspace handler to retrigger completions after deletion
    @kb.add("backspace")
    def _(event) -> None:
        """Handle backspace and retrigger completion if in @ or / context."""
        buffer = event.current_buffer

        # Perform the normal backspace action
        buffer.delete_before_cursor(count=1)

        # Check if we're in a completion context (@ or /)
        text = buffer.document.text_before_cursor
        if AT_MENTION_RE.search(text) or SLASH_COMMAND_RE.match(text):
            # Retrigger completion
            buffer.start_completion(select_first=False)

    from prompt_toolkit.styles import Style

    # Define styles for the toolbar with full-width background colors
    toolbar_style = Style.from_dict(
        {
            "bottom-toolbar": "noreverse",  # Disable default reverse video
            "toolbar-green": "bg:#10b981 #000000",  # Green for auto-accept ON
            "toolbar-orange": "bg:#f59e0b #000000",  # Orange for manual accept
            "toolbar-red": "bg:#ef4444 #ffffff",  # Red for critical context
            "toolbar-exit": "bg:#2563eb #ffffff",  # Blue for exit hint
        }
    )

    # Create session reference dict for toolbar to access session
    session_ref = {}

    # Force VT100 output on Windows when running in MINGW/Git Bash or similar Unix-like terminals
    output = None
    if sys.platform == "win32" and os.environ.get("TERM") in (
        "xterm-256color",
        "xterm",
    ):
        output = Vt100_Output.from_pty(sys.stdout)

    # Create the session
    session = PromptSession(
        output=output,
        message=HTML(f'<style fg="{COLORS["user"]}">></style> '),
        multiline=True,  # Keep multiline support but Enter submits
        key_bindings=kb,
        completer=merge_completers([CommandCompleter(), SkillCompleter(), AgentCompleter(), FilePathCompleter()]),
        editing_mode=EditingMode.EMACS,
        complete_while_typing=True,  # Show completions as you type
        complete_in_thread=True,  # Async completion prevents menu freezing
        mouse_support=False,
        enable_open_in_editor=True,  # Allow Ctrl+X Ctrl+E to open external editor
        bottom_toolbar=get_bottom_toolbar(
            session_state, session_ref
        ),  # Persistent status bar at bottom
        style=toolbar_style,  # Apply toolbar styling
        reserve_space_for_menu=7,  # Reserve space for completion menu to show 5-6 results
    )

    # Store session reference for toolbar to access
    session_ref["session"] = session

    # ── Monkey-patch paste_clipboard_data to intercept large text pastes ──
    # This catches ALL paste paths (Ctrl+V keybinding, bracketed paste mode,
    # middle-click paste, programmatic paste) regardless of terminal.
    if paste_tracker:
        _original_paste_clipboard = session.default_buffer.paste_clipboard_data
        _original_insert_text = session.default_buffer.insert_text

        def _should_summarize(text):
            return (
                len(text) >= PASTE_MIN_CHARS
                or text.count("\n") >= PASTE_MIN_NEWLINES
            )

        def _intercept_paste(text, insert_fn, *insert_args, **insert_kw):
            """Check if text is a large paste; if so, store & insert placeholder."""
            if text and _should_summarize(text):
                paste_id = paste_tracker.add_paste(text)
                placeholder = format_paste_placeholder(paste_id, text)
                insert_fn(placeholder, *insert_args, **insert_kw)
                console.print(
                    f"[dim]{placeholder} ({len(text):,} chars)[/dim]"
                )
                return True
            return False

        def _wrapped_paste_clipboard(data, paste_mode=None, count=1):
            """Intercept large pastes from Ctrl+V / paste_clipboard_data path."""
            if data and data.text:
                text = data.text.replace("\r\n", "\n").replace("\r", "\n")
                # Insert placeholder via insert_text so it appears at cursor
                if _intercept_paste(text, _original_insert_text):
                    return
            # Small paste — proceed as normal
            _original_paste_clipboard(data, paste_mode or PasteMode.EMACS, count)

        def _wrapped_insert_text(data, overwrite=False, fire_event=True):
            """Intercept large pastes from bracketed paste / insert_text path.

            Bracketed paste mode wraps pasted text in \\x1b[200~ ... \\x1b[201~
            and prompt_toolkit inserts it via insert_text(data) in one chunk.
            This wrapper catches those and converts them to placeholders.
            """
            if _intercept_paste(data, _original_insert_text, overwrite, fire_event=fire_event):
                return
            _original_insert_text(data, overwrite, fire_event=fire_event)

        session.default_buffer.paste_clipboard_data = _wrapped_paste_clipboard
        session.default_buffer.insert_text = _wrapped_insert_text

    return session
