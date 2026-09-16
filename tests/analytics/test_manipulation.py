"""Manipulation analytics (Phase 9, Step 6).

Unit-style: hand-built ticks exercise identification, phase derivation,
wash aggregation, volume double-counting proofs and error cases in
isolation. ``test_manipulation_simulation.py`` runs the same analytics
against real simulator output.
"""

import dataclasses
from decimal import Decimal

import pytest

from crypto_simulator.analytics import analyze_market, analyze_traders
from crypto_simulator.analytics.manipulation import (
    COVERAGE_COMPLETE,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    ActivityComparison,
    ManipulationReport,
    PumpAndDumpSummary,
    WashSummary,
    analyze_manipulation,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.liquidity.pool import PoolState, SwapResult
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade

BUY, SELL = TradeAction.BUY, TradeAction.SELL


def _fill(trader, quantity, price=2.0, side=BUY, strategy="retail", reason="", requested=None,
         wash=False, notional=None):
    return TraderTrade(trader_id=trader, strategy=strategy, side=side,
                       requested_quantity=quantity if requested is None else requested, quantity=quantity,
                       price=price, notional=quantity * price if notional is None else notional,
                       reason=reason, wash=wash)


def _tick(number, fills=(), price=2.0, volume=None, pool=None):
    fills = tuple(fills)
    if volume is None:
        volume = sum(f.quantity for f in fills) + 100.0
    return SimulationTick(tick=number, timestamp="t", price=price, market_cap=0.0, volume=volume,
                          trader_trades=fills, pool_state=pool)


def _pool():
    return PoolState(**{f.name: (0 if f.name == "swap_count" else Decimal(1)) for f in dataclasses.fields(PoolState)})


def _pump(trader, quantity, phase, price=2.0, side=BUY):
    return _fill(trader, quantity, price=price, side=side, strategy="pump_and_dump", reason=phase)


def _wash_pair(trader, quantity, price=2.0, notional=None):
    """One wash round trip: a buy leg then a sell leg, as ``execute_wash``
    actually records them."""
    buy = _fill(trader, quantity, price=price, side=BUY, strategy="wash_trader",
               reason="wash trade: buy leg", wash=True, notional=notional)
    sell = _fill(trader, quantity, price=price, side=SELL, strategy="wash_trader",
                reason="wash trade: sell leg", wash=True, notional=notional)
    return buy, sell


# --- basic shape -----------------------------------------------------------------------------------


def test_empty_input_is_an_empty_report():
    report = analyze_manipulation([])
    assert report == ManipulationReport(
        ticks=0, pricing_mode=None, coverage=COVERAGE_NONE, total_market_volume=0.0, participant_volume=0.0,
        manipulation_volume=0.0, pump_and_dump_volume=0.0, wash_volume=0.0, manipulation_share_of_total=None,
        manipulation_share_of_participants=None, fill_count=0, buy_volume=0.0, sell_volume=0.0, notional=0.0,
        active_ticks=0, first_tick=None, last_tick=None, pump_and_dump=(),
        wash=WashSummary(0, 0.0, 0.0, 0.0, 0.0, 0, None, None, None),
        activity_comparison=ActivityComparison(0.0, 0.0, None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, None, None),
        pump_and_dump_strategy=None, wash_strategy=None,
    )


def test_no_manipulation_reports_no_coverage():
    ticks = [_tick(1, [_fill("retail", 10.0)])]
    report = analyze_manipulation(ticks)
    assert report.coverage == COVERAGE_NONE
    assert report.pump_and_dump == () and report.wash.fill_count == 0
    assert report.manipulation_volume == 0.0


def test_pump_only_reports_partial_coverage():
    ticks = [_tick(1, [_pump("p", 10.0, "accumulate")])]
    report = analyze_manipulation(ticks)
    assert report.coverage == COVERAGE_PARTIAL
    assert report.pump_and_dump_trader("p").accumulation_volume == 10.0


def test_wash_only_reports_partial_coverage():
    ticks = [_tick(1, _wash_pair("w", 5.0))]
    report = analyze_manipulation(ticks)
    assert report.coverage == COVERAGE_PARTIAL
    assert report.wash.fill_count == 2


def test_both_scenarios_report_complete_coverage():
    ticks = [_tick(1, [_pump("p", 10.0, "accumulate"), *_wash_pair("w", 5.0)])]
    report = analyze_manipulation(ticks)
    assert report.coverage == COVERAGE_COMPLETE


def test_multiple_manipulators_get_their_own_summaries():
    ticks = [_tick(1, [_pump("p1", 10.0, "accumulate"), _pump("p2", 20.0, "accumulate")])]
    report = analyze_manipulation(ticks)
    assert {p.trader_id for p in report.pump_and_dump} == {"p1", "p2"}
    assert report.pump_and_dump_trader("p1").accumulation_volume == 10.0
    assert report.pump_and_dump_trader("p2").accumulation_volume == 20.0


# --- volume --------------------------------------------------------------------------------------------


def test_total_manipulation_volume_and_top_level_shares():
    ticks = [_tick(1, [_fill("retail", 5.0), _pump("p", 10.0, "accumulate"), *_wash_pair("w", 3.0)], volume=200.0)]
    report = analyze_manipulation(ticks)
    assert report.pump_and_dump_volume == 10.0
    assert report.wash_volume == 6.0  # both legs
    assert report.manipulation_volume == 16.0
    market = analyze_market(ticks).volume_breakdown
    assert report.manipulation_share_of_total == pytest.approx(16.0 / market.total_volume)
    assert report.manipulation_share_of_participants == pytest.approx(10.0 / market.participant_volume)


def test_participant_share_never_exceeds_one_even_with_heavy_wash():
    ticks = [_tick(1, list(_wash_pair("w", 1000.0)) + [_fill("retail", 1.0)])]
    report = analyze_manipulation(ticks)
    assert report.manipulation_share_of_participants is not None
    assert 0.0 <= report.manipulation_share_of_participants <= 1.0
    assert 0.0 <= report.manipulation_share_of_total <= 1.0


def test_zero_market_volume_reports_no_share_rather_than_a_manufactured_ratio():
    ticks = [_tick(1, [], volume=0.0)]
    report = analyze_manipulation(ticks)
    assert report.total_market_volume == 0.0
    assert report.manipulation_share_of_total is None
    assert report.manipulation_share_of_participants is None


def test_wash_volume_is_never_double_counted_against_the_total_decomposition():
    """The explicit proof section 8 asks for: total volume equals the
    five already-disjoint categories added once each."""
    ticks = [
        _tick(1, [_fill("retail", 4.0), _pump("p", 6.0, "pump"), *_wash_pair("w", 2.0)], volume=50.0),
        _tick(2, [_fill("retail", 3.0, side=SELL), _pump("p", 5.0, "dump", side=SELL)], volume=40.0),
    ]
    market = analyze_market(ticks).volume_breakdown
    reconstructed = (market.background_volume + market.whale_volume + market.organic_volume
                     + market.manipulator_volume + market.wash_volume)
    assert reconstructed == pytest.approx(market.total_volume)
    report = analyze_manipulation(ticks)
    assert report.manipulation_volume == pytest.approx(market.manipulator_volume + market.wash_volume)
    assert report.pump_and_dump_volume == pytest.approx(market.manipulator_volume)
    assert report.wash_volume == pytest.approx(market.wash_volume)


# --- pump-and-dump ---------------------------------------------------------------------------------------


def test_phase_fill_and_volume_counts():
    ticks = [
        _tick(1, [_pump("p", 4.0, "accumulate")]),
        _tick(2, [_pump("p", 6.0, "accumulate")]),
        _tick(3, [_pump("p", 20.0, "pump")]),
        _tick(4, [_pump("p", 15.0, "dump", side=SELL)]),
    ]
    summary = analyze_manipulation(ticks).pump_and_dump_trader("p")
    assert (summary.accumulation_fills, summary.accumulation_volume) == (2, 10.0)
    assert (summary.pump_fills, summary.pump_volume) == (1, 20.0)
    assert (summary.dump_fills, summary.dump_volume) == (1, 15.0)
    assert summary.total_fills == 4 and summary.total_volume == 45.0


def test_phase_boundaries_and_duration():
    ticks = [
        _tick(1, [_pump("p", 1.0, "accumulate")]),
        _tick(2, [_pump("p", 1.0, "accumulate")]),
        _tick(3, [_pump("p", 1.0, "pump")]),
        _tick(4, [_pump("p", 1.0, "pump")]),
        _tick(5, [_pump("p", 1.0, "dump", side=SELL)]),
    ]
    summary = analyze_manipulation(ticks).pump_and_dump_trader("p")
    assert (summary.first_accumulation_tick, summary.last_accumulation_tick) == (1, 2)
    assert (summary.pump_start_tick, summary.pump_end_tick) == (3, 4)
    assert (summary.dump_start_tick, summary.dump_end_tick) == (5, 5)
    assert (summary.first_tick, summary.last_tick, summary.duration) == (1, 5, 5)


def test_price_path_return_and_drawdown_come_from_analyze_market():
    prices = {1: 100.0, 2: 110.0, 3: 130.0, 4: 90.0, 5: 95.0}
    ticks = [
        _tick(1, [_pump("p", 1.0, "accumulate")], price=prices[1]),
        _tick(2, [_pump("p", 1.0, "pump")], price=prices[2]),
        _tick(3, [_pump("p", 1.0, "pump")], price=prices[3]),
        _tick(4, [_pump("p", 1.0, "dump", side=SELL)], price=prices[4]),
        _tick(5, [_pump("p", 1.0, "dump", side=SELL)], price=prices[5]),
    ]
    summary = analyze_manipulation(ticks).pump_and_dump_trader("p")
    direct = analyze_market(ticks)
    assert summary.market == direct
    assert summary.market.high_price == 130.0 and summary.market.high_tick == 3
    assert summary.market.cumulative_return == pytest.approx(95.0 / 100.0 - 1.0)
    assert summary.market.max_drawdown == pytest.approx(1.0 - 90.0 / 130.0)
    assert summary.price_at_accumulation_start == 100.0
    assert summary.price_at_dump_start == 90.0


def test_an_incomplete_scenario_range_reports_only_the_observed_phases():
    """Only accumulation fills fall within the supplied ticks; pump and
    dump are simply absent, not guessed."""
    ticks = [_tick(1, [_pump("p", 5.0, "accumulate")]), _tick(2, [_pump("p", 5.0, "accumulate")])]
    summary = analyze_manipulation(ticks).pump_and_dump_trader("p")
    assert summary.pump_fills == 0 and summary.pump_start_tick is None
    assert summary.dump_fills == 0 and summary.dump_start_tick is None
    assert summary.first_tick == 1 and summary.last_tick == 2


# --- wash --------------------------------------------------------------------------------------------------


def test_wash_buy_and_sell_legs_are_split():
    ticks = [_tick(1, _wash_pair("w", 8.0))]
    wash = analyze_manipulation(ticks).wash
    assert wash.buy_volume == 8.0 and wash.sell_volume == 8.0
    assert wash.volume == 16.0 and wash.fill_count == 2


def test_a_lone_buy_leg_is_still_counted_on_its_own_side():
    lone_buy = _fill("w", 4.0, side=BUY, strategy="wash_trader", reason="wash trade: buy leg", wash=True)
    wash = analyze_manipulation([_tick(1, [lone_buy])]).wash
    assert wash.buy_volume == 4.0 and wash.sell_volume == 0.0


def test_wash_tick_count_and_average_per_active_tick():
    ticks = [_tick(1, _wash_pair("w", 4.0)), _tick(2, _wash_pair("w", 6.0)), _tick(3, [_fill("retail", 1.0)])]
    wash = analyze_manipulation(ticks).wash
    assert wash.active_ticks == 2
    assert wash.first_tick == 1 and wash.last_tick == 2
    assert wash.average_volume_per_active_tick == pytest.approx((8.0 + 12.0) / 2)


def test_wash_notional_sums_recorded_notional():
    ticks = [_tick(1, _wash_pair("w", 5.0, price=3.0))]
    wash = analyze_manipulation(ticks).wash
    assert wash.notional == pytest.approx(30.0)  # two legs at 5.0 * 3.0 each


def test_wash_in_amm_mode_is_still_aggregated_correctly():
    swap_buy = _fill("w", 5.0, side=BUY, strategy="wash_trader", reason="wash trade: buy leg", wash=True)
    swap_sell = _fill("w", 5.0, side=SELL, strategy="wash_trader", reason="wash trade: sell leg", wash=True)
    ticks = [_tick(1, [swap_buy, swap_sell], pool=_pool())]
    report = analyze_manipulation(ticks)
    assert report.pricing_mode == "amm"
    assert report.wash.volume == 10.0
    assert report.pump_and_dump == ()  # AMM has no whales, but wash trading is not whale-only


# --- identity ----------------------------------------------------------------------------------------------


def test_a_registered_manipulator_strategy_is_identified():
    ticks = [_tick(1, [_pump("p", 100.0, "accumulate")])]
    assert analyze_manipulation(ticks).pump_and_dump_volume == 100.0


def test_an_unregistered_strategy_is_never_treated_as_manipulation():
    huge = _fill("mystery", 1_000_000.0, strategy="totally_not_registered")
    report = analyze_manipulation([_tick(1, [huge], volume=2_000_000.0)])
    assert report.manipulation_volume == 0.0
    assert report.activity_comparison.organic_volume == 1_000_000.0


def test_a_large_organic_fill_is_never_mistaken_for_manipulation():
    """Section 9: identification is registry-based, never inferred from
    size, speed of return, or unusual volume."""
    huge_retail = _fill("whale_looking_retail", 500_000.0, strategy="retail")
    report = analyze_manipulation([_tick(1, [huge_retail], volume=600_000.0)])
    assert report.pump_and_dump == () and report.wash.fill_count == 0
    assert report.activity_comparison.organic_volume == 500_000.0


def test_the_same_trader_id_under_two_strategies_is_rejected():
    conflicting = [_fill("x", 1.0, strategy="pump_and_dump", reason="accumulate"),
                  _fill("x", 1.0, strategy="retail")]
    with pytest.raises(ValueError, match="two strategies"):
        analyze_manipulation([_tick(1, conflicting)])


# --- comparisons -------------------------------------------------------------------------------------------


def test_manipulation_vs_organic_activity_comparison():
    ticks = [
        _tick(1, [_fill("retail", 10.0, side=BUY), _fill("retail", 4.0, side=SELL),
                 _pump("p", 20.0, "accumulate", side=BUY), *_wash_pair("w", 5.0)], volume=200.0),
    ]
    comparison = analyze_manipulation(ticks).activity_comparison
    assert comparison.organic_buy_volume == 10.0 and comparison.organic_sell_volume == 4.0
    assert comparison.manipulation_buy_volume == 20.0 + 5.0  # pump buy + wash buy leg
    assert comparison.manipulation_sell_volume == 5.0  # wash sell leg
    assert comparison.manipulation_volume == pytest.approx(30.0)
    assert comparison.organic_volume == pytest.approx(14.0)
    assert comparison.manipulation_volume_share == pytest.approx(30.0 / 44.0)


def test_average_fill_size_comparison():
    ticks = [_tick(1, [_fill("retail", 10.0), _fill("retail", 20.0), _pump("p", 100.0, "accumulate")])]
    comparison = analyze_manipulation(ticks).activity_comparison
    assert comparison.organic_average_fill_size == pytest.approx(15.0)
    assert comparison.manipulation_average_fill_size == pytest.approx(100.0)


def test_active_ticks_are_counted_once_per_tick_not_per_fill():
    ticks = [_tick(1, [_pump("p", 1.0, "accumulate"), _pump("p", 1.0, "accumulate")])]
    comparison = analyze_manipulation(ticks).activity_comparison
    assert comparison.manipulation_active_ticks == 1


def test_an_empty_side_reports_zero_not_a_missing_value():
    ticks = [_tick(1, [_pump("p", 10.0, "accumulate")])]
    comparison = analyze_manipulation(ticks).activity_comparison
    assert comparison.organic_volume == 0.0
    assert comparison.organic_average_fill_size is None  # no organic fills at all


# --- missing / incomplete data -----------------------------------------------------------------------------


def test_partial_tick_range_still_analyses_what_is_present():
    ticks = [_tick(t, [_pump("p", 1.0, "pump")]) for t in (10, 11, 12)]
    summary = analyze_manipulation(ticks).pump_and_dump_trader("p")
    assert summary.accumulation_fills == 0 and summary.dump_fills == 0
    assert summary.pump_fills == 3


def test_a_nonfinite_price_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=float("nan"), market_cap=0.0, volume=0.0)
    with pytest.raises(ValueError):
        analyze_manipulation([bad])


