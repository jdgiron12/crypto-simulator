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

**Batches** (Phase 20, Step 6). ``run_dashboard_batch`` is the CLI's
``--batch`` path — Phase 14's ``run_batch`` with ``run_simulation`` as the
runner, then Phase 15's ``aggregate_batch`` — capped at
``MAX_DASHBOARD_BATCH_RUNS``. The result is reduced at once to a
``DashboardBatch``: run counts, failures, each successful run's aggregated
market metric values and the ``AggregateStatistics`` unchanged. No payload,
price series or tick series survives the reduction, and nothing is
recomputed.

**Scenario comparisons** (Phase 20, Step 7). ``run_dashboard_comparison``
runs one such batch per explicitly selected configuration — a pricing
mode, a manipulation preset and a Phase 17 market condition — with every
other field of the request held constant and one shared base seed, so
corresponding runs have the same derived seed. ``plan_comparison`` checks
the selection first (the simulator's refusal of AMM with whales, the
per-configuration and ``MAX_COMPARISON_RUNS`` limits) and reports a problem
rather than adjusting the request. Each group keeps only its reduced batch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import blake2b
from itertools import product
from typing import Any, Callable, Iterable, Sequence

from crypto_simulator.analytics.aggregate import (
    AGGREGATED_METRICS,
    AggregateStatistics,
    _metric_value,
    aggregate_batch,
)
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
from crypto_simulator.services.batch import (
    MAX_BATCH_RUNS,
    MIN_BATCH_RUNS,
    BatchResult,
    run_batch,
)
from crypto_simulator.services.market_conditions import (
    MARKET_CONDITION_NAMES,
    apply_market_condition,
)
from crypto_simulator.services.simulation_params import (
    MAX_TICKS,
    PRICING_MODES,
    SCENARIOS,
    SimulationParams,
)

__all__ = [
    "BATCH_HISTOGRAM_METRICS",
    "MAX_BATCH_RUNS",
    "MAX_DASHBOARD_BATCH_RUNS",
    "MAX_SEED",
    "MAX_TICKS",
    "MIN_BATCH_RUNS",
    "MIN_SEED",
    "PRICING_MODES",
    "SCENARIOS",
    "BatchRunFailure",
    "BatchRunValues",
    "COMPARISON_MARKET_CONDITIONS",
    "COMPARISON_SCENARIOS",
    "ComparisonConfiguration",
    "ComparisonGroup",
    "ComparisonPlan",
    "DashboardBatch",
    "MARKET_CONDITION_LABELS",
    "MAX_COMPARISON_RUNS",
    "PRICING_MODE_LABELS",
    "SCENARIO_LABELS",
    "ScenarioComparison",
    "DashboardPayload",
    "DashboardRun",
    "PricePoint",
    "SimulationMeta",
    "SimulationParams",
    "TICK_SERIES_UNAVAILABLE_MESSAGE",
    "batch_to_dict",
    "comparison_configurations",
    "comparison_to_dict",
    "configured_seed",
    "payload_to_dict",
    "plan_comparison",
    "plan_to_dict",
    "reduce_batch",
    "run_dashboard_batch",
    "run_dashboard_comparison",
    "run_dashboard_simulation",
    "run_simulation",
    "tick_series_to_dict",
]

#: The dashboard's own cap on runs per batch (Phase 20, Step 6). A dashboard
#: batch runs synchronously inside one Streamlit rerun, so it is held well
#: below the batch service's ``MAX_BATCH_RUNS``, which is unchanged and
#: still what the CLI allows.
MAX_DASHBOARD_BATCH_RUNS = 200

#: The dashboard's cap on the simulations one scenario comparison runs in
#: total — configurations x runs per configuration (Phase 20, Step 7). Each
#: configuration is also held to ``MAX_DASHBOARD_BATCH_RUNS``; neither
#: changes the batch service's ``MAX_BATCH_RUNS``.
MAX_COMPARISON_RUNS = 400

#: The values a comparison can vary, in the order configurations are listed:
#: the existing pricing modes, manipulation presets and Phase 17 market
#: conditions, with ``None`` (no preset) first. Nothing is added to them.
COMPARISON_SCENARIOS: tuple[str | None, ...] = (None, *SCENARIOS)
COMPARISON_MARKET_CONDITIONS: tuple[str | None, ...] = (None, *MARKET_CONDITION_NAMES)

