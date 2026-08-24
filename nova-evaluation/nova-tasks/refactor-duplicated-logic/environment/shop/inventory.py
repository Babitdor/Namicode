"""Inventory handling."""


def _validate_sku(sku):
    if not isinstance(sku, str) or len(sku) != 8 or not sku.isalnum():
        raise ValueError(f"Invalid SKU: {sku!r}")
    return sku


def _validate_price(price):
    if not isinstance(price, (int, float)) or price < 0:
        raise ValueError(f"Invalid price: {price!r}")
    return price


def restock(sku, price, units):
    _validate_sku(sku)
    _validate_price(price)
    if units < 0:
        raise ValueError("Units cannot be negative")
    return {"sku": sku, "value": price * units}
