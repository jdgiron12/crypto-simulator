"""The ``Trade`` model: a completed (simulated) fill.

Produced by ``core.order_engine`` when an ``Order`` is matched against the
synthetic market. Never represents a real-world execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from crypto_simulator.models.order import OrderSide


@dataclass(frozen=True)
class Trade:
    """A completed fill resulting from a simulated order execution."""

    order_id: str
    account_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    id: str = field(default_factory=lambda: str(uuid4()))
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def notional(self) -> float:
        """Total value of the trade (quantity * price)."""
        return self.quantity * self.price