#: Display names for configuration labels. ``None`` is the default: no
#: manipulation preset, and the neutral market (no market-condition preset).
PRICING_MODE_LABELS: dict[str, str] = {"random_walk": "RW", "amm": "AMM"}
SCENARIO_LABELS: dict[str | None, str] = {
    None: "No manipulation",
    "pump_and_dump": "Pump & dump",
    "wash_trading": "Wash trading",
}
MARKET_CONDITION_LABELS: dict[str | None, str] = {
    None: "Neutral (no preset)",
    "bull": "Bull",
    "bear": "Bear",
    "meme": "Meme",
}

#: The aggregated market metrics drawn as per-run histograms (Phase 20,
#: Step 6) — a selection from ``AGGREGATED_METRICS``, not a second list of
#: metrics.
BATCH_HISTOGRAM_METRICS: tuple[str, ...] = (
    "close_price",
    "cumulative_return",
    "max_drawdown",
    "total_volume",
)

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


@dataclass(frozen=True)
class BatchRunValues:
    """One successful batch run, reduced to its aggregated market metrics
    (Phase 20, Step 6).

    ``metrics`` holds every ``AGGREGATED_METRICS`` value exactly as
    ``aggregate_batch`` reads it off the run's ``MarketSummary`` — ``None``
    where the run did not compute it.
    """

    index: int
    seed: int
    simulation_id: str
    metrics: dict[str, float | None]


@dataclass(frozen=True)
class BatchRunFailure:
    """One batch run that raised, with the message ``run_batch`` recorded."""

    index: int
    seed: int
    error: str


@dataclass(frozen=True)
class DashboardBatch:
    """A finished batch, reduced for the dashboard (Phase 20, Step 6).

    Everything the batch views read, and nothing else: the request (whose
    ``random_seed`` is the batch's base seed, as in ``BatchResult``), the
    run counts, each successful run's aggregated metric values, each
    failure, and the ``AggregateStatistics`` ``aggregate_batch`` returned,
    unchanged. No ``DashboardPayload``, price series or tick series is
    kept. ``coin_symbol`` is the first successful run's symbol, or
    ``None`` when no run finished.
    """

    params: SimulationParams
    base_seed: int
    requested_runs: int
    successful_runs: int
    failed_runs: int
    coin_symbol: str | None
    runs: tuple[BatchRunValues, ...]
    failures: tuple[BatchRunFailure, ...]
    aggregate: AggregateStatistics


def run_dashboard_batch(
    params: SimulationParams,
    runs: int,
    *,
    settings: Settings | None = None,
    runner: Callable[[SimulationParams], DashboardPayload] = run_simulation,
) -> DashboardBatch:
    """Run ``params`` ``runs`` times and return the reduced batch.

    The batch is Phase 14's ``run_batch`` with ``run_simulation`` as its
    runner — the CLI's ``--batch`` call — and its description is Phase
    15's ``aggregate_batch``; both are used as they are. ``runs`` is held
    to ``MAX_DASHBOARD_BATCH_RUNS`` here, and the full batch result is
    dropped once it is reduced.
    """
    if not isinstance(runs, int) or isinstance(runs, bool):
        raise ValueError(f"runs must be an integer (got {runs!r})")
    if not MIN_BATCH_RUNS <= runs <= MAX_DASHBOARD_BATCH_RUNS:
        raise ValueError(
            f"runs must be between {MIN_BATCH_RUNS} and {MAX_DASHBOARD_BATCH_RUNS} "
            f"(the dashboard batch limit; got {runs})"
        )
    return reduce_batch(run_batch(params, runs, runner=runner, settings=settings))


def reduce_batch(result: BatchResult) -> DashboardBatch:
    """The dashboard's reduction of a finished batch.

    The aggregate is ``aggregate_batch(result)`` itself; the per-run values
    are read through the same accessor it reads them with, so a run's
    value and the aggregate's observations can never disagree.
    """
    completed = result.completed
    return DashboardBatch(
        params=result.params,
        base_seed=result.base_seed,
        requested_runs=result.requested_runs,
        successful_runs=len(completed),
        failed_runs=len(result.failed),
        coin_symbol=completed[0].payload.simulation.coin_symbol if completed else None,
        runs=tuple(
            BatchRunValues(
                index=run.index,
                seed=run.seed,
                simulation_id=run.payload.simulation.simulation_id,
                metrics={
                    metric: _metric_value(run.payload.report.market, metric)
                    for metric in AGGREGATED_METRICS
                },
            )
            for run in completed
        ),
        failures=tuple(
            BatchRunFailure(index=run.index, seed=run.seed, error=run.error)
            for run in result.failed
        ),
        aggregate=aggregate_batch(result),
    )


