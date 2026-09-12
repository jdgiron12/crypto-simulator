"""The ``Asset`` model: a simulated tradable instrument (e.g. BTC, ETH).

This is a plain data holder — no market data or pricing logic lives here.
Price generation belongs to ``core.market_engine``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    """A fictional tradable asset in the simulation.

    Attributes:
        symbol: Ticker symbol, e.g. "BTC". Used as the primary identifier.
        name: Human-readable name, e.g. "Bitcoin (Simulated)".
        base_currency: Currency the asset is priced in, e.g. "USD".
    """

    symbol: str
    name: str
    base_currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Asset.symbol must not be empty")
