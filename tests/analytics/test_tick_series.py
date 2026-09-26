"""The tick-level visualization model (Phase 20, Step 3).

Hand-built ticks check each frozen field rule (returns without bridging,
the single-category volume split, explicit population, None semantics per
mode); simulated runs check the model against the report built from the
same ticks, so the model can never drift from the analytics' definitions.
"""

import copy
import dataclasses
import math
import re
from decimal import Decimal
from pathlib import Path

import pytest

from crypto_simulator.analytics import build_report
from crypto_simulator.analytics import tick_series as tick_series_module
from crypto_simulator.analytics._series import log_returns, simple_returns
from crypto_simulator.analytics.tick_series import (
    CLASS_COLUMNS,
    COLUMNS,
    ClassSeries,
    LiveEvent,
    TickSeries,
    build_tick_series,
)
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import SimulationTick, organic_breadth, organic_crowd_flow
from crypto_simulator.core.events.engine import EventState, EventStatus
from crypto_simulator.core.events.event import EventPhase
from crypto_simulator.core.liquidity.pool import PoolState, SwapResult
from crypto_simulator.core.psychology.state import PsychologyState
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade
from crypto_simulator.core.whale import WhaleTrade
from crypto_simulator.services.coin_simulation import build_coin_simulator

SUPPLY = 1_000.0
POP = {"retail": 2, "momentum": 1}

BUY, SELL = TradeAction.BUY, TradeAction.SELL


def _tick(number, price, volume=0.0, whales=(), trades=(), pool=None, events=None, psychology=None):
    return SimulationTick(tick=number, timestamp="t", price=price, market_cap=price * SUPPLY, volume=volume,
                          whale_trades=tuple(whales), trader_trades=tuple(trades), pool_state=pool,
                          event_state=events, psychology=psychology)


def _fill(trader_id, strategy, quantity, side=BUY, wash=False, swap=None, reason=""):
    return TraderTrade(trader_id=trader_id, strategy=strategy, side=side, requested_quantity=quantity,
                       quantity=quantity, price=2.0, notional=quantity * 2.0, reason=reason, swap=swap, wash=wash)


def _pool(coins="100", cash="200", swaps=0):
    return PoolState(coin_reserve=Decimal(coins), cash_reserve=Decimal(cash),
                     invariant=Decimal(coins) * Decimal(cash), spot_price=Decimal(cash) / Decimal(coins),
                     fee_rate=Decimal("0.003"), fees_collected_coins=Decimal("0.5"),
                     fees_collected_cash=Decimal("1.25"), total_shares=Decimal(1), swap_count=swaps)


def _swap(impact):
    one = Decimal(1)
    return SwapResult("buy", one, Decimal("0.003"), one, one, one, one, one, Decimal(impact), Decimal(0),
                      Decimal("0.003"), one, one)


def _build(ticks, population=POP, whale_count=0):
    return build_tick_series(ticks, total_supply=SUPPLY, population=population, whale_count=whale_count)


# --- shape --------------------------------------------------------------------------------------------


def test_an_empty_run_has_every_column_and_no_rows():
    series = _build([])
    assert series.rows == 0
    assert series.columns == COLUMNS
    assert all(series.data[name] == () for name in COLUMNS)
    assert set(series.classes) == {"momentum", "retail"}
    assert all(getattr(series.classes["retail"], field) == () for field in CLASS_COLUMNS)


def test_column_names_are_fixed_snake_case_and_unique():
    assert len(set(COLUMNS)) == len(COLUMNS)
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in (*COLUMNS, *CLASS_COLUMNS))
    assert COLUMNS[:6] == ("tick", "price", "market_cap", "volume", "simple_return", "log_return")
    assert CLASS_COLUMNS == tuple(f.name for f in dataclasses.fields(ClassSeries))


def test_a_single_tick_copies_the_market_fields_and_has_no_return():
    series = _build([_tick(7, 2.5, volume=3.0)])
    assert series.rows == 1
    assert series.data["tick"] == (7,)
    assert series.data["price"] == (2.5,)
    assert series.data["market_cap"] == (2500.0,)
    assert series.data["volume"] == (3.0,)
    assert series.data["simple_return"] == (None,)
    assert series.data["log_return"] == (None,)


