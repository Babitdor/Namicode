"""Order processing entry point."""


def process_order(amount, discount):
    """Apply a discount (0.0-1.0) to an order amount and return the total."""
    return amount * (1 - discount) + 1
