"""Trader analytics on hand-built records (Phase 9, Step 2).

Expected values are worked out by hand from the definitions in
``analytics/traders.py``: every record classified once (buy, sell, wash
leg, or a zero-quantity record that is not a fill), recorded quantities
and notionals taken as settlement recorded them, the CLI's equity/P&L
definition on supplied wallet balances, and exact AMM amounts from the
recorded swaps.
"""

import dataclasses
import math
from decimal import Decimal

import pytest

from crypto_simulator.analytics import StrategySummary, TraderReport, TraderSummary, analyze_traders
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.liquidity.pool import PoolState, SwapResult
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade

BUY, SELL = TradeAction.BUY, TradeAction.SELL


def _fill(trader, quantity, price=2.0, side=BUY, strategy="retail", requested=None, wash=False, swap=None,
          notional=None):
    return TraderTrade(trader_id=trader, strategy=strategy, side=side,
                       requested_quantity=quantity if requested is None else requested, quantity=quantity,
                       price=price, notional=quantity * price if notional is None else notional, swap=swap, wash=wash)


def _tick(number, fills=(), price=2.0, pool=None):
    return SimulationTick(tick=number, timestamp="t", price=price, market_cap=0.0, volume=0.0,
                          trader_trades=tuple(fills), pool_state=pool)


def _pool():
    return PoolState(**{f.name: (0 if f.name == "swap_count" else Decimal(1)) for f in dataclasses.fields(PoolState)})


def _swap(side, amount_in, fee, amount_out):
    one = Decimal(1)
    return SwapResult(side, Decimal(amount_in), Decimal(fee), Decimal(amount_in) - Decimal(fee), Decimal(amount_out),
                      one, one, one, Decimal(0), Decimal(0), Decimal("0.003"), one, one)


def _mixed_ticks():
    """Trader ``a``: two buys, one sell, a wash round trip and a zero-quantity record."""
    return [
        _tick(1, [_fill("a", 4.0, price=2.0), _fill("b", 1.0, strategy="momentum")]),
        _tick(2, [_fill("a", 2.0, price=3.0, side=SELL, requested=5.0),
                  _fill("a", 1.0, price=2.5, wash=True), _fill("a", 1.0, price=2.5, side=SELL, wash=True)]),
        _tick(4, [_fill("a", 3.0, price=4.0), _fill("a", 0.0, requested=6.0)]),
    ]


# --- classification, volume, notional, flows ----------------------------------------------------------


def test_every_record_is_classified_once():
    a = analyze_traders(_mixed_ticks()).trader("a")
    assert (a.records, a.fill_count, a.buy_count, a.sell_count, a.wash_leg_count) == (6, 5, 2, 1, 2)
    assert (a.buy_volume, a.sell_volume, a.wash_volume, a.total_volume) == (7.0, 2.0, 2.0, 11.0)
    assert a.total_volume == a.buy_volume + a.sell_volume + a.wash_volume  # wash counted exactly once
    assert (a.buy_notional, a.sell_notional, a.wash_notional) == (8.0 + 12.0, 6.0, 5.0)
    assert a.total_notional == 31.0 and a.vwap == 31.0 / 11.0  # every fill, wash legs included
    assert a.wash_share == 2.0 / 11.0


def test_flow_signs_follow_the_wallet():
    a = analyze_traders(_mixed_ticks()).trader("a")
    assert a.net_coin_flow == (4.0 + 1.0 + 3.0) - (2.0 + 1.0)   # bought - sold, wash legs included
    assert a.net_cash_flow == (6.0 + 2.5) - (8.0 + 2.5 + 12.0)  # sells receive cash, buys pay it


def test_requested_filled_and_fill_ratio():
    a = analyze_traders(_mixed_ticks()).trader("a")
    # Requested: 4 + 5 + 1 + 1 + 3 + 6 (the zero-quantity record asked for 6 and got nothing).
    assert a.requested_volume == 20.0 and a.fill_ratio == 11.0 / 20.0


def test_activity_ticks_and_sizes_count_fills_not_records():
    a = analyze_traders(_mixed_ticks()).trader("a")
    assert (a.active_ticks, a.first_fill_tick, a.last_fill_tick) == (3, 1, 4)
    assert a.average_fill_size == 11.0 / 5


