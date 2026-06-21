"""Synthesize a generalized approval rule from a single approved tool call.

Pure and dependency-light (no I/O, no policy/state imports) so it can be reused
by both the in-memory session layer and the persistent policy writer, and unit
tested in isolation.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from urllib.parse import urlparse

# Programs whose following words are meaningful subcommands worth keeping, so
# "npm run build" generalizes to `npm run build` (not all of `npm`), while a
# bare program like `pytest` generalizes to just `pytest`.
_MULTIPLEXERS: frozenset[str] = frozenset(
    {"npm", "yarn", "pnpm", "uv", "git", "cargo", "docker", "make", "poetry", "go", "dotnet"}
)

_SHELL_TOOLS: frozenset[str] = frozenset({"shell", "execute", "run_tests", "start_dev_server"})
_PATH_TOOLS: frozenset[str] = frozenset({"write_file", "edit_file"})
_URL_TOOLS: frozenset[str] = frozenset({"fetch_url"})

# For a multiplexer, keep at most this many leading tokens (program + up to two
# non-flag subcommand words, e.g. `npm run build`) so the rule stays bounded.
_MAX_MULTIPLEXER_TOKENS: int = 3


@dataclass(frozen=True)
class ProposedRule:
    """A generalized allow-rule derived from a tool call.

    Attributes:
        category: ``"shell"`` | ``"paths"`` | ``"domains"`` | ``"tool"``.
        value: The regex / glob / domain string, or ``"allow"`` for a tool tier.
        human: Short plain-English summary for the confirm UI.
        tool_name: Originating tool (used for ``"tool"``-category tier rules).
    """

    category: str
    value: str
    human: str
    tool_name: str


def _tool_fallback(tool_name: str) -> ProposedRule:
    return ProposedRule("tool", "allow", f"Allow all {tool_name} calls", tool_name)


def _shell_rule(tool_name: str, command: str) -> ProposedRule:
    try:
        tokens = [t for t in shlex.split(command, posix=True) if t]
    except ValueError:
        tokens = [t for t in command.split() if t]
    if not tokens:
        return _tool_fallback(tool_name)
    prog = tokens[0]
    if prog in _MULTIPLEXERS:
        # Keep the program plus following non-flag subcommand words (e.g.
        # `npm run build`), stopping at the first flag and a bounded length.
        keep = [prog]
        for token in tokens[1:]:
            if token.startswith("-") or len(keep) >= _MAX_MULTIPLEXER_TOKENS:
                break
            keep.append(token)
    else:
        keep = [prog]
    value = r"^\s*" + r"\s+".join(re.escape(t) for t in keep) + r"\b"
    human = " ".join(keep)
    return ProposedRule("shell", value, f"Allow shell commands starting with `{human}`", tool_name)


def _path_rule(tool_name: str, file_path: str) -> ProposedRule:
    norm = file_path.replace("\\", "/")
    stripped = norm.strip("/")
    if "/" in stripped:
        directory = norm.rsplit("/", 1)[0] or "/"
        value = f"{directory}/**"
        human = f"`{directory}/`"
    else:
        value = "/**"
        human = "the workspace root"
    return ProposedRule("paths", value, f"Allow {tool_name} under {human}", tool_name)


def _domain_rule(tool_name: str, url: str) -> ProposedRule:
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    if not host:
        return _tool_fallback(tool_name)
    return ProposedRule("domains", host, f"Allow {tool_name} to `{host}`", tool_name)


def synthesize_rule(tool_name: str, args: dict | None) -> ProposedRule:
    """Derive a :class:`ProposedRule` from one tool call (never raises).

    Args:
        tool_name: The name of the tool being called.
        args: The tool call arguments dict, or ``None``.

    Returns:
        A :class:`ProposedRule` for the most specific matching category.
    """
    args = args or {}
    if tool_name in _SHELL_TOOLS:
        return _shell_rule(tool_name, str(args.get("command") or ""))
    if tool_name in _PATH_TOOLS:
        file_path = str(args.get("file_path") or "")
        if file_path:
            return _path_rule(tool_name, file_path)
    if tool_name in _URL_TOOLS:
        url = str(args.get("url") or "")
        if url:
            return _domain_rule(tool_name, url)
    return _tool_fallback(tool_name)
