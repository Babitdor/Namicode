"""Git tools for structured repository operations.

This module provides structured git operations with parsed output,
making it easier for the agent to work with version control.

Key tools:
- git_status: Repository status (branch, staged, unstaged, untracked)
- git_log: Commit history with filters
- git_diff: Structured diff by file
- git_blame: Line-by-line attribution
- git_branch: Branch operations
- git_stash: Stash management

All tools return structured dictionaries instead of raw git output.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


def _run_git_command(args: list[str], repo_path: str = ".") -> tuple[int, str, str]:
    """Run a git command and return exit code, stdout, stderr.

    Args:
        args: Git command arguments (without 'git')
        repo_path: Path to git repository

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def git_status(
    repo_path: str = ".",
    porcelain: bool = False,
) -> dict[str, Any]:
    """Get git repository status with structured output.

    Provides detailed repository status including current branch,
    staged files, unstaged modifications, and untracked files.

    Args:
        repo_path: Path to git repository (default: current directory)
        porcelain: Return machine-readable output format

    Returns:
        Dictionary containing:
        - success: Whether command succeeded
        - is_repo: True if inside a git repository
        - branch: Current branch name
        - head: Current HEAD commit hash (first 12 chars)
        - staged: List of staged files with status
        - unstaged: List of unstaged files with status
        - untracked: List of untracked files
        - is_clean: True if no changes
        - ahead: Number of commits ahead of upstream
        - behind: Number of commits behind upstream
        - conflicts: List of files with merge conflicts

    Example:
        status = git_status()
        if status["is_clean"]:
            print("No changes")
        else:
            print(f"Modified: {status['unstaged']}")
    """
    # Check if we're in a git repo
    exit_code, _, _ = _run_git_command(["rev-parse", "--git-dir"], repo_path)
    if exit_code != 0:
        return {
            "success": False,
            "is_repo": False,
            "error": "Not a git repository",
        }

    # Get current branch
    _, branch, _ = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    branch = branch.strip()

    # Get HEAD commit
    _, head, _ = _run_git_command(["rev-parse", "--short=12", "HEAD"], repo_path)
    head = head.strip()

    # Get status
    _, status_output, _ = _run_git_command(["status", "--porcelain"], repo_path)

    staged = []
    unstaged = []
    untracked = []
    conflicts = []

    for line in status_output.strip().split("\n"):
        if not line:
            continue

        status_code = line[:2]
        filename = line[3:]

        if status_code == "??":
            untracked.append(filename)
        elif status_code in ("UU", "AA", "DD"):
            conflicts.append(filename)
        elif status_code[0] != " " and status_code[0] != "?":
            # Staged changes
            staged_status = {
                "file": filename,
                "status": status_code[0],
                "status_text": _status_code_to_text(status_code[0]),
            }
            staged.append(staged_status)

        if status_code[1] != " " and status_code[1] != "?":
            # Unstaged changes
            unstaged_status = {
                "file": filename,
                "status": status_code[1],
                "status_text": _status_code_to_text(status_code[1]),
            }
            unstaged.append(unstaged_status)

    # Get ahead/behind counts
    ahead = 0
    behind = 0
    _, ahead_behind, _ = _run_git_command(
        ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
        repo_path,
    )
    if ahead_behind.strip():
        parts = ahead_behind.strip().split("\t")
        if len(parts) == 2:
            try:
                behind = int(parts[0])
                ahead = int(parts[1])
            except ValueError:
                pass

    is_clean = not (staged or unstaged or untracked or conflicts)

    return {
        "success": True,
        "is_repo": True,
        "branch": branch,
        "head": head,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicts": conflicts,
        "is_clean": is_clean,
        "ahead": ahead,
        "behind": behind,
        "has_uncommitted_changes": bool(staged or unstaged),
        "has_untracked_files": bool(untracked),
        "has_conflicts": bool(conflicts),
    }


def _status_code_to_text(code: str) -> str:
    """Convert git status code to human-readable text."""
    status_map = {
        "M": "modified",
        "A": "added",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "U": "unmerged",
        "T": "type changed",
        "!": "ignored",
    }
    return status_map.get(code, f"unknown ({code})")


