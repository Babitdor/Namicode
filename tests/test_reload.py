import sys
# Force reload
if 'nami_deepagents.middleware.skills' in sys.modules:
    del sys.modules['nami_deepagents.middleware.skills']
if 'nami_deepagents.backends.filesystem' in sys.modules:
    del sys.modules['nami_deepagents.backends.filesystem']

import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s', stream=sys.stderr)

from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.middleware import skills

backend = FilesystemBackend(root_dir='C:/Users/Babit-PC/.nami/skills')
skill_list = skills._list_skills(backend, '.')

print(f"\nTotal skills loaded: {len(skill_list)}")
for s in skill_list[:5]:
    print(f"  - {s['name']}")