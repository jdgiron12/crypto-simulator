"""analyze_events on hand-built ticks with known answers."""

import dataclasses
import math
import statistics

import pytest

from crypto_simulator.analytics import (
    MIN_VOLATILITY_RETURNS,
    EventGroundTruth,
    EventObservation,
    ObservedMarket,
    ObservedPool,
    ObservedTrading,
    analyze_events,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events import MarketEvent
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade
from crypto_simulator.core.whale import WhaleTrade

BUY, SELL = TradeAction.BUY, TradeAction.SELL


def _tick(n, price, volume=100.0, fills=(), whales=()):
    return SimulationTick(tick=n, timestamp=f"t{n}", price=price, market_cap=price * 1e6, volume=volume,
                          whale_trades=tuple(whales), trader_trades=tuple(fills))


def _fill(trader_id, side, quantity, wash=False):
    return TraderTrade(trader_id=trader_id, strategy="retail", side=side, requested_quantity=quantity,
                       quantity=quantity, price=1.0, notional=quantity, reason="x", wash=wash)


def _event(event_id="e", start_tick=5, duration=3, decay_ticks=2, sentiment=0.5, severity=0.8):
    return MarketEvent(event_id=event_id, category="exchange_listing", severity=severity, sentiment=sentiment,
                       volatility_boost=0.4, attention=0.6, start_tick=start_tick, duration=duration,
                       decay_ticks=decay_ticks, headline="A fictional listing")


def _flat(n_ticks, price=100.0, overrides=None):
    """Ticks 1..n at ``price``; ``overrides`` maps tick -> price."""
    overrides = overrides or {}
    return [_tick(t, overrides.get(t, price)) for t in range(1, n_ticks + 1)]


def _one(ticks, event, **kwargs):
    (observation,) = analyze_events(ticks, [event], **kwargs)
    return observation


# --- ground truth ----------------------------------------------------------------------------


def test_ground_truth_is_the_event_as_created():
    event = _event(start_tick=5, duration=3, decay_ticks=2)
    truth = _one(_flat(20), event).ground_truth
    assert truth == EventGroundTruth(
        event_id="e", category="exchange_listing", headline="A fictional listing", severity=0.8, sentiment=0.5,
        volatility_boost=0.4, attention=0.6, start_tick=5, last_active_tick=7, duration=3, decay_ticks=2,
        expires_at=10,
    )


def test_ground_truth_and_observations_live_in_separate_structures():
    truth_fields = {f.name for f in dataclasses.fields(EventGroundTruth)}
    observed = set()
    for cls in (ObservedMarket, ObservedTrading, ObservedPool):
        observed |= {f.name for f in dataclasses.fields(cls)}
    assert {"severity", "sentiment", "attention", "volatility_boost", "category", "headline"} <= truth_fields
    assert not truth_fields & observed
    assert {f.name for f in dataclasses.fields(EventObservation)} == {
        "ground_truth", "market", "trading", "pool", "overlapping_event_ids",
        "event_ticks_observed", "event_window_complete", "post_window_complete",
    }


def test_only_events_starting_within_the_ticks_are_observed_in_timeline_order():
    events = [_event("late", start_tick=30), _event("b", start_tick=8), _event("a", start_tick=8),
              _event("first", start_tick=2)]
    observed = analyze_events(_flat(20), events)
    assert [o.ground_truth.event_id for o in observed] == ["first", "a", "b"]
    assert analyze_events([], events) == ()


# --- prices and returns ----------------------------------------------------------------------


def test_prices_and_returns_over_the_windows():
    ticks = _flat(20, 100.0, {4: 100.0, 5: 110.0, 6: 115.0, 7: 121.0, 12: 133.1})
    market = _one(ticks, _event(start_tick=5, duration=3), post_window=5).market
    assert (market.price_before, market.price_at_start, market.price_at_end, market.price_after_post_window) == (
        100.0, 110.0, 121.0, 133.1,
    )
    assert market.immediate_return == 110.0 / 100.0 - 1
    assert market.event_return == pytest.approx(0.10)
    assert market.post_event_return == pytest.approx(0.10)


def test_negative_and_zero_returns():
    falling = _flat(20, 100.0, {5: 100.0, 7: 90.0})
    assert _one(falling, _event()).market.event_return == pytest.approx(-0.10)
    flat = _one(_flat(20), _event()).market
    assert (flat.immediate_return, flat.event_return, flat.post_event_return) == (0.0, 0.0, 0.0)


def test_post_window_without_enough_ticks_is_unavailable():
    observation = _one(_flat(10), _event(start_tick=5, duration=3), post_window=5)
    assert observation.market.post_event_return is None
    assert observation.market.price_after_post_window is None
    assert not observation.post_window_complete
    assert _one(_flat(12), _event(start_tick=5, duration=3), post_window=5).post_window_complete


def test_event_on_the_first_tick_needs_the_initial_price_for_its_first_move():
    ticks = _flat(10, 100.0, {1: 105.0})
    assert _one(ticks, _event(start_tick=1)).market.immediate_return is None
    market = _one(ticks, _event(start_tick=1), initial_price=100.0).market
    assert market.price_before == 100.0
    assert market.immediate_return == pytest.approx(0.05)


def test_event_still_running_when_the_data_ends():
    observation = _one(_flat(6), _event(start_tick=5, duration=3))
    assert (observation.event_ticks_observed, observation.event_window_complete) == (2, False)
    assert observation.market.price_at_end is None
    assert observation.market.event_return is None


def test_single_tick_event_has_a_zero_window_return_and_no_volatility():
    market = _one(_flat(20, 100.0, {5: 104.0}), _event(start_tick=5, duration=1)).market
    assert market.event_return == 0.0
    assert market.volatility is None  # one log return is not enough


def test_non_positive_or_non_finite_prices_are_treated_as_missing():
    for bad in (0.0, -5.0, math.nan, math.inf):
        market = _one(_flat(20, 100.0, {5: bad}), _event(start_tick=5, duration=3)).market
        assert market.price_at_start is None
        assert market.immediate_return is None and market.event_return is None
        assert market.volatility is None  # only ln(p7/p6) survives


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"post_window": 0}, "post_window"),
        ({"baseline_window": 0}, "baseline_window"),
        ({"post_window": True}, "post_window"),
        ({"initial_price": 0.0}, "initial_price"),
        ({"initial_price": math.nan}, "initial_price"),
        ({"trader_count": 0}, "trader_count"),
    ],
)
def test_invalid_arguments_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        analyze_events(_flat(5), [], **kwargs)