def test_a_zero_quantity_record_is_not_a_fill_or_activity():
    report = analyze_traders([_tick(1, [_fill("z", 0.0, requested=3.0)])])
    z = report.trader("z")
    assert z.records == 1 and z.fill_count == 0 and not z.active and z.active_ticks == 0
    assert z.first_fill_tick is None and z.vwap is None and z.average_fill_size is None
    assert z.requested_volume == 3.0 and z.fill_ratio == 0.0
    assert report.active_traders == 0 and report.population == 1


def test_buy_only_sell_only_and_wash_only_traders():
    ticks = [_tick(1, [_fill("buyer", 3.0), _fill("seller", 2.0, side=SELL),
                       _fill("washer", 5.0, wash=True, strategy="wash_trader"),
                       _fill("washer", 5.0, side=SELL, wash=True, strategy="wash_trader")])]
    report = analyze_traders(ticks)
    buyer, seller, washer = report.trader("buyer"), report.trader("seller"), report.trader("washer")
    assert buyer.net_coin_flow == 3.0 and buyer.net_cash_flow == -6.0 and buyer.sell_count == 0
    assert seller.net_coin_flow == -2.0 and seller.net_cash_flow == 4.0 and seller.buy_count == 0
    assert (washer.buy_count, washer.sell_count, washer.wash_leg_count, washer.wash_share) == (0, 0, 2, 1.0)
    assert washer.net_coin_flow == 0.0 and washer.total_volume == 10.0


def test_missing_and_zero_requested_volume():
    missing = analyze_traders([_tick(1, [dataclasses.replace(_fill("a", 2.0), requested_quantity=None)])]).trader("a")
    assert missing.requested_volume is None and missing.fill_ratio is None
    zero = analyze_traders([_tick(1, [_fill("a", 2.0, requested=0.0)])]).trader("a")
    assert zero.requested_volume == 0.0 and zero.fill_ratio is None


def test_partial_fills_show_in_the_fill_ratio():
    a = analyze_traders([_tick(1, [_fill("a", 3.0, requested=10.0)]), _tick(2, [_fill("a", 5.0, requested=5.0)])]).trader("a")
    assert a.fill_ratio == 8.0 / 15.0


# --- AMM ---------------------------------------------------------------------------------------------------


def test_amm_exact_flows_and_fees_come_from_the_recorded_swaps():
    buy = _swap("buy", "10.5", "0.0315", "4.2")
    sell = _swap("sell", "1.25", "0.00375", "3.1")
    ticks = [_tick(1, [_fill("a", 4.2, notional=10.5, swap=buy)], pool=_pool()),
             _tick(2, [_fill("a", 1.25, side=SELL, notional=3.1, swap=sell)], pool=_pool())]
    report = analyze_traders(ticks)
    a = report.trader("a")
    assert report.pricing_mode == "amm"
    assert a.exact_cash_flow == Decimal("3.1") - Decimal("10.5")
    assert a.exact_coin_flow == Decimal("4.2") - Decimal("1.25")
    assert (a.fees_paid_cash, a.fees_paid_coins) == (Decimal("0.0315"), Decimal("0.00375"))
    assert (report.fees_paid_cash, report.fees_paid_coins) == (Decimal("0.0315"), Decimal("0.00375"))
    # The fee is inside the recorded amounts, never charged again.
    assert a.net_cash_flow == 3.1 - 10.5 and a.net_coin_flow == 4.2 - 1.25


def test_random_walk_has_no_amm_figures():
    a = analyze_traders(_mixed_ticks()).trader("a")
    assert a.fees_paid_cash is a.fees_paid_coins is a.exact_cash_flow is a.exact_coin_flow is None


def test_an_amm_trader_without_swaps_paid_nothing():
    report = analyze_traders([_tick(1, pool=_pool())], start_balances={"idle": (5.0, 1.0)})
    idle = report.trader("idle")
    assert idle.fees_paid_cash == idle.exact_cash_flow == Decimal(0)


def test_mixing_amm_and_random_walk_ticks_is_rejected():
    with pytest.raises(ValueError, match="mix AMM and random-walk"):
        analyze_traders([_tick(1, pool=_pool()), _tick(2)])


# --- balances, equity and P&L --------------------------------------------------------------------------


