"""``MarketEngine``: the single source of (synthetic) prices in this project.

No network calls, no exchange SDKs, no real market data — by design. This
keeps the "fictional simulator" guarantee structural rather than a policy
that has to be remembered elsewhere.

Drives a per-asset geometric Brownian motion (zero drift, so prices drift
neither up nor down on average) seeded from configuration: given the same
seed and the same sequence of ``step()`` calls, a price path is
reproducible.
"""

from __future__ import annotations

import math
import random

from crypto_simulator.core.clock import SimulationClock

DEFAULT_INITIAL_PRICE = 100.0


class MarketEngine:
    """Generates synthetic prices for the simulator's assets."""

    def __init__(
        self,
        symbols: list[str],
        clock: SimulationClock,
        *,
        seed: int | None = None,
        initial_prices: dict[str, float] | None = None,
        volatility: float = 0.02,
    ):
        self.symbols = list(symbols)
        self.clock = clock
        self.seed = seed
        self.volatility = volatility
        self._rng = random.Random(seed)
        prices = initial_prices or {}
        self._prices: dict[str, float] = {
            symbol: prices.get(symbol, DEFAULT_INITIAL_PRICE) for symbol in self.symbols
        }

    def current_price(self, symbol: str) -> float:
        """Return the current simulated price for ``symbol``."""
        try:
            return self._prices[symbol]
        except KeyError:
            raise ValueError(f"Unknown symbol: {symbol!r}") from None

    def set_price(self, symbol: str, price: float) -> None:
        """Directly set the current price for ``symbol``.

        Lets an external system (a whale trade, a future news-event shock)
        apply an out-of-band price adjustment that the *next* ``step()``
        compounds from, without that system reaching into ``_prices``
        itself.
        """
        if symbol not in self._prices:
            raise ValueError(f"Unknown symbol: {symbol!r}")
        if price <= 0:
            raise ValueError("price must be positive")
        self._prices[symbol] = price

    def step(self) -> dict[str, float]:
        """Advance the market by one tick and return new prices per symbol.

        Each asset's price follows an independent GBM step:
        ``price *= exp((-0.5 * volatility**2) + volatility * Z)`` where
        ``Z`` is a standard normal draw. The ``-0.5 * volatility**2`` term
        keeps the *expected* price unchanged tick to tick (zero drift);
        without it, compounding lognormal noise would drift prices upward
        even with symmetric randomness.
        """
        self.clock.advance()
        for symbol in self.symbols:
            shock = self._rng.gauss(0.0, 1.0)
            drift = -0.5 * self.volatility**2
            factor = math.exp(drift + self.volatility * shock)
            self._prices[symbol] *= factor
        return dict(self._prices)
