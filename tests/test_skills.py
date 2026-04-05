#!/usr/bin/env python
"""Test script to verify skills load without validation errors."""

import logging
import sys

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, "deepagents-Nova")
sys.path.insert(0, ".")

from nova_deepagents.backends.filesystem import FilesystemBackend
from nova_deepagents.middleware.skills import _list_skills


def main():
    backend = FilesystemBackend("C:\\Users\\Babit-PC\\.Nova\\skills")
    skills = _list_skills(backend, ".")

    print(f"Loaded {len(skills)} skills successfully:\n")
    for skill in skills:
        print(f"✓ {skill['name']}: {skill['description'][:80]}...")

    return len(skills)


if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)
