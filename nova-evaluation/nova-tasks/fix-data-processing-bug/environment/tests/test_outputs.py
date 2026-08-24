"""Test suite for the sales summary script. Do not modify."""

import os
import subprocess
import tempfile

SCRIPT = "/app/process.py"

SALES_CSV = (
    "product,quantity,price\n"
    "apple,2,1.50\n"
    "banana,3,0.75\n"
    "apple,1,2.00\n"
    "cherry,5,0.10\n"
)


def run_process(data, name="sales.csv"):
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, name)
        out = os.path.join(d, "summary.txt")
        with open(inp, "w") as f:
            f.write(data)
        r = subprocess.run(
            ["python3", SCRIPT, inp, out],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert r.returncode == 0, r.stderr
        return open(out).read()


def test_full_summary():
    result = run_process(SALES_CSV)
    assert result == "apple: 5.00\nbanana: 2.25\ncherry: 0.50\n"


def test_single_record():
    result = run_process("product,quantity,price\npear,4,1.00\n")
    assert result == "pear: 4.00\n"


def test_trailing_blank_line():
    result = run_process(SALES_CSV + "\n")
    assert result == "apple: 5.00\nbanana: 2.25\ncherry: 0.50\n"


def test_duplicate_products_accumulate():
    result = run_process("product,quantity,price\nfig,1,3.00\nfig,2,1.50\n")
    assert result == "fig: 6.00\n"
