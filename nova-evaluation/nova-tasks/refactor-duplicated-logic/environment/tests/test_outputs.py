"""Test suite for the shop package. Do not modify."""

import inspect

import pytest

import shop.inventory as inventory
import shop.orders as orders
import shop.validation as validation


def test_orders_behavior():
    assert orders.create_order("AB12CD34", 10.0, 2) == {
        "sku": "AB12CD34",
        "total": 20.0,
    }


def test_orders_rejects_bad_sku():
    with pytest.raises(ValueError):
        orders.create_order("bad", 10.0, 1)


def test_orders_rejects_bad_price():
    with pytest.raises(ValueError):
        orders.create_order("AB12CD34", -5.0, 1)


def test_inventory_behavior():
    assert inventory.restock("AB12CD34", 5.0, 10) == {
        "sku": "AB12CD34",
        "value": 50.0,
    }


def test_inventory_rejects_bad_sku():
    with pytest.raises(ValueError):
        inventory.restock("nope", 5.0, 1)


def test_validation_module_exposes_shared_helpers():
    assert callable(validation.validate_sku)
    assert callable(validation.validate_price)
    assert validation.validate_sku("AB12CD34") == "AB12CD34"
    assert validation.validate_price(9.99) == 9.99


def test_duplication_removed_from_orders():
    src = inspect.getsource(orders)
    assert "_validate_sku" not in src
    assert "_validate_price" not in src


def test_duplication_removed_from_inventory():
    src = inspect.getsource(inventory)
    assert "_validate_sku" not in src
    assert "_validate_price" not in src
