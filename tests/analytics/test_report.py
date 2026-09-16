"""Unified report data (Phase 9, Step 8a).

``build_report`` is composition only, so the central check is equality:
every section must be exactly what its analytics function returns when
called directly on the same scope. The rest covers unavailable data kept
as the underlying functions already report it, one shared tick scope,
purity, determinism, immutability, and that the layer adds no arithmetic
of its own and nothing depends back on it.
"""

import ast
import copy
import dataclasses
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics as analytics_package
import crypto_simulator.analytics.report as report_module
from crypto_simulator.analytics import (
    SimulationReport,
    analyze_event_windows,
    analyze_manipulation,
    analyze_market,
    analyze_psychology_market,
    analyze_regimes,
    analyze_traders,
    analyze_whale_activity,
    build_report,
)
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.whale import Whale
from crypto_simulator.core.whale_cohort import WhaleCohort
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _balances(sim):
    return {t.trader_id: (t.wallet.cash, t.wallet.coins) for t in sim.traders}


def _world(seed, *, mode="random_walk", whales=True, events=True, psychology=True, manipulation=True, ticks=150):
    """A run with each optional feature switchable. Returns the simulator,
    its ticks, the event timeline (or ``None``), the random event ids and
    the trader balances before and after the run."""
    whale_list, cohorts = [], None
    if whales and mode == "random_walk":
        whale_list = [
            Whale("legacy", 30_000.0, activity_probability=0.5, seed=seed),
            Whale("cycler", 10_000.0, starting_cash=200_000.0, activity_probability=0.6, max_trade_fraction=0.005,
                  cycle=[{"behavior": "accumulate", "duration": 6}, {"behavior": "neutral", "duration": 4}],
                  seed=seed + 1),
            Whale("member", 20_000.0, starting_cash=150_000.0, activity_probability=0.8, max_trade_fraction=0.004,
                  seed=seed + 2),
        ]
        cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                     {"behavior": "distribute", "duration": 5}], ("member",))]
    extras = {}
    if events:
        extras["events"] = EventEngine([
            MarketEvent(event_id="n1", category="custom", severity=0.8, sentiment=-0.6, volatility_boost=1.0,
                        attention=1.0, start_tick=30, duration=15, decay_ticks=5),
            MarketEvent(event_id="n2", category="listing", severity=0.5, sentiment=0.4, volatility_boost=0.3,
                        attention=0.5, start_tick=40, duration=10),
        ])
        extras["event_generator"] = RandomEventGenerator(probability=0.05, seed=seed)
    traders = _all_five(seed_base=seed)
    if manipulation:
        traders += [PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                                risk_tolerance=0.5, seed=seed + 20, start_tick=50),
                    WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                               max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 21)]
    sim = CoinSimulator(_coin(), seed=seed, whales=whale_list, whale_cohorts=cohorts, pricing_mode=mode,
                        traders=traders, reserve_cash=2_000_000.0 if mode == "amm" else 500_000.0,
                        psychology=psychology, whale_observation=bool(whale_list), **extras)
    start = _balances(sim)
    run = sim.run(ticks)
    timeline = list(sim.events.events) if events else None
    random_ids = ({e.event_id for e in sim.event_generator.generated_events} if events else None)
    return sim, run, timeline, random_ids, start, _balances(sim)


def _assert_sections_equal_direct_calls(report, scoped, *, events, random_ids, p0, supply, start, end,
                                        window_size=20):
    assert report.market == analyze_market(scoped, initial_price=p0, total_supply=supply)
    assert report.traders == analyze_traders(scoped, start_balances=start, end_balances=end, initial_price=p0)
    assert report.whale_activity == analyze_whale_activity(scoped)
    if events is None:
        assert report.event_windows is None
    else:
        assert report.event_windows == analyze_event_windows(scoped, events, initial_price=p0, total_supply=supply,
                                                             random_event_ids=random_ids)
    assert report.psychology_market == analyze_psychology_market(scoped, initial_price=p0)
    assert report.manipulation == analyze_manipulation(scoped, initial_price=p0)
    assert report.regimes == analyze_regimes(scoped, initial_price=p0, window_size=window_size, total_supply=supply)


# --- construction and composition ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_every_section_is_exactly_its_analytics_functions_own_result(mode):
    sim, ticks, events, random_ids, start, end = _world(3, mode=mode)
    p0, supply = sim.coin.starting_price, sim.coin.initial_supply
    report = build_report(ticks, events=events, random_event_ids=random_ids, initial_price=p0, total_supply=supply,
                          start_balances=start, end_balances=end)
    assert isinstance(report, SimulationReport)
    assert (report.ticks, report.start_tick, report.end_tick) == (150, None, None)
    _assert_sections_equal_direct_calls(report, ticks, events=events, random_ids=random_ids, p0=p0, supply=supply,
                                        start=start, end=end)


