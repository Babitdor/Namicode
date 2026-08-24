"""Statistical helpers built on the arithmetic operations."""

from calculator.operations import average


def mean(values):
    """Arithmetic mean of a non-empty list of numbers."""
    if not values:
        raise ValueError("Cannot compute mean of an empty list")
    return average(values) / len(values)


def median(values):
    """Median of a list of numbers."""
    if not values:
        raise ValueError("Cannot compute median of an empty list")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
