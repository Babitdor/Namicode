import logging
import sys
from nami_deepagents.middleware import skills
from nami_deepagents.backends.filesystem import FilesystemBackend

# Set up DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)

# Test the actual _list_skills function
backend = FilesystemBackend(root_dir='C:/Users/Babit-PC/.nami/skills')
skill_list = skills._list_skills(backend, '.')

# Check if any skills failed validation
print(f"Total skills loaded: {len(skill_list)}")
for s in skill_list:
    if 'algorithmic' in s['name']:
        print(f"\nFound algorithmic-art:")
        print(f"  name: {s['name']}")
        print(f"  path: {s['path']}")