def test_equity_and_pnl_follow_the_cli_definition():
    ticks = [_tick(1, [_fill("a", 2.0)], price=2.0), _tick(2, [], price=5.0)]
    report = analyze_traders(ticks, start_balances={"a": (10.0, 1.0)}, end_balances={"a": (6.0, 3.0)},
                             initial_price=1.5)
    a = report.trader("a")
    assert (a.start_cash, a.start_coins, a.end_cash, a.end_coins) == (10.0, 1.0, 6.0, 3.0)
    assert a.start_equity == 10.0 + 1.0 * 1.5 and a.end_equity == 6.0 + 3.0 * 5.0  # final tick's price
    assert a.pnl == a.end_equity - a.start_equity and a.equity_return == a.pnl / a.start_equity
    assert report.final_price == 5.0 and report.pnl == a.pnl and report.equity_return == a.equity_return


def test_missing_balances_or_initial_price_leave_equity_undefined():
    ticks = [_tick(1, [_fill("a", 2.0)])]
    none = analyze_traders(ticks).trader("a")
    assert none.start_equity is none.end_equity is none.pnl is none.equity_return is None
    no_price = analyze_traders(ticks, start_balances={"a": (1.0, 1.0)}, end_balances={"a": (1.0, 1.0)}).trader("a")
    assert no_price.start_equity is None and no_price.end_equity == 1.0 + 1.0 * 2.0 and no_price.pnl is None
    no_ticks = analyze_traders([], start_balances={"a": (1.0, 0.0)}, end_balances={"a": (1.0, 0.0)}, initial_price=1.0)
    assert no_ticks.final_price is None and no_ticks.trader("a").end_equity is None


def test_zero_starting_equity_has_no_return():
    a = analyze_traders([_tick(1)], start_balances={"a": (0.0, 0.0)}, end_balances={"a": (1.0, 0.0)},
                        initial_price=1.0).trader("a")
    assert a.pnl == 1.0 and a.equity_return is None


@pytest.mark.parametrize("balances, message", [
    ([("a", (1.0, 1.0))], "must be a mapping"),
    ({"a": (1.0,)}, r"\(cash, coins\) pair"),
    ({"a": 5.0}, r"\(cash, coins\) pair"),
    ({"a": (-1.0, 0.0)}, "cash must be a finite number >= 0"),
    ({"a": (1.0, math.nan)}, "coins must be a finite number >= 0"),
    ({"a": (True, 0.0)}, "cash must be"),
    ({"": (1.0, 1.0)}, "non-empty trader id"),
    ({3: (1.0, 1.0)}, "non-empty trader id"),
])
def test_malformed_balances_are_rejected(balances, message):
    with pytest.raises(ValueError, match=message):
        analyze_traders([_tick(1, [_fill("a", 1.0)])], start_balances=balances)


def test_balances_must_cover_every_reported_trader():
    with pytest.raises(ValueError, match="end_balances has no balance for trader id"):
        analyze_traders([_tick(1, [_fill("a", 1.0), _fill("b", 1.0)])], end_balances={"a": (1.0, 1.0)})


# --- population, trader ids and strategies -------------------------------------------------------------


def test_traders_known_only_from_balances_are_inactive_and_unlabelled():
    report = analyze_traders(_mixed_ticks(), start_balances={"a": (1.0, 1.0), "b": (1.0, 1.0), "idle": (9.0, 0.0)},
                             initial_price=2.0)
    idle = report.trader("idle")
    assert idle.strategy is None and idle.is_manipulator is None and not idle.active and idle.records == 0
    assert (report.population, report.active_traders, report.participation_rate) == (3, 2, 2 / 3)
    assert [s.strategy for s in report.strategies] == ["momentum", "retail", None]


def test_trader_ids_select_without_reordering():
    report = analyze_traders(_mixed_ticks(), trader_ids=("b", "a"))
    assert [t.trader_id for t in report.traders] == ["a", "b"] and report.population == 2
    only_a = analyze_traders(_mixed_ticks(), trader_ids=["a"])
    assert [t.trader_id for t in only_a.traders] == ["a"] and only_a.fill_count == 5


