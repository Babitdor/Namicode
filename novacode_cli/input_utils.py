"""Shared input utilities — image/paste tracking, file/agent mention parsing.

Extracted from the legacy ``input.py`` (which was tied to ``prompt_toolkit``).
These utilities are used by both the TUI and the headless mode.
"""

from __future__ import annotations

import re
from pathlib import Path

from novacode_cli.config.config import Settings
from novacode_cli.image_utils import ImageData

# Regex patterns for context-aware completion
AT_MENTION_RE = re.compile(r"@(?P<path>(?:[^\s@]|(?<=\\)\s)*)$")
SLASH_COMMAND_RE = re.compile(r"^/(?P<command>[a-z][a-z0-9:-]*)$")
# Pattern for @agent_name with optional query at start of input
AGENT_MENTION_RE = re.compile(r"^@([a-zA-Z0-9_-]+)(?:\s+(.+))?$", re.DOTALL)
# Pattern for an @name token ANYWHERE in the text (used to find multiple agent
# mentions). The (?<![^\s(]) guard avoids matching mid-word like "foo@bar" or
# an email's "@domain", while still allowing a leading "(@name".
ANY_MENTION_RE = re.compile(r"(?<![^\s(])@([a-zA-Z0-9_-]+)")


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

    def extend_paste(self, paste_id: str, text: str) -> bool:
        """Append more text to an existing paste (for coalescing fragments).

        A single large paste can be delivered by the terminal as several Paste
        events; appending the later fragments onto the first paste keeps the
        whole thing as one block under one placeholder.

        Args:
            paste_id: The paste ID to extend (e.g., "paste-1")
            text: The text to append

        Returns:
            True if the paste existed and was extended, False otherwise
        """
        if paste_id in self._pastes:
            self._pastes[paste_id] += text
            return True
        return False

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
            # No extension, no slash — check if the file actually exists on disk.
            # This handles files like @Makefile, @Dockerfile, @LICENSE, @README.
            try:
                bare_path = Path(match_str).expanduser()
                if not bare_path.is_absolute():
                    bare_path = Path.cwd() / bare_path
                if bare_path.exists() and bare_path.is_file():
                    return True
            except Exception:
                pass
            # Not a real file, not a path — skip
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
            # Unknown extension, no slash — check if the file actually exists on disk.
            # Handles dotfiles like .env.template, .gitignore, .python-version.
            try:
                bare_path = Path(match_str).expanduser()
                if not bare_path.is_absolute():
                    bare_path = Path.cwd() / bare_path
                if bare_path.exists() and bare_path.is_file():
                    return True
            except Exception:
                pass
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


def parse_agent_mentions_multi(
    text: str, settings: Settings | None = None
) -> list[str]:
    """Find every ``@name`` in *text* that resolves to a known agent.

    Unlike :func:`parse_agent_mentions` (which only matches a single agent at the
    very start), this scans the whole message so a request like
    ``"@dev-agent fix @app.py then hand to @test-agent"`` yields
    ``["dev-agent", "test-agent"]`` in order. ``@file`` mentions and unknown
    ``@words`` are ignored (only names matching a core subagent or a user-created
    agent count). Order-preserving and de-duplicated.
    """
    if settings is None:
        settings = Settings.from_environment()

    from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents

    core_names = {s["name"] for s in retrieve_core_subagents()}

    found: list[str] = []
    seen: set[str] = set()
    for match in ANY_MENTION_RE.finditer(text):
        name = match.group(1)
        if name in seen:
            continue
        if name in core_names or settings.find_agent(name) is not None:
            found.append(name)
            seen.add(name)
    return found
