"""Tests for normalize_source_paths.

graphify emits OS-native (Windows backslash) paths in ``source_file``. Those
leak into NOVA.md / the graph JSON, and the ``\\u``/``\\t`` escape sequences make
later edit_file matches fail (the agent loops on "String not found"). The
normalizer rewrites only path fields to forward slashes, leaving ids and code-
content labels alone.
"""

from novacode_cli.init.extract import normalize_source_paths

BS = chr(92)  # a single backslash, built explicitly to avoid escape headaches


def test_node_source_file_backslashes_become_forward_slashes():
    win = "novacode_cli" + BS + "ui" + BS + "ui_elements.py"
    ext = {"nodes": [{"id": "n1", "source_file": win}], "edges": []}
    out = normalize_source_paths(ext)
    assert out["nodes"][0]["source_file"] == "novacode_cli/ui/ui_elements.py"


def test_ids_and_code_labels_are_left_untouched():
    # label holds a code snippet whose backslash is a literal \n, NOT a path.
    label = "regex: foo" + BS + "n bar"
    ext = {
        "nodes": [{"id": "a" + BS + "b", "label": label, "source_file": "x" + BS + "y.py"}],
        "edges": [],
    }
    out = normalize_source_paths(ext)
    n = out["nodes"][0]
    assert n["source_file"] == "x/y.py"        # path normalized
    assert n["id"] == "a" + BS + "b"           # id untouched (ids are slash-free anyway)
    assert n["label"] == label                  # code content untouched


def test_edge_source_file_and_source_files_normalized():
    ext = {
        "nodes": [],
        "edges": [
            {
                "source": "a",
                "target": "b",
                "source_file": "examples" + BS + "hooks" + BS + "x.py",
                "source_files": ["a" + BS + "b.py", "c/d.py"],
            }
        ],
    }
    out = normalize_source_paths(ext)
    e = out["edges"][0]
    assert e["source_file"] == "examples/hooks/x.py"
    assert e["source_files"] == ["a/b.py", "c/d.py"]


def test_already_posix_paths_unchanged_and_missing_fields_ok():
    ext = {"nodes": [{"id": "n", "source_file": "already/posix.py"}, {"id": "m"}], "edges": []}
    out = normalize_source_paths(ext)
    assert out["nodes"][0]["source_file"] == "already/posix.py"
    assert "source_file" not in out["nodes"][1]  # missing field tolerated


def test_handles_empty_or_missing_collections():
    assert normalize_source_paths({}) == {}
    assert normalize_source_paths({"nodes": None, "edges": None}) == {"nodes": None, "edges": None}
