#!/usr/bin/env python
"""Test script to verify skills load without validation errors."""

import sys
import logging

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, 'deepagents-nami')
sys.path.insert(0, '.')

from nami_deepagents.middleware.skills import _list_skills
from nami_deepagents.backends.filesystem import FilesystemBackend

def main():
    backend = FilesystemBackend('C:\\Users\\Babit-PC\\.nami\\skills')
    skills = _list_skills(backend, '.')

    print(f"Loaded {len(skills)} skills successfully:\n")
    for skill in skills:
        print(f"✓ {skill['name']}: {skill['description'][:80]}...")

    return len(skills)

if __name__ == '__main__':
    count = main()
    sys.exit(0 if count > 0 else 1)