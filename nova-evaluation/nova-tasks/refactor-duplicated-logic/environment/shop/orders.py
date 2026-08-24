"""Order handling."""


def _validate_sku(sku):
    if not isinstance(sku, str) or len(sku) != 8 or not sku.isalnum():
        raise ValueError(f"Invalid SKU: {sku!r}")
    return sku


def _validate_price(price):
    if not isinstance(price, (int, float)) or price < 0:
        raise ValueError(f"Invalid price: {price!r}")
    return price


def create_order(sku, price, quantity):
    _validate_sku(sku)
    _validate_price(price)
    if quantity < 1:
        raise ValueError("Quantity must be at least 1")
    return {"sku": sku, "total": price * quantity}