@pytest.mark.parametrize("ids, message", [
    (["a", "a"], "repeats"), (["ghost"], "no records or balances"), ("a", "list or tuple"), ([""], "non-empty"),
])
def test_invalid_trader_ids_are_rejected(ids, message):
    with pytest.raises(ValueError, match=message):
        analyze_traders(_mixed_ticks(), trader_ids=ids)


def test_trader_ids_are_not_mutated():
    ids = ["b", "a"]
    analyze_traders(_mixed_ticks(), trader_ids=ids)
    assert ids == ["b", "a"]


def test_strategy_groups_sum_their_members():
    ticks = [_tick(1, [_fill("m1", 2.0, strategy="momentum"), _fill("m2", 3.0, price=4.0, strategy="momentum"),
                       _fill("m3", 0.0, strategy="momentum", requested=1.0),
                       _fill("p", 5.0, strategy="pump_and_dump")])]
    report = analyze_traders(ticks)
    momentum = report.strategy("momentum")
    assert (momentum.trader_count, momentum.active_trader_count, momentum.participation) == (3, 2, 2 / 3)
    assert momentum.total_volume == 5.0 and momentum.total_notional == 4.0 + 12.0 and momentum.vwap == 16.0 / 5.0
    assert momentum.requested_volume == 6.0 and momentum.fill_ratio == 5.0 / 6.0 and momentum.average_fill_size == 2.5
    assert momentum.is_manipulation_strategy is False
    assert report.strategy("pump_and_dump").is_manipulation_strategy is True
    assert report.trader("p").is_manipulator is True and report.trader("m1").is_manipulator is False


def test_one_trader_under_two_strategies_is_rejected():
    with pytest.raises(ValueError, match="two strategies"):
        analyze_traders([_tick(1, [_fill("a", 1.0, strategy="retail"), _fill("a", 1.0, strategy="momentum")])])


def test_report_totals_are_the_sum_of_the_traders():
    report = analyze_traders(_mixed_ticks())
    assert report.fill_count == 6 and report.total_volume == 12.0 == report.filled_volume
    assert report.buy_volume == 8.0 and report.sell_volume == 2.0 and report.wash_volume == 2.0
    assert report.net_coin_flow == math.fsum(t.net_coin_flow for t in report.traders)
    assert report.vwap == report.total_notional / report.total_volume


# --- empty inputs, ordering, validation --------------------------------------------------------------------


def test_empty_ticks():
    report = analyze_traders([])
    assert (report.ticks, report.population, report.active_traders, report.fill_count) == (0, 0, 0, 0)
    assert report.traders == () and report.strategies == ()
    assert report.participation_rate is None and report.vwap is None and report.pnl is None
    assert report.pricing_mode is None and report.final_price is None


def test_ticks_without_trader_trades():
    report = analyze_traders([_tick(1), _tick(2, price=3.0)])
    assert report.population == 0 and report.final_price == 3.0


def test_one_tick_one_trader():
    report = analyze_traders([_tick(1, [_fill("solo", 2.0)])])
    assert report.population == 1 and report.trader("solo").active_ticks == 1


def test_input_order_gaps_and_constant_prices():
    ticks = _mixed_ticks()
    assert analyze_traders(list(reversed(ticks))) == analyze_traders(ticks)
    gap = analyze_traders([_tick(1, [_fill("a", 1.0)]), _tick(9, [_fill("a", 1.0)])]).trader("a")
    assert gap.active_ticks == 2 and gap.last_fill_tick == 9


def test_duplicate_ticks_and_bad_prices_are_rejected():
    with pytest.raises(ValueError, match="duplicate tick 1"):
        analyze_traders([_tick(1), _tick(1)])
    with pytest.raises(ValueError, match="invalid price"):
        analyze_traders([_tick(1, price=0.0)])
    with pytest.raises(ValueError, match="initial_price"):
        analyze_traders([_tick(1)], initial_price=-1.0)


def test_the_results_are_frozen():
    report = analyze_traders(_mixed_ticks())
    for value, field in ((report, "ticks"), (report.traders[0], "fill_count"), (report.strategies[0], "fill_count")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, field, 0)
    assert isinstance(report, TraderReport) and isinstance(report.traders[0], TraderSummary)
    assert isinstance(report.strategies[0], StrategySummary) and isinstance(report.traders, tuple)