def git_log(
    repo_path: str = ".",
    max_count: int = 10,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    file_path: str | None = None,
    oneline: bool = False,
) -> dict[str, Any]:
    """Get commit history with structured output.

    Retrieves commit history with filtering options and returns
    parsed commit information suitable for programmatic use.

    Args:
        repo_path: Path to git repository
        max_count: Maximum commits to return (default: 10)
        author: Filter by author name or email
        since: Filter commits since date (e.g., "2024-01-01", "2 weeks ago")
        until: Filter commits until date
        file_path: Filter by file path
        oneline: Return compact one-line format

    Returns:
        Dictionary containing:
        - success: Whether command succeeded
        - commits: List of commit dicts with hash, author, date, message
        - total: Total commits found

    Example:
        history = git_log(max_count=5, since="2024-01-01")
        for commit in history["commits"]:
            print(f"{commit['hash'][:8]} {commit['message']}")
    """
    args = ["log", f"--max-count={max_count}"]

    if oneline:
        args.append("--oneline")
    else:
        args.append("--format=%H|%an|%ae|%aI|%s")

    if author:
        args.append(f"--author={author}")
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if file_path:
        args.append("--")
        args.append(file_path)

    exit_code, stdout, stderr = _run_git_command(args, repo_path)

    if exit_code != 0:
        return {
            "success": False,
            "error": stderr,
            "commits": [],
            "total": 0,
        }

    commits = []

    if oneline:
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2:
                commits.append(
                    {
                        "hash": parts[0],
                        "message": parts[1],
                        "author": None,
                        "email": None,
                        "date": None,
                    }
                )
    else:
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 4)
            if len(parts) == 5:
                commit_hash, author, email, date, message = parts
                commits.append(
                    {
                        "hash": commit_hash,
                        "author": author,
                        "email": email,
                        "date": date,
                        "message": message,
                    }
                )

    return {
        "success": True,
        "commits": commits,
        "total": len(commits),
        "has_more": len(commits) == max_count,
    }


def git_diff(
    repo_path: str = ".",
    commit1: str | None = None,
    commit2: str | None = None,
    file_path: str | None = None,
    staged: bool = False,
    stat_only: bool = False,
) -> dict[str, Any]:
    """Get diff with structured output.

    Shows changes between commits, commit and working tree, etc.
    Returns structured diff information with file-by-file changes.

    Args:
        repo_path: Path to git repository
        commit1: First commit (default: working tree changes)
        commit2: Second commit (default: HEAD or index)
        file_path: Filter by file path
        staged: Show staged changes (git diff --cached)
        stat_only: Show only statistics, not full diff

    Returns:
        Dictionary containing:
        - success: Whether command succeeded
        - files: List of changed files with additions/deletions
        - additions: Total lines added
        - deletions: Total lines deleted
        - diff: Full diff content (if stat_only=False)
        - changes: Dict of file → hunks (if stat_only=False)

    Example:
        diff = git_diff(staged=True)
        print(f"Staged files: {diff['files']}")
        print(f"Additions: +{diff['additions']}, Deletions: -{diff['deletions']}")
    """
    args = ["diff"]

    if staged:
        args.append("--cached")

    if stat_only:
        args.append("--stat")

    if commit1 and commit2:
        args.append(f"{commit1}..{commit2}")
    elif commit1:
        args.append(commit1)

    if file_path:
        args.append("--")
        args.append(file_path)

    exit_code, stdout, stderr = _run_git_command(args, repo_path)

    if exit_code != 0 and "no changes" not in stderr.lower():
        return {
            "success": False,
            "error": stderr,
            "files": [],
            "additions": 0,
            "deletions": 0,
        }

    # Parse file changes
    files = []
    additions = 0
    deletions = 0

    if stat_only:
        # Parse --stat output
        for line in stdout.strip().split("\n"):
            if " | " in line:
                parts = line.rsplit(" | ", 1)
                if len(parts) == 2:
                    filename = parts[0].strip()
                    stats_part = parts[1].strip()
                    # Extract additions/deletions from {+xxx/-yyy} format
                    file_additions = stats_part.count("+")
                    file_deletions = stats_part.count("-")
                    files.append(
                        {
                            "file": filename,
                            "additions": file_additions,
                            "deletions": file_deletions,
                        }
                    )
    else:
        # Parse full diff output
        current_file = None
        for line in stdout.split("\n"):
            if line.startswith("diff --git "):
                # New file
                parts = line.split(" ")
                if len(parts) >= 4:
                    current_file = parts[3].lstrip("a/")
            elif line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        # Get file list from diff
        args_files = ["diff", "--name-status"]
        if staged:
            args_files.append("--cached")
        if commit1 and commit2:
            args_files.append(f"{commit1}..{commit2}")
        elif commit1:
            args_files.append(commit1)
        if file_path:
            args_files.append("--")
            args_files.append(file_path)

        _, files_output, _ = _run_git_command(args_files, repo_path)
        for line in files_output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0]
                filename = parts[1]
                files.append(
                    {
                        "file": filename,
                        "status": status,
                        "status_text": _status_code_to_text(status),
                    }
                )
            elif len(parts) == 1:
                files.append(
                    {
                        "file": parts[0],
                        "status": "M",
                        "status_text": "modified",
                    }
                )

    return {
        "success": True,
        "files": files,
        "additions": additions,
        "deletions": deletions,
        "diff": stdout if not stat_only else None,
        "is_empty": len(files) == 0,
    }


