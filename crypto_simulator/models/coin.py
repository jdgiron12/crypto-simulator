"""The ``Coin`` model: a single fictional cryptocurrency's fixed economics.

This is a plain data holder — no price or volume simulation lives here
(that's ``core.coin_simulator``). Phase 1 has no minting/burning, so a
coin's supply is constant for the life of a simulation run; a later phase
that introduces inflation/burning would extend this, not replace it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coin:
    """A fictional, simulated cryptocurrency.

    Attributes:
        symbol: Ticker symbol, e.g. "FIC". Used as the primary identifier.
        name: Human-readable name, e.g. "FictiCoin (Simulated)".
        initial_supply: Total token supply, held constant in Phase 1.
        starting_price: Price per token at simulation tick 0, in the
            simulation's base currency.
    """

    symbol: str
    name: str
    initial_supply: float
    starting_price: float

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Coin.symbol must not be empty")
        if self.initial_supply <= 0:
            raise ValueError("Coin.initial_supply must be positive")
        if self.starting_price <= 0:
            raise ValueError("Coin.starting_price must be positive")
