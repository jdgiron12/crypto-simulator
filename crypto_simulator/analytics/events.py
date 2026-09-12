"""Descriptive analytics over a finished coin simulation's news events.

Post-processing only: reads ``SimulationTick``s and the ``MarketEvent``
timeline and returns frozen results. Nothing here feeds back into the
simulation, draws random numbers, or mutates its inputs.

Two kinds of information are kept apart:

- ``EventGroundTruth``: what the simulator knows because it created the
  event (category, severity, sentiment, timing, ...). Never inferred from
  market data.
- ``ObservedMarket`` / ``ObservedTrading`` / ``ObservedPool``: computed
  only from simulation output (prices, volumes, fills, pool snapshots).
  The trade records' labels (strategy, reason, wash flag) and the ticks'
  ``event_state`` are ground truth too and are not used: wash legs count
  as ordinary trades, as an observer would see them.

The windows are anchored on each event's ground-truth timing, so these
answer "what did the market do while this event was live?" — descriptive,
never causal. Other events, participants and noise act in the same
windows; overlapping events are listed, not disentangled.

Windows (ticks are 1-based; see ``MarketEvent``):
    before        the tick before ``start_tick`` (``initial_price`` for tick 1)
    event window  ``start_tick`` .. ``last_active_tick``
    post window   the ``post_window`` ticks after ``last_active_tick``
    baseline      the ``baseline_window`` ticks before ``start_tick``

Returns are fractions (0.05 = +5%), like every threshold in the project.
Anything that needs a tick outside the data, or a non-positive price, is
``None`` rather than estimated.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events.event import MarketEvent
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.traders.base import TradeAction

DEFAULT_POST_WINDOW = 5
DEFAULT_BASELINE_WINDOW = 10
# statistics.stdev (sample standard deviation) needs two values.
MIN_VOLATILITY_RETURNS = 2


@dataclass(frozen=True)
class EventGroundTruth:
    """The event as the simulator created it. Not a market observation."""

    event_id: str
    category: str
    headline: str
    severity: float
    sentiment: float
    volatility_boost: float
    attention: float
    start_tick: int
    last_active_tick: int
    duration: int
    decay_ticks: int
    expires_at: int  # first tick with no effect
    # True if a RandomEventGenerator started it, False if it was scheduled
    # (or injected by hand), None when the caller supplied no provenance.
    randomly_generated: bool | None = None

    @classmethod
    def of(cls, event: MarketEvent, randomly_generated: bool | None = None) -> EventGroundTruth:
        return cls(
            event_id=event.event_id,
            category=event.category,
            headline=event.headline,
            severity=event.severity,
            sentiment=event.sentiment,
            volatility_boost=event.volatility_boost,
            attention=event.attention,
            start_tick=event.start_tick,
            last_active_tick=event.last_active_tick,
            duration=event.duration,
            decay_ticks=event.decay_ticks,
            expires_at=event.expires_at,
            randomly_generated=randomly_generated,
        )


@dataclass(frozen=True)
class ObservedMarket:
    """Prices and volume around the event, from simulation output.

    ``immediate_return`` = price_at_start / price_before - 1 (the first
    event tick); ``event_return`` = price_at_end / price_at_start - 1;
    ``post_event_return`` = price_after_post_window / price_at_end - 1.
    Volatilities are sample standard deviations of per-tick log returns
    ``ln(p_t / p_{t-1})`` over the ticks of the event window / baseline,
    ``None`` with fewer than ``MIN_VOLATILITY_RETURNS`` returns. Volume is
    the simulator's synthetic volume; ``volume_ratio`` compares per-tick
    averages (event window / baseline).
    """

    price_before: float | None
    price_at_start: float | None
    price_at_end: float | None
    price_after_post_window: float | None
    immediate_return: float | None
    event_return: float | None
    post_event_return: float | None
    volatility: float | None
    baseline_volatility: float | None
    volume: float
    volume_per_tick: float | None
    baseline_volume_per_tick: float | None
    volume_ratio: float | None


@dataclass(frozen=True)
class ObservedTrading:
    """Trader fills in the event window (whale trades are not included).

    Volumes are in coins; ``net_flow`` = buy_volume - sell_volume.
    ``participation_rate`` is the share of the trader population with at
    least one fill, when the population size is supplied (it isn't in the
    tick data). ``trades_per_tick`` vs ``baseline_trades_per_tick``
    compares activity with the ticks before the event.
    """

    trade_count: int
    buy_volume: float
    sell_volume: float
    net_flow: float
    active_traders: int
    participation_rate: float | None
    trades_per_tick: float | None
    baseline_trades_per_tick: float | None


@dataclass(frozen=True)
class ObservedPool:
    """AMM pool activity in the event window, from recorded pool snapshots
    and swaps (exact ``Decimal``s). Reserve and fee changes compare the
    snapshot after the last event tick with the one before the first, so
    they are ``None`` when either is outside the data (e.g. an event
    starting on tick 1)."""

    spot_price_at_start: Decimal | None
    spot_price_at_end: Decimal | None
    swap_count: int
    coin_reserve_change: Decimal | None
    cash_reserve_change: Decimal | None
    fees_cash: Decimal | None
    fees_coins: Decimal | None
    largest_price_impact: Decimal | None  # max |price_impact| among the window's swaps


@dataclass(frozen=True)
class EventObservation:
    """One event: its ground truth, what the market did around it, and the
    other events live at the same time (from ground-truth timing: an
    event is live from ``start_tick`` to ``expires_at - 1``)."""

    ground_truth: EventGroundTruth
    market: ObservedMarket
    trading: ObservedTrading
    pool: ObservedPool | None  # None outside AMM mode
    overlapping_event_ids: tuple[str, ...]
    event_ticks_observed: int
    event_window_complete: bool
    post_window_complete: bool

    @property
    def overlapping(self) -> bool:
        """Other events were live too, so the window's metrics mix them."""
        return bool(self.overlapping_event_ids)


