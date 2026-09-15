"""Descriptive trader analytics over a finished coin simulation (Phase 9, Step 2).

Post-processing only: reads the ``TraderTrade`` records on each
``SimulationTick`` and returns frozen results. Nothing here feeds back
into the simulation, draws random numbers, or mutates its inputs. Every
figure describes what was recorded; none is a claim about why a trader
traded, nor a signal or a recommendation.

**Records, fills and legs.** A trade record is one ``TraderTrade``. A
*fill* is a record whose ``quantity`` moved coins (> 0); a zero-quantity
record is counted but is not a fill. Each fill is exactly one of: a buy, a
sell, or a wash leg — a fill flagged ``wash`` by the simulator, whichever
side it is. Wash legs are real settlements, so they are part of a
trader's ``total_volume`` and of every flow; they are reported apart
(``wash_*``) and never added a second time.

**Recorded values are authoritative.** ``quantity`` and ``notional`` are
what settlement moved: in random-walk mode ``notional`` is the exact cash
the wallet paid or received; in AMM mode it is the float value of the
exact ``Decimal`` amount, with the swap fee already inside it. Nothing is
re-priced and no fee is applied again. In AMM mode the exact flows are
also reported (``exact_cash_flow``/``exact_coin_flow``), taken from each
fill's recorded swap: a buy pays ``amount_in`` cash and receives
``amount_out`` coins; a sell pays ``amount_in`` coins and receives
``amount_out`` cash. The fee a swap charged is in its input asset —
cash for buys, coins for sells — and is reported per asset
(``fees_paid_*``) purely for information.

**Requested versus filled.** ``requested_quantity`` is what each
decision asked for. In random-walk mode settlement can only clamp it, so
the fill ratio is at most 1. In AMM mode a buy spends the budget that
quantity is worth at the tick's reference price, and the coins it
receives can differ either way — fees and slippage reduce them, while an
earlier swap in the same tick that lowered the pool price can raise
them — so an AMM fill ratio can exceed 1.

**Signs.** ``net_coin_flow`` = coins bought − coins sold;
``net_cash_flow`` = cash received on sells − cash paid on buys, so a buy
is negative cash and a sell positive — the direction the wallet moved.

**Equity and P&L** use the demo CLI's definition exactly: equity is
cash + coins × price — the expression ``Wallet.equity`` evaluates (the
analytics package imports only core types, so it is written out here and
a test pins it to ``Wallet.equity``) — valued at
``initial_price`` for the start balances and at the last analysed tick's
price for the end balances; P&L = end equity − start equity; return =
P&L / start equity when that is positive. The balances are the
simulator's own wallet balances, supplied by the caller as
``{trader_id: (cash, coins)}`` snapshots (the ticks do not record
wallets). Nothing is reconstructed from fills here, and there is no
realized/unrealized split, cost basis or fee accounting beyond what the
wallets already hold. Without the balances (or ``initial_price``) those
figures are ``None``.

**Population.** A trader with no trade record is invisible in the ticks.
The population is every trader seen in a record plus every trader in the
supplied balances — or exactly ``trader_ids`` when given. A trader known
only from balances has no recorded strategy (``strategy`` is ``None``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from crypto_simulator.analytics._series import is_valid_price, ordered_ticks, require_price
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.liquidity.amounts import EXACT, ZERO
from crypto_simulator.core.liquidity.pool import BUY
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES


@dataclass(frozen=True)
class TraderSummary:
    """One trader's recorded activity; see the module docstring.

    Buy and sell figures exclude wash legs, which have their own
    ``wash_*`` figures; ``total_*``, ``vwap`` and the flows cover every
    fill. ``requested_volume`` sums ``requested_quantity`` over every
    record (a zero-quantity record requested and received nothing), and
    is ``None`` if any record lacks it. AMM-only figures are ``None`` in
    random-walk mode; balance-based figures are ``None`` without balances.
    """

    trader_id: str
    strategy: str | None
    is_manipulator: bool | None
    records: int
    fill_count: int
    buy_count: int
    sell_count: int
    wash_leg_count: int
    buy_volume: float
    sell_volume: float
    wash_volume: float
    total_volume: float
    buy_notional: float
    sell_notional: float
    wash_notional: float
    total_notional: float
    vwap: float | None
    wash_share: float | None
    net_coin_flow: float
    net_cash_flow: float
    requested_volume: float | None
    fill_ratio: float | None
    active_ticks: int
    first_fill_tick: int | None
    last_fill_tick: int | None
    average_fill_size: float | None
    fees_paid_cash: Decimal | None
    fees_paid_coins: Decimal | None
    exact_cash_flow: Decimal | None
    exact_coin_flow: Decimal | None
    start_cash: float | None
    start_coins: float | None
    end_cash: float | None
    end_coins: float | None
    start_equity: float | None
    end_equity: float | None
    pnl: float | None
    equity_return: float | None

    @property
    def active(self) -> bool:
        return self.fill_count > 0


@dataclass(frozen=True)
class StrategySummary:
    """Traders grouped by their recorded strategy label (``None``: traders
    known only from balances). Sums of the members' figures; ``pnl`` and
    the equities are ``None`` unless every member has them."""

    strategy: str | None
    is_manipulation_strategy: bool | None
    trader_count: int
    active_trader_count: int
    participation: float | None
    fill_count: int
    buy_volume: float
    sell_volume: float
    wash_volume: float
    total_volume: float
    total_notional: float
    vwap: float | None
    net_coin_flow: float
    net_cash_flow: float
    requested_volume: float | None
    filled_volume: float
    fill_ratio: float | None
    average_fill_size: float | None
    start_equity: float | None
    end_equity: float | None
    pnl: float | None


@dataclass(frozen=True)
class TraderReport:
    """Trader analytics for a finished run.

    ``traders`` is ordered by trader id and ``strategies`` by label (the
    unlabelled group last). The totals are sums over ``traders``;
    ``final_price`` is the last analysed tick's price, which values the
    end balances.
    """

    ticks: int
    pricing_mode: str | None
    final_price: float | None
    population: int
    active_traders: int
    participation_rate: float | None
    traders: tuple[TraderSummary, ...]
    strategies: tuple[StrategySummary, ...]
    fill_count: int
    buy_volume: float
    sell_volume: float
    wash_volume: float
    total_volume: float
    total_notional: float
    vwap: float | None
    net_coin_flow: float
    net_cash_flow: float
    requested_volume: float | None
    filled_volume: float
    fill_ratio: float | None
    fees_paid_cash: Decimal | None
    fees_paid_coins: Decimal | None
    start_equity: float | None
    end_equity: float | None
    pnl: float | None
    equity_return: float | None

    def trader(self, trader_id: str) -> TraderSummary:
        for summary in self.traders:
            if summary.trader_id == trader_id:
                return summary
        raise KeyError(f"no trader {trader_id!r} in this report")

    def strategy(self, name: str | None) -> StrategySummary:
        for summary in self.strategies:
            if summary.strategy == name:
                return summary
        raise KeyError(f"no strategy {name!r} in this report")


class _Activity:
    """Mutable per-trader accumulator for the single pass over the records."""

    def __init__(self):
        self.strategy: str | None = None
        self.records = 0
        self.buys: list[tuple[float, float]] = []   # (quantity, notional), non-wash
        self.sells: list[tuple[float, float]] = []
        self.wash_buys: list[tuple[float, float]] = []
        self.wash_sells: list[tuple[float, float]] = []
        self.requested: list[float] = []
        self.requested_missing = False
        self.fill_ticks: list[int] = []
        self.swaps: list = []          # (side, swap) per fill, AMM only
        self.unswapped_fills = 0


def analyze_traders(
    ticks: Iterable[SimulationTick],
    *,
    start_balances: Mapping[str, tuple[float, float]] | None = None,
    end_balances: Mapping[str, tuple[float, float]] | None = None,
    initial_price: float | None = None,
    trader_ids: Sequence[str] | None = None,
) -> TraderReport:
    """Describe the trader activity recorded on ``ticks``.

    ``start_balances``/``end_balances`` are ``{trader_id: (cash, coins)}``
    wallet snapshots taken at the start and end of the analysed ticks;
    ``initial_price`` values the start balances (the pre-run price for a
    whole run). ``trader_ids`` restricts the report to those traders.

    Pure: the same ticks, in any order, always give the same report; the
    inputs are not mutated and no randomness is drawn.
    """
    if initial_price is not None:
        require_price("initial_price", initial_price)
    start = _balances("start_balances", start_balances)
    end = _balances("end_balances", end_balances)
    ordered = ordered_ticks(ticks)
    for tick in ordered:
        if not is_valid_price(tick.price):
            raise ValueError(f"tick {tick.tick} has an invalid price {tick.price!r}")
    mode = _pricing_mode(ordered)
    final_price = ordered[-1].price if ordered else None

    activity: dict[str, _Activity] = {}
    for tick in ordered:
        for fill in tick.trader_trades:
            _record(activity.setdefault(fill.trader_id, _Activity()), fill, tick.tick)

    known = set(activity) | set(start or {}) | set(end or {})
    ids = _selected(trader_ids, known)
    for name, balances in (("start_balances", start), ("end_balances", end)):
        if balances is not None:
            missing = sorted(i for i in ids if i not in balances)
            if missing:
                raise ValueError(f"{name} has no balance for trader id(s) {missing}")

    summaries = tuple(
        _summarize(trader_id, activity.get(trader_id, _Activity()), mode, start, end, initial_price, final_price)
        for trader_id in sorted(ids)
    )
    return _report(len(ordered), mode, final_price, summaries)


# --- input handling ---------------------------------------------------------------------------------


def _balances(name: str, balances) -> dict[str, tuple[float, float]] | None:
    if balances is None:
        return None
    if not isinstance(balances, Mapping):
        raise ValueError(f"{name} must be a mapping of trader id to (cash, coins) (got {type(balances).__name__})")
    out = {}
    for trader_id, value in balances.items():
        if not isinstance(trader_id, str) or not trader_id:
            raise ValueError(f"{name} keys must be non-empty trader id strings (got {trader_id!r})")
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError(f"{name}[{trader_id!r}] must be a (cash, coins) pair (got {value!r})")
        for label, amount in zip(("cash", "coins"), value):
            if (isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount)
                    or amount < 0):
                raise ValueError(f"{name}[{trader_id!r}] {label} must be a finite number >= 0 (got {amount!r})")
        out[trader_id] = (float(value[0]), float(value[1]))
    return out


def _selected(trader_ids, known: set[str]) -> set[str]:
    if trader_ids is None:
        return known
    if isinstance(trader_ids, str) or not isinstance(trader_ids, (list, tuple)):
        raise ValueError(f"trader_ids must be a list or tuple of trader ids (got {trader_ids!r})")
    wanted = list(trader_ids)
    if not all(isinstance(i, str) and i for i in wanted):
        raise ValueError(f"trader_ids must be non-empty strings (got {wanted!r})")
    seen: set[str] = set()
    repeated = sorted({i for i in wanted if i in seen or seen.add(i)})
    if repeated:
        raise ValueError(f"trader_ids repeats {repeated}")
    unknown = sorted(set(wanted) - known)
    if unknown:
        raise ValueError(f"no records or balances for trader id(s) {unknown}; known: {sorted(known)}")
    return set(wanted)


def _pricing_mode(ordered: list[SimulationTick]) -> str | None:
    pooled = {tick.pool_state is not None for tick in ordered}
    if len(pooled) > 1:
        raise ValueError("ticks mix AMM and random-walk records; analyse one run at a time")
    if not pooled:
        return None
    return "amm" if pooled.pop() else "random_walk"


def _record(acc: _Activity, fill, tick_number: int) -> None:
    if acc.strategy is not None and fill.strategy != acc.strategy:
        raise ValueError(
            f"trader {fill.trader_id!r} is recorded under two strategies ({acc.strategy!r} and {fill.strategy!r})"
        )
    acc.strategy = fill.strategy
    acc.records += 1
    if fill.requested_quantity is None:
        acc.requested_missing = True
    else:
        acc.requested.append(fill.requested_quantity)
    if not fill.quantity > 0:
        return  # a record, not a fill
    pair = (fill.quantity, fill.notional)
    is_buy = fill.side is TradeAction.BUY
    if fill.wash:
        (acc.wash_buys if is_buy else acc.wash_sells).append(pair)
    else:
        (acc.buys if is_buy else acc.sells).append(pair)
    if not acc.fill_ticks or acc.fill_ticks[-1] != tick_number:
        acc.fill_ticks.append(tick_number)
    if fill.swap is None:
        acc.unswapped_fills += 1
    else:
        acc.swaps.append(fill.swap)


# --- summaries --------------------------------------------------------------------------------------


def _equity(cash: float, coins: float, price: float) -> float:
    """``Wallet.equity``: cash plus coins marked to ``price``, the same
    expression evaluated the same way."""
    return cash + coins * price


def _sum(pairs, index):
    return math.fsum(pair[index] for pair in pairs)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _summarize(trader_id, acc, mode, start, end, initial_price, final_price) -> TraderSummary:
    buy_volume, sell_volume = _sum(acc.buys, 0), _sum(acc.sells, 0)
    wash = acc.wash_buys + acc.wash_sells
    wash_volume = _sum(wash, 0)
    bought = acc.buys + acc.wash_buys
    sold = acc.sells + acc.wash_sells
    fills = bought + sold
    total_volume = _sum(fills, 0)
    total_notional = _sum(fills, 1)
    requested = None if acc.requested_missing else math.fsum(acc.requested)

    fees_cash = fees_coins = exact_cash = exact_coins = None
    if mode == "amm":
        fees_cash = fees_coins = exact_cash = exact_coins = ZERO
        for swap in acc.swaps:
            if swap.side == BUY:
                fees_cash = EXACT.add(fees_cash, swap.fee)
                exact_cash = EXACT.subtract(exact_cash, swap.amount_in)
                exact_coins = EXACT.add(exact_coins, swap.amount_out)
            else:
                fees_coins = EXACT.add(fees_coins, swap.fee)
                exact_coins = EXACT.subtract(exact_coins, swap.amount_in)
                exact_cash = EXACT.add(exact_cash, swap.amount_out)
        if acc.unswapped_fills:
            exact_cash = exact_coins = None  # not every fill carries its exact amounts

    start_cash, start_coins = start[trader_id] if start is not None else (None, None)
    end_cash, end_coins = end[trader_id] if end is not None else (None, None)
    start_equity = (_equity(start_cash, start_coins, initial_price)
                    if start is not None and initial_price is not None else None)
    end_equity = (_equity(end_cash, end_coins, final_price)
                  if end is not None and final_price is not None else None)
    pnl = end_equity - start_equity if start_equity is not None and end_equity is not None else None
    return TraderSummary(
        trader_id=trader_id,
        strategy=acc.strategy,
        is_manipulator=None if acc.strategy is None else acc.strategy in MANIPULATION_STRATEGIES,
        records=acc.records,
        fill_count=len(fills),
        buy_count=len(acc.buys),
        sell_count=len(acc.sells),
        wash_leg_count=len(wash),
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        wash_volume=wash_volume,
        total_volume=total_volume,
        buy_notional=_sum(acc.buys, 1),
        sell_notional=_sum(acc.sells, 1),
        wash_notional=_sum(wash, 1),
        total_notional=total_notional,
        vwap=_ratio(total_notional, total_volume),
        wash_share=_ratio(wash_volume, total_volume),
        net_coin_flow=_sum(bought, 0) - _sum(sold, 0),
        net_cash_flow=_sum(sold, 1) - _sum(bought, 1),
        requested_volume=requested,
        fill_ratio=_ratio(total_volume, requested) if requested is not None and requested > 0 else None,
        active_ticks=len(acc.fill_ticks),
        first_fill_tick=acc.fill_ticks[0] if acc.fill_ticks else None,
        last_fill_tick=acc.fill_ticks[-1] if acc.fill_ticks else None,
        average_fill_size=_ratio(total_volume, len(fills)),
        fees_paid_cash=fees_cash,
        fees_paid_coins=fees_coins,
        exact_cash_flow=exact_cash,
        exact_coin_flow=exact_coins,
        start_cash=start_cash,
        start_coins=start_coins,
        end_cash=end_cash,
        end_coins=end_coins,
        start_equity=start_equity,
        end_equity=end_equity,
        pnl=pnl,
        equity_return=pnl / start_equity if pnl is not None and start_equity > 0 else None,
    )


def _all_or_none(values):
    values = list(values)
    return None if any(v is None for v in values) else math.fsum(values)


def _decimal_total(values):
    values = list(values)
    if any(v is None for v in values):
        return None
    total = ZERO
    for value in values:
        total = EXACT.add(total, value)
    return total


def _strategy(name, members: list[TraderSummary]) -> StrategySummary:
    active = sum(1 for m in members if m.active)
    total_volume = math.fsum(m.total_volume for m in members)
    total_notional = math.fsum(m.total_notional for m in members)
    fills = sum(m.fill_count for m in members)
    requested = _all_or_none(m.requested_volume for m in members)
    return StrategySummary(
        strategy=name,
        is_manipulation_strategy=None if name is None else name in MANIPULATION_STRATEGIES,
        trader_count=len(members),
        active_trader_count=active,
        participation=active / len(members),
        fill_count=fills,
        buy_volume=math.fsum(m.buy_volume for m in members),
        sell_volume=math.fsum(m.sell_volume for m in members),
        wash_volume=math.fsum(m.wash_volume for m in members),
        total_volume=total_volume,
        total_notional=total_notional,
        vwap=_ratio(total_notional, total_volume),
        net_coin_flow=math.fsum(m.net_coin_flow for m in members),
        net_cash_flow=math.fsum(m.net_cash_flow for m in members),
        requested_volume=requested,
        filled_volume=total_volume,
        fill_ratio=_ratio(total_volume, requested) if requested is not None and requested > 0 else None,
        average_fill_size=_ratio(total_volume, fills),
        start_equity=_all_or_none(m.start_equity for m in members),
        end_equity=_all_or_none(m.end_equity for m in members),
        pnl=_all_or_none(m.pnl for m in members),
    )


def _report(tick_count, mode, final_price, summaries: tuple[TraderSummary, ...]) -> TraderReport:
    groups: dict[str | None, list[TraderSummary]] = {}
    for summary in summaries:
        groups.setdefault(summary.strategy, []).append(summary)
    strategies = tuple(_strategy(name, groups[name])
                       for name in sorted(groups, key=lambda n: (n is None, n or "")))
    active = sum(1 for s in summaries if s.active)
    total_volume = math.fsum(s.total_volume for s in summaries)
    total_notional = math.fsum(s.total_notional for s in summaries)
    requested = _all_or_none(s.requested_volume for s in summaries)
    start_equity = _all_or_none(s.start_equity for s in summaries) if summaries else None
    end_equity = _all_or_none(s.end_equity for s in summaries) if summaries else None
    pnl = _all_or_none(s.pnl for s in summaries) if summaries else None
    return TraderReport(
        ticks=tick_count,
        pricing_mode=mode,
        final_price=final_price,
        population=len(summaries),
        active_traders=active,
        participation_rate=_ratio(active, len(summaries)),
        traders=summaries,
        strategies=strategies,
        fill_count=sum(s.fill_count for s in summaries),
        buy_volume=math.fsum(s.buy_volume for s in summaries),
        sell_volume=math.fsum(s.sell_volume for s in summaries),
        wash_volume=math.fsum(s.wash_volume for s in summaries),
        total_volume=total_volume,
        total_notional=total_notional,
        vwap=_ratio(total_notional, total_volume),
        net_coin_flow=math.fsum(s.net_coin_flow for s in summaries),
        net_cash_flow=math.fsum(s.net_cash_flow for s in summaries),
        requested_volume=requested,
        filled_volume=total_volume,
        fill_ratio=_ratio(total_volume, requested) if requested is not None and requested > 0 else None,
        fees_paid_cash=_decimal_total(s.fees_paid_cash for s in summaries) if mode == "amm" else None,
        fees_paid_coins=_decimal_total(s.fees_paid_coins for s in summaries) if mode == "amm" else None,
        start_equity=start_equity,
        end_equity=end_equity,
        pnl=pnl,
        equity_return=pnl / start_equity if pnl is not None and start_equity > 0 else None,
    )