def test_returns_follow_the_series_definitions_and_never_bridge_a_gap():
    ticks = [_tick(1, 2.0), _tick(2, 2.2), _tick(3, 1.98), _tick(5, 2.5), _tick(6, 2.4)]
    series = _build(ticks)
    assert series.data["tick"] == (1, 2, 3, 5, 6)
    simple, log = series.data["simple_return"], series.data["log_return"]
    assert simple[0] is None and simple[3] is None  # first row, and the row after the gap
    assert log[0] is None and log[3] is None
    path = [(t.tick, t.price) for t in ticks]
    assert [v for v in simple if v is not None] == simple_returns(path)
    assert [v for v in log if v is not None] == log_returns(path)


# --- volume -------------------------------------------------------------------------------------------


def test_every_recorded_quantity_lands_in_exactly_one_volume_category():
    trades = [
        _fill("r1", "retail", 4.0),
        _fill("m1", "momentum", 1.5, side=SELL),
        _fill("w1", "wash_trader", 2.0, wash=True),
        _fill("w1", "wash_trader", 2.0, side=SELL, wash=True),
        _fill("p1", "pump_and_dump", 3.0, reason="pump"),
    ]
    whales = [WhaleTrade("wh", "buy", 5.0, 1.01), WhaleTrade("wh", "sell", 0.0, 1.0)]
    population = {**POP, "wash_trader": 1, "pump_and_dump": 1}
    series = _build([_tick(1, 2.0, volume=30.0, whales=whales, trades=trades)], population, whale_count=1)
    row = {name: series.data[name][0] for name in COLUMNS}
    assert row["organic_volume"] == 5.5
    assert row["manipulator_volume"] == 3.0
    assert row["wash_volume"] == 4.0
    assert row["whale_volume"] == 5.0
    assert row["background_volume"] == 30.0 - math.fsum([5.0, 0.0, 4.0, 1.5, 2.0, 2.0, 3.0])
    assert (row["organic_fills"], row["manipulator_fills"], row["wash_legs"]) == (2, 1, 2)
    assert (row["whale_fills"], row["zero_quantity_whale_trades"]) == (1, 1)
    assert (row["whale_buy_volume"], row["whale_sell_volume"]) == (5.0, 0.0)
    assert (row["whale_buy_trades"], row["whale_sell_trades"]) == (1, 0)
    assert row["pump_pump_volume"] == 3.0
    assert (row["pump_accumulate_volume"], row["pump_dump_volume"]) == (0.0, 0.0)


def test_a_wash_only_tick_counts_only_wash():
    trades = [_fill("w1", "wash_trader", 2.0, wash=True), _fill("w1", "wash_trader", 2.0, side=SELL, wash=True)]
    series = _build([_tick(1, 2.0, volume=4.0, trades=trades)], {**POP, "wash_trader": 1})
    assert series.data["wash_volume"] == (4.0,)
    assert series.data["wash_legs"] == (2,)
    assert series.data["organic_volume"] == (0.0,)
    assert series.data["manipulator_fills"] == (0,)
    assert series.data["organic_crowd_flow"] == (0.0,)
    assert (series.data["organic_net_buyers"], series.data["organic_net_sellers"]) == ((0,), (0,))
    assert series.data["background_volume"] == (0.0,)


def test_a_zero_quantity_whale_trade_is_a_record_not_a_fill():
    series = _build([_tick(1, 2.0, whales=[WhaleTrade("wh", "sell", 0.0, 1.0)])], whale_count=1)
    assert series.data["whale_fills"] == (0,)
    assert series.data["zero_quantity_whale_trades"] == (1,)
    assert series.data["whale_sell_trades"] == (0,)
    assert series.data["whale_volume"] == (0.0,)


# --- population ---------------------------------------------------------------------------------------


def test_a_class_in_the_run_with_no_fills_has_true_zeros():
    series = _build([_tick(1, 2.0, trades=[_fill("r1", "retail", 1.0)]), _tick(2, 2.0)])
    momentum = series.classes["momentum"]
    assert momentum == ClassSeries((0, 0), (0, 0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0, 0))


