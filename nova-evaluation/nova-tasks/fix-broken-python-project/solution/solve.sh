#!/bin/bash
# Reference solution for nova/fix-broken-python-project.
set -e
cd /app

# Bug 1: syntax error in operations.py — missing colon on def add.
python - <<'EOF'
import re
p = "calculator/operations.py"
src = open(p).read()
src = src.replace("def add(a, b)\n", "def add(a, b):\n")
open(p, "w").write(src)
EOF

# Bug 2: stats.py imports a non-existent name; use the real helpers.
python - <<'EOF'
p = "calculator/stats.py"
src = open(p).read()
src = src.replace(
    "from calculator.operations import average",
    "from calculator.operations import add",
)
src = src.replace("return average(values) / len(values)", "return add(sum(values), 0) / len(values)")
open(p, "w").write(src)
EOF

# Bug 3: off-by-one in process_order.
python - <<'EOF'
p = "calculator/main.py"
src = open(p).read()
src = src.replace("return amount * (1 - discount) + 1", "return amount * (1 - discount)")
open(p, "w").write(src)
EOF

python -m pytest tests/ -q