def analyze_events(
    ticks: Sequence[SimulationTick],
    events: Iterable[MarketEvent],
    *,
    post_window: int = DEFAULT_POST_WINDOW,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    initial_price: float | None = None,
    trader_count: int | None = None,
    random_event_ids: Iterable[str] | None = None,
) -> tuple[EventObservation, ...]:
    """Observe every event that started within ``ticks``.

    ``events`` is the ground-truth timeline (e.g. ``EventEngine.events``);
    events starting outside the ticks are skipped but still count as
    overlaps where their live span reaches into the data. ``initial_price``
    (the price before tick 1) and ``trader_count`` are optional facts the
    ticks don't record. ``random_event_ids`` is the provenance record (e.g.
    the ids in ``RandomEventGenerator.generated_events``): listed events are
    marked ``randomly_generated=True``, all others ``False``; without it,
    provenance is ``None`` (unknown). Results are ordered by
    (start_tick, event_id).
    """
    for name, value in (("post_window", post_window), ("baseline_window", baseline_window)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be an integer >= 1 (got {value!r})")
    if initial_price is not None and not _valid_price(initial_price):
        raise ValueError(f"initial_price must be a positive finite number (got {initial_price!r})")
    if trader_count is not None and (isinstance(trader_count, bool) or not isinstance(trader_count, int)
                                     or trader_count < 1):
        raise ValueError(f"trader_count must be an integer >= 1 (got {trader_count!r})")

    by_tick: dict[int, SimulationTick] = {}
    for tick in ticks:
        if tick.tick in by_tick:
            raise ValueError(f"duplicate tick {tick.tick}")
        by_tick[tick.tick] = tick
    if not by_tick:
        return ()
    first, last = min(by_tick), max(by_tick)
    timeline = sorted(events, key=lambda e: (e.start_tick, e.event_id))
    overlaps = _overlaps([e for e in timeline if e.start_tick <= last and e.expires_at - 1 >= first])
    data = _Ticks(by_tick, initial_price)
    random_ids = None if random_event_ids is None else frozenset(random_event_ids)
    return tuple(
        _observe(
            event, data, overlaps.get(event.event_id, ()), post_window, baseline_window, trader_count,
            None if random_ids is None else event.event_id in random_ids,
        )
        for event in timeline
        if first <= event.start_tick <= last
    )


class _Ticks:
    """Lookups over the ticks, by tick number."""

    def __init__(self, by_tick: dict[int, SimulationTick], initial_price: float | None):
        self.by_tick = by_tick
        self.initial_price = initial_price

    def price(self, tick: int) -> float | None:
        if tick in self.by_tick:
            price = self.by_tick[tick].price
            return price if _valid_price(price) else None
        return self.initial_price if tick == 0 else None

    def span(self, start: int, end: int) -> list[SimulationTick]:
        return [self.by_tick[t] for t in range(max(start, 1), end + 1) if t in self.by_tick]

    def log_returns(self, start: int, end: int) -> list[float]:
        returns = []
        for t in range(max(start, 1), end + 1):
            before, after = self.price(t - 1), self.price(t)
            if before is not None and after is not None:
                returns.append(math.log(after / before))
        return returns


def _observe(event, data, overlapping, post_window, baseline_window, trader_count,
             randomly_generated) -> EventObservation:
    start, end = event.start_tick, event.last_active_tick
    window = data.span(start, end)
    baseline = data.span(start - baseline_window, start - 1)
    return EventObservation(
        ground_truth=EventGroundTruth.of(event, randomly_generated),
        market=_market(data, start, end, window, baseline, post_window, baseline_window),
        trading=_trading(window, baseline, trader_count),
        pool=_pool(data, start, end, window),
        overlapping_event_ids=overlapping,
        event_ticks_observed=len(window),
        event_window_complete=len(window) == event.duration,
        post_window_complete=all(t in data.by_tick for t in range(end + 1, end + post_window + 1)),
    )


def _market(data, start, end, window, baseline, post_window, baseline_window) -> ObservedMarket:
    before, at_start, at_end = data.price(start - 1), data.price(start), data.price(end)
    after = data.price(end + post_window)
    volume = math.fsum(t.volume for t in window)
    volume_per_tick = volume / len(window) if window else None
    baseline_volume_per_tick = math.fsum(t.volume for t in baseline) / len(baseline) if baseline else None
    return ObservedMarket(
        price_before=before,
        price_at_start=at_start,
        price_at_end=at_end,
        price_after_post_window=after,
        immediate_return=_return(before, at_start),
        event_return=_return(at_start, at_end),
        post_event_return=_return(at_end, after),
        volatility=_volatility(data.log_returns(start, end)),
        baseline_volatility=_volatility(data.log_returns(start - baseline_window, start - 1)),
        volume=volume,
        volume_per_tick=volume_per_tick,
        baseline_volume_per_tick=baseline_volume_per_tick,
        volume_ratio=_ratio(volume_per_tick, baseline_volume_per_tick),
    )


def _trading(window, baseline, trader_count) -> ObservedTrading:
    fills = [fill for tick in window for fill in tick.trader_trades]
    buy_volume = math.fsum(f.quantity for f in fills if f.side is TradeAction.BUY)
    sell_volume = math.fsum(f.quantity for f in fills if f.side is TradeAction.SELL)
    active = len({f.trader_id for f in fills})
    baseline_fills = sum(len(tick.trader_trades) for tick in baseline)
    return ObservedTrading(
        trade_count=len(fills),
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        net_flow=buy_volume - sell_volume,
        active_traders=active,
        participation_rate=active / trader_count if trader_count else None,
        trades_per_tick=len(fills) / len(window) if window else None,
        baseline_trades_per_tick=baseline_fills / len(baseline) if baseline else None,
    )


def _pool(data, start, end, window) -> ObservedPool | None:
    if not any(tick.pool_state is not None for tick in window):
        return None
    state_at = {t: data.by_tick[t].pool_state for t in (start - 1, start, end) if t in data.by_tick}
    pre, at_start, at_end = state_at.get(start - 1), state_at.get(start), state_at.get(end)
    swaps = [fill.swap for tick in window for fill in tick.trader_trades if fill.swap is not None]
    both = pre is not None and at_end is not None
    return ObservedPool(
        spot_price_at_start=at_start.spot_price if at_start is not None else None,
        spot_price_at_end=at_end.spot_price if at_end is not None else None,
        swap_count=len(swaps),
        coin_reserve_change=EXACT.subtract(at_end.coin_reserve, pre.coin_reserve) if both else None,
        cash_reserve_change=EXACT.subtract(at_end.cash_reserve, pre.cash_reserve) if both else None,
        fees_cash=EXACT.subtract(at_end.fees_collected_cash, pre.fees_collected_cash) if both else None,
        fees_coins=EXACT.subtract(at_end.fees_collected_coins, pre.fees_collected_coins) if both else None,
        largest_price_impact=max((abs(s.price_impact) for s in swaps), default=None),
    )


def _overlaps(events: list[MarketEvent]) -> dict[str, tuple[str, ...]]:
    """Pairs of events whose live spans intersect; ``events`` is sorted by
    start tick, so each event only scans forward until starts pass its end."""
    found: dict[str, list[str]] = {e.event_id: [] for e in events}
    for i, event in enumerate(events):
        live_until = event.expires_at - 1
        for j in range(i + 1, len(events)):
            other = events[j]
            if other.start_tick > live_until:
                break
            found[event.event_id].append(other.event_id)
            found[other.event_id].append(event.event_id)
    return {event_id: tuple(ids) for event_id, ids in found.items()}


def _valid_price(price: object) -> bool:
    return (not isinstance(price, bool) and isinstance(price, (int, float))
            and math.isfinite(price) and price > 0)


def _return(start: float | None, end: float | None) -> float | None:
    return None if start is None or end is None else end / start - 1.0


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _volatility(log_returns: list[float]) -> float | None:
    return statistics.stdev(log_returns) if len(log_returns) >= MIN_VOLATILITY_RETURNS else None
