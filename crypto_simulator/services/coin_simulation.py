"""Builds a ``CoinSimulator`` from ``Settings``.

The single place coin-economy config is turned into objects, so the demo
script, tests and any future UI construct identical simulations. Each
participant gets its own seed derived from ``simulation.random_seed`` —
whales at ``+100 + i``, traders at ``+1000 + i``, manipulators at
``+2000 + i``, the random-event generator at ``+3000`` — so every RNG
stream is reproducible and independent of the price/volume streams
(``seed`` and ``seed + 1`` inside ``CoinSimulator``), adding manipulators
never reseeds the organic traders, and the random-event stream doesn't
depend on how many participants there are.

News events (``coin.events``) become an ``EventEngine`` of catalog-built
``MarketEvent``s (scheduled events use no randomness at all) plus, when
``random.probability`` is above 0, a ``RandomEventGenerator``.
"""

from __future__ import annotations

from dataclasses import dataclass

from crypto_simulator.config.settings import (
    EventSettings,
    RandomEventSettings,
    ScheduledEventSettings,
    Settings,
    TraderSettings,
)
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import (
    EventEngine,
    MarketEvent,
    RandomEventGenerator,
    create_event,
    validate_random_event_parameters,
)
from crypto_simulator.core.traders.registry import (
    create_manipulator,
    create_trader,
    enabled_crowd_sensitivity,
)
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.coin import Coin

WHALE_SEED_OFFSET = 100
TRADER_SEED_OFFSET = 1000
MANIPULATOR_SEED_OFFSET = 2000
RANDOM_EVENT_SEED_OFFSET = 3000

#: Distance between the base seeds of two runs of a batch (Phase 14).
#:
#: A run's base seed is not only the ``CoinSimulator``'s own seed (see
#: ``seed=base_seed`` below) but also the origin the participant seeds are
#: offset from, the largest of those offsets being
#: ``RANDOM_EVENT_SEED_OFFSET`` plus a participant index. Spacing runs by
#: one would therefore hand run *i*'s price engine the seed run *i - 100*
#: already gave a whale: different consumers drawing on an identical
#: stream. A stride wider than any within-run offset keeps each run's
#: whole seed space to itself, and 10,000 leaves room for thousands of
#: participants of every kind before the spaces could meet.
BATCH_SEED_STRIDE = 10_000

#: Bounds on a requested base seed — the value ``simulation.random_seed``
#: holds and ``_derive_seed`` adds its offsets to. They live here, beside
#: the derivation they bound, because both front ends that let a user pick
#: a seed (the CLI's ``--seed`` and the dashboard's seed control) already
#: import this module; neither defines a bound of its own, so the two
#: accept exactly the same seeds and a run seeded in one is reproducible
#: in the other. Not a simulator limit: ``_derive_seed`` is plain integer
#: addition and ``random.Random`` accepts any int.
MIN_SEED = 0
MAX_SEED = 2**32 - 1


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


# Per-tick random-event chance used by `scripts/simulate_coin.py --random-events`.
DEMO_RANDOM_EVENT_PROBABILITY = 0.1

# A small news schedule for `scripts/simulate_coin.py --events`: good news
# early, bad news later, both inside the default 20-tick demo.
DEMO_EVENTS: tuple[ScheduledEventSettings, ...] = (
    ScheduledEventSettings(
        id="demo-listing", category="exchange_listing", severity=0.8, start_tick=4, duration=4, decay_ticks=4,
    ),
    ScheduledEventSettings(
        id="demo-incident", category="security_incident", severity=0.7, start_tick=13, duration=3, decay_ticks=4,
    ),
)


def build_event_engine(events: EventSettings) -> EventEngine | None:
    """The ``EventEngine`` for ``coin.events``, or ``None`` when no event
    is configured (so the simulation runs exactly as without events).

    Each scheduled event is built through the catalog, so ``MarketEvent``
    and ``EventEngine`` do all event validation (duplicate ids included);
    errors are re-raised naming the offending event. The random-event
    settings are validated here too (by the generator's own rules), even
    though random events are started by ``build_event_generator``.
    """
    _check_random_event_settings(events.random)
    if not events.scheduled:
        return None
    return EventEngine(_scheduled_event(cfg) for cfg in events.scheduled)


