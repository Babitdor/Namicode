import logging
import sys
import os
from nami_deepagents.middleware.skills import _parse_skill_metadata

# Set up DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)

# Read the actual SKILL.md content
skill_md_path = 'C:/Users/Babit-PC/.nami/skills/algorithmic-art/SKILL.md'
with open(skill_md_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Extract directory name from path
skill_dir_path = 'C:/Users/Babit-PC/.nami/skills/algorithmic-art/'
directory_name = os.path.basename(skill_dir_path.rstrip("/\\"))
print(f"Extracted directory_name: {repr(directory_name)}")
print(f"Calling _parse_skill_metadata with:")
print(f"  skill_path: {repr(skill_md_path)}")
print(f"  directory_name: {repr(directory_name)}")
print()

result = _parse_skill_metadata(content, skill_md_path, directory_name)
if result:
    print(f"Result: {result['name']}")
else:
    print("Result: None (parsing failed)")