#!/bin/bash
# Reference solution for nova/harden-insecure-web-app.
set -e
cd /app

# The vulnerability: the query is interpolated into the SQL string.
# Fix: use a parameterized query so user input is always data.
python - <<'EOF'
p = "app.py"
src = open(p).read()
src = src.replace(
    'rows = conn.execute(\n        f"SELECT name, price FROM products WHERE name LIKE \'%{query}%\'"\n    ).fetchall()',
    'rows = conn.execute(\n        "SELECT name, price FROM products WHERE name LIKE ?",\n        (f"%{query}%",),\n    ).fetchall()',
)
open(p, "w").write(src)
EOF

python -m pytest tests/ -q