def test_zero_volume_ticks_are_a_real_zero_not_a_gap():
    ticks = [_tick(1, [], volume=0.0), _tick(2, [], volume=0.0)]
    report = analyze_manipulation(ticks)
    assert report.total_market_volume == 0.0
    assert report.coverage == COVERAGE_NONE


def test_a_single_tick_scenario_reports_a_zero_return_not_a_missing_one():
    summary = analyze_manipulation([_tick(1, [_pump("p", 1.0, "accumulate")])]).pump_and_dump_trader("p")
    assert summary.market.cumulative_return == 0.0


# --- integrity -----------------------------------------------------------------------------------------------


def test_duplicate_tick_numbers_are_rejected():
    ticks = [_tick(1), _tick(1)]
    with pytest.raises(ValueError, match="duplicate tick"):
        analyze_manipulation(ticks)


def test_non_simulation_ticks_are_rejected():
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_manipulation([{"tick": 1}])


def test_the_report_and_its_nested_dataclasses_are_frozen():
    ticks = [_tick(1, [_pump("p", 5.0, "accumulate")])]
    report = analyze_manipulation(ticks)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.ticks = 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.pump_and_dump[0].accumulation_volume = 0.0
    assert isinstance(report.pump_and_dump[0], PumpAndDumpSummary)
    assert isinstance(report.wash, WashSummary)
    assert isinstance(report.activity_comparison, ActivityComparison)


def test_analysis_is_deterministic_and_order_independent():
    ticks = [_tick(1, [_pump("p", 5.0, "accumulate")]), _tick(2, _wash_pair("w", 3.0))]
    forward = analyze_manipulation(ticks)
    backward = analyze_manipulation(list(reversed(ticks)))
    assert forward == backward == analyze_manipulation(ticks)


def test_pump_and_dump_strategy_and_wash_strategy_are_analyze_traders_own():
    ticks = [_tick(1, [_pump("p", 5.0, "accumulate")]), _tick(2, _wash_pair("w", 3.0))]
    report = analyze_manipulation(ticks)
    direct = analyze_traders(ticks)
    assert report.pump_and_dump_strategy == direct.strategy("pump_and_dump")
    assert report.wash_strategy == direct.strategy("wash_trader")


def test_pnl_is_always_none_without_balances():
    ticks = [_tick(1, [_pump("p", 5.0, "accumulate")])]
    report = analyze_manipulation(ticks)
    assert report.pump_and_dump_strategy.pnl is None
