"""Descriptive analytics over the Phase 5 manipulation scenarios a
finished run recorded (Phase 9, Step 6).

Post-processing only: reads the ``TraderTrade`` records on each
``SimulationTick`` and returns frozen results. Nothing here feeds back
into the simulation, draws random numbers, or mutates its inputs, and
nothing here is a second settlement or volume engine — it reuses
``analytics/market.py``'s ``VolumeBreakdown`` for every top-level volume
figure and ``analytics/traders.py``'s ``StrategySummary`` for per-strategy
trader accounting, embedding both rather than recomputing them.

**Identification is registry-based, never inferred from behavior.** A
fill is manipulation exactly when the simulator itself recorded it that
way: ``TraderTrade.wash`` (set by ``execute_wash``/``execute_wash_via_pool``
regardless of strategy — "a wash leg is a self-trade whoever made it",
market.py's own phrase) or ``TraderTrade.strategy`` naming a class in
``MANIPULATION_STRATEGIES`` (``core/traders/registry.py``). A large trade,
a fast return or an unusual volume is never treated as manipulation on its
own — only the recorded label is. This module's own classification order
exactly mirrors ``analytics/market.py``'s ``_volume_breakdown`` (wash
checked first, then strategy, then organic), so the two never disagree
about which category a fill belongs to.

**Volume, precisely.** ``analyze_market``'s ``VolumeBreakdown`` already
classifies every recorded quantity exactly once:
``total = background + whale + organic + manipulator + wash``. This
module's ``manipulation_volume`` is ``manipulator_volume + wash_volume`` —
two of those five *already-disjoint* categories — never wash volume added
on top of a total that already contains it, and never a wash leg counted
twice. ``pump_and_dump_volume`` is ``manipulator_volume`` under today's
registry (the only non-wash manipulation strategy); should a second
non-wash manipulation strategy ever be registered, this module's own
per-fill classification (not a shortcut through that one field) is what
actually attributes volume to ``PumpAndDump`` specifically.

**Pump-and-dump phases** come from ``TraderTrade.reason`` — the exact,
already-recorded string ``PumpAndDump._decide`` sets on every fill it
produces ("accumulate", "pump", "dump"; see ``core/traders/manipulation.py``).
This module derives phase boundaries only from those recorded reasons on
each trader's own fills, never by reconstructing the scheme's tick
schedule (which this function's signature — ``ticks`` only — has no
access to) and never by guessing from a price threshold. One
``PumpAndDumpSummary`` per manipulator id: phases are inherently
per-trader (each ``PumpAndDump`` instance runs its own schedule), so
aggregating several manipulators' phases into one blob would misrepresent
them. Each summary's price/return/drawdown figures are one
``analyze_market`` call over that trader's own observed span
(``first_tick``..``last_tick``, the earliest to latest fill of any
phase) — Step 1's exact definitions, embedded rather than recomputed:
peak price is ``market.high_price``, trough ``market.low_price``,
scenario return ``market.cumulative_return``, and the drawdown figures
are ``market.max_drawdown``/``.drawdown_peak_tick``/``.drawdown_trough_tick``/
``.recovery_tick``. This module makes no claim that a scenario ran to
completion within the supplied ticks, or that any observed price move
belongs to it — see below.

**Wash trading** (``WashSummary``) aggregates every fill flagged
``wash`` (both legs, buy and sell, whoever recorded them) into fill
counts, volume, a buy/sell split (which ``analytics/traders.py`` does not
report — it deliberately keeps wash apart from a trader's buy/sell
figures), notional, active-tick timing and an average per active tick.
Price observations around wash activity (before/during/after) are exactly
that — observations — never a claim of a "wash-trading price impact".
Random-walk wash legs settle at the going price with no impact of their
own; AMM wash legs are real swaps through the pool and can move its spot
price through the pool's own mechanics, which this module never
attributes to "manipulation working".

**Manipulation vs. organic** (``ActivityComparison``) puts volume, buy/sell
split, notional, active ticks and average fill size for manipulation
(wash + non-wash manipulator fills) side by side with everything else
(organic fills) — a comparison, never a ranking, and never a claim about
how well either worked, whether they moved together on purpose, or
whether one responded to the other.

**Coverage.** Unlike whale observation or psychology, which are opt-in
recording flags a run can be missing, ``SimulationTick.trader_trades`` is
always fully recorded for whatever traders existed — there is no "was
manipulation recording turned on" question here. ``coverage`` therefore
describes something narrower and fully knowable: which manipulation
*kinds* this report found any fills for — ``"none"`` (neither),
``"partial"`` (exactly one of pump-and-dump/wash), or ``"complete"``
(both). It is not, and cannot honestly be, a claim that any one
scenario's full temporal extent was captured by the supplied ticks; a
``PumpAndDumpSummary`` with no dump fills may mean the scheme never
reached that phase, or that the phase lies outside the analysed range —
this module cannot tell the two apart and does not pretend to.

**P&L/equity** are not computed here: this function's signature carries
no wallet balances (only ``ticks``), and ``analytics/traders.py``'s own
convention requires them for an exact figure. Call ``analyze_traders``
directly with balances for P&L; the embedded ``StrategySummary`` objects
here always show ``pnl=None`` accordingly — never invented.

Conventions shared with the rest of ``analytics/``:

- Ticks are ordered by tick number (duplicates rejected) before anything
  reads them.
- A trader id recorded under two different strategies is rejected —
  ``analyze_traders``'s own check, reused rather than re-implemented.
- Collections are sorted deterministically (by trader id); nothing relies
  on dict insertion order for a returned result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from crypto_simulator.analytics._series import ordered_ticks
from crypto_simulator.analytics.market import MarketSummary, analyze_market
from crypto_simulator.analytics.traders import StrategySummary, analyze_traders
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES

COVERAGE_NONE = "none"
COVERAGE_PARTIAL = "partial"
COVERAGE_COMPLETE = "complete"
"""Which manipulation *kinds* were observed — see the module docstring
for why this is not, and cannot be, a claim about scenario completeness."""

_PUMP_AND_DUMP = PumpAndDump.strategy_name
_WASH_TRADER = WashTrader.strategy_name
_PHASES = ("accumulate", "pump", "dump")


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


@dataclass(frozen=True)
class PumpAndDumpSummary:
    """One manipulator's recorded pump-and-dump activity, phased entirely
    from its own fills' recorded ``reason`` (see the module docstring).

    ``first_tick``/``last_tick`` span every recorded phase; ``duration``
    is their tick distance plus one. ``market`` is ``analyze_market`` over
    that exact span: ``market.high_price``/``.low_price`` are the peak and
    trough observed, ``market.cumulative_return`` the scenario return,
    and ``market.max_drawdown``/``.drawdown_peak_tick``/
    ``.drawdown_trough_tick``/``.recovery_tick`` the drawdown after the
    peak. None of this is a claim of profit or success — an observed
    accounting result only, using ``analyze_market``'s existing
    definitions.
    """

    trader_id: str
    accumulation_fills: int
    accumulation_volume: float
    first_accumulation_tick: int | None
    last_accumulation_tick: int | None
    pump_fills: int
    pump_volume: float
    pump_start_tick: int | None
    pump_end_tick: int | None
    dump_fills: int
    dump_volume: float
    dump_start_tick: int | None
    dump_end_tick: int | None
    first_tick: int
    last_tick: int
    duration: int
    price_at_accumulation_start: float | None
    price_at_dump_start: float | None
    market: MarketSummary

    @property
    def total_volume(self) -> float:
        return self.accumulation_volume + self.pump_volume + self.dump_volume

    @property
    def total_fills(self) -> int:
        return self.accumulation_fills + self.pump_fills + self.dump_fills


@dataclass(frozen=True)
class WashSummary:
    """Aggregate wash-trading activity across every fill flagged ``wash``
    (both legs, whoever recorded them; see the module docstring). Zero
    fields are a real, fully-observed fact here — not a coverage gap —
    since ``trader_trades`` is always completely recorded.
    """

    fill_count: int
    volume: float
    buy_volume: float
    sell_volume: float
    notional: float
    active_ticks: int
    first_tick: int | None
    last_tick: int | None
    average_volume_per_active_tick: float | None


@dataclass(frozen=True)
class ActivityComparison:
    """Manipulation (wash + non-wash manipulator fills) alongside organic
    trader activity — a side-by-side comparison, never a ranking and
    never a claim about how well either worked or whether one responded
    to the other."""

    manipulation_volume: float
    organic_volume: float
    manipulation_volume_share: float | None  # of (manipulation + organic); None if both zero
    manipulation_buy_volume: float
    manipulation_sell_volume: float
    organic_buy_volume: float
    organic_sell_volume: float
    manipulation_notional: float
    organic_notional: float
    manipulation_active_ticks: int
    organic_active_ticks: int
    manipulation_average_fill_size: float | None
    organic_average_fill_size: float | None


@dataclass(frozen=True)
class ManipulationReport:
    """Descriptive manipulation analytics for one finished run.

    ``total_market_volume``/``participant_volume`` and the three volume
    figures below them are ``analyze_market``'s own ``VolumeBreakdown``
    for these same ticks — the exact Step 1 definitions, so a caller can
    verify ``manipulation_volume`` never double-counts wash (see the
    module docstring). Both share fields are ``None`` only with a zero
    denominator, never a manufactured ratio; note their numerators differ
    on purpose — ``manipulation_share_of_total`` divides
    ``manipulation_volume`` (manipulator + wash) by
    ``total_market_volume`` (which includes wash), while
    ``manipulation_share_of_participants`` divides only the non-wash
    ``pump_and_dump_volume`` by ``participant_volume``, since Step 1
    already excludes wash — a self-cancelling leg — from
    ``participant_volume``; dividing a wash-inclusive numerator by a
    wash-exclusive denominator would not be a share of anything and could
    exceed 1. ``pump_and_dump`` is ordered by trader id;
    ``pump_and_dump_strategy``/``wash_strategy`` are ``analyze_traders``'s
    own ``StrategySummary`` for those two strategy labels, embedded,
    ``None`` when that strategy had no recorded fills.
    """

    ticks: int
    pricing_mode: str | None
    coverage: str
    total_market_volume: float
    participant_volume: float
    manipulation_volume: float
    pump_and_dump_volume: float
    wash_volume: float
    manipulation_share_of_total: float | None
    manipulation_share_of_participants: float | None
    fill_count: int
    buy_volume: float
    sell_volume: float
    notional: float
    active_ticks: int
    first_tick: int | None
    last_tick: int | None
    pump_and_dump: tuple[PumpAndDumpSummary, ...]
    wash: WashSummary
    activity_comparison: ActivityComparison
    pump_and_dump_strategy: StrategySummary | None
    wash_strategy: StrategySummary | None

    def pump_and_dump_trader(self, trader_id: str) -> PumpAndDumpSummary:
        for summary in self.pump_and_dump:
            if summary.trader_id == trader_id:
                return summary
        raise KeyError(f"no pump-and-dump activity recorded for trader {trader_id!r}")


class _PumpAcc:
    """Mutable per-trader accumulator for one pass over the fills."""

    __slots__ = ("fills",)

    def __init__(self) -> None:
        self.fills: dict[str, list[tuple[int, float]]] = {phase: [] for phase in _PHASES}

    def add(self, reason: str, tick: int, quantity: float) -> None:
        self.fills.setdefault(reason, []).append((tick, quantity))


def _classify(ordered: Sequence[SimulationTick]):
    """One linear pass over every recorded fill, building the raw
    aggregates every summary in this module is built from. Mirrors
    ``analytics/market.py``'s own per-fill precedence exactly: wash first
    (whoever recorded it), then a registered manipulation strategy, then
    organic."""
    pump_by_trader: dict[str, _PumpAcc] = {}
    wash_buy: list[tuple[int, float, float]] = []
    wash_sell: list[tuple[int, float, float]] = []
    wash_ticks: set[int] = set()
    organic_buy: list[tuple[int, float, float]] = []
    organic_sell: list[tuple[int, float, float]] = []
    organic_ticks: set[int] = set()
    manipulation_ticks: set[int] = set()

    for tick in ordered:
        for fill in tick.trader_trades:
            if not fill.quantity > 0:
                continue  # a record, not a fill
            if fill.wash:
                bucket = wash_buy if fill.side is TradeAction.BUY else wash_sell
                bucket.append((tick.tick, fill.quantity, fill.notional))
                wash_ticks.add(tick.tick)
                manipulation_ticks.add(tick.tick)
            elif fill.strategy in MANIPULATION_STRATEGIES:
                manipulation_ticks.add(tick.tick)
                if fill.strategy == _PUMP_AND_DUMP:
                    acc = pump_by_trader.setdefault(fill.trader_id, _PumpAcc())
                    acc.add(fill.reason, tick.tick, fill.quantity)
            else:
                bucket = organic_buy if fill.side is TradeAction.BUY else organic_sell
                bucket.append((tick.tick, fill.quantity, fill.notional))
                organic_ticks.add(tick.tick)

    return pump_by_trader, wash_buy, wash_sell, wash_ticks, organic_buy, organic_sell, organic_ticks, manipulation_ticks


def _phase_stats(fills: list[tuple[int, float]]) -> tuple[int, float, int | None, int | None]:
    if not fills:
        return 0, 0.0, None, None
    ticks = [tick for tick, _ in fills]
    return len(fills), math.fsum(quantity for _, quantity in fills), min(ticks), max(ticks)


def _pump_and_dump_summary(
    trader_id: str, acc: _PumpAcc, by_tick: dict[int, SimulationTick], initial_price: float | None
) -> PumpAndDumpSummary:
    accumulate = acc.fills.get("accumulate", [])
    pump = acc.fills.get("pump", [])
    dump = acc.fills.get("dump", [])
    acc_fills, acc_volume, acc_first, acc_last = _phase_stats(accumulate)
    pump_fills, pump_volume, pump_start, pump_end = _phase_stats(pump)
    dump_fills, dump_volume, dump_start, dump_end = _phase_stats(dump)

    all_ticks = [tick for phase in (accumulate, pump, dump) for tick, _ in phase]
    first_tick, last_tick = min(all_ticks), max(all_ticks)
    window = [by_tick[t] for t in range(first_tick, last_tick + 1) if t in by_tick]
    market = analyze_market(window, initial_price=initial_price)

    return PumpAndDumpSummary(
        trader_id=trader_id,
        accumulation_fills=acc_fills,
        accumulation_volume=acc_volume,
        first_accumulation_tick=acc_first,
        last_accumulation_tick=acc_last,
        pump_fills=pump_fills,
        pump_volume=pump_volume,
        pump_start_tick=pump_start,
        pump_end_tick=pump_end,
        dump_fills=dump_fills,
        dump_volume=dump_volume,
        dump_start_tick=dump_start,
        dump_end_tick=dump_end,
        first_tick=first_tick,
        last_tick=last_tick,
        duration=last_tick - first_tick + 1,
        price_at_accumulation_start=by_tick[acc_first].price if acc_first in by_tick else None,
        price_at_dump_start=by_tick[dump_start].price if dump_start in by_tick else None,
        market=market,
    )


def _wash_summary(wash_buy, wash_sell, wash_ticks) -> WashSummary:
    all_legs = wash_buy + wash_sell
    volume = math.fsum(quantity for _, quantity, _ in all_legs)
    active = len(wash_ticks)
    ticks = sorted(wash_ticks)
    return WashSummary(
        fill_count=len(all_legs),
        volume=volume,
        buy_volume=math.fsum(quantity for _, quantity, _ in wash_buy),
        sell_volume=math.fsum(quantity for _, quantity, _ in wash_sell),
        notional=math.fsum(notional for _, _, notional in all_legs),
        active_ticks=active,
        first_tick=ticks[0] if ticks else None,
        last_tick=ticks[-1] if ticks else None,
        average_volume_per_active_tick=volume / active if active else None,
    )


def _activity_comparison(
    pump_by_trader, wash_buy, wash_sell, wash_ticks, organic_buy, organic_sell, organic_ticks, manipulation_ticks
) -> ActivityComparison:
    pump_buy = [(tick, qty) for acc in pump_by_trader.values() for tick, qty in acc.fills.get("accumulate", []) + acc.fills.get("pump", [])]
    pump_sell = [(tick, qty) for acc in pump_by_trader.values() for tick, qty in acc.fills.get("dump", [])]

    manipulation_buy_volume = math.fsum(qty for _, qty in pump_buy) + math.fsum(q for _, q, _ in wash_buy)
    manipulation_sell_volume = math.fsum(qty for _, qty in pump_sell) + math.fsum(q for _, q, _ in wash_sell)
    manipulation_volume = manipulation_buy_volume + manipulation_sell_volume
    manipulation_notional = math.fsum(n for _, _, n in wash_buy + wash_sell)
    manipulation_fill_count = len(pump_buy) + len(pump_sell) + len(wash_buy) + len(wash_sell)

    organic_volume = math.fsum(q for _, q, _ in organic_buy + organic_sell)
    organic_notional = math.fsum(n for _, _, n in organic_buy + organic_sell)
    organic_fill_count = len(organic_buy) + len(organic_sell)

    total = manipulation_volume + organic_volume
    return ActivityComparison(
        manipulation_volume=manipulation_volume,
        organic_volume=organic_volume,
        manipulation_volume_share=manipulation_volume / total if total > 0 else None,
        manipulation_buy_volume=manipulation_buy_volume,
        manipulation_sell_volume=manipulation_sell_volume,
        organic_buy_volume=math.fsum(q for _, q, _ in organic_buy),
        organic_sell_volume=math.fsum(q for _, q, _ in organic_sell),
        manipulation_notional=manipulation_notional,
        organic_notional=organic_notional,
        manipulation_active_ticks=len(manipulation_ticks),
        organic_active_ticks=len(organic_ticks),
        manipulation_average_fill_size=manipulation_volume / manipulation_fill_count if manipulation_fill_count else None,
        organic_average_fill_size=organic_volume / organic_fill_count if organic_fill_count else None,
    )


def analyze_manipulation(
    ticks: Sequence[SimulationTick], *, initial_price: float | None = None
) -> ManipulationReport:
    """Describe the manipulation activity recorded on ``ticks``.

    ``initial_price`` feeds ``analyze_market`` for the top-level and
    per-scenario windows (market cap and the pre-run price point are not
    computed here; this is only for return/drawdown continuity into
    tick 1).

    Pure: the inputs are not mutated, no randomness is drawn, and the
    same ticks always produce the same report whatever order they arrive
    in. Raises ``ValueError`` on non-``SimulationTick`` values, duplicate
    tick numbers, an invalid price, or a trader id recorded under two
    strategies — every check reused from ``analyze_market``/
    ``analyze_traders``, not re-implemented.
    """
    ordered = ordered_ticks(ticks)
    by_tick = {tick.tick: tick for tick in ordered}
    market_summary = analyze_market(ordered, initial_price=initial_price)
    trader_report = analyze_traders(ordered)

    pump_by_trader, wash_buy, wash_sell, wash_ticks, organic_buy, organic_sell, organic_ticks, manipulation_ticks = (
        _classify(ordered)
    )

    pump_and_dump = tuple(
        _pump_and_dump_summary(trader_id, pump_by_trader[trader_id], by_tick, initial_price)
        for trader_id in sorted(pump_by_trader)
    )
    wash = _wash_summary(wash_buy, wash_sell, wash_ticks)
    comparison = _activity_comparison(
        pump_by_trader, wash_buy, wash_sell, wash_ticks, organic_buy, organic_sell, organic_ticks, manipulation_ticks
    )

    volume = market_summary.volume_breakdown
    coverage = COVERAGE_COMPLETE if pump_by_trader and wash.fill_count else (
        COVERAGE_NONE if not pump_by_trader and not wash.fill_count else COVERAGE_PARTIAL
    )
    all_manipulation_ticks = sorted(manipulation_ticks)
    total = volume.total_volume
    participant = volume.participant_volume
    manipulation_volume = volume.manipulator_volume + volume.wash_volume

    try:
        pump_strategy = trader_report.strategy(_PUMP_AND_DUMP)
    except KeyError:
        pump_strategy = None
    try:
        wash_strategy = trader_report.strategy(_WASH_TRADER)
    except KeyError:
        wash_strategy = None

    return ManipulationReport(
        ticks=len(ordered),
        pricing_mode=market_summary.pricing_mode,
        coverage=coverage,
        total_market_volume=total,
        participant_volume=participant,
        manipulation_volume=manipulation_volume,
        pump_and_dump_volume=volume.manipulator_volume,
        wash_volume=volume.wash_volume,
        manipulation_share_of_total=manipulation_volume / total if total > 0 else None,
        # participant_volume (Step 1) is whale + organic + manipulator —
        # wash is deliberately excluded there as a self-cancelling leg, so
        # pairing it against manipulation_volume (which includes wash)
        # would make a numerator that isn't a subset of its denominator
        # and could exceed 1. This share instead asks "how much of actual
        # participant activity was the non-wash manipulator volume",
        # which participant_volume actually contains.
        manipulation_share_of_participants=(
            volume.manipulator_volume / participant if participant > 0 else None
        ),
        fill_count=_fill_count(pump_by_trader, wash),
        buy_volume=comparison.manipulation_buy_volume,
        sell_volume=comparison.manipulation_sell_volume,
        notional=comparison.manipulation_notional,
        active_ticks=len(manipulation_ticks),
        first_tick=all_manipulation_ticks[0] if all_manipulation_ticks else None,
        last_tick=all_manipulation_ticks[-1] if all_manipulation_ticks else None,
        pump_and_dump=pump_and_dump,
        wash=wash,
        activity_comparison=comparison,
        pump_and_dump_strategy=pump_strategy,
        wash_strategy=wash_strategy,
    )


def _fill_count(pump_by_trader, wash: WashSummary) -> int:
    pump_fills = sum(
        len(acc.fills.get("accumulate", [])) + len(acc.fills.get("pump", [])) + len(acc.fills.get("dump", []))
        for acc in pump_by_trader.values()
    )
    return pump_fills + wash.fill_count
