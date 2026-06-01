"""Git-related tools for version control operations.

Provides tools for:
- git_status: Check repository status (branch, staged, unstaged, untracked)
- git_log: View commit history with structured output
- git_diff: Compare commits or working tree changes
- git_blame: Line-by-line attribution for files
"""

import subprocess
from pathlib import Path
from typing import Any

from novacode_cli.git_safety import (
    BLOCKED_COMMANDS,
    DANGEROUS_GIT_COMMANDS,
    detect_command_injection,
    extract_command_prefix,
)


def _run_git_command(args: list[str], cwd: str | Path | None = None) -> tuple[int, str, str]:
    """Run a git command and return exit code, stdout, stderr.

    Args:
        args: Git command arguments (e.g., ['status', '--porcelain'])
        cwd: Working directory (defaults to current directory)

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,  # 30 second timeout for safety
            encoding="utf-8",
            errors="replace",  # Replace undecodable characters
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", "git command not found"
    except Exception as e:
        return -1, "", str(e)


def validate_git_command(command: str) -> dict[str, Any]:
    """Validate a git command for safety before execution.

    Checks for:
    - Command injection patterns
    - Blocked commands
    - Dangerous commands requiring approval

    Args:
        command: The git command to validate

    Returns:
        Dictionary containing:
        - safe: bool - Whether the command is safe to execute
        - requires_approval: bool - Whether command requires user approval
        - reason: str - Reason if command is unsafe or requires approval
        - command_prefix: str - The extracted command prefix
    """
    # Check for command injection
    if detect_command_injection(command):
        return {
            "safe": False,
            "requires_approval": False,
            "reason": "Command injection detected - command contains suspicious patterns",
            "command_prefix": "command_injection_detected",
        }

    # Extract command prefix
    command_prefix = extract_command_prefix(command)

    # Check for blocked commands
    for blocked, reason in BLOCKED_COMMANDS.items():
        if blocked in command:
            return {
                "safe": False,
                "requires_approval": False,
                "reason": f"Blocked command: {reason}",
                "command_prefix": command_prefix,
            }

    # Check for dangerous commands
    for dangerous, reason in DANGEROUS_GIT_COMMANDS.items():
        if dangerous in command:
            return {
                "safe": True,
                "requires_approval": True,
                "reason": f"Dangerous operation: {reason}",
                "command_prefix": command_prefix,
            }

    return {
        "safe": True,
        "requires_approval": False,
        "reason": "",
        "command_prefix": command_prefix,
    }


def git_status(
    path: str | None = None,
    porcelain: bool = False,
) -> dict[str, Any]:
    """Check git repository status.

    Shows branch, staged files, unstaged changes, and untracked files.

    Args:
        path: Directory to check (defaults to current directory)
        porcelain: If True, return machine-readable output

    Returns:
        Dictionary containing:
        - success: bool - Whether the command succeeded
        - branch: str - Current branch name
        - staged: list - Staged files with status
        - unstaged: list - Unstaged changes with status
        - untracked: list - Untracked files
        - ahead: int - Commits ahead of upstream
        - behind: int - Commits behind upstream
        - clean: bool - Whether the working tree is clean
        - error: str - Error message (if failed)

    Example:
        git_status()
        git_status(path="/path/to/repo")
        git_status(porcelain=True)
    """
    work_dir = Path(path) if path else Path.cwd()

    # Check if we're in a git repository
    exit_code, _, stderr = _run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Not a git repository",
            "path": str(work_dir),
        }

    # Get branch name
    exit_code, branch, stderr = _run_git_command(["branch", "--show-current"], cwd=work_dir)
    if exit_code != 0:
        # Try to get HEAD reference (detached HEAD state)
        exit_code, branch, stderr = _run_git_command(["rev-parse", "--short", "HEAD"], cwd=work_dir)
        if exit_code != 0:
            branch = "unknown"
    branch = branch.strip()

    # Get porcelain status
    exit_code, status_output, stderr = _run_git_command(
        ["status", "--porcelain", "-b"], cwd=work_dir
    )
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Failed to get status",
            "path": str(work_dir),
        }

    # Parse status
    staged = []
    unstaged = []
    untracked = []
    ahead = 0
    behind = 0

    for line in status_output.strip().split("\n"):
        if not line:
            continue

        # Branch tracking info (## branch...upstream [ahead N, behind M])
        if line.startswith("## "):
            branch_info = line[3:]
            if "ahead" in branch_info:
                try:
                    ahead = int(branch_info.split("ahead ")[1].split(",")[0].split("]")[0])
                except (IndexError, ValueError):
                    pass
            if "behind" in branch_info:
                try:
                    behind = int(branch_info.split("behind ")[1].split(",")[0].split("]")[0])
                except (IndexError, ValueError):
                    pass
            continue

        # File status (XY filename)
        if len(line) >= 2:
            x = line[0]  # Staged status
            y = line[1]  # Unstaged status
            filename = line[3:].strip() if len(line) > 2 else ""

            # Staged changes (X column)
            if x in "MADRC":  # Modified, Added, Deleted, Renamed, Copied
                status_map = {
                    "M": "modified",
                    "A": "added",
                    "D": "deleted",
                    "R": "renamed",
                    "C": "copied",
                }
                staged.append({"file": filename, "status": status_map.get(x, x)})

            # Unstaged changes (Y column)
            if y in "MD":  # Modified, Deleted
                status_map = {"M": "modified", "D": "deleted"}
                unstaged.append({"file": filename, "status": status_map.get(y, y)})

            # Untracked files
            if line.startswith("??"):
                untracked.append(filename)

    clean = not (staged or unstaged or untracked)

    if porcelain:
        return {
            "success": True,
            "branch": branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "ahead": ahead,
            "behind": behind,
            "clean": clean,
        }

    # Human-readable summary
    summary_parts = []
    if branch:
        summary_parts.append(f"On branch {branch}")
    if ahead:
        summary_parts.append(f"{ahead} commit(s) ahead of upstream")
    if behind:
        summary_parts.append(f"{behind} commit(s) behind upstream")
    if clean:
        summary_parts.append("Working tree clean")
    else:
        if staged:
            summary_parts.append(f"{len(staged)} file(s) staged")
        if unstaged:
            summary_parts.append(f"{len(unstaged)} file(s) modified")
        if untracked:
            summary_parts.append(f"{len(untracked)} untracked file(s)")

    return {
        "success": True,
        "branch": branch,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "ahead": ahead,
        "behind": behind,
        "clean": clean,
        "summary": "\n".join(summary_parts),
    }


def git_log(
    path: str | None = None,
    max_count: int = 10,
    oneline: bool = False,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """View git commit history.

    Returns structured commit log with author, date, and message information.

    Args:
        path: Repository path (defaults to current directory)
        max_count: Maximum number of commits to return (default: 10)
        oneline: If True, return one-line format per commit
        author: Filter by author name/email
        since: Show commits since date (e.g., "2024-01-01", "2 weeks ago")
        until: Show commits until date
        file_path: Show commits affecting specific file

    Returns:
        Dictionary containing:
        - success: bool - Whether the command succeeded
        - commits: list - List of commit dictionaries
        - count: int - Number of commits returned
        - error: str - Error message (if failed)

    Example:
        git_log()
        git_log(max_count=20, oneline=True)
        git_log(author="John", since="2024-01-01")
        git_log(file_path="src/main.py")
    """
    work_dir = Path(path) if path else Path.cwd()

    # Check if we're in a git repository
    exit_code, _, stderr = _run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Not a git repository",
            "path": str(work_dir),
        }

    # Build git log command
    args = ["log"]

    # Format for structured output
    if oneline:
        args.append("--oneline")
        format_str = "%H%n%h%n%s%n%an%n%ae%n%ad%n%D"
    else:
        format_str = "%H%n%h%n%s%n%an%n%ae%n%ad%n%D%n%b"

    args.append(f"--format={format_str}")
    args.append(f"-{max_count}")

    # Add filters
    if author:
        args.append(f"--author={author}")
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if file_path:
        args.append("--")
        args.append(file_path)

    exit_code, output, stderr = _run_git_command(args, cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Failed to get log",
            "path": str(work_dir),
        }

    # Parse commits
    commits = []
    commit_blocks = output.strip().split("\n\n") if output.strip() else []

    for block in commit_blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 6:
            commit = {
                "hash": lines[0],
                "short_hash": lines[1],
                "subject": lines[2],
                "author_name": lines[3],
                "author_email": lines[4],
                "date": lines[5],
            }
            if len(lines) > 6:
                commit["refs"] = lines[6]
            if not oneline and len(lines) > 7:
                commit["body"] = "\n".join(lines[7:])
            commits.append(commit)

    return {
        "success": True,
        "commits": commits,
        "count": len(commits),
    }


def git_diff(
    path: str | None = None,
    staged: bool = False,
    commit1: str | None = None,
    commit2: str | None = None,
    file_path: str | None = None,
    context_lines: int = 3,
) -> dict[str, Any]:
    """Compare changes in git.

    Shows differences between commits, or between working tree and index.

    Args:
        path: Repository path (defaults to current directory)
        staged: If True, show staged changes (git diff --staged)
        commit1: First commit to compare (optional)
        commit2: Second commit to compare (optional)
        file_path: Specific file to diff (optional)
        context_lines: Number of context lines (default: 3)

    Returns:
        Dictionary containing:
        - success: bool - Whether the command succeeded
        - diff: str - Raw diff output
        - files_changed: list - List of changed files
        - additions: int - Number of lines added
        - deletions: int - Number of lines deleted
        - error: str - Error message (if failed)

    Example:
        git_diff()  # Unstaged changes
        git_diff(staged=True)  # Staged changes
        git_diff(commit1="HEAD~1", commit2="HEAD")  # Compare commits
        git_diff(file_path="src/main.py")  # Specific file
    """
    work_dir = Path(path) if path else Path.cwd()

    # Check if we're in a git repository
    exit_code, _, stderr = _run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Not a git repository",
            "path": str(work_dir),
        }

    # Build git diff command
    args = ["diff"]

    if staged:
        args.append("--staged")

    if commit1 and commit2:
        args.append(f"{commit1}..{commit2}")
    elif commit1:
        args.append(commit1)

    args.append(f"-U{context_lines}")

    if file_path:
        args.append("--")
        args.append(file_path)

    exit_code, diff_output, stderr = _run_git_command(args, cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Failed to get diff",
            "path": str(work_dir),
        }

    # Parse diff for stats
    files_changed = []
    additions = 0
    deletions = 0

    if diff_output.strip():
        # Get stats
        stat_args = ["diff", "--shortstat"]
        if staged:
            stat_args.append("--staged")
        if commit1 and commit2:
            stat_args.append(f"{commit1}..{commit2}")
        elif commit1:
            stat_args.append(commit1)
        if file_path:
            stat_args.append("--")
            stat_args.append(file_path)

        _, stat_output, _ = _run_git_command(stat_args, cwd=work_dir)

        # Parse stats (e.g., "3 files changed, 10 insertions(+), 5 deletions(-)")
        if stat_output:
            import re

            files_match = re.search(r"(\d+) file", stat_output)
            insertions_match = re.search(r"(\d+) insertion", stat_output)
            deletions_match = re.search(r"(\d+) deletion", stat_output)

            if files_match:
                # Get list of changed files
                name_args = ["diff", "--name-only"]
                if staged:
                    name_args.append("--staged")
                if commit1 and commit2:
                    name_args.append(f"{commit1}..{commit2}")
                elif commit1:
                    name_args.append(commit1)
                if file_path:
                    name_args.append("--")
                    name_args.append(file_path)

                _, names_output, _ = _run_git_command(name_args, cwd=work_dir)
                files_changed = [f for f in names_output.strip().split("\n") if f]

            if insertions_match:
                additions = int(insertions_match.group(1))
            if deletions_match:
                deletions = int(deletions_match.group(1))

    return {
        "success": True,
        "diff": diff_output,
        "files_changed": files_changed,
        "additions": additions,
        "deletions": deletions,
    }


def git_blame(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    show_email: bool = False,
) -> dict[str, Any]:
    """Show line-by-line attribution for a file.

    Returns commit hash, author, date, and line content for each line.

    Args:
        file_path: Path to the file to blame (required)
        start_line: First line to show (1-indexed, optional)
        end_line: Last line to show (optional)
        show_email: If True, show author email instead of name

    Returns:
        Dictionary containing:
        - success: bool - Whether the command succeeded
        - lines: list - List of line dictionaries with blame info
        - file: str - File path
        - total_lines: int - Total number of lines in result
        - error: str - Error message (if failed)

    Example:
        git_blame("src/main.py")
        git_blame("src/main.py", start_line=10, end_line=20)
        git_blame("src/main.py", show_email=True)
    """
    if not file_path:
        return {
            "success": False,
            "error": "file_path is required",
        }

    work_dir = Path.cwd()
    file_path_obj = Path(file_path)

    # Check if file exists
    if not file_path_obj.exists():
        return {
            "success": False,
            "error": f"File not found: {file_path}",
            "file": file_path,
        }

    # Check if we're in a git repository
    exit_code, _, stderr = _run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Not a git repository",
            "file": file_path,
        }

    # Build git blame command
    args = ["blame", "--line-porcelain"]

    if start_line and end_line:
        args.extend(["-L", f"{start_line},{end_line}"])
    elif start_line:
        args.extend(["-L", f"{start_line},{start_line}"])

    args.append(file_path)

    exit_code, output, stderr = _run_git_command(args, cwd=work_dir)
    if exit_code != 0:
        return {
            "success": False,
            "error": stderr or "Failed to get blame",
            "file": file_path,
        }

    # Parse porcelain output
    lines = []
    current_line = {}

    for line in output.split("\n"):
        if line.startswith("author "):
            current_line["author"] = line[7:]
        elif line.startswith("author-mail "):
            current_line["author_email"] = line[12:].strip("<>")
        elif line.startswith("author-time "):
            import time

            try:
                timestamp = int(line[12:])
                current_line["date"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
            except ValueError:
                current_line["date"] = line[12:]
        elif line.startswith("summary "):
            current_line["summary"] = line[8:]
        elif line.startswith("\t"):
            # The actual line content (prefixed with tab)
            current_line["content"] = line[1:]
            # Extract short hash from the first line of each block
            if "hash" not in current_line and output:
                # The hash is at the beginning of the porcelain block
                first_line = output.split("\n")[0]
                if first_line and " " in first_line:
                    current_line["hash"] = first_line.split()[0][:8]

            if current_line.get("hash"):
                lines.append(
                    {
                        "hash": current_line.get("hash", ""),
                        "author": current_line.get("author_email" if show_email else "author", ""),
                        "date": current_line.get("date", ""),
                        "summary": current_line.get("summary", ""),
                        "content": current_line.get("content", ""),
                    }
                )
            current_line = {}

    return {
        "success": True,
        "file": file_path,
        "lines": lines,
        "total_lines": len(lines),
    }
