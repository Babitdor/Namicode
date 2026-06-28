"""Optimized FilesystemBackend wrapping deepagents.backends.filesystem.

Improvements over the upstream :class:`FilesystemBackend`, all delivered as
method overrides (the deepagents package is never modified — the filesystem
tools call ``backend.read/edit/glob/grep``, so overriding those backend methods
improves the tools transparently):

1. **grep hang fix** — the upstream Python fallback walks the tree with
   ``rglob("*")``, which cannot skip large, uninteresting directories (``.venv``,
   ``.git``, ``node_modules``). We override ``_python_search`` to use ``os.walk``
   with in-place ``dirnames`` pruning so those subtrees are never descended into.

2. **Regex support** — ``grep()`` gains an opt-in ``use_regex`` flag, fully
   backward-compatible with the literal default.

3. **Smart-case grep** — a lower-case pattern matches case-insensitively; a
   pattern with any upper-case letter stays case-sensitive (ripgrep's default).

4. **read encoding recovery** — ``read()`` falls back to ``utf-8-sig`` / cp1252 /
   latin-1 when a file isn't utf-8, instead of returning a decode error.

5. **edit failure hints** — a failed ``edit()`` gets an actionable hint (closest
   line for a miss, replace_all/disambiguation tip for an ambiguous match).

6. **glob prune + ordering** — ``glob()`` drops vendored-dir noise and returns
   newest-first.

Async tool calls (``aread``/``aedit``/``aglob``/``agrep``) delegate to these
sync methods via ``asyncio.to_thread`` in the protocol base, so they are covered
too without overriding the async variants.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import wcmatch.glob as wcglob
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.protocol import EditResult, GlobResult, GrepResult, ReadResult

__all__ = ["OptimizedFilesystemBackend", "OptimizedLocalShellBackend"]

# Wall-clock budget for a single grep, in seconds. Defined locally rather than
# imported from deepagents.backends.protocol: the constant only exists in
# deepagents>=0.6.8, but Nova is launched against environments still on 0.6.7
# (e.g. a miniconda install). The value matches upstream's default.
_GREP_TIMEOUT = 30


@functools.cache
def _resolve_ripgrep_path() -> str | None:
    r"""Locate the ``rg`` executable, more thoroughly than ``shutil.which``.

    The upstream resolver only checks ``PATH``. On Windows, package managers like
    winget install ripgrep as a loose archive and never link it onto ``PATH``
    (e.g. ``...\\WinGet\\Packages\\BurntSushi.ripgrep...\\rg.exe``), so the agent
    silently falls back to the slow Python search even though ripgrep is present.

    Resolution order:
    1. ``NOVA_RIPGREP_PATH`` / ``RIPGREP_PATH`` env override (explicit wins).
    2. ``shutil.which`` (honours ``PATH`` — the fast, normal case).
    3. Known package-manager install locations (winget, VS Code bundle, cargo,
       scoop, chocolatey), globbed for the versioned subdirectories they use.

    Cached for the process lifetime; ``cache_clear()`` re-probes.
    """
    for env_var in ("NOVA_RIPGREP_PATH", "RIPGREP_PATH"):
        override = os.environ.get(env_var)
        if override and Path(override).is_file():
            return override

    for name in ("rg", "rg.exe"):
        found = shutil.which(name)
        if found:
            return found

    # Glob patterns for package managers that don't touch PATH. Each may contain
    # a version directory, so we glob and take the newest match.
    local = os.environ.get("LOCALAPPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")
    programdata = os.environ.get("PROGRAMDATA", "")
    candidates: list[str] = []
    if local:
        candidates += [
            # winget loose-archive install
            rf"{local}\Microsoft\WinGet\Packages\BurntSushi.ripgrep*\**\rg.exe",
            # VS Code bundled ripgrep
            rf"{local}\Programs\Microsoft VS Code\resources\app\node_modules*\**\rg.exe",
        ]
    if userprofile:
        candidates += [
            rf"{userprofile}\.cargo\bin\rg.exe",
            rf"{userprofile}\scoop\shims\rg.exe",
            rf"{userprofile}\scoop\apps\ripgrep\**\rg.exe",
        ]
    if programdata:
        candidates.append(rf"{programdata}\chocolatey\bin\rg.exe")

    newest: tuple[float, str] | None = None
    for pattern in candidates:
        for match in _glob_abs(pattern):
            try:
                if not match.is_file():
                    continue
                mtime = match.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest[0]:
                newest = (mtime, str(match))
    return newest[1] if newest else None


def _glob_abs(windows_pattern: str) -> list[Path]:
    r"""Glob an absolute Windows pattern by anchoring at its drive root.

    ``Path.glob`` rejects absolute/drive-anchored patterns, so split off the
    anchor (e.g. ``C:\\``) and glob the remainder against it:
    ``C:\\a\\**\\rg.exe`` → ``Path("C:\\").glob("a/**/rg.exe")``.
    """
    p = Path(windows_pattern)
    anchor = p.anchor
    if not anchor:
        return list(Path().glob(str(p).replace("\\", "/")))
    rel = str(p)[len(anchor) :].replace("\\", "/")
    try:
        return list(Path(anchor).glob(rel))
    except (OSError, ValueError):
        return []


# Directory names pruned during the Python grep fallback. These are virtually
# always gitignored and can each hold millions of files; descending into them is
# what made the fallback hang. An explicit search *into* one of these (e.g.
# path="/node_modules") still works — only nested occurrences are skipped.
_SKIP_DIRS = frozenset(
    {
        ".venv",
        ".env",
        "venv",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".turbo",
        ".cargo",
        "target",
        "out",
        ".vscode",
        ".idea",
    }
)


class OptimizedFilesystemBackend(FilesystemBackend):
    """FilesystemBackend with a non-hanging grep fallback and regex support."""

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        use_regex: bool = False,
    ) -> GrepResult:
        """Search for a pattern in files.

        Args:
            pattern: Text to search for. Literal by default; a regular expression
                when ``use_regex=True``.
            path: Directory or file to search in. Defaults to the current directory.
            glob: Optional glob to filter which files are searched (e.g. ``"*.py"``).
            use_regex: If ``False`` (default) ``pattern`` is matched literally; if
                ``True`` it is compiled as a Python regular expression.

        Returns:
            A ``GrepResult`` with matches or an error.
        """
        # Literal mode is the parent's exact behaviour — and since the parent
        # calls self._ripgrep_search / self._python_search, it already picks up
        # both of our overrides (hang fix included). No need to duplicate it.
        if not use_regex:
            return super().grep(pattern, path, glob)

        # Regex mode: same orchestration as the parent, but the pattern is passed
        # through unescaped to both ripgrep (no -F) and the Python fallback.
        try:
            base_full = self._resolve_path(path or ".")
            if not base_full.exists():
                return GrepResult(matches=[])
        except ValueError:
            return GrepResult(matches=[])
        except (OSError, RuntimeError) as e:
            return GrepResult(error=f"Error searching path '{path or '.'}': {e}", matches=[])

        try:
            re.compile(pattern)
        except re.error as e:
            return GrepResult(error=f"Invalid regex pattern: {e}", matches=[])

        results = self._ripgrep_search(pattern, base_full, glob, use_regex=True)
        partial_error: str | None = None
        if results is None:
            results, partial_error = self._python_search(pattern, base_full, glob)

        matches = [
            {"path": fpath, "line": int(line_num), "text": line_text}
            for fpath, items in results.items()
            for line_num, line_text in items
        ]
        return GrepResult(error=partial_error, matches=matches)

    def _ripgrep_search(  # noqa: PLR0912, PLR0915
        self,
        pattern: str,
        base_full: Path,
        include_glob: str | None,
        *,
        use_regex: bool = False,
    ) -> dict[str, list[tuple[int, str]]] | None:
        """Search with ripgrep.

        Identical to the upstream implementation except that the fixed-string
        flag (``-F``) is omitted when ``use_regex`` is set, so the pattern is
        interpreted as a regular expression. The parent's literal ``grep()`` call
        passes no ``use_regex`` and therefore keeps ``-F``.

        Returns ``None`` to signal "fall back to the Python search" (ripgrep
        missing, timed out, or errored).
        """
        rg_path = _resolve_ripgrep_path()
        if rg_path is None:
            return None

        # --smart-case: a lower-case pattern matches case-insensitively, but a
        # pattern containing an upper-case letter stays case-sensitive. Matches
        # ripgrep's CLI default and the Python fallback below, so literal grep is
        # forgiving for the common lower-case query without losing precision.
        cmd = [rg_path, "--json", "--smart-case"]
        if not use_regex:
            cmd.append("-F")  # fixed-string (literal) mode
        if include_glob:
            cmd.extend(["--glob", include_glob])

        rg_cwd: str | None = None
        if base_full.is_dir():
            cmd.extend(["--", pattern, "."])
            rg_cwd = str(base_full)
        else:
            cmd.extend(["--", pattern, str(base_full)])

        try:
            proc = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=_GREP_TIMEOUT,
                check=False,
                cwd=rg_cwd,
            )
        except subprocess.TimeoutExpired:
            return None
        except (FileNotFoundError, PermissionError, NotADirectoryError):
            # rg resolved at cache time but failed to exec — re-probe next call.
            _resolve_ripgrep_path.cache_clear()
            return None

        # 0 = match, 1 = no match (both fine); 2+ = hard error → fall back.
        if proc.returncode not in (0, 1):
            return None

        results: dict[str, list[tuple[int, str]]] = {}
        base_resolved = base_full.resolve()
        # On Windows, proc.stdout can be None even with a 0/1 returncode.
        # Treat that as "no matches" rather than crashing on splitlines().
        if not proc.stdout:
            return results
        for line in proc.stdout.splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("type") != "match":
                continue
            pdata = data.get("data", {})
            ftext = pdata.get("path", {}).get("text")
            if not ftext:
                continue
            raw = Path(ftext)
            p = raw if raw.is_absolute() else (base_full / raw)
            # Containment guard: drop any result that resolves outside the root.
            try:
                p.resolve().relative_to(base_resolved)
            except (ValueError, OSError):
                continue
            if self.virtual_mode:
                try:
                    virt = self._to_virtual_path(p)
                except (ValueError, OSError, RuntimeError):
                    continue
            else:
                virt = str(p)
            ln = pdata.get("line_number")
            if ln is None:
                continue
            lt = pdata.get("lines", {}).get("text", "").rstrip("\n")
            results.setdefault(virt, []).append((int(ln), lt))

        return results

    def _python_search(  # noqa: PLR0912
        self,
        pattern: str,
        base_full: Path,
        include_glob: str | None,
        *,
        timeout: int = _GREP_TIMEOUT,
    ) -> tuple[dict[str, list[tuple[int, str]]], str | None]:
        """Python fallback that prunes large directories to avoid hanging.

        Drop-in replacement for the upstream ``_python_search`` (same signature,
        so the parent ``grep()`` calls this automatically). The only behavioural
        difference is that subtrees in :data:`_SKIP_DIRS` are never descended
        into, which is what kept the upstream version from completing on repos
        with a vendored ``.venv`` / ``node_modules``.

        Args:
            pattern: Regex pattern. Callers pass ``re.escape(...)`` for a literal
                search (the parent does this) or a raw regex for regex mode.
            base_full: Resolved base path to search.
            include_glob: Optional glob to filter files.
            timeout: Wall-clock budget in seconds.

        Returns:
            ``(results, partial_error)``; ``partial_error`` is set when the walk
            was cut short by the timeout or aborted mid-iteration.
        """
        deadline = time.monotonic() + timeout
        # Smart-case to mirror the ripgrep path: case-insensitive unless the
        # pattern carries an upper-case letter. `pattern` is already re.escape'd
        # for literal searches, which never adds upper-case, so the check is safe.
        smart_flags = re.IGNORECASE if pattern == pattern.lower() else 0
        regex = re.compile(pattern, smart_flags)
        results: dict[str, list[tuple[int, str]]] = {}
        root = base_full if base_full.is_dir() else base_full.parent

        def _timed_out() -> str:
            return (
                f"Grep of '{base_full}' timed out after {timeout}s with "
                f"{len(results)} matching file(s); try a more specific pattern "
                f"or a narrower path."
            )

        try:
            for dirpath, dirnames, filenames in os.walk(str(root)):
                if time.monotonic() > deadline:
                    return results, _timed_out()

                # Prune in place so os.walk never descends into skipped subtrees.
                dirnames[:] = [
                    d for d in dirnames if d not in _SKIP_DIRS and not d.endswith(".egg-info")
                ]

                for filename in filenames:
                    if time.monotonic() > deadline:
                        return results, _timed_out()

                    fp = Path(dirpath) / filename

                    if include_glob:
                        rel_path = str(fp.relative_to(root))
                        if not wcglob.globmatch(
                            rel_path, include_glob, flags=wcglob.BRACE | wcglob.GLOBSTAR
                        ):
                            continue

                    try:
                        if fp.stat().st_size > self.max_file_size_bytes:
                            continue
                    except (OSError, RuntimeError):
                        continue

                    try:
                        content = fp.read_text()
                    except (UnicodeDecodeError, PermissionError, OSError, RuntimeError):
                        continue

                    for line_num, line in enumerate(content.splitlines(), 1):
                        if not regex.search(line):
                            continue
                        if self.virtual_mode:
                            try:
                                virt_path = self._to_virtual_path(fp)
                            except (ValueError, OSError, RuntimeError):
                                continue
                        else:
                            virt_path = str(fp)
                        results.setdefault(virt_path, []).append((line_num, line))

        except (OSError, RuntimeError) as e:
            msg = f"Grep of '{base_full}' aborted after {len(results)} matching file(s): {e}"
            return results, msg

        return results, None

    # -- read: recover non-utf-8 files ---------------------------------------

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """Read a file, recovering from a utf-8 decode failure.

        Upstream opens text files as utf-8 only, so a cp1252 / latin-1 / UTF-16
        file returns a decode error and reads *nothing*. On that error we re-read
        the bytes through a short encoding ladder (``latin-1`` always succeeds),
        returning the same windowed ``ReadResult`` the tool expects.
        """
        result = super().read(file_path, offset, limit)
        if result.error and "codec can't decode" in result.error:
            recovered = self._read_fallback_encoding(file_path, offset, limit)
            if recovered is not None:
                return recovered
        return result

    def _read_fallback_encoding(
        self, file_path: str, offset: int, limit: int
    ) -> ReadResult | None:
        """Re-read ``file_path`` trying non-utf-8 encodings; ``None`` if all fail."""
        try:
            raw = self._resolve_path(file_path).read_bytes()
        except (OSError, RuntimeError, ValueError):
            return None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                content = raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
            lines = content.splitlines(keepends=True)
            if lines and offset >= len(lines):
                return ReadResult(
                    error=f"Line offset {offset} exceeds file length ({len(lines)} lines)"
                )
            end = min(offset + limit, len(lines))
            windowed = "".join(lines[offset:end])
            return ReadResult(file_data={"content": windowed, "encoding": "utf-8"})
        return None

    # -- edit: actionable failure feedback -----------------------------------

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        """Edit a file, adding a recovery hint when the match fails.

        The upstream error ("String not found" / "appears N times") tells the
        model *that* it failed but not how to fix it. We append a hint — the
        closest line for a miss, or a replace_all/disambiguation tip for an
        ambiguous match — so the next attempt usually lands.
        """
        result = super().edit(file_path, old_string, new_string, replace_all)
        if not result.error:
            return result
        hint = self._edit_failure_hint(file_path, old_string, result.error)
        if hint:
            return EditResult(error=f"{result.error}\n\n{hint}")
        return result

    def _edit_failure_hint(self, file_path: str, old_string: str, error: str) -> str | None:
        """Build a one-line recovery hint for a failed edit (``None`` if none)."""
        low = error.lower()
        if "appears" in low and "times" in low:
            return (
                "Hint: pass replace_all=True to change every occurrence, or extend "
                "old_string with surrounding lines so it matches exactly one place."
            )
        if "not found" not in low:
            return None
        try:
            content = self._resolve_path(file_path).read_text(encoding="utf-8", errors="replace")
        except (OSError, RuntimeError, ValueError):
            return None
        first = next((ln for ln in old_string.splitlines() if ln.strip()), "")
        needle = re.sub(r"\s+", " ", first).strip()
        if not needle:
            return None
        # Whitespace-insensitive locate: indentation / internal-spacing drift is
        # the most common reason an otherwise-correct old_string doesn't match.
        for i, line in enumerate(content.splitlines(), 1):
            norm = re.sub(r"\s+", " ", line).strip()
            if norm and needle in norm:
                return (
                    f"Hint: no exact match, but line {i} is close:\n  {i}: {line}\n"
                    "old_string must match byte-for-byte (indentation, quotes, trailing "
                    f"spaces). Re-read around line {i} and copy the exact text."
                )
        return None

    # -- glob: prune noise + newest-first ------------------------------------

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Glob, then drop vendored-dir noise and order newest-first.

        Bare ``glob`` over a repo with a vendored ``.venv`` / ``node_modules``
        returns thousands of irrelevant hits in arbitrary order. We filter out
        the same :data:`_SKIP_DIRS` the grep fallback prunes and sort by mtime so
        the files the user is likely working on come first.
        """
        result = super().glob(pattern, path)
        if result.error or not result.matches:
            return result
        pruned = [m for m in result.matches if not self._under_skip_dir(m.get("path", ""))]
        pruned.sort(key=lambda m: self._best_effort_mtime(m.get("path", "")), reverse=True)
        return GlobResult(matches=pruned)

    @staticmethod
    def _under_skip_dir(path_str: str) -> bool:
        """True if any path segment is a pruned vendored directory."""
        return any(part in _SKIP_DIRS for part in Path(path_str.replace("\\", "/")).parts)

    def _best_effort_mtime(self, path_str: str) -> float:
        """Modification time of ``path_str`` (real/virtual), ``0.0`` if unstattable."""
        try:
            return self._resolve_path(path_str).stat().st_mtime
        except (OSError, RuntimeError, ValueError):
            return 0.0


class OptimizedLocalShellBackend(LocalShellBackend, OptimizedFilesystemBackend):
    """A ``LocalShellBackend`` that uses Nova's guarded, non-hanging grep.

    Nova's local-mode composite default backend must support the ``execute``
    tool (so subagents can run commands), which is why deepagents'
    :class:`LocalShellBackend` is used. But ``LocalShellBackend`` subclasses the
    *base* deepagents ``FilesystemBackend``, whose ``_ripgrep_search`` lacks the
    Windows None-stdout guard and whose Python fallback walks ``.venv`` /
    ``node_modules`` (the hang this package fixes). The MRO here —
    ``LocalShellBackend`` → :class:`OptimizedFilesystemBackend` → ``FilesystemBackend``
    — keeps ``execute`` from the former while resolving ``grep`` /
    ``_ripgrep_search`` to the optimized, guarded versions. No new behaviour of
    its own.
    """
