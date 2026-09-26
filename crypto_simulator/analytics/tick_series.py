"""Tick-level visualization model (Phase 20, Step 3).

A pure, read-only projection of one finished run's ``SimulationTick``
sequence into descriptive per-tick columns for the Phase 20 charts. It is
the frozen Step 2 field contract, implemented as written: nothing here is a
new simulation output, a behavioral model or a replacement for
``SimulationReport``, and nothing is added that the ticks (plus the run's
explicit population) do not already contain.

**Columnar.** ``TickSeries.data`` maps each column name to one value per
tick, in the order the ticks were given; ``TickSeries.columns`` fixes the
column order. Per-class activity lives in ``TickSeries.classes`` (strategy
name -> ``ClassSeries``), keyed only by the organic strategies actually in
the population, in sorted order.

**Population is an input, never inferred.** ``population`` maps each
strategy in the run to its trader count and ``whale_count`` is the number of
whales; together they decide *presence* only. A class in the population that
never fills gets true zeros; a class not in the run has no key. Whale fields
are ``None`` when the run has no whales (and always in AMM mode), and the
pump-and-dump phase volumes are ``None`` when no ``pump_and_dump`` trader is
in the run. A fill whose strategy is not in the population is rejected
rather than guessed at.

**Definitions are the existing ones.** Volume is classified exactly as
``analytics/market.py`` classifies it — whale, then wash (whoever made it),
then manipulation strategy, then organic — and the random-walk background is
that module's per-tick residual. Returns follow ``analytics/_series``: a
return exists only when the previous *recorded* tick is the immediately
preceding tick number, and gaps are never bridged. Pump-and-dump phases are
the recorded ``reason`` of ``pump_and_dump`` fills, as
``analytics/manipulation.py`` reads them. ``organic_crowd_flow`` and
``organic_breadth`` are the simulator's own functions, and the net buyer /
seller counts net each trader's fills exactly as ``organic_breadth`` does.
Every volume sum is ``math.fsum``.

**Descriptive only.** Event columns are the configured event state recorded
on each tick. Psychology columns are the market psychology recorded on each
tick, ``None`` when psychology is off. The crowd-flow and breadth columns
describe tick *t*'s own completed organic fills; a value a trader was
*delivered* at tick *t* is the previous row's. No column states or implies
why anything moved.

**Not in the model:** timestamps, per-trade or per-trader rows, decision
records (holds, inactive ticks, tilts), leave-self-out breadth, replayed
holdings or P&L, drawdown or rolling volatility, VWAP, slippage,
``total_shares``, ``fee_rate`` and whale ``price_impact``.

Deterministic and read-only: no randomness, no clock, no mutation of the
ticks or anything they reference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from crypto_simulator.analytics.market import AMM, _pricing_mode
from crypto_simulator.core.coin_simulator import SimulationTick, organic_breadth, organic_crowd_flow
from crypto_simulator.core.events.event import EventPhase
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES, TRADER_STRATEGIES

__all__ = [
    "CLASS_COLUMNS",
    "COLUMNS",
    "PUMP_AND_DUMP",
    "ClassSeries",
    "LiveEvent",
    "TickSeries",
    "build_tick_series",
]

#: The recorded ``reason`` values of ``pump_and_dump`` fills, and the column
#: each one's volume goes to (``analytics/manipulation.py``'s phases).
PUMP_AND_DUMP = "pump_and_dump"
_PUMP_PHASE_COLUMNS = (
    ("accumulate", "pump_accumulate_volume"),
    ("pump", "pump_pump_volume"),
    ("dump", "pump_dump_volume"),
)

#: Every per-tick column, in the frozen Step 2 order (sections 3.1-3.10;
#: per-class columns are in ``CLASS_COLUMNS``).
COLUMNS: tuple[str, ...] = (
    # 3.1 market
    "tick",
    "price",
    "market_cap",
    "volume",
    "simple_return",
    "log_return",
    # 3.2 volume decomposition
    "whale_volume",
    "organic_volume",
    "manipulator_volume",
    "wash_volume",
    "background_volume",
    "whale_fills",
    "zero_quantity_whale_trades",
    "organic_fills",
    "manipulator_fills",
    "wash_legs",
    # 3.4 whales
    "whale_buy_volume",
    "whale_sell_volume",
    "whale_buy_trades",
    "whale_sell_trades",
    # 3.5 pump-and-dump phases
    "pump_accumulate_volume",
    "pump_pump_volume",
    "pump_dump_volume",
    # 3.6 recorded event state
    "event_sentiment",
    "event_volatility_multiplier",
    "event_attention_multiplier",
    "event_live",
    # 3.7 psychology
    "fear",
    "fomo",
    "conviction",
    "uncertainty",
    # 3.8 AMM pool
    "pool_coin_reserve",
    "pool_cash_reserve",
    "pool_spot_price",
    "pool_invariant",
    "pool_fees_collected_coins",
    "pool_fees_collected_cash",
    "pool_swap_count",
    "pool_swaps",
    "pool_max_abs_price_impact",
    # 3.10 organic crowd observables
    "organic_crowd_flow",
    "organic_breadth",
    "organic_net_buyers",
    "organic_net_sellers",
)

#: Per-class columns (section 3.3), in order.
CLASS_COLUMNS: tuple[str, ...] = (
    "buy_fills",
    "sell_fills",
    "buy_volume",
    "sell_volume",
    "net_coin_flow",
    "filled_traders",
)

_WHALE_COLUMNS = (
    "whale_volume",
    "whale_fills",
    "zero_quantity_whale_trades",
    "whale_buy_volume",
    "whale_sell_volume",
    "whale_buy_trades",
    "whale_sell_trades",
)
_POOL_COLUMNS = tuple(name for name in COLUMNS if name.startswith("pool_"))
_PSYCHOLOGY_COLUMNS = ("fear", "fomo", "conviction", "uncertainty")
_EVENT_COLUMNS = ("event_sentiment", "event_volatility_multiplier", "event_attention_multiplier", "event_live")


@dataclass(frozen=True)
class LiveEvent:
    """One event live on a tick, as the tick's ``EventState`` recorded it."""

    event_id: str
    category: str
    phase: EventPhase
    intensity: float