def test_duplicate_ticks_are_rejected():
    with pytest.raises(ValueError, match="duplicate tick 3"):
        analyze_events(_flat(5) + [_tick(3, 1.0)], [])


# --- volatility ---------------------------------------------------------------------------


def _prices_from_log_returns(start_price, returns_by_tick, n_ticks):
    prices, price = {}, start_price
    for t in range(1, n_ticks + 1):
        price *= math.exp(returns_by_tick.get(t, 0.0))
        prices[t] = price
    return [_tick(t, p) for t, p in prices.items()]


def test_volatility_is_the_sample_std_of_log_returns_in_each_window():
    returns = {2: 0.004, 3: -0.002, 4: 0.001, 5: 0.01, 6: -0.02, 7: 0.03}
    ticks = _prices_from_log_returns(100.0, returns, 20)
    market = _one(ticks, _event(start_tick=5, duration=3), baseline_window=3).market
    assert market.volatility == pytest.approx(statistics.stdev([0.01, -0.02, 0.03]), rel=1e-9)
    assert market.baseline_volatility == pytest.approx(statistics.stdev([0.004, -0.002, 0.001]), rel=1e-9)
    assert MIN_VOLATILITY_RETURNS == 2
    assert _one(ticks, _event(start_tick=5, duration=3), baseline_window=3) == _one(
        ticks, _event(start_tick=5, duration=3), baseline_window=3
    )