def batch_to_dict(batch: DashboardBatch) -> dict[str, Any]:
    """The reduced batch as JSON-compatible Python, by the same
    ``dashboard.serialization`` rules as the payload. Each run's
    ``metrics`` object has sorted keys; the aggregate's ``metrics`` list
    keeps ``AGGREGATED_METRICS`` order."""
    if not isinstance(batch, DashboardBatch):
        raise TypeError(f"expected a DashboardBatch, got {type(batch).__name__}")
    return to_jsonable(batch)


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


# --- scenario comparison (Phase 20, Step 7) ----------------------------------------------------------------


@dataclass(frozen=True)
class ComparisonConfiguration:
    """The three dimensions a comparison varies; everything else about a
    request is held constant across its configurations."""

    pricing_mode: str
    scenario: str | None
    market_condition: str | None

    @property
    def label(self) -> str:
        """``RW | Pump & dump | Bull`` — every compared dimension, named."""
        return (
            f"{PRICING_MODE_LABELS[self.pricing_mode]} | {SCENARIO_LABELS[self.scenario]} | "
            f"{MARKET_CONDITION_LABELS[self.market_condition]}"
        )


@dataclass(frozen=True)
class ComparisonPlan:
    """What a comparison would run, checked before anything runs.

    ``problems`` is empty exactly when the comparison may run; each entry
    says what to change. ``compared_dimensions`` are the dimensions given
    more than one value; ``held_constant`` is the request every
    configuration shares apart from those three fields.
    """

    held_constant: SimulationParams
    configurations: tuple[ComparisonConfiguration, ...]
    labels: tuple[str, ...]
    configuration_count: int
    runs_per_configuration: int
    total_runs: int
    compared_dimensions: tuple[str, ...]
    problems: tuple[str, ...]


@dataclass(frozen=True)
class ComparisonGroup:
    """One configuration's batch: its identity and its reduced batch
    (``DashboardBatch``, exactly as a Step 6 batch is reduced)."""

    label: str
    pricing_mode: str
    scenario: str | None
    market_condition: str | None
    batch: DashboardBatch


@dataclass(frozen=True)
class ScenarioComparison:
    """Separate batches of explicitly selected configurations.

    ``held_constant`` is the request every configuration shared apart from
    its pricing mode, manipulation preset and market condition; every
    group's batch ran from ``base_seed``, so corresponding runs have the
    same derived seed.
    """

    held_constant: SimulationParams
    base_seed: int
    runs_per_configuration: int
    compared_dimensions: tuple[str, ...]
    groups: tuple[ComparisonGroup, ...]


def comparison_configurations(
    pricing_modes: Iterable[str],
    scenarios: Iterable[str | None],
    market_conditions: Iterable[str | None],
) -> tuple[ComparisonConfiguration, ...]:
    """Every combination of the selected values, in the canonical order of
    ``PRICING_MODES``, ``COMPARISON_SCENARIOS`` and
    ``COMPARISON_MARKET_CONDITIONS`` whatever order they were selected in.

    Raises:
        ValueError: a value is not one those lists hold.
    """
    selected = (set(pricing_modes), set(scenarios), set(market_conditions))
    known = (PRICING_MODES, COMPARISON_SCENARIOS, COMPARISON_MARKET_CONDITIONS)
    for name, values, allowed in zip(("pricing mode", "scenario", "market condition"), selected, known):
        unknown = values - set(allowed)
        if unknown:
            raise ValueError(f"unknown {name} {sorted(map(str, unknown))}; expected one of {list(allowed)}")
    return tuple(
        ComparisonConfiguration(pricing_mode=mode, scenario=scenario, market_condition=condition)
        for mode, scenario, condition in product(
            *([value for value in allowed if value in values] for values, allowed in zip(selected, known))
        )
    )


