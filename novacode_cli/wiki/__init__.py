"""Wiki — persistent project wiki for the agent.

The wiki lives at ``<project_root>/.nova/wiki/`` and provides three
slash commands:

* ``/ingest <path>`` — Ingest a raw source into wiki pages.
* ``/ask <question>`` — Answer with wiki context prepended.
* ``/file <topic>`` — File recent conversation as a wiki page.
"""

from novacode_cli.wiki.manager import WikiManager

__all__ = [
    "WikiManager",
]