@dataclass(frozen=True)
class ClassSeries:
    """One organic strategy's fills per tick (non-wash fills only).

    Each field holds one value per tick. ``filled_traders`` counts the
    class's distinct traders with at least one fill that tick — a fill
    count, not a participation rate, and the absence of a fill says
    nothing about what a trader decided.
    """

    buy_fills: tuple[int, ...]
    sell_fills: tuple[int, ...]
    buy_volume: tuple[float, ...]
    sell_volume: tuple[float, ...]
    net_coin_flow: tuple[float, ...]
    filled_traders: tuple[int, ...]


@dataclass(frozen=True)
class TickSeries:
    """A run's per-tick observables, columnar (see the module docstring).

    ``rows`` is the number of ticks; every column in ``data`` and every
    field of every ``ClassSeries`` has exactly ``rows`` values.
    ``population`` and ``whale_count`` are the presence inputs the model
    was built with, carried once rather than per row.
    """

    columns: tuple[str, ...]
    rows: int
    data: Mapping[str, tuple[Any, ...]]
    classes: Mapping[str, ClassSeries]
    population: Mapping[str, int]
    whale_count: int


def build_tick_series(
    ticks: Sequence[SimulationTick],
    *,
    total_supply: float,
    population: Mapping[str, int],
    whale_count: int,
) -> TickSeries:
    """Project ``ticks`` (one run, in recorded order) into a ``TickSeries``.

    ``total_supply`` is the coin's supply, the denominator
    ``organic_crowd_flow`` uses. ``population`` maps every strategy in the
    run to its trader count; ``whale_count`` is the number of whales. One
    pass over the ticks and their recorded trades.

    Raises:
        ValueError: an invalid population or supply, ticks that mix AMM and
            random-walk records, whale trades in a run declared to have no
            whales, or a trader fill whose strategy is not in the population.
    """
    population = _validated_population(population)
    if isinstance(whale_count, bool) or not isinstance(whale_count, int) or whale_count < 0:
        raise ValueError(f"whale_count must be an int >= 0 (got {whale_count!r})")
    ticks = tuple(ticks)
    amm = _pricing_mode(list(ticks)) == AMM
    has_whales = whale_count > 0 and not amm
    has_pump = PUMP_AND_DUMP in population
    organic_classes = tuple(sorted(name for name in population if name in TRADER_STRATEGIES))

    data: dict[str, list[Any]] = {name: [] for name in COLUMNS}
    class_data = {name: {column: [] for column in CLASS_COLUMNS} for name in organic_classes}
    previous: SimulationTick | None = None
    for tick in ticks:
        row = _market_row(tick, previous)
        row.update(_trade_rows(tick, population, class_data, has_whales, has_pump))
        row.update(_event_row(tick))
        row.update(_psychology_row(tick))
        row.update(_pool_row(tick))
        row["organic_crowd_flow"] = organic_crowd_flow(tick.trader_trades, total_supply)
        row["organic_breadth"] = organic_breadth(tick.trader_trades)
        for name in COLUMNS:
            data[name].append(row[name])
        previous = tick

    return TickSeries(
        columns=COLUMNS,
        rows=len(ticks),
        data={name: tuple(values) for name, values in data.items()},
        classes={
            name: ClassSeries(**{column: tuple(values) for column, values in columns.items()})
            for name, columns in class_data.items()
        },
        population=dict(sorted(population.items())),
        whale_count=whale_count,
    )


