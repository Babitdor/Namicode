"""Tests for the write_file dict-content coercion patch.

Models often pass the ``content`` arg to ``write_file`` as a JSON object instead
of a string (notably /init's semantic-extraction subagents writing graph
fragments). deepagents' ``WriteFileSchema`` types ``content: str`` and rejects
that at validation, so the file is never written. The patch coerces dict/list
``content`` to a JSON string.
"""

import json

import pytest

from novacode_cli.utils.backend_patches import apply_write_file_dict_content_patch


def _schema():
    fs = pytest.importorskip("deepagents.middleware.filesystem")
    return fs.WriteFileSchema


def test_dict_content_is_serialized_to_json_string():
    apply_write_file_dict_content_patch()
    frag = {"nodes": [{"id": "a_b"}], "edges": [], "hyperedges": []}
    m = _schema().model_validate({"file_path": "/x.json", "content": frag})
    assert isinstance(m.content, str)
    assert json.loads(m.content) == frag


def test_list_content_is_serialized():
    apply_write_file_dict_content_patch()
    m = _schema().model_validate({"file_path": "/x.json", "content": [1, 2, 3]})
    assert m.content == "[1, 2, 3]"


def test_string_content_is_unchanged():
    apply_write_file_dict_content_patch()
    m = _schema().model_validate({"file_path": "/x.json", "content": '{"a": 1}'})
    assert m.content == '{"a": 1}'


def test_idempotent():
    apply_write_file_dict_content_patch()
    apply_write_file_dict_content_patch()  # must not double-wrap or raise
    m = _schema().model_validate({"file_path": "/x.json", "content": {"k": "v"}})
    assert json.loads(m.content) == {"k": "v"}
