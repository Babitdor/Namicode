import logging
import sys

# Set up DEBUG logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    stream=sys.stderr
)

from nami_deepagents.middleware.skills import _parse_skill_metadata, _validate_skill_name

# Test with a simple example
name = "algorithmic-art"
directory_name = "algorithmic-art"

print(f"Testing with name='{name}' and directory_name='{directory_name}'")
result = _validate_skill_name(name, directory_name)
print(f"is_valid: {result[0]}")
print(f"error: {result[1]}")