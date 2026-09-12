"""``Whale``: a large coin holder capable of moving price with one trade.

Phase 1's ``CoinSimulator`` drives price purely through ``MarketEngine``'s
random walk — nothing represents an actor whose trade size, relative to
total supply, is large enough to move price on its own. This adds exactly
that: on ticks it decides to act, a whale buys or sells a random fraction
of total supply and the resulting trade size determines a multiplicative
price-impact factor.

Deliberately minimal: no order book, no liquidity-depth curve, no
counterparties to trade against — a plain linear impact model
(``impact = 1 + impact_coefficient * fraction_of_supply``). A later
liquidity-pool phase should replace this impact function with something
depth-aware, not bolt more cases onto it. There's also no shared ledger of
"everyone else's" holdings — a whale's own ``holdings`` only bounds how
much *it* can sell, consistent with this being a single-participant
extension, not a full market model.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class WhaleTrade:
    """One whale's trade for a single tick."""

    whale_id: str
    side: str
    quantity: float
    price_impact: float


class Whale:
    """A large holder that occasionally trades a chunk of total supply."""

    def __init__(
        self,
        whale_id: str,
        holdings: float,
        *,
        activity_probability: float = 0.1,
        max_trade_fraction: float = 0.05,
        impact_coefficient: float = 2.0,
        seed: int | None = None,
    ):
        if not whale_id:
            raise ValueError("whale_id must not be empty")
        if holdings < 0:
            raise ValueError("holdings must not be negative")
        if not 0.0 <= activity_probability <= 1.0:
            raise ValueError("activity_probability must be within [0, 1]")
        if not 0.0 < max_trade_fraction <= 1.0:
            raise ValueError("max_trade_fraction must be within (0, 1]")
        self.whale_id = whale_id
        self.holdings = holdings
        self.activity_probability = activity_probability
        self.max_trade_fraction = max_trade_fraction
        self.impact_coefficient = impact_coefficient
        self._rng = random.Random(seed)

    def maybe_trade(self, total_supply: float) -> WhaleTrade | None:
        """With probability ``activity_probability``, execute one trade.

        Returns ``None`` on ticks the whale sits out. Sells are capped at
        current holdings; buys are not (Phase 1 has no explicit
        counterparty ledger, so external liquidity is assumed). A sell's
        price impact divides price by the impact factor; a buy's
        multiplies by it.
        """
        if self._rng.random() > self.activity_probability:
            return None

        side = self._rng.choice(("buy", "sell"))
        trade_fraction = self._rng.uniform(0.0, self.max_trade_fraction)
        requested_quantity = trade_fraction * total_supply

        if side == "sell":
            quantity = min(self.holdings, requested_quantity)
            self.holdings -= quantity
        else:
            quantity = requested_quantity
            self.holdings += quantity

        fraction_of_supply = quantity / total_supply if total_supply else 0.0
        impact = 1.0 + self.impact_coefficient * fraction_of_supply
        price_impact = impact if side == "buy" else 1.0 / impact

        return WhaleTrade(
            whale_id=self.whale_id,
            side=side,
            quantity=quantity,
            price_impact=price_impact,
        )