def test_a_representative_run_fills_every_section():
    sim, ticks, events, random_ids, start, end = _world(4)
    report = build_report(ticks, events=events, random_event_ids=random_ids, initial_price=sim.coin.starting_price,
                          total_supply=sim.coin.initial_supply, start_balances=start, end_balances=end)
    assert report.market.ticks == 150
    assert report.traders.pnl is not None
    assert report.whale_activity.coverage == "complete" and report.whale_activity.cohort_ids == ("k",)
    assert set(report.event_windows.event_ids) >= {"n1", "n2"}
    assert report.psychology_market.coverage == "complete"
    assert report.manipulation.coverage == "complete"
    assert report.regimes.total_windows == 8


def test_window_size_passes_through_to_regimes_only():
    sim, ticks, events, random_ids, start, end = _world(5, ticks=60)
    report = build_report(ticks, initial_price=sim.coin.starting_price, window_size=7)
    assert report.regimes == analyze_regimes(ticks, initial_price=sim.coin.starting_price, window_size=7)


# --- optional and unavailable data ----------------------------------------------------------------------


def test_no_event_timeline_leaves_event_windows_absent_not_empty():
    sim, ticks, *_ = _world(6, events=False)
    report = build_report(ticks, initial_price=sim.coin.starting_price)
    assert report.event_windows is None


def test_an_empty_timeline_is_an_empty_event_report_not_an_absent_one():
    sim, ticks, *_ = _world(6, events=False)
    report = build_report(ticks, events=(), initial_price=sim.coin.starting_price)
    assert report.event_windows == analyze_event_windows(ticks, (), initial_price=sim.coin.starting_price)
    assert report.event_windows.events == ()


def test_events_are_passed_through_not_reconstructed_from_ticks():
    sim, ticks, events, random_ids, *_ = _world(7)
    only_n2 = [e for e in events if e.event_id == "n2"]
    report = build_report(ticks, events=only_n2, initial_price=sim.coin.starting_price)
    assert report.event_windows.event_ids == ("n2",)  # n1 is live in the ticks but not in the supplied timeline
    assert report.event_windows.events[0].ground_truth.randomly_generated is None  # no provenance given


def test_disabled_psychology_keeps_its_own_no_coverage_report():
    sim, ticks, *_ = _world(8, psychology=False)
    report = build_report(ticks, initial_price=sim.coin.starting_price)
    assert report.psychology_market == analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    assert report.psychology_market.coverage == "none" and report.psychology_market.observations == ()
    assert all(o.context.mean_fear is None for o in report.regimes.observations)


def test_no_whales_keeps_whale_activity_unavailable_not_zero():
    sim, ticks, *_ = _world(9, whales=False)
    report = build_report(ticks, initial_price=sim.coin.starting_price)
    assert report.whale_activity == analyze_whale_activity(ticks)
    assert report.whale_activity.coverage == "none" and report.whale_activity.whale_volume is None


def test_no_manipulators_keeps_manipulation_empty():
    sim, ticks, *_ = _world(10, manipulation=False)
    report = build_report(ticks, initial_price=sim.coin.starting_price)
    assert report.manipulation == analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
    assert report.manipulation.coverage == "none" and report.manipulation.pump_and_dump == ()


def test_without_balances_or_initial_price_those_figures_stay_none():
    _, ticks, *_ = _world(11, ticks=40)
    report = build_report(ticks)
    assert report.traders.pnl is None and report.traders.start_equity is None
    assert report.market.market_cap_start is None and report.regimes.observations[0].market.turnover is None


def test_the_default_builder_run():
    sim = build_coin_simulator(get_settings())
    ticks = sim.run(80)
    report = build_report(ticks, initial_price=sim.coin.starting_price, total_supply=sim.coin.initial_supply)
    _assert_sections_equal_direct_calls(report, ticks, events=None, random_ids=None, p0=sim.coin.starting_price,
                                        supply=sim.coin.initial_supply, start=None, end=None)


def test_empty_input_is_a_report_of_empty_sections():
    report = build_report([])
    assert report.ticks == 0 and report.event_windows is None
    _assert_sections_equal_direct_calls(report, [], events=None, random_ids=None, p0=None, supply=None,
                                        start=None, end=None)


# --- one shared scope ----------------------------------------------------------------------------------


@pytest.mark.parametrize("start_tick, end_tick", [(41, 120), (1, 60), (100, None), (None, 35)])
def test_every_section_uses_the_same_tick_scope(start_tick, end_tick):
    sim, ticks, events, random_ids, *_ = _world(12)
    p0, supply = sim.coin.starting_price, sim.coin.initial_supply
    report = build_report(ticks, events=events, random_event_ids=random_ids, initial_price=p0, total_supply=supply,
                          start_tick=start_tick, end_tick=end_tick)
    scoped = [t for t in ticks if (start_tick is None or t.tick >= start_tick)
              and (end_tick is None or t.tick <= end_tick)]
    assert (report.ticks, report.start_tick, report.end_tick) == (len(scoped), start_tick, end_tick)
    _assert_sections_equal_direct_calls(report, scoped, events=events, random_ids=random_ids, p0=p0, supply=supply,
                                        start=None, end=None)
    assert report.market == analyze_market(ticks, initial_price=p0, total_supply=supply,
                                           start_tick=start_tick, end_tick=end_tick)
    for section in (report.traders, report.psychology_market, report.manipulation, report.regimes):
        assert section.ticks == len(scoped)


