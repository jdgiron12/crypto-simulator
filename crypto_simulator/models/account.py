"""The ``Account`` and ``Holding`` models: simulated cash + positions.

Balance math (deposits, fills applied, valuation) belongs to
``core.portfolio`` — these are plain data containers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Holding:
    """A position in a single simulated asset held by an account."""

    symbol: str
    quantity: float = 0.0
    average_cost: float = 0.0


@dataclass
class Account:
    """A simulated trading account: a cash balance plus asset holdings."""

    cash_balance: float
    base_currency: str = "USD"
    id: str = field(default_factory=lambda: str(uuid4()))
    holdings: dict[str, Holding] = field(default_factory=dict)
