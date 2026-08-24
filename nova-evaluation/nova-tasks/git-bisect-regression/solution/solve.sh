#!/bin/bash
# Reference solution for nova/git-bisect-regression.
set -e
cd /app/repo

# The regression was introduced in "refactor tax handling": the tax was
# added instead of applied as a multiplier. Restore correct behavior.
cat > prices.py <<'EOF'
def total_price(unit_price, quantity=1, tax_rate=0.0):
    subtotal = unit_price * quantity
    return subtotal * (1 + tax_rate)
EOF

python -m pytest /app/tests/ -q
