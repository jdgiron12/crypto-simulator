"""Strategy-name → trader-class lookup, used to build traders from config.

Adding a strategy means writing a ``TraderAgent`` subclass and listing it
here; ``CoinSimulator`` never needs to know the concrete types.

Organic strategies (``TRADER_STRATEGIES``, config ``coin.traders``) and
market-manipulation strategies (``MANIPULATION_STRATEGIES``, config
``coin.manipulators``) are kept in separate registries so a manipulator
can't end up in the organic population by accident.
"""

from __future__ import annotations

from typing import Any

from crypto_simulator.core.traders.base import TraderAgent
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
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

MANIPULATION_STRATEGIES: dict[str, type[TraderAgent]] = {
    cls.strategy_name: cls for cls in (PumpAndDump, WashTrader)
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
    hint = " (manipulation strategies go under coin.manipulators)" if strategy in MANIPULATION_STRATEGIES else ""
    return _create(TRADER_STRATEGIES, "trader", strategy, trader_id, params, common, hint)


def create_manipulator(
    strategy: str,
    trader_id: str,
    *,
    params: dict[str, Any] | None = None,
    **common: Any,
) -> TraderAgent:
    """Like ``create_trader``, for ``MANIPULATION_STRATEGIES``."""
    return _create(MANIPULATION_STRATEGIES, "manipulator", strategy, trader_id, params, common)


def _create(registry, role, strategy, trader_id, params, common, hint="") -> TraderAgent:
    try:
        cls = registry[strategy]
    except KeyError:
        raise ValueError(
            f"Unknown {role} strategy {strategy!r}; expected one of {sorted(registry)}{hint}"
        ) from None
    try:
        return cls(trader_id, **common, **(params or {}))
    except TypeError as exc:
        raise ValueError(f"Invalid parameters for {strategy!r} {role} {trader_id!r}: {exc}") from exc
