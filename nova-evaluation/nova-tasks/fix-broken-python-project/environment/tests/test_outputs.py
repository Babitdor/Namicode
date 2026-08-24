"""Test suite for the calculator package. Do not modify."""

import pytest

from calculator.main import process_order
from calculator.operations import add, divide, multiply
from calculator.stats import mean, median


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_multiply():
    assert multiply(3, 4) == 12
    assert multiply(-2, 5) == -10


def test_divide():
    assert divide(10, 2) == 5
    assert divide(1, 4) == 0.25
    with pytest.raises(ValueError):
        divide(1, 0)


def test_mean():
    assert mean([1, 2, 3, 4]) == 2.5
    assert mean([7]) == 7
    with pytest.raises(ValueError):
        mean([])


def test_median():
    assert median([1, 3, 2]) == 2
    assert median([1, 2, 3, 4]) == 2.5
    assert median([5]) == 5


def test_process_order():
    assert process_order(100, 0.1) == 90.0
    assert process_order(50, 0.0) == 50.0
    assert process_order(200, 0.25) == 150.0