def test_a_class_not_in_the_run_has_no_key():
    series = _build([_tick(1, 2.0, trades=[_fill("r1", "retail", 1.0)])], {"retail": 1})
    assert set(series.classes) == {"retail"}


def test_class_presence_comes_from_the_population_never_from_fills():
    series = _build([_tick(1, 2.0)], {"retail": 1, "dip_buyer": 3})
    assert list(series.classes) == ["dip_buyer", "retail"]
    assert dict(series.population) == {"dip_buyer": 3, "retail": 1}


def test_class_fields_count_fills_volumes_and_distinct_traders():
    trades = [
        _fill("r1", "retail", 2.0),
        _fill("r1", "retail", 1.0),
        _fill("r2", "retail", 0.5, side=SELL),
        _fill("m1", "momentum", 3.0, side=SELL),
    ]
    retail = _build([_tick(1, 2.0, trades=trades)]).classes["retail"]
    assert (retail.buy_fills, retail.sell_fills) == ((2,), (1,))
    assert (retail.buy_volume, retail.sell_volume, retail.net_coin_flow) == ((3.0,), (0.5,), (2.5,))
    assert retail.filled_traders == (2,)


def test_manipulation_and_wash_fills_never_enter_a_class():
    trades = [_fill("w1", "wash_trader", 2.0, wash=True), _fill("p1", "pump_and_dump", 1.0, reason="accumulate")]
    series = _build([_tick(1, 2.0, trades=trades)], {**POP, "wash_trader": 1, "pump_and_dump": 1})
    assert all(sum(getattr(c, "buy_fills")) == 0 for c in series.classes.values())
    assert "wash_trader" not in series.classes and "pump_and_dump" not in series.classes
    assert series.data["pump_accumulate_volume"] == (1.0,)


def test_whale_and_pump_fields_are_none_when_those_participants_are_absent():
    series = _build([_tick(1, 2.0, trades=[_fill("r1", "retail", 1.0)])])
    for name in ("whale_volume", "whale_fills", "zero_quantity_whale_trades", "whale_buy_volume",
                 "whale_sell_volume", "whale_buy_trades", "whale_sell_trades",
                 "pump_accumulate_volume", "pump_pump_volume", "pump_dump_volume"):
        assert series.data[name] == (None,), name
    assert series.data["background_volume"] == (-1.0,)  # RW residual is never clamped


@pytest.mark.parametrize(
    "population, whale_count, ticks, message",
    [
        ({"retail": 1}, 0, [_tick(1, 2.0, trades=[_fill("m1", "momentum", 1.0)])], "not in the population"),
        ({"retail": 1}, 0, [_tick(1, 2.0, whales=[WhaleTrade("wh", "buy", 1.0, 1.0)])], "no whales"),
        ({"nobody": 1}, 0, [], "unknown strategy"),
        ({"retail": 0}, 0, [], "must be an int > 0"),
        ({"retail": 1}, -1, [], "whale_count"),
        ({"retail": 1}, 0, [_tick(1, 2.0), _tick(2, 2.0, pool=_pool())], "mix AMM"),
    ],
)
def test_inconsistent_inputs_are_rejected_rather_than_guessed(population, whale_count, ticks, message):
    with pytest.raises(ValueError, match=message):
        _build(ticks, population, whale_count)


# --- modes, events, psychology --------------------------------------------------------------------------


def test_rw_has_no_pool_fields():
    series = _build([_tick(1, 2.0)])
    for name in COLUMNS:
        if name.startswith("pool_"):
            assert series.data[name] == (None,), name


