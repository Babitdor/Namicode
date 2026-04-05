"""Lock file management for installed skills.

Tracks the source URL, branch, and install metadata for each skill
installed via `Nova skills add`. Enables `Nova skills update` to
re-fetch from the original source.

Lock file location:
  Global:  ~/.Nova/skills-lock.json
  Project: {project_root}/.Nova/skills-lock.json

The lock file sits *adjacent* to the skills/ directory (in the .Nova dir),
not inside it.
"""

import json
from pathlib import Path


class SkillLock:
    """Read/write a skills-lock.json file.

    All I/O is gracefully degraded — a missing or malformed lock file
    never causes a skill operation to fail.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path

    @classmethod
    def for_skills_dir(cls, skills_dir: Path) -> "SkillLock":
        """Create a SkillLock whose file lives adjacent to skills_dir.

        Example: skills_dir = ~/.Nova/skills/ → lock at ~/.Nova/skills-lock.json
        """
        lock_path = skills_dir.parent / "skills-lock.json"
        return cls(lock_path)

    def read(self) -> dict:
        """Read the lock file. Returns {"skills": {}} if missing or invalid."""
        if not self.lock_path.exists():
            return {"skills": {}}
        try:
            data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "skills" not in data:
                return {"skills": {}}
            return data
        except (json.JSONDecodeError, OSError):
            return {"skills": {}}

    def write(self, data: dict) -> None:
        """Write data to the lock file."""
        self.lock_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def update(self, skill_name: str, entry: dict) -> None:
        """Insert or replace the lock entry for skill_name."""
        data = self.read()
        data["skills"][skill_name] = entry
        self.write(data)

    def remove(self, skill_name: str) -> None:
        """Remove the lock entry for skill_name. Safe no-op if not present."""
        data = self.read()
        data["skills"].pop(skill_name, None)
        self.write(data)

    def get(self, skill_name: str) -> dict | None:
        """Return the lock entry for skill_name, or None if not present."""
        return self.read()["skills"].get(skill_name)

    def all_entries(self) -> dict[str, dict]:
        """Return all skill entries keyed by skill name."""
        return self.read()["skills"]


__all__ = ["SkillLock"]
