"""Optimized FilesystemBackend wrapping deepagents.backends.filesystem.

Two improvements over the upstream :class:`FilesystemBackend`, both delivered as
method overrides so the parent's ``grep()`` orchestration is reused unchanged:

1. **grep hang fix** — the upstream Python fallback walks the tree with
   ``rglob("*")``, which cannot skip large, uninteresting directories (``.venv``,
   ``.git``, ``node_modules``). On a repo with a vendored virtualenv this walks
   millions of files and blows past the timeout. We override ``_python_search``
   to use ``os.walk`` with in-place ``dirnames`` pruning so those subtrees are
   never descended into.

2. **Regex support** — ``grep()`` gains an opt-in ``use_regex`` flag. The default
   (``False``) preserves the exact literal-search behaviour, so this is fully
   backward-compatible.

Because the parent ``grep()`` calls ``self._ripgrep_search(...)`` and
``self._python_search(...)``, overriding those two methods is enough for the
literal path to benefit automatically — ``grep()`` is only overridden to thread
the new ``use_regex`` flag through.
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
from deepagents.backends.protocol import GrepResult

__all__ = ["OptimizedFilesystemBackend"]

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
    rel = str(p)[len(anchor):].replace("\\", "/")
    try:
        return list(Path(anchor).glob(rel))
    except (OSError, ValueError):
        return []

# Directory names pruned during the Python grep fallback. These are virtually
# always gitignored and can each hold millions of files; descending into them is
# what made the fallback hang. An explicit search *into* one of these (e.g.
# path="/node_modules") still works — only nested occurrences are skipped.
_SKIP_DIRS = frozenset({
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
})


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

        cmd = [rg_path, "--json"]
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
        regex = re.compile(pattern)
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
                    d for d in dirnames
                    if d not in _SKIP_DIRS and not d.endswith(".egg-info")
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
