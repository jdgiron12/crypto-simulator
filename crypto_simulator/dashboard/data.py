"""The dashboard's data interface (Phase 10, Steps 1 and 7).

The one place the dashboard is allowed to reach the simulator, and the
only thing the view is given:

    build_coin_simulator -> CoinSimulator.run -> build_report
                         -> DashboardPayload -> payload_to_dict

``run_simulation`` runs a simulation *once*, builds its
``SimulationReport`` *once*, and returns one ``DashboardPayload`` for the
whole dashboard to read. Nothing here is a second analytics engine: every
analytical figure comes from the report, which this module neither
recomputes nor adjusts. The price series it adds alongside the report is
the simulator's own recorded per-tick price and volume — output copied,
not analysis redone.

**Observer only.** The simulator is the source of truth. This module
builds a simulator, runs it and reads the finished run; it never writes to
ticks, wallets, traders, whales, psychology, events, the pool or the RNG,
and nothing in ``core``/``services``/``analytics`` imports it. Running a
simulation here is identical to running ``scripts/simulate_coin.py`` with
the same flags — same builder, same seeds, same report inputs — so the
dashboard cannot produce numbers the CLI would not.

**Parameters are a closed set.** ``SimulationParams`` accepts only the
options the CLI already exposes plus the seed (Step 7), validated against
known values (``PricingMode``, ``MANIPULATION_SCENARIOS``) with explicit
tick and seed bounds. Nothing is evaluated, imported or executed by name
from caller input.

**Determinism.** Same parameters in, same payload out: the run is seeded
from config unless the request names a seed, ``simulation_id`` is derived
from the parameters and the seed actually used (never random, never a
clock reading), and the payload carries tick *numbers* rather than the
clock's wall-clock-anchored timestamps, which would differ between two
otherwise identical runs.

**The seed is selected, not invented** (Step 7). A requested seed
replaces ``simulation.random_seed`` in a copy of the settings and reaches
the run only through ``build_coin_simulator``'s own derivation, so a
seeded dashboard run is still exactly a CLI run — the run
``scripts/simulate_coin.py`` performs with those flags and that seed
configured. Requesting no seed leaves the settings untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import blake2b
from typing import Any, Callable, Iterable, Sequence

from crypto_simulator.analytics.report import SimulationReport, build_report
from crypto_simulator.analytics.tick_series import TickSeries, build_tick_series
from crypto_simulator.config import get_settings
from crypto_simulator.config.settings import Settings
from crypto_simulator.core.coin_simulator import CoinSimulator, SimulationTick
from crypto_simulator.dashboard.serialization import to_jsonable
from crypto_simulator.services.coin_simulation import (
    DEMO_EVENTS,
    DEMO_RANDOM_EVENT_PROBABILITY,
    MAX_SEED,
    MIN_SEED,
    build_coin_simulator,
)
from crypto_simulator.services.market_conditions import apply_market_condition
from crypto_simulator.services.simulation_params import (
    MAX_TICKS,
    PRICING_MODES,
    SCENARIOS,
    SimulationParams,
)

__all__ = [
    "MAX_SEED",
    "MAX_TICKS",
    "MIN_SEED",
    "PRICING_MODES",
    "SCENARIOS",
    "DashboardPayload",
    "DashboardRun",
    "PricePoint",
    "SimulationMeta",
    "SimulationParams",
    "TICK_SERIES_UNAVAILABLE_MESSAGE",
    "configured_seed",
    "payload_to_dict",
    "run_dashboard_simulation",
    "run_simulation",
    "tick_series_to_dict",
]

#: What a Phase 20 view shows for a run that has no ``TickSeries`` — every
#: saved run, since the tick series is never persisted and is never rebuilt
#: from a stored payload.
TICK_SERIES_UNAVAILABLE_MESSAGE = "Tick-level data was not recorded for this saved run."


#: ``MAX_TICKS``, ``PRICING_MODES``, ``SCENARIOS``, ``SimulationParams``,
#: ``MIN_SEED`` and ``MAX_SEED`` are re-exported from ``services``, which
#: owns them: the seed bounds beside the derivation they bound (Phase 11)
#: and the request type beside the builder whose arguments it mirrors
#: (Phase 13, so a scenario service can validate into it without importing
#: a front end). They stay in this module's namespace for the view and the
#: tests that already read them from here.


@dataclass(frozen=True)
class PricePoint:
    """One recorded tick, as the simulator recorded it.

    The tick's own ``price``, ``market_cap`` and ``volume`` — copied, not
    derived. There is no timestamp: the clock is anchored to the wall
    clock the run started at, so timestamps would differ between two
    identical runs, while tick numbers are the run's stable time axis.
    """

    tick: int
    price: float
    market_cap: float
    volume: float


@dataclass(frozen=True)
class SimulationMeta:
    """What was run, and what came back.

    ``simulation_id`` is derived from ``params`` and ``random_seed``, so
    the same request always has the same id. ``completed_ticks`` is how
    many ticks the run actually produced (``requested_ticks`` is what was
    asked for); the coin fields are the run's configuration, not analytics.
    """

    simulation_id: str
    params: SimulationParams
    coin_symbol: str
    coin_name: str
    initial_supply: float
    starting_price: float
    pricing_mode: str
    random_seed: int | None
    requested_ticks: int
    completed_ticks: int


@dataclass(frozen=True)
class DashboardPayload:
    """One finished run, ready for the dashboard.

    ``report`` is the ``SimulationReport`` unchanged — the analytical
    source of truth for every section. ``price_series`` is the recorded
    price path for charting. ``simulation`` is the run's metadata.
    """

    simulation: SimulationMeta
    report: SimulationReport
    price_series: tuple[PricePoint, ...]


def run_simulation(
    params: SimulationParams | None = None,
    *,
    settings: Settings | None = None,
    builder: Callable[..., CoinSimulator] = build_coin_simulator,
) -> DashboardPayload:
    """Run one simulation and return its payload.

    ``settings`` defaults to the application settings; ``builder`` exists
    so tests can drive the failure path, and defaults to the same builder
    the CLI uses. Any ``ValueError`` (an unsupported combination such as
    whales in AMM mode, say) propagates from the builder or the simulator
    unchanged — the caller decides how to show it.
    """
    payload, _, _ = _execute(params, settings, builder)
    return payload


@dataclass(frozen=True)
class DashboardRun:
    """One finished run for the dashboard (Phase 20, Step 3).

    ``payload`` is exactly the ``DashboardPayload`` ``run_simulation``
    returns for the same request. ``tick_series`` is the run's
    ``TickSeries`` — ephemeral dashboard analytical data built from the
    same ticks, never part of the payload and never persisted, so a saved
    run has none (``TICK_SERIES_UNAVAILABLE_MESSAGE``).
    """

    payload: DashboardPayload
    tick_series: TickSeries


def run_dashboard_simulation(
    params: SimulationParams | None = None,
    *,
    settings: Settings | None = None,
    builder: Callable[..., CoinSimulator] = build_coin_simulator,
) -> DashboardRun:
    """Run one simulation and return its payload and its tick series.

    The simulation runs once, through the same path as ``run_simulation``,
    so the payload is the one ``run_simulation`` would return for the same
    arguments. The tick series is built afterwards from the recorded ticks,
    with the population read from the built simulator: each trader's
    strategy and the number of whales.
    """
    payload, sim, ticks = _execute(params, settings, builder)
    population: dict[str, int] = {}
    for trader in sim.traders:
        population[trader.strategy_name] = population.get(trader.strategy_name, 0) + 1
    tick_series = build_tick_series(
        ticks,
        total_supply=sim.coin.initial_supply,
        population=population,
        whale_count=len(sim.whales),
    )
    return DashboardRun(payload=payload, tick_series=tick_series)


def tick_series_to_dict(tick_series: TickSeries) -> dict[str, Any]:
    """The tick series as JSON-compatible Python, by the same
    ``dashboard.serialization`` rules as the payload: ``{"columns": [...],
    "rows": N, "data": {column: [...]}, "classes": {strategy: {field:
    [...]}}, "population": {...}, "whale_count": n}``."""
    if not isinstance(tick_series, TickSeries):
        raise TypeError(f"expected a TickSeries, got {type(tick_series).__name__}")
    return to_jsonable(tick_series)


def _execute(
    params: SimulationParams | None,
    settings: Settings | None,
    builder: Callable[..., CoinSimulator],
) -> tuple[DashboardPayload, CoinSimulator, tuple[SimulationTick, ...]]:
    """Build, run and report one simulation — the single execution path
    behind ``run_simulation`` and ``run_dashboard_simulation``."""
    params = params or SimulationParams()
    settings = _with_seed_override(
        _with_event_overrides(_with_market_condition(settings or get_settings(), params), params),
        params,
    )
    sim = builder(
        settings,
        include_traders=params.include_traders,
        include_whales=params.include_whales,
        pricing_mode=params.pricing_mode,
        scenario=params.scenario,
        psychology=params.psychology,
        whale_observation=params.whale_observation,
    )
    # Read before the run, exactly as the CLI does: the report's P&L needs
    # each trader's starting wallet.
    start_balances = _balances(sim)
    ticks = sim.run(params.ticks)
    report = _build_report(sim, ticks, start_balances)
    meta = SimulationMeta(
        simulation_id=_simulation_id(params, settings.simulation.random_seed),
        params=params,
        coin_symbol=sim.coin.symbol,
        coin_name=sim.coin.name,
        initial_supply=sim.coin.initial_supply,
        starting_price=sim.coin.starting_price,
        pricing_mode=sim.pricing_mode.value,
        random_seed=settings.simulation.random_seed,
        requested_ticks=params.ticks,
        completed_ticks=len(ticks),
    )
    payload = DashboardPayload(simulation=meta, report=report, price_series=_price_series(ticks))
    return payload, sim, tuple(ticks)


def payload_to_dict(payload: DashboardPayload) -> dict[str, Any]:
    """The payload as JSON-compatible Python — the dashboard's contract.

    ``{"simulation": {...}, "report": {...}, "price_series": [...]}``,
    every value converted by ``dashboard.serialization`` rules.
    """
    if not isinstance(payload, DashboardPayload):
        raise TypeError(f"expected a DashboardPayload, got {type(payload).__name__}")
    return to_jsonable(payload)


def _with_event_overrides(settings: Settings, params: SimulationParams) -> Settings:
    """Apply ``--events`` / ``--random-events`` the way the CLI does."""
    events = settings.coin.events
    if params.events:
        events = replace(events, scheduled=list(DEMO_EVENTS))
    if params.random_events:
        events = replace(events, random=replace(events.random, probability=DEMO_RANDOM_EVENT_PROBABILITY))
    if events is settings.coin.events:
        return settings
    return replace(settings, coin=replace(settings.coin, events=events))


def configured_seed(settings: Settings | None = None) -> int:
    """The seed a run uses when the request names none (Step 7).

    The dashboard's single reader of ``simulation.random_seed``: the view
    shows it as the seed control's starting value, so turning the control
    on without changing the number reproduces the configured run rather
    than silently switching to some other one. Settings access stays in
    this module — the view reads no configuration of its own.
    """
    return (settings or get_settings()).simulation.random_seed


def _with_market_condition(settings: Settings, params: SimulationParams) -> Settings:
    """Apply a requested market condition (Phase 17).

    Applied before the event overrides, so a request that also asks for
    ``events``/``random_events`` still gets those on top: a preset sets
    the weather, an explicit flag overrules it. ``None`` returns the
    settings unchanged, by identity.

    The effective pricing mode is passed through because a preset's
    sentiment drift belongs to the random walk and the simulator refuses
    it in AMM mode.
    """
    return apply_market_condition(
        settings, params.market_condition, pricing_mode=params.pricing_mode
    )


def _with_seed_override(settings: Settings, params: SimulationParams) -> Settings:
    """Apply a requested seed (Step 7), the way the CLI applies its flags.

    ``None`` returns the settings unchanged — the configured seed, which
    is what every run used before Step 7 — so a defaulted request builds
    the same simulator, from the same settings object, as it always did.
    An integer replaces only ``simulation.random_seed``; every
    participant seed then follows from it through the builder's own
    derivation, so nothing here seeds a participant directly.
    """
    if params.random_seed is None:
        return settings
    return replace(
        settings, simulation=replace(settings.simulation, random_seed=params.random_seed)
    )


def _build_report(
    sim: CoinSimulator, ticks: Sequence[SimulationTick], start_balances: dict[str, tuple[float, float]]
) -> SimulationReport:
    """The unified report for a finished run, built once, from the same
    inputs ``scripts/simulate_coin.py --report`` uses."""
    events = random_ids = None
    if sim.events is not None:
        events = sim.events.events
        generated = sim.event_generator.generated_events if sim.event_generator else ()
        random_ids = [event.event_id for event in generated]
    return build_report(
        ticks,
        events=events,
        random_event_ids=random_ids,
        initial_price=sim.coin.starting_price,
        total_supply=sim.coin.initial_supply,
        start_balances=start_balances,
        end_balances=_balances(sim),
    )


def _balances(sim: CoinSimulator) -> dict[str, tuple[float, float]]:
    return {trader.trader_id: (trader.wallet.cash, trader.wallet.coins) for trader in sim.traders}


def _price_series(ticks: Iterable[SimulationTick]) -> tuple[PricePoint, ...]:
    return tuple(
        PricePoint(tick=tick.tick, price=tick.price, market_cap=tick.market_cap, volume=tick.volume)
        for tick in ticks
    )


#: Fields left out of a run's id while they are unset.
#:
#: The id is a hash of the request, so adding a field to
#: ``SimulationParams`` would otherwise change the id of every request
#: ever made — including ones already quoted in a saved run or a report.
#: A field listed here contributes only once it is used, so a request
#: that does not mention it keeps the id it has always had, and two
#: requests that differ in it still differ. Phase 17 added
#: ``market_condition``; the same treatment is what a later optional
#: field should get.
_ID_OPTIONAL_FIELDS = ("market_condition",)


def _simulation_id(params: SimulationParams, seed: int | None) -> str:
    """A stable id for a request: the same parameters and seed always give
    the same id, and nothing else feeds into it."""
    fields = to_jsonable(params)
    for name in _ID_OPTIONAL_FIELDS:
        if fields.get(name) is None:
            del fields[name]
    canonical = json.dumps(
        {"params": fields, "seed": seed}, sort_keys=True, separators=(",", ":")
    )
    return blake2b(canonical.encode("utf-8"), digest_size=8).hexdigest()