def test_amm_pool_fields_equal_the_recorded_pool_state():
    pool = _pool("100", "250", swaps=7)
    trades = [_fill("r1", "retail", 1.0, swap=_swap("0.02")), _fill("m1", "momentum", 1.0, swap=_swap("-0.05"))]
    series = _build([_tick(1, 2.5, volume=2.0, trades=trades, pool=pool), _tick(2, 2.5, pool=pool)], whale_count=2)
    first = {name: series.data[name][0] for name in COLUMNS}
    assert first["pool_coin_reserve"] == float(pool.coin_reserve)
    assert first["pool_cash_reserve"] == float(pool.cash_reserve)
    assert first["pool_spot_price"] == float(pool.spot_price)
    assert first["pool_invariant"] == float(pool.invariant)
    assert first["pool_fees_collected_coins"] == float(pool.fees_collected_coins)
    assert first["pool_fees_collected_cash"] == float(pool.fees_collected_cash)
    assert first["pool_swap_count"] == 7
    assert first["pool_swaps"] == 2
    assert first["pool_max_abs_price_impact"] == 0.05
    assert series.data["pool_max_abs_price_impact"][1] is None  # no swap that tick
    # AMM has no whales and no synthetic background, whatever whale_count says.
    assert first["whale_volume"] is None and first["background_volume"] is None


def test_event_columns_are_the_recorded_event_state():
    live = EventStatus(event_id="e1", category="hack", phase=EventPhase.ACTIVE, intensity=0.8)
    ticks = [
        _tick(1, 2.0, events=EventState(tick=1, sentiment=-0.4, volatility_multiplier=1.5,
                                        attention_multiplier=2.0, events=(live,))),
        _tick(2, 2.0, events=EventState(tick=2)),
        _tick(3, 2.0),
    ]
    data = _build(ticks).data
    assert data["event_sentiment"] == (-0.4, 0.0, None)
    assert data["event_volatility_multiplier"] == (1.5, 1.0, None)
    assert data["event_attention_multiplier"] == (2.0, 1.0, None)
    assert data["event_live"] == ((LiveEvent("e1", "hack", EventPhase.ACTIVE, 0.8),), (), None)


def test_psychology_columns_are_none_when_off_and_recorded_when_on():
    state = PsychologyState(fear=0.1, fomo=0.2, conviction=0.3, uncertainty=0.4)
    data = _build([_tick(1, 2.0, psychology=state), _tick(2, 2.0)]).data
    assert (data["fear"], data["fomo"], data["conviction"], data["uncertainty"]) == (
        (0.1, None), (0.2, None), (0.3, None), (0.4, None))


# --- organic crowd observables ------------------------------------------------------------------------


def test_crowd_observables_are_the_simulator_functions_with_disambiguating_counts():
    trades = [
        _fill("r1", "retail", 3.0),
        _fill("r1", "retail", 1.0, side=SELL),  # r1 nets +2: a buyer
        _fill("r2", "retail", 1.0, side=SELL),
        _fill("m1", "momentum", 2.0),
        _fill("m1", "momentum", 2.0, side=SELL),  # m1 nets to zero: neither side
    ]
    ticks = [_tick(1, 2.0, trades=trades), _tick(2, 2.0)]
    data = _build(ticks).data
    assert data["organic_crowd_flow"] == tuple(organic_crowd_flow(t.trader_trades, SUPPLY) for t in ticks)
    assert data["organic_breadth"] == tuple(organic_breadth(t.trader_trades) for t in ticks)
    assert (data["organic_net_buyers"], data["organic_net_sellers"]) == ((1, 0), (1, 0))
    assert data["organic_breadth"] == (0.0, 0.0)  # balanced, then nobody: the counts tell them apart


# --- determinism, purity, vocabulary ------------------------------------------------------------------


def _mixed_ticks():
    live = EventStatus(event_id="e1", category="hack", phase=EventPhase.DECAYING, intensity=0.3)
    return [
        _tick(1, 2.0, volume=9.0, whales=[WhaleTrade("wh", "buy", 2.0, 1.01)],
              trades=[_fill("r1", "retail", 1.0), _fill("m1", "momentum", 2.0, side=SELL)],
              events=EventState(tick=1, events=(live,)), psychology=PsychologyState(fear=0.5)),
        _tick(2, 2.1, volume=1.0, trades=[_fill("r2", "retail", 0.5)]),
    ]


def test_the_same_input_always_gives_the_same_series():
    ticks = _mixed_ticks()
    first, second = _build(ticks, whale_count=1), _build(ticks, whale_count=1)
    assert first == second