def test_an_invalid_scope_is_rejected_by_analyze_markets_own_check():
    _, ticks, *_ = _world(13, ticks=30)
    with pytest.raises(ValueError, match="must not exceed"):
        build_report(ticks, start_tick=20, end_tick=10)
    with pytest.raises(ValueError, match="start_tick must be an integer"):
        build_report(ticks, start_tick=0)


def test_invalid_input_is_rejected_by_the_owning_function():
    _, ticks, *_ = _world(14, ticks=10)
    with pytest.raises(ValueError, match="duplicate tick"):
        build_report(list(ticks) + [ticks[3]])
    with pytest.raises(ValueError, match="window_size"):
        build_report(ticks, window_size=0)


# --- purity, determinism and immutability ------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
            [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_building_is_pure_and_repeatable():
    sim, ticks, events, random_ids, start, end = _world(21)
    snapshot = copy.deepcopy((ticks, events, start, end))
    states, global_state = _rng_states(sim), random.getstate()
    kwargs = dict(events=events, random_event_ids=random_ids, initial_price=sim.coin.starting_price,
                  total_supply=sim.coin.initial_supply, start_balances=start, end_balances=end)
    first = build_report(ticks, **kwargs)
    assert first == build_report(ticks, **kwargs)
    assert (ticks, events, start, end) == snapshot
    assert _rng_states(sim) == states and random.getstate() == global_state


def test_building_mid_run_does_not_change_the_rest_of_the_run():
    def run(build):
        sim, ticks, events, random_ids, *_ = _world(33, ticks=70)
        if build:
            build_report(ticks, events=events, random_event_ids=random_ids, initial_price=sim.coin.starting_price)
        rest = sim.run(50)
        return [(t.tick, t.price, t.volume, t.trader_trades, t.whale_trades, t.psychology) for t in rest], \
            _rng_states(sim)

    assert run(True) == run(False)


def test_input_order_does_not_matter():
    sim, ticks, events, random_ids, *_ = _world(22, ticks=90)
    shuffled = list(ticks)
    random.Random(22).shuffle(shuffled)
    kwargs = dict(initial_price=sim.coin.starting_price, random_event_ids=random_ids)
    assert build_report(shuffled, events=list(reversed(events)), **kwargs) == \
        build_report(ticks, events=events, **kwargs)


def test_the_report_is_frozen():
    _, ticks, events, *_ = _world(23, ticks=30)
    report = build_report(ticks, events=events)
    for field in dataclasses.fields(SimulationReport):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(report, field.name, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.market.ticks = 0
    assert isinstance(report.regimes.observations, tuple)


# --- composition only, and the dependency direction ---------------------------------------------------


def test_the_builder_computes_nothing_of_its_own():
    tree = ast.parse(Path(report_module.__file__).read_text())
    # ``X | None`` annotations parse as BitOr; any arithmetic would not.
    arithmetic = [node for node in ast.walk(tree)
                  if isinstance(node, ast.AugAssign)
                  or (isinstance(node, ast.BinOp) and not isinstance(node.op, ast.BitOr))]
    assert not arithmetic
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported == {
        "__future__", "dataclasses", "typing", "crypto_simulator.analytics._series",
        "crypto_simulator.analytics.event_windows", "crypto_simulator.analytics.manipulation",
        "crypto_simulator.analytics.market", "crypto_simulator.analytics.psychology_market",
        "crypto_simulator.analytics.regimes", "crypto_simulator.analytics.traders",
        "crypto_simulator.analytics.whale_activity", "crypto_simulator.core.coin_simulator",
        "crypto_simulator.core.events.event",
    }


def test_no_analytics_module_depends_on_the_report_layer():
    """Layers run one way: individual analytics -> report data -> rendering
    (Step 8b). Only the renderer and the package namespace sit above the
    report; no individual analytics module imports it, and the report data
    never imports its renderer."""
    layers = {"crypto_simulator.analytics.report", "crypto_simulator.analytics.rendering"}
    for module in Path(analytics_package.__file__).parent.glob("*.py"):
        tree = ast.parse(module.read_text())
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        if module.name == "__init__.py":
            continue
        if module.name == "rendering.py":
            assert "crypto_simulator.analytics.report" in imported
            continue
        if module.name == "report.py":
            assert "crypto_simulator.analytics.rendering" not in imported
            continue
        assert not imported & layers, module.name


def test_the_report_layer_renders_nothing_and_makes_no_claims():
    text = Path(report_module.__file__).read_text()
    assert "print(" not in text and "open(" not in text
    for phrase in ("caused", "led to", "drove", "because of", "due to", "signal", "predict", "recommend"):
        assert phrase not in text.lower(), phrase