def plan_comparison(
    held_constant: SimulationParams,
    configurations: Sequence[ComparisonConfiguration],
    runs: int,
) -> ComparisonPlan:
    """Check a comparison without running it.

    A configuration the simulator would refuse is reported rather than
    adjusted: AMM with whales is not run with the whales quietly removed.
    """
    problems = []
    if not configurations:
        problems.append("Select at least one pricing mode, manipulation scenario and market condition.")
    if isinstance(runs, bool) or not isinstance(runs, int) or not MIN_BATCH_RUNS <= runs <= MAX_DASHBOARD_BATCH_RUNS:
        problems.append(
            f"Runs per configuration must be between {MIN_BATCH_RUNS} and {MAX_DASHBOARD_BATCH_RUNS} "
            f"(the dashboard batch limit; got {runs!r})."
        )
        total = 0
    else:
        total = len(configurations) * runs
    if total > MAX_COMPARISON_RUNS:
        problems.append(
            f"{len(configurations)} configurations x {runs} runs is {total} simulations, above the "
            f"dashboard comparison limit of {MAX_COMPARISON_RUNS}. Select fewer configurations or runs."
        )
    if held_constant.include_whales and any(c.pricing_mode == "amm" for c in configurations):
        problems.append(
            "AMM configurations cannot run with whales: the simulator refuses whales in AMM mode. Turn "
            "off 'Whales' in the run options to include AMM; every configuration then runs without whales."
        )
    dimensions = (
        ("pricing mode", {c.pricing_mode for c in configurations}),
        ("manipulation scenario", {c.scenario for c in configurations}),
        ("market condition", {c.market_condition for c in configurations}),
    )
    return ComparisonPlan(
        held_constant=held_constant,
        configurations=tuple(configurations),
        labels=tuple(c.label for c in configurations),
        configuration_count=len(configurations),
        runs_per_configuration=runs,
        total_runs=total,
        compared_dimensions=tuple(name for name, values in dimensions if len(values) > 1),
        problems=tuple(problems),
    )


def run_dashboard_comparison(
    held_constant: SimulationParams,
    configurations: Sequence[ComparisonConfiguration],
    runs: int,
    *,
    base_seed: int,
    settings: Settings | None = None,
    runner: Callable[[SimulationParams], DashboardPayload] = run_simulation,
) -> ScenarioComparison:
    """Run one batch per configuration from one shared base seed, and
    reduce each at once.

    Each batch is ``run_batch`` with ``run_simulation`` as the runner and
    ``base_seed`` as its base, reduced by ``reduce_batch`` (which calls
    ``aggregate_batch``), so a group is exactly the Step 6 batch of its
    request. Only the three compared fields differ between requests.

    Raises:
        ValueError: the plan has a problem, or ``base_seed`` is not a
            valid seed. Nothing has run.
    """
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) or not MIN_SEED <= base_seed <= MAX_SEED:
        raise ValueError(f"base_seed must be an integer between {MIN_SEED} and {MAX_SEED} (got {base_seed!r})")
    plan = plan_comparison(held_constant, configurations, runs)
    if plan.problems:
        raise ValueError(" ".join(plan.problems))
    held_constant = replace(held_constant, random_seed=base_seed)
    groups = []
    for configuration in plan.configurations:
        params = replace(
            held_constant,
            pricing_mode=configuration.pricing_mode,
            scenario=configuration.scenario,
            market_condition=configuration.market_condition,
        )
        batch = reduce_batch(run_batch(params, runs, runner=runner, base_seed=base_seed, settings=settings))
        groups.append(ComparisonGroup(
            label=configuration.label,
            pricing_mode=configuration.pricing_mode,
            scenario=configuration.scenario,
            market_condition=configuration.market_condition,
            batch=batch,
        ))
    return ScenarioComparison(
        held_constant=held_constant,
        base_seed=base_seed,
        runs_per_configuration=runs,
        compared_dimensions=plan.compared_dimensions,
        groups=tuple(groups),
    )


def plan_to_dict(plan: ComparisonPlan) -> dict[str, Any]:
    """The plan as JSON-compatible Python, by ``dashboard.serialization``."""
    if not isinstance(plan, ComparisonPlan):
        raise TypeError(f"expected a ComparisonPlan, got {type(plan).__name__}")
    return to_jsonable(plan)


def comparison_to_dict(comparison: ScenarioComparison) -> dict[str, Any]:
    """The comparison as JSON-compatible Python, by
    ``dashboard.serialization``; each group's ``batch`` is serialized as
    ``batch_to_dict`` serializes a Step 6 batch."""
    if not isinstance(comparison, ScenarioComparison):
        raise TypeError(f"expected a ScenarioComparison, got {type(comparison).__name__}")
    return to_jsonable(comparison)