def git_blame(
    file_path: str,
    repo_path: str = ".",
    line_range: tuple[int, int] | None = None,
    show_email: bool = False,
) -> dict[str, Any]:
    """Get line-by-line attribution with structured output.

    Shows which commit and author last modified each line of a file.
    Useful for understanding code history and finding experts.

    Args:
        file_path: Path to file (relative to repo root)
        repo_path: Path to git repository
        line_range: Optional (start, end) line range to blame
        show_email: Show email instead of author name

    Returns:
        Dictionary containing:
        - success: Whether command succeeded
        - lines: Dict of line number → {author, date, commit, content}
        - authors: List of unique authors who modified this file
        - total_lines: Total lines in file
        - file_path: Path to the blamed file

    Example:
        blame = git_blame("src/main.py", line_range=(1, 20))
        for line_num, info in blame["lines"].items():
            print(f"{line_num}: {info['author']} - {info['commit'][:8]}")
    """
    args = ["blame", "-w"]  # -w ignores whitespace changes

    if show_email:
        args.append("-e")  # Show email instead of name

    args.append("-f")  # Show author and commit info

    if line_range:
        start, end = line_range
        args.extend([f"-L{start},{end}"])

    args.append(file_path)

    exit_code, stdout, stderr = _run_git_command(args, repo_path)

    if exit_code != 0:
        return {
            "success": False,
            "error": stderr,
            "file_path": file_path,
            "lines": {},
            "authors": [],
            "total_lines": 0,
        }

    lines = {}
    authors = set()
    commits = {}

    for line_num, line in enumerate(stdout.split("\n"), 1):
        if not line:
            continue

        # Parse blame line format: hash (author date time timezone line) content
        # Format: <hash> <author> <date> <time> <tz> <line_num> <content>
        import re

        # Git blame porcelain format is complex, use regex to extract
        match = re.match(
            r"^([0-9a-f]+)\s+\(([^)]+)\s+(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}"
            r"\s+[+-]\d{4}\s+(\d+)\)",
            line,
        )

        if match:
            commit_hash = match.group(1)
            author = match.group(2).strip()
            date = match.group(3)
            content_line_num = int(match.group(4))
            # Content is the rest after the match
            content = line[match.end() :].lstrip()

            lines[content_line_num] = {
                "commit": commit_hash,
                "author": author,
                "date": date,
                "content": content,
            }
            authors.add(author)
            commits[commit_hash] = author

    return {
        "success": True,
        "file_path": file_path,
        "lines": lines,
        "authors": list(authors),
        "author_count": len(authors),
        "total_lines": len(lines),
        "commits": commits,
    }


def git_branch(
    repo_path: str = ".",
    action: Literal["list", "current", "create", "delete", "checkout"] = "list",
    branch_name: str | None = None,
    remote: bool = False,
) -> dict[str, Any]:
    """Manage git branches with structured output.

    List branches, create new branches, delete branches, or switch branches.

    Args:
        repo_path: Path to git repository
        action: Branch action to perform
            - "list": List all branches
            - "current": Get current branch name
            - "create": Create new branch
            - "delete": Delete a branch
            - "checkout": Switch to a branch
        branch_name: Branch name (required for create/delete/checkout)
        remote: Include remote branches when listing

    Returns:
        Dictionary containing:
        - success: Whether command succeeded
        - branches: List of branch info (for list action)
        - current_branch: Current branch name
        - error: Error message if failed

    Example:
        branches = git_branch(action="list")
        print(f"Current: {branches['current_branch']}")
        for branch in branches['branches']:
            print(f"  {branch['name']} {'*' if branch['current'] else ''}")
    """
    if action == "current":
        _, branch, _ = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
        return {
            "success": True,
            "current_branch": branch.strip(),
        }

    if action == "list":
        args = ["branch"]
        if remote:
            args.append("-a")

        exit_code, stdout, stderr = _run_git_command(args, repo_path)

        if exit_code != 0:
            return {
                "success": False,
                "error": stderr,
                "branches": [],
                "current_branch": None,
            }

        branches = []
        current_branch = None

        for line in stdout.strip().split("\n"):
            if not line:
                continue

            line = line.strip()
            is_current = line.startswith("* ")
            if is_current:
                line = line[2:]
                current_branch = line

            # Check if it's a remote branch
            is_remote = line.startswith("remotes/")
            branch_name_full = line
            branch_name = line.split("/")[-1] if is_remote else line

            branches.append(
                {
                    "name": branch_name,
                    "full_name": branch_name_full,
                    "current": is_current,
                    "remote": is_remote,
                }
            )

        return {
            "success": True,
            "branches": branches,
            "current_branch": current_branch,
            "total": len(branches),
        }

    if action == "create":
        if not branch_name:
            return {
                "success": False,
                "error": "branch_name required for create action",
            }
        exit_code, stdout, stderr = _run_git_command(["branch", branch_name], repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr}
        return {
            "success": True,
            "message": f"Created branch: {branch_name}",
            "branch": branch_name,
        }

    if action == "delete":
        if not branch_name:
            return {
                "success": False,
                "error": "branch_name required for delete action",
            }
        exit_code, stdout, stderr = _run_git_command(["branch", "-D", branch_name], repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr}
        return {
            "success": True,
            "message": f"Deleted branch: {branch_name}",
            "branch": branch_name,
        }

    if action == "checkout":
        if not branch_name:
            return {
                "success": False,
                "error": "branch_name required for checkout action",
            }
        exit_code, stdout, stderr = _run_git_command(["checkout", branch_name], repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr}
        return {
            "success": True,
            "message": f"Switched to branch: {branch_name}",
            "current_branch": branch_name,
        }

    return {
        "success": False,
        "error": f"Unknown action: {action}",
    }


