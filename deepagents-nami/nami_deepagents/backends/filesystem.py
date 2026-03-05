"""FilesystemBackend: Read and write files directly from the filesystem.

Security and search upgrades:
- Secure path resolution with root containment when in virtual_mode (sandboxed to cwd)
- Prevent symlink-following on file I/O using O_NOFOLLOW when available
- Ripgrep-powered grep with JSON parsing, plus Python fallback with regex
  and optional glob include filtering, while preserving virtual path behavior
"""

import json
import os
import re
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

import wcmatch.glob as wcglob

from nami_deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from nami_deepagents.backends.utils import (
    check_empty_content,
    format_content_with_line_numbers,
    perform_string_replacement,
)


class FilesystemBackend(BackendProtocol):
    """Backend that reads and writes files directly from the filesystem.

    Files are accessed using their actual filesystem paths. Relative paths are
    resolved relative to the current working directory. Content is read/written
    as plain text, and metadata (timestamps) are derived from filesystem stats.

    Security Notes:
    - In virtual_mode=True: Paths are contained to root_dir with traversal prevention
    - In virtual_mode=False: Paths are validated against allowed_prefixes if set
    - Symlink attacks are mitigated with O_NOFOLLOW on POSIX systems
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
        allowed_prefixes: list[str | Path] | None = None,
    ) -> None:
        """Initialize filesystem backend.

        Args:
            root_dir: Optional root directory for file operations. If provided,
                     all file paths will be resolved relative to this directory.
                     If not provided, uses the current working directory.
            virtual_mode: If True, treat paths as virtual and enforce strict containment.
                         If False, allow absolute paths with optional prefix validation.
            max_file_size_mb: Maximum file size in megabytes to read.
            allowed_prefixes: Optional list of directory prefixes for non-virtual mode.
                             Only paths under these directories will be allowed.
                             Has no effect when virtual_mode=True.
        """
        self.cwd = Path(root_dir).resolve() if root_dir else Path.cwd()
        self.virtual_mode = virtual_mode
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        # Normalize allowed prefixes to absolute paths
        self.allowed_prefixes: list[Path] | None = [Path(p).resolve() for p in allowed_prefixes] if allowed_prefixes else None

    def _resolve_path(self, key: str) -> Path:
        """Resolve a file path with security checks.

        When virtual_mode=True, treat incoming paths as virtual absolute paths under
        self.cwd, disallow traversal (.., ~) and ensure resolved path stays within root.
        When virtual_mode=False, preserve legacy behavior: absolute paths are allowed
        with optional allowed_prefixes validation.

        Security:
        - Path traversal (..) and ~ are always blocked
        - URL-encoded traversal (%2e%2e) is blocked
        - Null bytes are blocked
        - Symlink escaping is prevented by resolving paths
        - In virtual_mode=True, paths are contained to self.cwd
        - In virtual_mode=False with allowed_prefixes, paths must be under allowed dirs

        Args:
            key: File path (absolute, relative, or virtual when virtual_mode=True)

        Returns:
            Resolved absolute Path object

        Raises:
            ValueError: If path traversal is detected or path is outside allowed directories
        """
        # Security: Block null bytes
        if "\x00" in key:
            raise ValueError(f"Null byte in path not allowed: {key[:50]}...")

        # Security: Block URL-encoded traversal (single and double-encoded)
        if "%" in key:
            try:
                decoded = urllib.parse.unquote(key)
                if ".." in decoded or "~" in decoded:
                    raise ValueError(f"URL-encoded path traversal not allowed: {key}")
                # Second pass: catch double-encoded sequences like %252e%252e
                if "%" in decoded:
                    double_decoded = urllib.parse.unquote(decoded)
                    if ".." in double_decoded or "~" in double_decoded:
                        raise ValueError(f"Double-encoded path traversal not allowed: {key}")
            except ValueError:
                raise
            except Exception:
                raise ValueError(f"Invalid URL-encoded path: {key}")

        # Security: Always check for traversal attempts
        if ".." in key or key.startswith("~"):
            raise ValueError(f"Path traversal not allowed: {key}")

        # Non-virtual mode: resolve without strict containment
        if not self.virtual_mode:
            path = Path(key)
            if path.is_absolute():
                resolved = path.resolve()
            else:
                resolved = (self.cwd / path).resolve()

            # If allowed_prefixes is set, validate path is under allowed directories
            if self.allowed_prefixes is not None:
                for prefix in self.allowed_prefixes:
                    try:
                        resolved.relative_to(prefix)
                        # Path is under this prefix, allow it
                        break
                    except ValueError:
                        continue
                else:
                    # Path is not under any allowed prefix
                    allowed_str = ", ".join(str(p) for p in self.allowed_prefixes)
                    raise ValueError(f"Path {resolved} is outside allowed directories: {allowed_str}")
            return resolved

        # Virtual mode: treat paths as virtual paths under self.cwd
        # Security: Block common system paths that could be used to escape sandbox
        blocked_prefixes = [
            "/etc/",
            "/root/",
            "/home/",
            "/var/",
            "/usr/",
            "/bin/",
            "/sbin/",
            "/proc/",
            "/sys/",
            "/dev/",
            "/boot/",
            "/lib/",
            "/lib64/",
        ]
        for blocked in blocked_prefixes:
            if key.startswith(blocked):
                raise ValueError(f"Access to system path not allowed: {key}")

        vpath = key if key.startswith("/") else "/" + key
        full = (self.cwd / vpath.lstrip("/")).resolve()
        try:
            full.relative_to(self.cwd)
        except ValueError:
            raise ValueError(f"Path {full} is outside root directory: {self.cwd}") from None
        return full

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories in the specified directory (non-recursive)."""
        dir_path = self._resolve_path(path)
        if not dir_path.exists() or not dir_path.is_dir():
            return []

        results: list[FileInfo] = []

        # WINDOWS FIX: Normalize to forward slashes for comparison
        cwd_str = str(self.cwd).replace("\\", "/")
        if not cwd_str.endswith("/"):
            cwd_str += "/"

        # List only direct children (non-recursive)
        try:
            for child_path in dir_path.iterdir():
                # Security: in virtual mode, skip symlinks that escape the sandbox
                if self.virtual_mode and child_path.is_symlink():
                    try:
                        child_path.resolve().relative_to(self.cwd)
                    except (ValueError, OSError):
                        continue
                try:
                    is_file = child_path.is_file()
                    is_dir = child_path.is_dir()
                except OSError:
                    continue

                # WINDOWS FIX: Normalize to forward slashes
                abs_path = str(child_path).replace("\\", "/")

                if not self.virtual_mode:
                    # Non-virtual mode: use absolute paths (but normalized)
                    if is_file:
                        try:
                            st = child_path.stat()
                            results.append(
                                {
                                    "path": abs_path,
                                    "is_dir": False,
                                    "size": int(st.st_size),
                                    "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                }
                            )
                        except OSError:
                            results.append({"path": abs_path, "is_dir": False})
                    elif is_dir:
                        try:
                            st = child_path.stat()
                            results.append(
                                {
                                    "path": abs_path + "/",
                                    "is_dir": True,
                                    "size": 0,
                                    "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                }
                            )
                        except OSError:
                            results.append({"path": abs_path + "/", "is_dir": True})
                else:
                    # Virtual mode: strip cwd prefix
                    if abs_path.startswith(cwd_str):
                        relative_path = abs_path[len(cwd_str) :]
                    elif abs_path.startswith(str(self.cwd).replace("\\", "/")):
                        # Handle case where cwd doesn't end with /
                        relative_path = abs_path[len(str(self.cwd).replace("\\", "/")) :].lstrip("/")
                    else:
                        # Path is outside cwd, return as-is or skip
                        relative_path = abs_path

                    virt_path = "/" + relative_path

                    if is_file:
                        try:
                            st = child_path.stat()
                            results.append(
                                {
                                    "path": virt_path,
                                    "is_dir": False,
                                    "size": int(st.st_size),
                                    "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                }
                            )
                        except OSError:
                            results.append({"path": virt_path, "is_dir": False})
                    elif is_dir:
                        try:
                            st = child_path.stat()
                            results.append(
                                {
                                    "path": virt_path + "/",
                                    "is_dir": True,
                                    "size": 0,
                                    "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                                }
                            )
                        except OSError:
                            results.append({"path": virt_path + "/", "is_dir": True})
        except (OSError, PermissionError):
            pass

        # Keep deterministic order by path
        results.sort(key=lambda x: x.get("path", ""))
        return results

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content with line numbers.

        Args:
            file_path: Absolute or relative file path.
            offset: Line offset to start reading from (0-indexed).
            limit: Maximum number of lines to read.

        Returns:
            Formatted file content with line numbers, or error message.
        """
        resolved_path = self._resolve_path(file_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return f"Error: File '{file_path}' not found"

        try:
            # Open with O_NOFOLLOW where available to avoid symlink traversal
            fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                content = f.read()

            empty_msg = check_empty_content(content)
            if empty_msg:
                return empty_msg

            lines = content.splitlines()
            start_idx = offset
            end_idx = min(start_idx + limit, len(lines))

            if start_idx >= len(lines):
                return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

            selected_lines = lines[start_idx:end_idx]
            return format_content_with_line_numbers(selected_lines, start_line=start_idx + 1)
        except (OSError, UnicodeDecodeError) as e:
            return f"Error reading file '{file_path}': {e}"

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file with content.
        Returns WriteResult. External storage sets files_update=None.
        """
        resolved_path = self._resolve_path(file_path)

        if resolved_path.exists():
            return WriteResult(error=f"Cannot write to {file_path} because it already exists. Read and then make an edit, or write to a new path.")

        try:
            # Create parent directories if needed (validate chain in virtual mode first)
            self._validate_parent_chain(resolved_path)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)

            # Prefer O_NOFOLLOW to avoid writing through symlinks
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved_path, flags, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            return WriteResult(path=file_path, files_update=None)
        except (OSError, UnicodeEncodeError) as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences.
        Returns EditResult. External storage sets files_update=None.
        """
        resolved_path = self._resolve_path(file_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return EditResult(error=f"Error: File '{file_path}' not found")

        try:
            # Read securely
            fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                content = f.read()

            result = perform_string_replacement(content, old_string, new_string, replace_all)

            if isinstance(result, str):
                return EditResult(error=result)

            new_content, occurrences = result

            # Write securely
            flags = os.O_WRONLY | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved_path, flags)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)

            return EditResult(path=file_path, files_update=None, occurrences=int(occurrences))
        except (OSError, UnicodeDecodeError, UnicodeEncodeError) as e:
            return EditResult(error=f"Error editing file '{file_path}': {e}")

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        # Security: Limit pattern complexity to prevent ReDoS
        MAX_PATTERN_LENGTH = 5000
        if len(pattern) > MAX_PATTERN_LENGTH:
            return f"Pattern too long (max {MAX_PATTERN_LENGTH} chars)"

        # Validate regex
        try:
            compiled = re.compile(pattern)
            # Warn about potentially slow patterns (nested quantifiers)
            # This is a heuristic check for common ReDoS patterns
            if re.search(r"(\+|\*|\{[\d,]+\})\s*(\+|\*|\{[\d,]+\})", pattern):
                # Complex nested quantifiers - could be slow
                pass  # Allow but will timeout if slow
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        # Resolve base path
        try:
            base_full = self._resolve_path(path or ".")
        except ValueError:
            return []

        if not base_full.exists():
            return []

        # Try ripgrep first
        results = self._ripgrep_search(pattern, base_full, glob)
        if results is None:
            results = self._python_search(pattern, base_full, glob)

        matches: list[GrepMatch] = []
        for fpath, items in results.items():
            for line_num, line_text in items:
                matches.append({"path": fpath, "line": int(line_num), "text": line_text})
        return matches

    def _ripgrep_search(self, pattern: str, base_full: Path, include_glob: str | None) -> dict[str, list[tuple[int, str]]] | None:
        cmd = ["rg", "--json"]
        if include_glob:
            cmd.extend(["--glob", include_glob])
        cmd.extend(["--", pattern, str(base_full)])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        results: dict[str, list[tuple[int, str]]] = {}
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
            p = Path(ftext)
            if self.virtual_mode:
                try:
                    # WINDOWS FIX: Normalize to forward slashes
                    rel_path = str(p.resolve().relative_to(self.cwd)).replace("\\", "/")
                    virt = "/" + rel_path
                except Exception:
                    continue
            else:
                virt = str(p)
            ln = pdata.get("line_number")
            lt = pdata.get("lines", {}).get("text", "").rstrip("\n")
            if ln is None:
                continue
            results.setdefault(virt, []).append((int(ln), lt))

        return results

    def _validate_parent_chain(self, path: Path) -> None:
        """In virtual mode, ensure no not-yet-existing parent is an outbound symlink.

        Args:
            path: The resolved file path whose parents may be auto-created.

        Raises:
            ValueError: If any parent component is a symlink outside the sandbox.
        """
        if not self.virtual_mode:
            return
        check = path.parent
        while check != check.parent:  # stop at filesystem root
            if check.exists():
                break  # existing dirs were already validated at resolve time
            if check.is_symlink():
                try:
                    check.resolve().relative_to(self.cwd)
                except (ValueError, OSError):
                    raise ValueError(
                        f"Parent path {check} is a symlink outside sandbox"
                    ) from None
            check = check.parent

    def _python_search(self, pattern: str, base_full: Path, include_glob: str | None) -> dict[str, list[tuple[int, str]]]:
        try:
            regex = re.compile(pattern)
        except re.error:
            return {}

        results: dict[str, list[tuple[int, str]]] = {}
        root = base_full if base_full.is_dir() else base_full.parent

        # Security: followlinks=False prevents circular-symlink DoS and sandbox escape
        walk_iter = (
            Path(dirpath) / filename
            for dirpath, _dirs, filenames in os.walk(root, followlinks=False)
            for filename in filenames
        )
        for fp in walk_iter:
            if include_glob:
                # Match against both filename and relative path so patterns like
                # "src/**/*.py" work correctly, not just simple "*.py" patterns.
                try:
                    rel = str(fp.relative_to(root)).replace("\\", "/")
                except ValueError:
                    rel = fp.name
                if not (
                    wcglob.globmatch(fp.name, include_glob, flags=wcglob.BRACE)
                    or wcglob.globmatch(rel, include_glob, flags=wcglob.BRACE | wcglob.GLOBSTAR)
                ):
                    continue
            try:
                if fp.stat().st_size > self.max_file_size_bytes:
                    continue
            except OSError:
                continue
            try:
                content = fp.read_text()
            except (UnicodeDecodeError, PermissionError, OSError):
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    if self.virtual_mode:
                        try:
                            # WINDOWS FIX: Normalize to forward slashes
                            rel_path = str(fp.resolve().relative_to(self.cwd)).replace("\\", "/")
                            virt_path = "/" + rel_path
                        except Exception:
                            continue
                    else:
                        virt_path = str(fp)
                    results.setdefault(virt_path, []).append((line_num, line))

        return results

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """List files matching a glob pattern."""
        # Normalize pattern to use forward slashes (wcmatch.glob expects this)
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")
        pattern = pattern.replace("\\", "/")

        search_path = self.cwd if path == "/" else self._resolve_path(path)
        if not search_path.exists() or not search_path.is_dir():
            return []

        results: list[FileInfo] = []
        try:
            # Use wcmatch.glob for advanced pattern support including **
            # FORCEUNIX flag ensures forward slash handling on all platforms
            flags = wcglob.GLOBSTAR | wcglob.BRACE | wcglob.FORCEUNIX
            matched_paths = wcglob.glob(pattern, root_dir=str(search_path), flags=flags)

            for matched_rel in matched_paths:
                matched_path = search_path / matched_rel
                # Security: in virtual mode, skip symlinks that escape the sandbox
                if self.virtual_mode and matched_path.is_symlink():
                    try:
                        matched_path.resolve().relative_to(self.cwd)
                    except (ValueError, OSError):
                        continue
                try:
                    is_file = matched_path.is_file()
                except OSError:
                    continue
                if not is_file:
                    continue

                # WINDOWS FIX: Normalize to forward slashes
                abs_path = str(matched_path).replace("\\", "/")

                if not self.virtual_mode:
                    try:
                        st = matched_path.stat()
                        results.append(
                            {
                                "path": abs_path,
                                "is_dir": False,
                                "size": int(st.st_size),
                                "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                            }
                        )
                    except OSError:
                        results.append({"path": abs_path, "is_dir": False})
                else:
                    # WINDOWS FIX: Normalize cwd to forward slashes
                    cwd_str = str(self.cwd).replace("\\", "/")
                    if not cwd_str.endswith("/"):
                        cwd_str += "/"

                    if abs_path.startswith(cwd_str):
                        relative_path = abs_path[len(cwd_str) :]
                    elif abs_path.startswith(str(self.cwd).replace("\\", "/")):
                        relative_path = abs_path[len(str(self.cwd).replace("\\", "/")) :].lstrip("/")
                    else:
                        relative_path = abs_path

                    virt = "/" + relative_path
                    try:
                        st = matched_path.stat()
                        results.append(
                            {
                                "path": virt,
                                "is_dir": False,
                                "size": int(st.st_size),
                                "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
                            }
                        )
                    except OSError:
                        results.append({"path": virt, "is_dir": False})
        except (OSError, ValueError):
            pass

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the filesystem.

        Args:
            files: List of (path, content) tuples where content is bytes.

        Returns:
            List of FileUploadResponse objects, one per input file.
            Response order matches input order.
        """
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                resolved_path = self._resolve_path(path)

                # Create parent directories if needed (validate chain in virtual mode first)
                self._validate_parent_chain(resolved_path)
                resolved_path.parent.mkdir(parents=True, exist_ok=True)

                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW  # type: ignore
                fd = os.open(resolved_path, flags, 0o644)
                with os.fdopen(fd, "wb") as f:
                    f.write(content)

                responses.append(FileUploadResponse(path=path, error=None))
            except FileNotFoundError:
                responses.append(FileUploadResponse(path=path, error="file_not_found"))
            except PermissionError:
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except (ValueError, OSError) as e:
                # ValueError from _resolve_path for path traversal, OSError for other file errors
                if isinstance(e, ValueError) or "invalid" in str(e).lower():
                    responses.append(FileUploadResponse(path=path, error="invalid_path"))
                else:
                    # Generic error fallback
                    responses.append(FileUploadResponse(path=path, error="invalid_path"))

        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the filesystem.

        Args:
            paths: List of file paths to download.

        Returns:
            List of FileDownloadResponse objects, one per input path.
        """
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                resolved_path = self._resolve_path(path)
                # Use flags to optionally prevent symlink following if
                # supported by the OS
                fd = os.open(resolved_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as f:
                    content = f.read()
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except FileNotFoundError:
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
            except PermissionError:
                responses.append(FileDownloadResponse(path=path, content=None, error="permission_denied"))
            except IsADirectoryError:
                responses.append(FileDownloadResponse(path=path, content=None, error="is_directory"))
            except ValueError:
                responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
            # Let other errors propagate
        return responses
