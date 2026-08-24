#!/bin/bash
# Reference solution for nova/fix-data-processing-bug.
set -e
cd /app

# The bug: `lines[1:-1]` drops the last record. Process all data rows.
python - <<'EOF'
p = "process.py"
src = open(p).read()
src = src.replace("for line in lines[1:-1]:  # skip header", "for line in lines[1:]:  # skip header")
open(p, "w").write(src)
EOF

python -m pytest tests/ -q