def _validated_population(population: Mapping[str, int]) -> dict[str, int]:
    known = set(TRADER_STRATEGIES) | set(MANIPULATION_STRATEGIES)
    checked: dict[str, int] = {}
    for name, count in population.items():
        if name not in known:
            raise ValueError(f"unknown strategy {name!r} in population; known: {sorted(known)}")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"population[{name!r}] must be an int > 0 (got {count!r})")
        checked[name] = count
    return checked


def _market_row(tick: SimulationTick, previous: SimulationTick | None) -> dict[str, Any]:
    simple = log = None
    # analytics/_series: a return needs the immediately preceding tick number;
    # a gap is never bridged. Same expressions as simple_returns/log_returns.
    if previous is not None and tick.tick == previous.tick + 1:
        before, after = previous.price, tick.price
        simple = after / before - 1.0
        log = math.log(after / before)
    return {
        "tick": tick.tick,
        "price": tick.price,
        "market_cap": tick.market_cap,
        "volume": tick.volume,
        "simple_return": simple,
        "log_return": log,
    }


def _trade_rows(
    tick: SimulationTick,
    population: Mapping[str, int],
    class_data: dict[str, dict[str, list[Any]]],
    has_whales: bool,
    has_pump: bool,
) -> dict[str, Any]:
    amm = tick.pool_state is not None
    if tick.whale_trades and not has_whales:
        raise ValueError(f"tick {tick.tick} has whale trades but the run was declared to have no whales")

    quantities: list[float] = []
    whale, whale_buy, whale_sell = [], [], []
    whale_fills = zero_whale = whale_buy_trades = whale_sell_trades = 0
    for trade in tick.whale_trades:
        whale.append(trade.quantity)
        quantities.append(trade.quantity)
        if trade.quantity > 0:
            whale_fills += 1
            if trade.side == TradeAction.BUY.value:
                whale_buy_trades += 1
            else:
                whale_sell_trades += 1
        else:
            zero_whale += 1
        (whale_buy if trade.side == TradeAction.BUY.value else whale_sell).append(trade.quantity)

    organic, manipulator, wash = [], [], []
    organic_fills = manipulator_fills = wash_legs = 0
    pump = {reason: [] for reason, _ in _PUMP_PHASE_COLUMNS}
    per_class = {name: {"buy": [], "sell": [], "traders": set()} for name in class_data}
    net_by_trader: dict[str, float] = {}
    for fill in tick.trader_trades:
        if fill.strategy not in population:
            raise ValueError(
                f"tick {tick.tick}: fill by {fill.trader_id!r} has strategy {fill.strategy!r}, "
                f"which is not in the population"
            )
        quantities.append(fill.quantity)
        # analytics/market.py: one category per fill, the wash flag first.
        if fill.wash:
            wash.append(fill.quantity)
            wash_legs += 1
        elif fill.strategy in MANIPULATION_STRATEGIES:
            manipulator.append(fill.quantity)
            manipulator_fills += 1
            # analytics/manipulation.py: a pump-and-dump phase is the fill's
            # recorded reason; a zero-quantity record is not a fill.
            if fill.strategy == PUMP_AND_DUMP and fill.quantity > 0 and fill.reason in pump:
                pump[fill.reason].append(fill.quantity)
        else:
            organic.append(fill.quantity)
            organic_fills += 1
            bucket = per_class[fill.strategy]
            bucket["buy" if fill.side is TradeAction.BUY else "sell"].append(fill.quantity)
            bucket["traders"].add(fill.trader_id)
            signed = fill.quantity if fill.side is TradeAction.BUY else -fill.quantity
            net_by_trader[fill.trader_id] = net_by_trader.get(fill.trader_id, 0.0) + signed

    for name, bucket in per_class.items():
        buy_volume, sell_volume = math.fsum(bucket["buy"]), math.fsum(bucket["sell"])
        columns = class_data[name]
        columns["buy_fills"].append(len(bucket["buy"]))
        columns["sell_fills"].append(len(bucket["sell"]))
        columns["buy_volume"].append(buy_volume)
        columns["sell_volume"].append(sell_volume)
        columns["net_coin_flow"].append(buy_volume - sell_volume)
        columns["filled_traders"].append(len(bucket["traders"]))

    # organic_breadth's netting, accumulated the same way: one count per
    # organic trader, on the side of its net filled quantity; a trader
    # netting to zero counts on neither.
    nets = list(net_by_trader.values())
    row: dict[str, Any] = {
        "organic_volume": math.fsum(organic),
        "manipulator_volume": math.fsum(manipulator),
        "wash_volume": math.fsum(wash),
        "background_volume": None if amm else tick.volume - math.fsum(quantities),
        "organic_fills": organic_fills,
        "manipulator_fills": manipulator_fills,
        "wash_legs": wash_legs,
        "organic_net_buyers": sum(1 for net in nets if net > 0),
        "organic_net_sellers": sum(1 for net in nets if net < 0),
    }
    if has_whales:
        row.update(
            whale_volume=math.fsum(whale),
            whale_fills=whale_fills,
            zero_quantity_whale_trades=zero_whale,
            whale_buy_volume=math.fsum(whale_buy),
            whale_sell_volume=math.fsum(whale_sell),
            whale_buy_trades=whale_buy_trades,
            whale_sell_trades=whale_sell_trades,
        )
    else:
        row.update(dict.fromkeys(_WHALE_COLUMNS))
    for reason, column in _PUMP_PHASE_COLUMNS:
        row[column] = math.fsum(pump[reason]) if has_pump else None
    return row


