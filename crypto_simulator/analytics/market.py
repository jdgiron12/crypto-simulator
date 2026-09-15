"""Core market analytics over a finished coin simulation (Phase 9, Step 1).

Post-processing only: reads ``SimulationTick`` records and returns frozen
results. Nothing here feeds back into the simulation, draws random
numbers, or mutates its inputs. Every figure describes what was recorded;
none is a claim about why the market moved.

**Price path.** One price per tick (the tick's close); there are no
candles and no tick 0. ``initial_price`` — the pre-run price, normally
``coin.starting_price`` — joins the path as point ``PRE_RUN_TICK`` (0)
only when tick 1 is among the analysed ticks, exactly as
``analytics/events.py`` treats it. ``start_tick``/``end_tick`` select a
window of tick numbers; every definition below then applies to that
window alone.

**Returns** exist only between consecutive tick numbers (the pre-run
point counts as the one before tick 1); a missing tick is never bridged.
``volatility`` is the sample standard deviation of those log returns —
``events.py``'s definition, at least ``MIN_VOLATILITY_RETURNS`` returns —
and ``realized_volatility`` is sqrt(sum of squared log returns). Neither
is annualized: a tick is simulated time, not calendar time.

**Drawdown** is ``1 - price / running peak`` along the path; recovery is
the first later point back at or above the peak of the deepest drawdown.

**Volume.** A random-walk tick's ``volume`` is built by the simulator as
the tick's synthetic volume plus every whale trade's quantity plus every
trader fill's quantity — *both* legs of a wash trade included — and
``SimulationTick.wash_volume`` is derived from those same legs. Each
recorded quantity is therefore classified exactly once::

    total = background + whale + organic + manipulator (non-wash) + wash

- whale: every ``WhaleTrade`` quantity;
- wash: trader fills flagged ``wash`` (whoever made them);
- manipulator: other fills whose strategy is a manipulation strategy;
- organic: every other trader fill;
- background: the synthetic volume, which is not recorded, so it is the
  per-tick residual ``volume - fsum(participant quantities)``. That is
  exact up to floating-point rounding (a few units in the last place of
  the tick's volume) and is never clamped.

An AMM tick's volume is only its trader fills (wash legs included); AMM
mode has no whales and no synthetic volume, so ``background_volume`` is
``None`` there — not applicable, rather than a measured zero.

**Turnover** is volume relative to the coin's total supply —
``total_volume / total_supply`` — the same scale the synthetic volume is
drawn at (``VolumeModel``: a fraction of supply per tick).
``participant_turnover`` counts only whale, organic and manipulator
volume: the synthetic background and self-cancelling wash legs are left
out. Both need ``total_supply``; so do the market caps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from crypto_simulator.analytics._series import (
    PRE_RUN_TICK,
    drawdown,
    log_returns,
    ordered_ticks,
    price_path,
    realized_volatility,
    require_price,
    sample_volatility,
    simple_returns,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.liquidity.amounts import EXACT, ZERO
from crypto_simulator.core.liquidity.pool import BUY
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES

RANDOM_WALK = "random_walk"
AMM = "amm"


@dataclass(frozen=True)
class VolumeBreakdown:
    """Where the recorded volume came from; see the module docstring.

    Volumes are in coins. The fill counts classify every trade record once:
    ``whale_fills`` are whale trades that moved coins and
    ``zero_quantity_whale_trades`` those that did not (an unfunded whale
    selling with nothing to sell), which are not fills.
    ``background_volume`` is ``None`` in AMM mode and for an empty input.
    """

    total_volume: float
    background_volume: float | None
    whale_volume: float
    organic_volume: float
    manipulator_volume: float
    wash_volume: float
    whale_fills: int
    zero_quantity_whale_trades: int
    organic_fills: int
    manipulator_fills: int
    wash_legs: int

    @property
    def participant_volume(self) -> float:
        """Whale, organic and manipulator volume — everything except the
        synthetic background and wash legs."""
        return math.fsum((self.whale_volume, self.organic_volume, self.manipulator_volume))

    @property
    def trader_fills(self) -> int:
        """Non-wash trader fills (organic and manipulator)."""
        return self.organic_fills + self.manipulator_fills

    @property
    def fills(self) -> int:
        """Every record that moved coins: whale fills, trader fills and wash legs."""
        return self.whale_fills + self.organic_fills + self.manipulator_fills + self.wash_legs


@dataclass(frozen=True)
class PoolActivity:
    """AMM swap activity, from the recorded swaps (exact ``Decimal``).

    A swap's fee is charged in its input asset, so buy fees are cash and
    sell fees are coins; the two are reported apart and never added.
    ``max_abs_price_impact`` is the largest relative spot-price change of
    any single swap, or ``None`` with no swaps. Wash legs are real swaps
    and are included.
    """

    swap_count: int
    fees_cash: Decimal
    fees_coins: Decimal
    max_abs_price_impact: Decimal | None


@dataclass(frozen=True)
class MarketSummary:
    """Descriptive market figures for a run, or a window of one.

    ``None`` means not computable from the data (no ticks, too few
    returns, no ``total_supply``, ...), never a stand-in value.
    ``high_tick``, ``low_tick`` and the drawdown ticks are tick numbers,
    with ``PRE_RUN_TICK`` (0) for the pre-run point.
    """

    ticks: int
    first_tick: int | None
    last_tick: int | None
    missing_tick_count: int
    pricing_mode: str | None
    open_price: float | None
    close_price: float | None
    cumulative_return: float | None
    log_return: float | None
    high_price: float | None
    high_tick: int | None
    low_price: float | None
    low_tick: int | None
    mean_price: float | None
    return_count: int
    mean_return: float | None
    volatility: float | None
    realized_volatility: float | None
    max_drawdown: float | None
    drawdown_peak_tick: int | None
    drawdown_trough_tick: int | None
    recovery_tick: int | None
    end_drawdown: float | None
    market_cap_start: float | None
    market_cap_end: float | None
    volume_breakdown: VolumeBreakdown
    average_trade_size: float | None
    turnover: float | None
    participant_turnover: float | None
    trader_vwap: float | None
    pool_activity: PoolActivity | None


def analyze_market(
    ticks: Iterable[SimulationTick],
    *,
    initial_price: float | None = None,
    total_supply: float | None = None,
    start_tick: int | None = None,
    end_tick: int | None = None,
) -> MarketSummary:
    """Describe the market recorded on ``ticks``.

    ``initial_price`` is the pre-run price (used only when tick 1 is
    analysed); ``total_supply`` enables market caps and turnover;
    ``start_tick``/``end_tick`` (inclusive, 1-based) restrict the analysis
    to a window of tick numbers.

    Pure: the same ticks, in any order, always give the same summary; the
    inputs are not mutated and no randomness is drawn.
    """
    if initial_price is not None:
        require_price("initial_price", initial_price)
    if total_supply is not None:
        require_price("total_supply", total_supply)
    for name, value in (("start_tick", start_tick), ("end_tick", end_tick)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ValueError(f"{name} must be an integer >= 1 (got {value!r})")
    if start_tick is not None and end_tick is not None and start_tick > end_tick:
        raise ValueError(f"start_tick ({start_tick}) must not exceed end_tick ({end_tick})")

    ordered = [tick for tick in ordered_ticks(ticks)
               if (start_tick is None or tick.tick >= start_tick) and (end_tick is None or tick.tick <= end_tick)]
    path = price_path(ordered, initial_price)
    mode = _pricing_mode(ordered)
    volume = _volume_breakdown(ordered, mode)

    if not path:
        return MarketSummary(
            ticks=0, first_tick=None, last_tick=None, missing_tick_count=0, pricing_mode=None,
            open_price=None, close_price=None, cumulative_return=None, log_return=None,
            high_price=None, high_tick=None, low_price=None, low_tick=None, mean_price=None,
            return_count=0, mean_return=None, volatility=None, realized_volatility=None,
            max_drawdown=None, drawdown_peak_tick=None, drawdown_trough_tick=None, recovery_tick=None,
            end_drawdown=None, market_cap_start=None, market_cap_end=None, volume_breakdown=volume,
            average_trade_size=None, turnover=None, participant_turnover=None, trader_vwap=None,
            pool_activity=None,
        )

    open_price, close_price = path[0][1], path[-1][1]
    high_tick, high_price = _extreme(path, higher=True)
    low_tick, low_price = _extreme(path, higher=False)
    simple, logs = simple_returns(path), log_returns(path)
    dd = drawdown(path)
    first, last = ordered[0].tick, ordered[-1].tick
    trader_fills = [f for tick in ordered for f in tick.trader_trades if not f.wash]
    traded = math.fsum(f.quantity for f in trader_fills)
    return MarketSummary(
        ticks=len(ordered),
        first_tick=first,
        last_tick=last,
        missing_tick_count=(last - first + 1) - len(ordered),
        pricing_mode=mode,
        open_price=open_price,
        close_price=close_price,
        cumulative_return=close_price / open_price - 1.0,
        log_return=math.log(close_price / open_price),
        high_price=high_price,
        high_tick=high_tick,
        low_price=low_price,
        low_tick=low_tick,
        mean_price=math.fsum(tick.price for tick in ordered) / len(ordered),
        return_count=len(simple),
        mean_return=math.fsum(simple) / len(simple) if simple else None,
        volatility=sample_volatility(logs),
        realized_volatility=realized_volatility(logs),
        max_drawdown=dd.maximum,
        drawdown_peak_tick=dd.peak_tick,
        drawdown_trough_tick=dd.trough_tick,
        recovery_tick=dd.recovery_tick,
        end_drawdown=dd.end,
        market_cap_start=None if total_supply is None else open_price * total_supply,
        market_cap_end=None if total_supply is None else close_price * total_supply,
        volume_breakdown=volume,
        average_trade_size=(volume.participant_volume / (volume.whale_fills + volume.trader_fills)
                            if volume.whale_fills + volume.trader_fills else None),
        turnover=None if total_supply is None else volume.total_volume / total_supply,
        participant_turnover=None if total_supply is None else volume.participant_volume / total_supply,
        trader_vwap=math.fsum(f.notional for f in trader_fills) / traded if traded > 0 else None,
        pool_activity=_pool_activity(ordered) if mode == AMM else None,
    )


def _extreme(path: list[tuple[int, float]], *, higher: bool) -> tuple[int, float]:
    """The highest (or lowest) point; ties go to the earliest."""
    best_tick, best = path[0]
    for tick, price in path[1:]:
        if (price > best) if higher else (price < best):
            best_tick, best = tick, price
    return best_tick, best


def _pricing_mode(ordered: list[SimulationTick]) -> str | None:
    """AMM ticks carry a pool snapshot and random-walk ticks never do; a
    mixture cannot come from one run."""
    pooled = {tick.pool_state is not None for tick in ordered}
    if len(pooled) > 1:
        raise ValueError("ticks mix AMM and random-walk records; analyse one run at a time")
    if not pooled:
        return None
    return AMM if pooled.pop() else RANDOM_WALK


def _volume_breakdown(ordered: list[SimulationTick], mode: str | None) -> VolumeBreakdown:
    whale, organic, manipulator, wash, background = [], [], [], [], []
    whale_fills = zero_whale = organic_fills = manipulator_fills = wash_legs = 0
    for tick in ordered:
        quantities = []
        for trade in tick.whale_trades:
            whale.append(trade.quantity)
            quantities.append(trade.quantity)
            if trade.quantity > 0:
                whale_fills += 1
            else:
                zero_whale += 1
        for fill in tick.trader_trades:
            quantities.append(fill.quantity)
            # One category per fill: the wash flag first (a wash leg is a
            # self-trade whoever made it), then the strategy label.
            if fill.wash:
                wash.append(fill.quantity)
                wash_legs += 1
            elif fill.strategy in MANIPULATION_STRATEGIES:
                manipulator.append(fill.quantity)
                manipulator_fills += 1
            else:
                organic.append(fill.quantity)
                organic_fills += 1
        if mode == RANDOM_WALK:
            background.append(tick.volume - math.fsum(quantities))
    return VolumeBreakdown(
        total_volume=math.fsum(tick.volume for tick in ordered),
        background_volume=math.fsum(background) if mode == RANDOM_WALK else None,
        whale_volume=math.fsum(whale),
        organic_volume=math.fsum(organic),
        manipulator_volume=math.fsum(manipulator),
        wash_volume=math.fsum(wash),
        whale_fills=whale_fills,
        zero_quantity_whale_trades=zero_whale,
        organic_fills=organic_fills,
        manipulator_fills=manipulator_fills,
        wash_legs=wash_legs,
    )


def _pool_activity(ordered: list[SimulationTick]) -> PoolActivity:
    swaps = [fill.swap for tick in ordered for fill in tick.trader_trades if fill.swap is not None]
    fees_cash = fees_coins = ZERO
    for swap in swaps:
        if swap.side == BUY:
            fees_cash = EXACT.add(fees_cash, swap.fee)
        else:
            fees_coins = EXACT.add(fees_coins, swap.fee)
    return PoolActivity(
        swap_count=len(swaps),
        fees_cash=fees_cash,
        fees_coins=fees_coins,
        # copy_abs is exact; abs() would round to the default Decimal context.
        max_abs_price_impact=max((swap.price_impact.copy_abs() for swap in swaps), default=None),
    )
