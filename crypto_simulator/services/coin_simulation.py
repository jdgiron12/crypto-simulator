"""Builds a ``CoinSimulator`` from ``Settings``.

The single place coin-economy config is turned into objects, so the demo
script, tests and any future UI construct identical simulations. Each
participant gets its own seed derived from ``simulation.random_seed`` —
whales at ``+100 + i``, traders at ``+1000 + i`` — so every RNG stream is
reproducible and independent of the price/volume streams (``seed`` and
``seed + 1`` inside ``CoinSimulator``).
"""

from __future__ import annotations

from crypto_simulator.config.settings import Settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.traders.registry import create_trader
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.coin import Coin

WHALE_SEED_OFFSET = 100
TRADER_SEED_OFFSET = 1000


def _derive_seed(base_seed: int | None, offset: int) -> int | None:
    return None if base_seed is None else base_seed + offset


def build_coin_simulator(
    settings: Settings,
    *,
    include_traders: bool = True,
    include_whales: bool = True,
    pricing_mode: str | None = None,
) -> CoinSimulator:
    """``pricing_mode`` overrides ``settings.coin.pricing_mode`` when given.

    AMM mode rejects whales (see ``CoinSimulator``); pass
    ``include_whales=False`` to run it with a config that defines some.
    """
    coin_cfg = settings.coin
    base_seed = settings.simulation.random_seed
    coin = Coin(
        symbol=coin_cfg.symbol,
        name=coin_cfg.name,
        initial_supply=coin_cfg.initial_supply,
        starting_price=coin_cfg.starting_price,
    )
    whales = [
        Whale(
            whale_id=w.id,
            holdings=w.holdings,
            activity_probability=w.activity_probability,
            max_trade_fraction=w.max_trade_fraction,
            impact_coefficient=w.impact_coefficient,
            seed=_derive_seed(base_seed, WHALE_SEED_OFFSET + i),
        )
        for i, w in enumerate(coin_cfg.whales)
    ] if include_whales else []
    traders = (
        [
            create_trader(
                t.strategy,
                t.id,
                params=t.params,
                starting_cash=t.starting_cash,
                starting_coins=t.starting_coins,
                trade_probability=t.trade_probability,
                max_trade_size=t.max_trade_size,
                risk_tolerance=t.risk_tolerance,
                seed=_derive_seed(base_seed, TRADER_SEED_OFFSET + i),
            )
            for i, t in enumerate(coin_cfg.traders)
        ]
        if include_traders
        else []
    )
    return CoinSimulator(
        coin,
        seed=base_seed,
        volatility=coin_cfg.volatility,
        base_volume_pct=coin_cfg.base_volume_pct,
        tick_interval_seconds=settings.simulation.tick_interval_seconds,
        whales=whales,
        traders=traders,
        reserve_cash=coin_cfg.market_reserve_cash,
        trader_impact_coefficient=coin_cfg.trader_impact_coefficient,
        pricing_mode=pricing_mode or coin_cfg.pricing_mode,
        amm_pool_coins=coin_cfg.amm.pool_coin_reserve,
        amm_fee_rate=coin_cfg.amm.fee_rate,
    )