def test_baseline_volatility_needs_two_returns():
    ticks = _flat(20)
    assert _one(ticks, _event(start_tick=2)).market.baseline_volatility is None  # only ln(p1/p0): p0 unknown
    assert _one(ticks, _event(start_tick=3)).market.baseline_volatility is None  # only ln(p2/p1)
    assert _one(ticks, _event(start_tick=4)).market.baseline_volatility == 0.0


# --- volume -------------------------------------------------------------------------------


def test_volume_totals_per_tick_averages_and_ratio():
    ticks = [_tick(t, 100.0, volume=300.0 if 5 <= t <= 7 else 100.0) for t in range(1, 21)]
    market = _one(ticks, _event(start_tick=5, duration=3), baseline_window=4).market
    assert (market.volume, market.volume_per_tick) == (900.0, 300.0)
    assert market.baseline_volume_per_tick == 100.0
    assert market.volume_ratio == 3.0


def test_volume_ratio_is_unavailable_without_a_usable_baseline():
    quiet = [_tick(t, 100.0, volume=0.0 if t < 5 else 50.0) for t in range(1, 21)]
    market = _one(quiet, _event(start_tick=5)).market
    assert (market.baseline_volume_per_tick, market.volume_ratio) == (0.0, None)
    first = _one(_flat(20), _event(start_tick=1)).market
    assert (first.baseline_volume_per_tick, first.volume_ratio) == (None, None)
    truncated = _one(_flat(20), _event(start_tick=3), baseline_window=10).market
    assert truncated.baseline_volume_per_tick == 100.0  # ticks 1-2 only


# --- trading ------------------------------------------------------------------------------


def test_trader_fills_in_the_event_window():
    ticks = _flat(20)
    ticks[4] = _tick(5, 100.0, fills=[_fill("a", BUY, 10.0), _fill("b", SELL, 4.0)])
    ticks[5] = _tick(6, 100.0, fills=[_fill("a", BUY, 5.0)], whales=[WhaleTrade("w", "sell", 999.0, 0.9)])
    ticks[2] = _tick(3, 100.0, fills=[_fill("c", SELL, 1.0), _fill("c", SELL, 1.0)])  # baseline
    trading = _one(ticks, _event(start_tick=5, duration=3), baseline_window=4, trader_count=4).trading
    assert (trading.trade_count, trading.buy_volume, trading.sell_volume, trading.net_flow) == (3, 15.0, 4.0, 11.0)
    assert (trading.active_traders, trading.participation_rate) == (2, 0.5)
    assert trading.trades_per_tick == 1.0
    assert trading.baseline_trades_per_tick == 0.5
    assert _one(ticks, _event(start_tick=5, duration=3)).trading.participation_rate is None


def test_wash_legs_count_as_ordinary_trades_because_observers_cannot_tell():
    ticks = _flat(20)
    ticks[4] = _tick(5, 100.0, fills=[_fill("w", BUY, 50.0, wash=True), _fill("w", SELL, 50.0, wash=True)])
    trading = _one(ticks, _event(start_tick=5)).trading
    assert (trading.trade_count, trading.buy_volume, trading.sell_volume, trading.net_flow) == (2, 50.0, 50.0, 0.0)


def test_no_fills_gives_zero_activity_not_missing_data():
    trading = _one(_flat(20), _event()).trading
    assert (trading.trade_count, trading.net_flow, trading.active_traders, trading.trades_per_tick) == (0, 0.0, 0, 0.0)
    assert _one(_flat(20), _event()).pool is None  # random-walk ticks have no pool snapshots


# --- overlaps -----------------------------------------------------------------------------


