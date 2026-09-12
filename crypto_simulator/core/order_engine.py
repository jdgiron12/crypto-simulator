"""``OrderEngine``: fictional order matching / execution.

Takes an ``Order`` and the current synthetic market state and decides how
(and whether) it fills, producing ``Trade`` records. This never touches a
real venue — "execution" here means updating simulated state only.

Scaffolding stage: interface only, no matching logic yet.
"""

from __future__ import annotations

from crypto_simulator.core.market_engine import MarketEngine
from crypto_simulator.models.order import Order
from crypto_simulator.models.trade import Trade


class OrderEngine:
    """Matches simulated orders against the ``MarketEngine``'s prices."""

    def __init__(self, market_engine: MarketEngine):
        self.market_engine = market_engine

    def submit(self, order: Order) -> Trade:
        """Attempt to fill ``order`` against current simulated prices.

        Not yet implemented — pending matching-rule design (see roadmap):
        market orders filling at current price, limit orders filling only
        when the simulated price crosses the limit, and fee/slippage
        modeling.
        """
        raise NotImplementedError(
            "OrderEngine.submit is not implemented yet; "
            "see docs/ROADMAP.md for the planned matching rules."
        )
