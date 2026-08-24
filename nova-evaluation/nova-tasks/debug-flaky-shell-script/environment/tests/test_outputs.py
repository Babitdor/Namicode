"""Test suite for the report script. Do not modify."""

import os
import subprocess
import tempfile

SCRIPT = "/app/report.sh"


def run_script(args):
    return subprocess.run(
        ["bash", SCRIPT, *args], capture_output=True, text=True, cwd="/app"
    )


def test_missing_file_exits_nonzero():
    r = run_script(["/nonexistent/data.txt", "/tmp/out.txt"])
    assert r.returncode != 0


def test_basic_report():
    with tempfile.TemporaryDirectory() as d:
        data = os.path.join(d, "data.txt")
        out = os.path.join(d, "out.txt")
        with open(data, "w") as f:
            f.write("b\nc\na\n")
        r = run_script([data, out])
        assert r.returncode == 0, r.stderr
        assert os.path.exists(out)
        assert open(out).read().strip() == "3"


def test_path_with_spaces():
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "my data dir")
        os.makedirs(sub)
        data = os.path.join(sub, "data file.txt")
        out = os.path.join(sub, "out file.txt")
        with open(data, "w") as f:
            f.write("x\ny\n")
        r = run_script([data, out])
        assert r.returncode == 0, r.stderr
        assert os.path.exists(out)
        assert open(out).read().strip() == "2"


def test_concurrent_runs_do_not_interfere():
    with tempfile.TemporaryDirectory() as d:
        data1 = os.path.join(d, "data1.txt")
        data2 = os.path.join(d, "data2.txt")
        with open(data1, "w") as f:
            f.write("\n".join(f"a{i}" for i in range(30)))
        with open(data2, "w") as f:
            f.write("\n".join(f"b{i}" for i in range(70)))
        out1 = os.path.join(d, "out1.txt")
        out2 = os.path.join(d, "out2.txt")
        p1 = subprocess.Popen(["bash", SCRIPT, data1, out1], cwd="/app")
        p2 = subprocess.Popen(["bash", SCRIPT, data2, out2], cwd="/app")
        p1.wait()
        p2.wait()
        assert open(out1).read().strip() == "30"
        assert open(out2).read().strip() == "70"