def test_building_does_not_mutate_the_ticks():
    ticks = _mixed_ticks()
    before = copy.deepcopy(ticks)
    _build(ticks, whale_count=1)
    assert ticks == before


def test_the_module_draws_no_randomness_and_reads_no_clock():
    source = Path(tick_series_module.__file__).read_text()
    for forbidden in ("import random", "from random", "datetime", "time.", "numpy.random"):
        assert forbidden not in source


FORBIDDEN_WORDS = ("herding", "herd", "influence", "contagion", "propagat", "cascade", "caused", "effect of")


def test_no_causal_or_behavioral_interpretation_words():
    source = Path(tick_series_module.__file__).read_text().lower()
    for word in FORBIDDEN_WORDS:
        assert word not in source, word


# --- against the report of a simulated run -----------------------------------------------------------

CASES = [
    dict(pricing_mode="random_walk"),
    dict(pricing_mode="random_walk", psychology=True, scenario="pump_and_dump"),
    dict(pricing_mode="random_walk", scenario="wash_trading", include_whales=False),
    dict(pricing_mode="amm", include_whales=False, psychology=True),
    dict(pricing_mode="amm", include_whales=False, scenario="wash_trading"),
    dict(pricing_mode="amm", include_whales=False, scenario="pump_and_dump"),
]
TICKS = 60


def _simulate(case):
    sim = build_coin_simulator(get_settings(), **case)
    population: dict[str, int] = {}
    for trader in sim.traders:
        population[trader.strategy_name] = population.get(trader.strategy_name, 0) + 1
    balances = lambda: {t.trader_id: (t.wallet.cash, t.wallet.coins) for t in sim.traders}  # noqa: E731
    start = balances()
    ticks = sim.run(TICKS)
    series = build_tick_series(ticks, total_supply=sim.coin.initial_supply, population=population,
                               whale_count=len(sim.whales))
    report = build_report(ticks, initial_price=sim.coin.starting_price, total_supply=sim.coin.initial_supply,
                          start_balances=start, end_balances=balances())
    return sim, ticks, series, report


@pytest.fixture(scope="module", params=CASES, ids=lambda c: "-".join(f"{k}={v}" for k, v in c.items()))
def run(request):
    return _simulate(request.param)


def _close(a, b, rel=1e-9):
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-9)


def test_v1_v2_rows_and_market_fields_match_the_ticks(run):
    _, ticks, series, _ = run
    assert series.rows == len(ticks) == TICKS
    assert series.data["tick"] == tuple(t.tick for t in ticks)
    assert series.data["price"] == tuple(t.price for t in ticks)
    assert series.data["market_cap"] == tuple(t.market_cap for t in ticks)
    assert series.data["volume"] == tuple(t.volume for t in ticks)
    assert all(len(values) == series.rows for values in series.data.values())


def test_v3_volume_reconciles_per_tick_and_with_the_report(run):
    sim, ticks, series, report = run
    data, breakdown = series.data, report.market.volume_breakdown
    amm = sim.pricing_mode.value == "amm"
    for i, tick in enumerate(ticks):
        parts = [data["organic_volume"][i], data["manipulator_volume"][i], data["wash_volume"][i]]
        if amm:
            assert _close(math.fsum(parts), tick.volume, 1e-12)
        else:
            parts += [data["whale_volume"][i] or 0.0, data["background_volume"][i]]
            assert _close(math.fsum(parts), tick.volume, 1e-12)
        assert _close(data["wash_volume"][i], tick.wash_volume, 1e-12)
    for column, total in (("organic_volume", breakdown.organic_volume),
                          ("manipulator_volume", breakdown.manipulator_volume),
                          ("wash_volume", breakdown.wash_volume)):
        assert _close(math.fsum(data[column]), total), column
    for column, count in (("organic_fills", breakdown.organic_fills),
                          ("manipulator_fills", breakdown.manipulator_fills),
                          ("wash_legs", breakdown.wash_legs)):
        assert sum(data[column]) == count, column
    if amm or not sim.whales:
        assert data["whale_volume"] == (None,) * TICKS
    else:
        assert _close(math.fsum(data["whale_volume"]), breakdown.whale_volume)
        assert sum(data["whale_fills"]) == breakdown.whale_fills
        assert sum(data["zero_quantity_whale_trades"]) == breakdown.zero_quantity_whale_trades
        assert _close(math.fsum(data["background_volume"]), breakdown.background_volume)