def git_stash(
    repo_path: str = ".",
    action: Literal["list", "push", "pop", "apply", "drop", "clear"] = "list",
    message: str | None = None,
    stash_index: int | None = None,
) -> dict[str, Any]:
    """Manage git stash with structured output.

    List, create, apply, or drop stashes.

    Args:
        repo_path: Path to git repository
        action: Stash action to perform
            - "list": List all stashes
            - "push": Create new stash
            - "pop": Apply and remove latest stash
            - "apply": Apply stash without removing
            - "drop": Delete a stash
            - "clear": Delete all stashes
        message: Message for new stash (for push action)
        stash_index: Stash index to apply/drop (default: 0 for latest)

    Returns:
        Dictionary containing:
        - success: Whether command succeeded
        - stashes: List of stash info (for list action)
        - message: Status message

    Example:
        stashes = git_stash(action="list")
        for stash in stashes["stashes"]:
            print(f"{stash['index']}: {stash['message']}")
    """
    if action == "list":
        exit_code, stdout, stderr = _run_git_command(["stash", "list"], repo_path)

        if exit_code != 0:
            return {
                "success": False,
                "error": stderr,
                "stashes": [],
            }

        stashes = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue

            # Format: stash@{0}: on branch: message
            import re

            match = re.match(r"stash@\{(\d+)\}:\s+(.+)", line)
            if match:
                index = int(match.group(1))
                rest = match.group(2)
                # Parse branch and message
                if ":" in rest:
                    branch_msg = rest.split(":", 1)
                    branch = branch_msg[0].replace("on ", "").strip()
                    message = branch_msg[1].strip() if len(branch_msg) > 1 else ""
                else:
                    branch = ""
                    message = rest

                stashes.append(
                    {
                        "index": index,
                        "branch": branch,
                        "message": message,
                    }
                )

        return {
            "success": True,
            "stashes": stashes,
            "total": len(stashes),
        }

    if action == "push":
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        exit_code, _, stderr = _run_git_command(args, repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr}
        return {
            "success": True,
            "message": "Created stash",
        }

    if action == "pop":
        args = ["stash", "pop"]
        if stash_index is not None:
            args.append(f"stash@{{{stash_index}}}")
        exit_code, stdout, stderr = _run_git_command(args, repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr, "output": stdout}
        return {
            "success": True,
            "message": "Applied and removed stash",
            "output": stdout,
        }

    if action == "apply":
        args = ["stash", "apply"]
        if stash_index is not None:
            args.append(f"stash@{{{stash_index}}}")
        exit_code, stdout, stderr = _run_git_command(args, repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr, "output": stdout}
        return {
            "success": True,
            "message": "Applied stash",
            "output": stdout,
        }

    if action == "drop":
        args = ["stash", "drop"]
        if stash_index is not None:
            args.append(f"stash@{{{stash_index}}}")
        exit_code, _, stderr = _run_git_command(args, repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr}
        return {
            "success": True,
            "message": "Dropped stash",
        }

    if action == "clear":
        exit_code, _, stderr = _run_git_command(["stash", "clear"], repo_path)
        if exit_code != 0:
            return {"success": False, "error": stderr}
        return {
            "success": True,
            "message": "Cleared all stashes",
        }

    return {
        "success": False,
        "error": f"Unknown action: {action}",
    }


# List of all git tools for easy import
GIT_TOOLS = [
    git_status,
    git_log,
    git_diff,
    git_blame,
    git_branch,
    git_stash,
]
