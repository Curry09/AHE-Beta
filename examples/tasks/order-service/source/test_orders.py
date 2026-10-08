"""Visible checks for the order service's public behavior."""

import pytest
from orders import OrderItem, total_cents


def test_empty_cart():
    assert total_cents([]) == 0


def test_single_item():
    assert total_cents([OrderItem("book", 1299)]) == 1299


def test_multiple_units_are_charged():
    assert total_cents([OrderItem("book", 1299, 3)]) == 3897


def test_mixed_cart():
    assert total_cents([OrderItem("book", 1299, 2), OrderItem("pen", 250, 4)]) == 3598


@pytest.mark.parametrize("item", [OrderItem("bad", -1), OrderItem("bad", 100, 0)])
def test_invalid_input(item):
    with pytest.raises(ValueError):
        total_cents([item])
