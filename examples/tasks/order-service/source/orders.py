"""A small order service using integer cents."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderItem:
    sku: str
    unit_price_cents: int
    quantity: int = 1


def total_cents(items: Iterable[OrderItem]) -> int:
    """Return the cart total, rejecting invalid prices or quantities."""
    total = 0
    for item in items:
        if item.unit_price_cents < 0:
            raise ValueError("price must not be negative")
        if item.quantity < 1:
            raise ValueError("quantity must be positive")
        total += item.unit_price_cents
    return total