def test_overlapping_events_are_flagged_with_each_other_and_measured_independently():
    a = _event("a", start_tick=5, duration=3, decay_ticks=2)   # live 5-9
    b = _event("b", start_tick=8, duration=3, decay_ticks=2)   # live 8-12
    c = _event("c", start_tick=20, duration=1, decay_ticks=0)  # live 20
    ticks = [_tick(t, 100.0, fills=[_fill("x", BUY, 1.0)]) for t in range(1, 25)]
    by_id = {o.ground_truth.event_id: o for o in analyze_events(ticks, [c, b, a])}
    assert by_id["a"].overlapping_event_ids == ("b",) and by_id["a"].overlapping
    assert by_id["b"].overlapping_event_ids == ("a",)
    assert by_id["c"].overlapping_event_ids == () and not by_id["c"].overlapping
    # Each window is measured whole: shared ticks count for both (no splitting or attribution).
    assert by_id["a"].trading.trade_count == 3 and by_id["b"].trading.trade_count == 3


def test_decay_counts_toward_overlap_and_earlier_events_are_listed():
    early = _event("early", start_tick=1, duration=1, decay_ticks=0)       # live 1 only
    fading = _event("fading", start_tick=2, duration=2, decay_ticks=6)     # live 2-9
    later = _event("later", start_tick=9, duration=1, decay_ticks=0)       # live 9
    by_id = {o.ground_truth.event_id: o for o in analyze_events(_flat(12), [early, fading, later])}
    assert by_id["early"].overlapping_event_ids == ()
    assert by_id["fading"].overlapping_event_ids == ("later",)
    assert by_id["later"].overlapping_event_ids == ("fading",)


def test_events_that_started_before_the_data_still_count_as_overlaps():
    ongoing = _event("ongoing", start_tick=2, duration=10)
    new = _event("new", start_tick=6, duration=2)
    ticks = [_tick(t, 100.0) for t in range(5, 15)]
    (observation,) = analyze_events(ticks, [ongoing, new])
    assert observation.ground_truth.event_id == "new"
    assert observation.overlapping_event_ids == ("ongoing",)


# --- determinism / purity -------------------------------------------------------------------


def test_same_input_same_report_and_inputs_untouched():
    ticks = _prices_from_log_returns(100.0, {t: 0.001 * ((t * 7) % 5 - 2) for t in range(2, 40)}, 40)
    events = [_event("a", start_tick=5), _event("b", start_tick=6), _event("c", start_tick=30)]
    ticks_before, events_before = list(ticks), list(events)
    first = analyze_events(ticks, events, trader_count=3, initial_price=100.0)
    assert analyze_events(ticks, events, trader_count=3, initial_price=100.0) == first
    assert analyze_events(tuple(reversed(ticks)), list(reversed(events)), trader_count=3, initial_price=100.0) == first
    assert ticks == ticks_before and events == events_before


# --- provenance -----------------------------------------------------------------------------


def test_provenance_marks_listed_events_random_and_the_rest_not():
    events = [_event("sched", start_tick=3), _event("rand", start_tick=6)]
    by_id = {o.ground_truth.event_id: o for o in analyze_events(_flat(20), events, random_event_ids=["rand", "gone"])}
    assert by_id["rand"].ground_truth.randomly_generated is True
    assert by_id["sched"].ground_truth.randomly_generated is False
    assert all(o.ground_truth.randomly_generated is False
               for o in analyze_events(_flat(20), events, random_event_ids=()))


def test_provenance_is_unknown_when_not_supplied_and_never_changes_metrics():
    events = [_event("a", start_tick=3), _event("b", start_tick=6)]
    plain = analyze_events(_flat(20), events)
    tagged = analyze_events(_flat(20), events, random_event_ids=["b"])
    assert all(o.ground_truth.randomly_generated is None for o in plain)
    for before, after in zip(plain, tagged):
        assert dataclasses.replace(after.ground_truth, randomly_generated=None) == before.ground_truth
        assert (after.market, after.trading, after.pool, after.overlapping_event_ids) == (
            before.market, before.trading, before.pool, before.overlapping_event_ids,
        )
