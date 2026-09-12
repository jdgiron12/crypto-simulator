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

        Lets an external system (a whale trade, trader flow) apply an
        out-of-band price adjustment that the *next* ``step()`` compounds
        from, without that system reaching into ``_prices`` itself. (News
        events don't use this: they adjust the process via ``step()``.)
        """
        if symbol not in self._prices:
            raise ValueError(f"Unknown symbol: {symbol!r}")
        if price <= 0:
            raise ValueError("price must be positive")
        self._prices[symbol] = price

    def step(self, *, drift: float = 0.0, volatility_scale: float = 1.0) -> dict[str, float]:
        """Advance the market by one tick and return new prices per symbol.

        Each asset's price follows an independent GBM step:
        ``price *= exp((-0.5 * volatility**2) + volatility * Z)`` where
        ``Z`` is a standard normal draw. The ``-0.5 * volatility**2`` term
        keeps the *expected* price unchanged tick to tick (zero drift);
        without it, compounding lognormal noise would drift prices upward
        even with symmetric randomness.

        ``drift`` (extra log-return per tick) and ``volatility_scale``
        (multiplies ``volatility``) let an external process — the coin
        simulation's news events — shift the process itself rather than
        the price: ``price *= exp(drift - 0.5 * s**2 + s * Z)`` with
        ``s = volatility * volatility_scale``, applied to every symbol.
        The ``-0.5 * s**2`` term still keeps a volatility change alone from
        moving the expected price. Either way exactly one normal draw is
        made per symbol, and the defaults take the original code path, so
        ``step()`` results are unchanged bit for bit.
        """
        if drift != 0.0 or volatility_scale != 1.0:
            return self._adjusted_step(drift, volatility_scale)
        self.clock.advance()
        for symbol in self.symbols:
            shock = self._rng.gauss(0.0, 1.0)
            drift_term = -0.5 * self.volatility**2
            factor = math.exp(drift_term + self.volatility * shock)
            self._prices[symbol] *= factor
        return dict(self._prices)

    def _adjusted_step(self, drift: float, volatility_scale: float) -> dict[str, float]:
        """``step()`` with a drift and/or scaled volatility (see there).

        Raises ``ValueError`` instead of letting an extreme drift push a
        price to zero or infinity; no price changes in that case.
        """
        if not math.isfinite(drift):
            raise ValueError(f"drift must be finite (got {drift!r})")
        if not math.isfinite(volatility_scale) or volatility_scale < 0:
            raise ValueError(f"volatility_scale must be finite and non-negative (got {volatility_scale!r})")
        sigma = self.volatility * volatility_scale
        log_drift = drift - 0.5 * sigma**2
        self.clock.advance()
        new_prices = {}
        for symbol in self.symbols:
            shock = self._rng.gauss(0.0, 1.0)
            try:
                factor = math.exp(log_drift + sigma * shock)
            except OverflowError:
                factor = math.inf
            price = self._prices[symbol] * factor
            if not 0.0 < price < math.inf:
                raise ValueError(
                    f"Adjusted step would move {symbol} from {self._prices[symbol]!r} to {price!r} "
                    f"(drift {drift!r}, volatility_scale {volatility_scale!r}); the price must stay "
                    "positive and finite"
                )
            new_prices[symbol] = price
        self._prices.update(new_prices)
        return dict(self._prices)
