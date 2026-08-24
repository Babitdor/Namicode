"""Test suite for the pricing module. Do not modify."""

import sys

sys.path.insert(0, "/app/repo")

from prices import total_price


def test_total_price_with_tax():
    assert total_price(10, 1, 0.1) == 11.0


def test_total_price_no_tax():
    assert total_price(10, 3, 0.0) == 30.0


def test_total_price_with_tax_and_quantity():
    assert total_price(5, 2, 0.2) == 12.0


def test_total_price_defaults():
    assert total_price(7) == 7.0
