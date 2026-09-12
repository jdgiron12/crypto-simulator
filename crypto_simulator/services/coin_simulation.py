"""Builds a ``CoinSimulator`` from ``Settings``.

The single place coin-economy config is turned into objects, so the demo
script, tests and any future UI construct identical simulations. Each
participant gets its own seed derived from ``simulation.random_seed`` —
whales at ``+100 + i``, traders at ``+1000 + i``, manipulators at
``+2000 + i`` — so every RNG stream is reproducible and independent of the
price/volume streams (``seed`` and ``seed + 1`` inside ``CoinSimulator``),
and adding manipulators never reseeds the organic traders.
"""

from __future__ import annotations

from dataclasses import dataclass

from crypto_simulator.config.settings import Settings, TraderSettings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.traders.registry import create_manipulator, create_trader
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.coin import Coin

WHALE_SEED_OFFSET = 100
TRADER_SEED_OFFSET = 1000
MANIPULATOR_SEED_OFFSET = 2000


@dataclass(frozen=True)
class ManipulationScenario:
    """A ready-made manipulation setup.

    ``manipulators`` replace ``coin.manipulators``; ``followers`` are extra
    *organic* traders (``TRADER_STRATEGIES``) the scheme depends on — e.g.
    the crowd a pump-and-dump sells to — appended after ``coin.traders``.
    """

    description: str
    manipulators: tuple[TraderSettings, ...]
    followers: tuple[TraderSettings, ...] = ()


def _mark(i: int) -> TraderSettings:
    """A momentum chaser that jumps on a sharp rise and is slow to sell."""
    return TraderSettings(
        id=f"mark-{i}",
        strategy="momentum",
        starting_cash=20_000.0,
        trade_probability=0.8,
        max_trade_size=50_000.0,
        risk_tolerance=0.5,
        params={"lookback": 3, "entry_threshold": 0.15, "exit_threshold": 0.30},
    )


# Sized for the default `coin:` config; meant to be run in AMM mode, where
# price impact is measured against pool depth (see docs/ROADMAP.md).
MANIPULATION_SCENARIOS: dict[str, ManipulationScenario] = {
    "pump_and_dump": ManipulationScenario(
        description=(
            "Accumulate over ticks 5-14, pump ticks 15-16, dump ticks 17-19 onto "
            "four momentum-chasing marks"
        ),
        manipulators=(
            TraderSettings(
                id="pump-and-dump-1",
                strategy="pump_and_dump",
                starting_cash=30_000.0,
                trade_probability=1.0,
                max_trade_size=100_000.0,
                risk_tolerance=1.0,
                params={
                    "start_tick": 5,
                    "accumulate_ticks": 10,
                    "accumulate_share": 0.3,
                    "pump_ticks": 2,
                    "dump_ticks": 3,
                },
            ),
        ),
        followers=tuple(_mark(i) for i in range(1, 5)),
    ),
    "wash_trading": ManipulationScenario(
        description="One account trading with itself most ticks to inflate reported volume",
        manipulators=(
            TraderSettings(
                id="wash-trader-1",
                strategy="wash_trader",
                starting_cash=50_000.0,
                trade_probability=0.9,
                max_trade_size=40_000.0,
                risk_tolerance=0.8,
            ),
        ),
    ),
}


def _derive_seed(base_seed: int | None, offset: int) -> int | None:
    return None if base_seed is None else base_seed + offset


def build_coin_simulator(
    settings: Settings,
    *,
    include_traders: bool = True,
    include_whales: bool = True,
    pricing_mode: str | None = None,
    scenario: str | None = None,
) -> CoinSimulator:
    """``pricing_mode`` overrides ``settings.coin.pricing_mode`` when given.

    AMM mode rejects whales (see ``CoinSimulator``); pass
    ``include_whales=False`` to run it with a config that defines some.

    ``scenario`` (a key of ``MANIPULATION_SCENARIOS``) replaces
    ``settings.coin.manipulators`` and adds the scenario's followers after
    ``coin.traders``. ``include_traders`` only controls ``coin.traders``;
    scenario participants are always included. Manipulators trade last
    each tick.
    """
    coin_cfg = settings.coin
    base_seed = settings.simulation.random_seed
    if scenario is None:
        manipulator_cfgs, follower_cfgs = coin_cfg.manipulators, ()
    elif scenario in MANIPULATION_SCENARIOS:
        preset = MANIPULATION_SCENARIOS[scenario]
        manipulator_cfgs, follower_cfgs = preset.manipulators, preset.followers
    else:
        raise ValueError(
            f"Unknown manipulation scenario {scenario!r}; "
            f"expected one of {sorted(MANIPULATION_SCENARIOS)}"
        )
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
    # Followers continue the trader seed sequence after coin.traders, so
    # neither group's seeds depend on include_traders.
    organic = list(enumerate(coin_cfg.traders)) if include_traders else []
    organic += [(len(coin_cfg.traders) + j, t) for j, t in enumerate(follower_cfgs)]
    traders = [
        create_trader(t.strategy, t.id, **_common(t, _derive_seed(base_seed, TRADER_SEED_OFFSET + i)))
        for i, t in organic
    ]
    manipulators = [
        create_manipulator(m.strategy, m.id, **_common(m, _derive_seed(base_seed, MANIPULATOR_SEED_OFFSET + i)))
        for i, m in enumerate(manipulator_cfgs)
    ]
    return CoinSimulator(
        coin,
        seed=base_seed,
        volatility=coin_cfg.volatility,
        base_volume_pct=coin_cfg.base_volume_pct,
        tick_interval_seconds=settings.simulation.tick_interval_seconds,
        whales=whales,
        traders=traders + manipulators,
        reserve_cash=coin_cfg.market_reserve_cash,
        trader_impact_coefficient=coin_cfg.trader_impact_coefficient,
        pricing_mode=pricing_mode or coin_cfg.pricing_mode,
        amm_pool_coins=coin_cfg.amm.pool_coin_reserve,
        amm_fee_rate=coin_cfg.amm.fee_rate,
    )


def _common(cfg: TraderSettings, seed: int | None) -> dict:
    return dict(
        params=cfg.params,
        starting_cash=cfg.starting_cash,
        starting_coins=cfg.starting_coins,
        trade_probability=cfg.trade_probability,
        max_trade_size=cfg.max_trade_size,
        risk_tolerance=cfg.risk_tolerance,
        seed=seed,
    )