def _event_row(tick: SimulationTick) -> dict[str, Any]:
    state = tick.event_state
    if state is None:
        return dict.fromkeys(_EVENT_COLUMNS)
    return {
        "event_sentiment": state.sentiment,
        "event_volatility_multiplier": state.volatility_multiplier,
        "event_attention_multiplier": state.attention_multiplier,
        "event_live": tuple(
            LiveEvent(event_id=s.event_id, category=s.category, phase=s.phase, intensity=s.intensity)
            for s in state.events
        ),
    }


def _psychology_row(tick: SimulationTick) -> dict[str, Any]:
    state = tick.psychology
    if state is None:
        return dict.fromkeys(_PSYCHOLOGY_COLUMNS)
    return {name: getattr(state, name) for name in _PSYCHOLOGY_COLUMNS}


def _pool_row(tick: SimulationTick) -> dict[str, Any]:
    pool = tick.pool_state
    if pool is None:
        return dict.fromkeys(_POOL_COLUMNS)
    impacts = [abs(fill.swap.price_impact) for fill in tick.trader_trades if fill.swap is not None]
    return {
        "pool_coin_reserve": float(pool.coin_reserve),
        "pool_cash_reserve": float(pool.cash_reserve),
        "pool_spot_price": float(pool.spot_price),
        "pool_invariant": float(pool.invariant),
        "pool_fees_collected_coins": float(pool.fees_collected_coins),
        "pool_fees_collected_cash": float(pool.fees_collected_cash),
        "pool_swap_count": pool.swap_count,
        "pool_swaps": len(impacts),
        "pool_max_abs_price_impact": float(max(impacts)) if impacts else None,
    }
