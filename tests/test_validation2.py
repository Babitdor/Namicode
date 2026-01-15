import logging
import sys
import os

# Set up DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)

from nami_deepagents.middleware.skills import _parse_skill_metadata, _validate_skill_name

# Test 1: Simple case
print("Test 1: Simple case")
name = "algorithmic-art"
directory_name = "algorithmic-art"
result = _validate_skill_name(name, directory_name)
print(f"  name='{name}', directory_name='{directory_name}'")
print(f"  is_valid: {result[0]}")
print(f"  error: {result[1]}")
print()

# Test 2: Path with trailing slash
print("Test 2: Path with trailing slash")
skill_dir_path = 'C:\\Users\\Babit-PC\\.nami\\skills\\algorithmic-art/'
directory_name_extracted = os.path.basename(skill_dir_path.rstrip('/\\'))
print(f"  skill_dir_path: {repr(skill_dir_path)}")
print(f"  directory_name extracted: {repr(directory_name_extracted)}")
result = _validate_skill_name(name, directory_name_extracted)
print(f"  is_valid: {result[0]}")
print(f"  error: {result[1]}")
print()

# Test 3: Path without trailing slash
print("Test 3: Path without trailing slash")
skill_dir_path = 'C:\\Users\\Babit-PC\\.nami\\skills\\algorithmic-art'
directory_name_extracted = os.path.basename(skill_dir_path.rstrip('/\\'))
print(f"  skill_dir_path: {repr(skill_dir_path)}")
print(f"  directory_name extracted: {repr(directory_name_extracted)}")
result = _validate_skill_name(name, directory_name_extracted)
print(f"  is_valid: {result[0]}")
print(f"  error: {result[1]}")