def _scheduled_event(cfg: ScheduledEventSettings) -> MarketEvent:
    try:
        return create_event(
            cfg.category,
            event_id=cfg.id,
            severity=cfg.severity,
            start_tick=cfg.start_tick,
            duration=cfg.duration,
            decay_ticks=cfg.decay_ticks,
            headline=cfg.headline,
            sentiment=cfg.sentiment,
            volatility_boost=cfg.volatility_boost,
            attention=cfg.attention,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid scheduled event {cfg.id!r}: {exc}") from exc


def _check_random_event_settings(cfg: RandomEventSettings) -> None:
    try:
        validate_random_event_parameters(
            cfg.probability, cfg.categories, cfg.severity, cfg.duration, cfg.decay_ticks
        )
    except ValueError as exc:
        raise ValueError(f"coin.events.random: {exc}") from exc


def build_event_generator(cfg: RandomEventSettings, seed: int | None) -> RandomEventGenerator | None:
    """The generator for ``coin.events.random``, or ``None`` when its
    probability is 0 — then nothing is created and no random draw is made."""
    _check_random_event_settings(cfg)
    if cfg.probability == 0:
        return None
    return RandomEventGenerator(
        probability=cfg.probability,
        categories=cfg.categories,
        severity=cfg.severity,
        duration=cfg.duration,
        decay_ticks=cfg.decay_ticks,
        seed=seed,
    )


def _derive_seed(base_seed: int | None, offset: int) -> int | None:
    return None if base_seed is None else base_seed + offset


def build_coin_simulator(
    settings: Settings,
    *,
    include_traders: bool = True,
    include_whales: bool = True,
    pricing_mode: str | None = None,
    scenario: str | None = None,
    psychology: bool = False,
    whale_observation: bool = False,
    crowd_observation: bool = False,
    crowd_response: bool = False,
) -> CoinSimulator:
    """``pricing_mode`` overrides ``settings.coin.pricing_mode`` when given.

    ``psychology`` turns on market psychology and ``whale_observation``
    the per-tick whale recording (see ``CoinSimulator``); both are off by
    default and neither is part of the config.

    ``crowd_observation`` puts the previous completed tick's organic flow
    on every trader's context (Phase 19 Step 2) and ``crowd_response``
    lets the strategies that have one react to it (Step 4), by giving each
    trader its ``enabled_crowd_sensitivity``. Both default off, and they
    are separate flags on purpose: observation alone is the arm in which
    the signal is present and ignored, which is the only honest baseline
    to measure the response against. ``crowd_response`` implies
    ``crowd_observation``, since a sensitivity with nothing to read would
    be silently inert. Neither is part of the config.

    AMM mode rejects whales (see ``CoinSimulator``); pass
    ``include_whales=False`` to run it with a config that defines some.

    ``scenario`` (a key of ``MANIPULATION_SCENARIOS``) replaces
    ``settings.coin.manipulators`` and adds the scenario's followers after
    ``coin.traders``. ``include_traders`` only controls ``coin.traders``;
    scenario participants are always included. Manipulators trade last
    each tick.

    ``coin.events`` supplies the event engine (see ``build_event_engine``),
    the random-event generator (``build_event_generator``, seeded at
    ``simulation.random_seed + 3000``) and ``drift_per_sentiment``.
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
    events = build_event_engine(coin_cfg.events)
    event_generator = build_event_generator(
        coin_cfg.events.random, _derive_seed(base_seed, RANDOM_EVENT_SEED_OFFSET)
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
            starting_cash=w.starting_cash,
            behavior=w.behavior,
            target_coin_fraction=w.target_coin_fraction,
            min_trade_fraction=w.min_trade_fraction,
            cooldown_ticks=w.cooldown_ticks,
            min_trade_interval_ticks=w.min_trade_interval_ticks,
            intent_strength=w.intent_strength,
            cycle=w.cycle,
        )
        for i, w in enumerate(coin_cfg.whales)
    ] if include_whales else []
    # Followers continue the trader seed sequence after coin.traders, so
    # neither group's seeds depend on include_traders.
    organic = list(enumerate(coin_cfg.traders)) if include_traders else []
    organic += [(len(coin_cfg.traders) + j, t) for j, t in enumerate(follower_cfgs)]
    traders = [
        create_trader(
            t.strategy,
            t.id,
            **_common(t, _derive_seed(base_seed, TRADER_SEED_OFFSET + i)),
            crowd_sensitivity=enabled_crowd_sensitivity(t.strategy) if crowd_response else 0.0,
        )
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
        events=events,
        drift_per_sentiment=coin_cfg.events.drift_per_sentiment,
        event_generator=event_generator,
        psychology=psychology,
        whale_observation=whale_observation,
        crowd_observation=crowd_observation or crowd_response,
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
