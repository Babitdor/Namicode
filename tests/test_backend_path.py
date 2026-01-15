import logging
import sys
import os
from nami_deepagents.backends.filesystem import FilesystemBackend

# Set up DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)

backend = FilesystemBackend(root_dir='C:/Users/Babit-PC/.nami/skills')
items = backend.ls_info('.')
skill_dirs = [item['path'] for item in items if item.get('is_dir')]

# Get algorithmic-art directory
skill_dir_path = [d for d in skill_dirs if 'algorithmic' in d][0]

print(f"skill_dir_path from backend: {repr(skill_dir_path)}")
print(f"skill_dir_path length: {len(skill_dir_path)}")
print(f"skill_dir_path ends with /: {skill_dir_path.endswith('/')}")
print(f"skill_dir_path ends with \\\\: {skill_dir_path.endswith(chr(92))}")
print()

# Simulate what _list_skills does
directory_name = os.path.basename(skill_dir_path.rstrip("/\\"))
print(f"directory_name after os.path.basename(skill_dir_path.rstrip('/\\\\')): {repr(directory_name)}")
print()

# Test if it contains separators
normalized_dir_name = directory_name.rstrip("/\\")
print(f"normalized_dir_name after rstrip: {repr(normalized_dir_name)}")
print(f"Contains os.sep ({repr(os.sep)}): {os.sep in normalized_dir_name}")
print(f"Contains '/': {'/' in normalized_dir_name}")

if os.sep in normalized_dir_name or "/" in normalized_dir_name:
    print("Calling os.path.basename again...")
    normalized_dir_name = os.path.basename(normalized_dir_name)
    print(f"After os.path.basename: {repr(normalized_dir_name)}")