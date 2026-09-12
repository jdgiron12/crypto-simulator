"""Strategy-name → trader-class lookup, used to build traders from config.

Adding a strategy means writing a ``TraderAgent`` subclass and listing it
here; ``CoinSimulator`` never needs to know the concrete types.
"""

from __future__ import annotations

from typing import Any

from crypto_simulator.core.traders.base import TraderAgent
from crypto_simulator.core.traders.strategies import (
    DipBuyer,
    LongTermHolder,
    MomentumTrader,
    PanicSeller,
    RetailTrader,
)

TRADER_STRATEGIES: dict[str, type[TraderAgent]] = {
    cls.strategy_name: cls
    for cls in (RetailTrader, MomentumTrader, DipBuyer, PanicSeller, LongTermHolder)
}


def create_trader(
    strategy: str,
    trader_id: str,
    *,
    params: dict[str, Any] | None = None,
    **common: Any,
) -> TraderAgent:
    """Instantiate the trader registered under ``strategy``.

    ``common`` carries the shared ``TraderAgent`` characteristics
    (starting_cash, trade_probability, seed, ...); ``params`` carries
    strategy-specific parameters.
    """
    try:
        cls = TRADER_STRATEGIES[strategy]
    except KeyError:
        raise ValueError(
            f"Unknown trader strategy {strategy!r}; "
            f"expected one of {sorted(TRADER_STRATEGIES)}"
        ) from None
    try:
        return cls(trader_id, **common, **(params or {}))
    except TypeError as exc:
        raise ValueError(f"Invalid parameters for {strategy!r} trader {trader_id!r}: {exc}") from exc
