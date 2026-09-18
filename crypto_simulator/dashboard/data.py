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
from crypto_simulator.config import get_settings
from crypto_simulator.config.settings import Settings
from crypto_simulator.core.coin_simulator import CoinSimulator, PricingMode, SimulationTick
from crypto_simulator.dashboard.serialization import to_jsonable
from crypto_simulator.services.coin_simulation import (
    DEMO_EVENTS,
    DEMO_RANDOM_EVENT_PROBABILITY,
    MANIPULATION_SCENARIOS,
    MAX_SEED,
    MIN_SEED,
    build_coin_simulator,
)

__all__ = [
    "MAX_SEED",
    "MAX_TICKS",
    "MIN_SEED",
    "PRICING_MODES",
    "SCENARIOS",
    "DashboardPayload",
    "PricePoint",
    "SimulationMeta",
    "SimulationParams",
    "configured_seed",
    "payload_to_dict",
    "run_simulation",
]

#: Upper bound on a dashboard run. A dashboard run is synchronous, so the
#: bound keeps one request from blocking the UI indefinitely; it is not a
#: simulator limit (the CLI has none).
MAX_TICKS = 2000

#: ``MIN_SEED``/``MAX_SEED`` are re-exported from
#: ``services.coin_simulation``, which owns the seed derivation they
#: bound. Phase 11 moved them there so the CLI's ``--seed`` and this
#: module's seed control share one bound rather than each carrying its
#: own; they stay in this module's namespace for the view and the tests
#: that already read them from here.

PRICING_MODES: tuple[str, ...] = tuple(mode.value for mode in PricingMode)
SCENARIOS: tuple[str, ...] = tuple(sorted(MANIPULATION_SCENARIOS))


@dataclass(frozen=True)
class SimulationParams:
    """What to run — the CLI's flags, validated.

    Each field mirrors an option of ``scripts/simulate_coin.py``:
    ``ticks`` (``--ticks``), ``pricing_mode`` (``--pricing-mode``),
    ``include_traders``/``include_whales`` (``--no-traders``/
    ``--no-whales``), ``scenario`` (``--scenario``), ``events``
    (``--events``), ``random_events`` (``--random-events``),
    ``psychology`` (``--psychology``) and ``whale_observation``
    (``--whale-observation``). The defaults are the CLI's defaults.

    ``random_seed`` (Step 7) is the exception: it mirrors no flag,
    because the CLI has none — the seed reaches a CLI run from
    ``simulation.random_seed`` in the configuration. ``None`` means
    exactly that, the configured seed, which is what every run did before
    Step 7; an integer runs the same request against a different seed.
    The seed is not a new simulator input, only a selected one: it is the
    value ``build_coin_simulator`` already derives every participant seed
    from.

    Validation happens on construction and rejects anything outside the
    known set, so an invalid dashboard request never reaches the builder.
    """

    ticks: int = 20
    pricing_mode: str = PricingMode.RANDOM_WALK.value
    include_traders: bool = True
    include_whales: bool = True
    scenario: str | None = None
    events: bool = False
    random_events: bool = False
    psychology: bool = False
    whale_observation: bool = False
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ticks, int) or isinstance(self.ticks, bool):
            raise ValueError(f"ticks must be an integer (got {self.ticks!r})")
        if not 1 <= self.ticks <= MAX_TICKS:
            raise ValueError(f"ticks must be between 1 and {MAX_TICKS} (got {self.ticks})")
        if self.pricing_mode not in PRICING_MODES:
            raise ValueError(
                f"unknown pricing_mode {self.pricing_mode!r}; expected one of {list(PRICING_MODES)}"
            )
        if self.scenario is not None and self.scenario not in MANIPULATION_SCENARIOS:
            raise ValueError(
                f"unknown scenario {self.scenario!r}; expected one of {list(SCENARIOS)} or None"
            )
        for name in ("include_traders", "include_whales", "events", "random_events",
                     "psychology", "whale_observation"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be True or False (got {value!r})")
        if self.random_seed is not None:
            if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
                raise ValueError(
                    f"random_seed must be an integer or None (got {self.random_seed!r})"
                )
            if not MIN_SEED <= self.random_seed <= MAX_SEED:
                raise ValueError(
                    f"random_seed must be between {MIN_SEED} and {MAX_SEED} "
                    f"(got {self.random_seed})"
                )


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
    params = params or SimulationParams()
    settings = _with_seed_override(
        _with_event_overrides(settings or get_settings(), params), params
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
    return DashboardPayload(simulation=meta, report=report, price_series=_price_series(ticks))


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


def _simulation_id(params: SimulationParams, seed: int | None) -> str:
    """A stable id for a request: the same parameters and seed always give
    the same id, and nothing else feeds into it."""
    canonical = json.dumps(
        {"params": to_jsonable(params), "seed": seed}, sort_keys=True, separators=(",", ":")
    )
    return blake2b(canonical.encode("utf-8"), digest_size=8).hexdigest()
