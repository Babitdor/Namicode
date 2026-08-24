#!/bin/bash
# Reference solution for nova/refactor-duplicated-logic.
set -e
cd /app

cat > shop/validation.py <<'EOF'
"""Shared validation helpers."""


def validate_sku(sku):
    if not isinstance(sku, str) or len(sku) != 8 or not sku.isalnum():
        raise ValueError(f"Invalid SKU: {sku!r}")
    return sku


def validate_price(price):
    if not isinstance(price, (int, float)) or price < 0:
        raise ValueError(f"Invalid price: {price!r}")
    return price
EOF

cat > shop/orders.py <<'EOF'
"""Order handling."""

from shop.validation import validate_price, validate_sku


def create_order(sku, price, quantity):
    validate_sku(sku)
    validate_price(price)
    if quantity < 1:
        raise ValueError("Quantity must be at least 1")
    return {"sku": sku, "total": price * quantity}
EOF

cat > shop/inventory.py <<'EOF'
"""Inventory handling."""

from shop.validation import validate_price, validate_sku


def restock(sku, price, units):
    validate_sku(sku)
    validate_price(price)
    if units < 0:
        raise ValueError("Units cannot be negative")
    return {"sku": sku, "value": price * units}
EOF

python -m pytest tests/ -q
