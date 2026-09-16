"""Unified report data for a finished run (Phase 9, Step 8a).

A composition layer, nothing more: ``build_report`` calls each existing
Phase 9 analytics function once, over one shared scope, and holds the
results unchanged in a frozen ``SimulationReport``. It computes no figure
of its own — no volume, price, balance, fee or label — so every section is
exactly what calling that analytics function directly returns, and each
of those functions remains fully usable on its own. Nothing here imports
back into the individual modules, renders anything, or feeds into the
simulation.

**Sections**, each the named function's own result:

    market             analyze_market
    traders            analyze_traders
    whale_activity     analyze_whale_activity   (embeds analyze_whales)
    event_windows      analyze_event_windows    (embeds analyze_events' ground truth and overlap)
    psychology_market  analyze_psychology_market (embeds analyze_psychology)
    manipulation       analyze_manipulation
    regimes            analyze_regimes

**Unavailable data keeps its own meaning.** A section is never filled in
to look complete. A run without psychology, whale observation or
manipulators still gets those sections, carrying whatever their function
already reports for that case (coverage ``"none"``, empty tuples, ``None``
figures). The one section that can be absent is ``event_windows``, which
is ``None`` when no event timeline is supplied: the ticks do not record
events' ground truth and this layer never reconstructs it, so "no timeline
given" is kept distinct from "a timeline with no events" (``events=()``,
an empty report).

**Scope.** ``start_tick``/``end_tick`` (inclusive, 1-based) select one set
of ticks for every section. Only ``analyze_market`` accepts a range
itself, so the builder orders and validates the ticks once, lets
``analyze_market`` validate and apply the range, and hands the identical
scoped ticks to every other function — the market section is therefore
equal to ``analyze_market`` over the scoped ticks as well as over the full
ticks with the range. Each function then applies its own conventions to
that scope: the pre-run price joins a path only when tick 1 is in scope,
regime windows stay on the tick-number grid, events are reported only if
they start in scope, and ``start_balances``/``end_balances`` must be the
wallets at the start and end of the scope (the ticks record no wallets).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from crypto_simulator.analytics._series import ordered_ticks
from crypto_simulator.analytics.event_windows import EventWindowReport, analyze_event_windows
from crypto_simulator.analytics.manipulation import ManipulationReport, analyze_manipulation
from crypto_simulator.analytics.market import MarketSummary, analyze_market
from crypto_simulator.analytics.psychology_market import PsychologyMarketReport, analyze_psychology_market
from crypto_simulator.analytics.regimes import DEFAULT_WINDOW_SIZE, RegimeReport, analyze_regimes
from crypto_simulator.analytics.traders import TraderReport, analyze_traders
from crypto_simulator.analytics.whale_activity import WhaleActivityReport, analyze_whale_activity
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events.event import MarketEvent


@dataclass(frozen=True)
class SimulationReport:
    """Every Phase 9 analytics result for one run, over one scope.

    ``start_tick``/``end_tick`` are the requested scope (``None`` for an
    open end); ``ticks`` is how many supplied ticks fell inside it. Each
    section is its analytics function's own frozen result; see the module
    docstring for what each holds when its data is unavailable.
    """

    ticks: int
    start_tick: int | None
    end_tick: int | None
    market: MarketSummary
    traders: TraderReport
    whale_activity: WhaleActivityReport
    event_windows: EventWindowReport | None
    psychology_market: PsychologyMarketReport
    manipulation: ManipulationReport
    regimes: RegimeReport


def build_report(
    ticks: Iterable[SimulationTick],
    *,
    events: Iterable[MarketEvent] | None = None,
    random_event_ids: Iterable[str] | None = None,
    initial_price: float | None = None,
    total_supply: float | None = None,
    start_balances: Mapping[str, tuple[float, float]] | None = None,
    end_balances: Mapping[str, tuple[float, float]] | None = None,
    window_size: int = DEFAULT_WINDOW_SIZE,
    start_tick: int | None = None,
    end_tick: int | None = None,
) -> SimulationReport:
    """Build the unified report for ``ticks``.

    ``events`` is the ground-truth timeline (e.g. ``EventEngine.events``)
    and ``random_event_ids`` its provenance; ``event_windows`` is ``None``
    without a timeline. ``initial_price``, ``total_supply``, the balances
    and ``window_size`` pass straight to the functions that take them.
    ``start_tick``/``end_tick`` scope every section alike.

    Pure: the inputs are not mutated, no randomness is drawn, and the same
    inputs always give the same report. Any ``ValueError`` comes from the
    analytics function that owns the check.
    """
    ordered = ordered_ticks(ticks)
    market = analyze_market(ordered, initial_price=initial_price, total_supply=total_supply,
                            start_tick=start_tick, end_tick=end_tick)
    scoped = [tick for tick in ordered
              if (start_tick is None or tick.tick >= start_tick) and (end_tick is None or tick.tick <= end_tick)]
    return SimulationReport(
        ticks=len(scoped),
        start_tick=start_tick,
        end_tick=end_tick,
        market=market,
        traders=analyze_traders(scoped, start_balances=start_balances, end_balances=end_balances,
                                initial_price=initial_price),
        whale_activity=analyze_whale_activity(scoped),
        event_windows=None if events is None else analyze_event_windows(
            scoped, events, initial_price=initial_price, total_supply=total_supply,
            random_event_ids=random_event_ids),
        psychology_market=analyze_psychology_market(scoped, initial_price=initial_price),
        manipulation=analyze_manipulation(scoped, initial_price=initial_price),
        regimes=analyze_regimes(scoped, initial_price=initial_price, window_size=window_size,
                                total_supply=total_supply),
    )