def test_v4_classes_reconcile_with_organic_volume_and_the_strategy_summaries(run):
    _, _, series, report = run
    data = series.data
    for i in range(series.rows):
        volume = math.fsum(c.buy_volume[i] + c.sell_volume[i] for c in series.classes.values())
        assert _close(volume, data["organic_volume"][i], 1e-12)
        fills = sum(c.buy_fills[i] + c.sell_fills[i] for c in series.classes.values())
        assert fills == data["organic_fills"][i]
    summaries = {s.strategy: s for s in report.traders.strategies}
    for name, cls in series.classes.items():
        if name not in summaries:
            # analyze_traders knows a trader's strategy only from its records,
            # so a class that never filled has no summary of its own — which is
            # why the model takes its population explicitly. Its columns are zeros.
            assert sum(cls.buy_fills) == sum(cls.sell_fills) == sum(cls.filled_traders) == 0
            continue
        summary = summaries[name]
        assert summary.trader_count == series.population[name]
        assert _close(math.fsum(cls.buy_volume), summary.buy_volume)
        assert _close(math.fsum(cls.sell_volume), summary.sell_volume)
        assert all(0 <= n <= series.population[name] for n in cls.filled_traders)


def test_v5_v6_mode_fields(run):
    sim, ticks, series, _ = run
    if sim.pricing_mode.value == "amm":
        for i, tick in enumerate(ticks):
            pool = tick.pool_state
            assert series.data["pool_coin_reserve"][i] == float(pool.coin_reserve)
            assert series.data["pool_cash_reserve"][i] == float(pool.cash_reserve)
            assert series.data["pool_spot_price"][i] == float(pool.spot_price)
            assert series.data["pool_invariant"][i] == float(pool.invariant)
            assert series.data["pool_swap_count"][i] == pool.swap_count
        assert series.data["background_volume"] == (None,) * TICKS
    else:
        for name in COLUMNS:
            if name.startswith("pool_"):
                assert series.data[name] == (None,) * TICKS, name


def test_v7_psychology_null_semantics(run):
    _, ticks, series, _ = run
    on = ticks[0].psychology is not None
    for name in ("fear", "fomo", "conviction", "uncertainty"):
        values = series.data[name]
        assert all((v is not None) if on else (v is None) for v in values), name


def test_pump_phases_reconcile_with_the_manipulation_report(run):
    _, _, series, report = run
    if "pump_and_dump" not in series.population:
        assert series.data["pump_pump_volume"] == (None,) * TICKS
        return
    summaries = report.manipulation.pump_and_dump
    for column, field in (("pump_accumulate_volume", "accumulation_volume"),
                          ("pump_pump_volume", "pump_volume"), ("pump_dump_volume", "dump_volume")):
        assert _close(math.fsum(series.data[column]), math.fsum(getattr(s, field) for s in summaries)), column


def test_v11_crowd_observables_match_the_core_functions(run):
    sim, ticks, series, _ = run
    for i, tick in enumerate(ticks):
        assert series.data["organic_crowd_flow"][i] == organic_crowd_flow(tick.trader_trades, sim.coin.initial_supply)
        breadth = organic_breadth(tick.trader_trades)
        assert series.data["organic_breadth"][i] == breadth
        buyers, sellers = series.data["organic_net_buyers"][i], series.data["organic_net_sellers"][i]
        assert breadth == ((buyers - sellers) / (buyers + sellers) if buyers + sellers else 0.0)


@pytest.mark.parametrize("case", [CASES[1], CASES[3]], ids=["rw", "amm"])
def test_v8_two_identical_runs_give_equal_series(case):
    assert _simulate(case)[2] == _simulate(case)[2]
