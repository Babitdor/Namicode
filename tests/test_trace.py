import logging
import sys
import os

# Set up DEBUG logging for the specific logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)

# Manually add a handler to see the DEBUG messages
from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.middleware import skills

backend = FilesystemBackend(root_dir='C:/Users/Babit-PC/.nami/skills')

# Manually trace through the code
items = backend.ls_info('.')
skill_dirs = [item['path'] for item in items if item.get('is_dir')]

# Get algorithmic-art directory
skill_dir_path = [d for d in skill_dirs if 'algorithmic' in d][0]

print(f"\n=== Manual trace ===")
print(f"skill_dir_path from backend: {repr(skill_dir_path)}")

# This is what the code does
directory_name = os.path.basename(skill_dir_path.rstrip("/\\"))
print(f"directory_name = os.path.basename(skill_dir_path.rstrip('/\\\\')): {repr(directory_name)}")

# Now simulate _parse_skill_metadata normalization
normalized_dir_name = directory_name.rstrip("/\\")
print(f"normalized_dir_name = directory_name.rstrip('/\\\\'): {repr(normalized_dir_name)}")

if os.sep in normalized_dir_name or "/" in normalized_dir_name:
    print(f"Found separator, calling os.path.basename again")
    normalized_dir_name = os.path.basename(normalized_dir_name)
    print(f"After os.path.basename: {repr(normalized_dir_name)}")
else:
    print(f"No separator found")

print(f"\nFinal normalized_dir_name: {repr(normalized_dir_name)}")
print(f"Expected: 'algorithmic-art'")
print(f"Match: {normalized_dir_name == 'algorithmic-art'}")

# Now call _list_skills and see what happens
print(f"\n=== Calling _list_skills ===")
skill_list = skills._list_skills(backend, '.')
print(f"Total skills loaded: {len(skill_list)}")
for s in skill_list:
    if 'algorithmic' in s['name']:
        print(f"  Found: {s['name']}")