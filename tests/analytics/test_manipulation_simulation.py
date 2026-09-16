"""Manipulation analytics on real simulations (Phase 9, Step 6).

Runs the analytics against real ``CoinSimulator`` output — traders,
funded whales, cohorts, psychology, scheduled and random events,
pump-and-dump, wash trading, both pricing modes — and checks the report
stays a strict downstream read: pure, deterministic, order-independent,
and never feeding back into the simulation. Cross-checks the embedded
volume/strategy figures against ``analyze_market``/``analyze_traders``
directly, since this module is built on both.
"""

import ast
import copy
import math
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics.manipulation as manipulation_module
from crypto_simulator.analytics import analyze_manipulation, analyze_market, analyze_traders
from crypto_simulator.analytics.manipulation import COVERAGE_COMPLETE, COVERAGE_NONE
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.whale import Whale
from crypto_simulator.core.whale_cohort import WhaleCohort
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _manipulators(seed):
    return [PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                        risk_tolerance=0.5, seed=seed, start_tick=5, accumulate_ticks=8, pump_ticks=4,
                        dump_ticks=4),
            WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                       max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 1)]


def _world(seed, mode="random_walk", psychology=True, ticks=120):
    g = random.Random(seed)
    whales, cohorts = [], None
    if mode == "random_walk":
        whales = [Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
                        activity_probability=0.6, max_trade_fraction=0.01, seed=seed + 1)]
        cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                     {"behavior": "distribute", "duration": 5}], ("acc",))]
    events = [MarketEvent(event_id="n1", category="custom", severity=0.8, sentiment=-0.6, volatility_boost=1.0,
                          attention=1.0, start_tick=10, duration=8, decay_ticks=4)]
    sim = CoinSimulator(_coin(), seed=seed, whales=whales, whale_cohorts=cohorts, pricing_mode=mode,
                        traders=_all_five(seed_base=seed) + _manipulators(seed + 7),
                        reserve_cash=2_000_000.0 if mode == "amm" else 500_000.0,
                        events=EventEngine(events), psychology=psychology, whale_observation=True)
    return sim, sim.run(ticks)


# --- shape against a real run ------------------------------------------------------------------------------


def test_a_random_walk_run_reports_both_manipulators():
    sim, ticks = _world(1)
    report = analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
    assert report.coverage == COVERAGE_COMPLETE
    assert report.pump_and_dump_trader("pump").total_fills > 0
    assert report.wash.fill_count > 0


def test_a_run_with_no_manipulators_reports_no_coverage():
    sim = CoinSimulator(_coin(), seed=2, traders=_all_five(seed_base=2), reserve_cash=500_000.0)
    ticks = sim.run(60)
    report = analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
    assert report.coverage == COVERAGE_NONE
    assert report.pump_and_dump == () and report.wash.fill_count == 0


def test_an_amm_run_still_reports_wash_and_pump_and_dump_where_they_fill():
    sim, ticks = _world(3, mode="amm")
    report = analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
    assert report.pricing_mode == "amm"
    # AMM has no whales, but manipulators are ordinary wallet-holding traders.
    assert report.wash.fill_count > 0


# --- cross-checks against analyze_market / analyze_traders, which this module reuses -------------------------


def test_volume_decomposition_never_double_counts_wash_on_a_real_run():
    for seed in range(8):
        _, ticks = _world(seed)
        market = analyze_market(ticks).volume_breakdown
        reconstructed = (market.background_volume + market.whale_volume + market.organic_volume
                         + market.manipulator_volume + market.wash_volume)
        assert math.isclose(reconstructed, market.total_volume, rel_tol=1e-9)
        report = analyze_manipulation(ticks)
        assert report.manipulation_volume == pytest.approx(market.manipulator_volume + market.wash_volume)
        assert report.pump_and_dump_volume == pytest.approx(market.manipulator_volume)
        assert report.wash_volume == pytest.approx(market.wash_volume)
        assert 0.0 <= report.manipulation_share_of_total <= 1.0 + 1e-9
        assert 0.0 <= report.manipulation_share_of_participants <= 1.0 + 1e-9


def test_pump_and_dump_summary_market_matches_a_direct_analyze_market_call():
    for seed in range(6):
        sim, ticks = _world(seed)
        report = analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
        summary = report.pump_and_dump_trader("pump")
        window = [t for t in ticks if summary.first_tick <= t.tick <= summary.last_tick]
        direct = analyze_market(window, initial_price=sim.coin.starting_price)
        assert summary.market == direct


def test_embedded_strategy_summaries_match_analyze_traders_exactly():
    for seed in range(6):
        _, ticks = _world(seed)
        report = analyze_manipulation(ticks)
        direct = analyze_traders(ticks)
        assert report.pump_and_dump_strategy == direct.strategy("pump_and_dump")
        assert report.wash_strategy == direct.strategy("wash_trader")


def test_phase_totals_never_exceed_the_strategys_own_total_volume():
    for seed in range(6):
        _, ticks = _world(seed)
        report = analyze_manipulation(ticks)
        summary = report.pump_and_dump_trader("pump")
        assert summary.total_volume == pytest.approx(report.pump_and_dump_strategy.total_volume)


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
           [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_repeatable_and_draws_no_randomness():
    sim, ticks = _world(21)
    snapshot, states, global_state = copy.deepcopy(ticks), _rng_states(sim), random.getstate()
    first = analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
    second = analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
    assert first == second
    assert ticks == snapshot and _rng_states(sim) == states and random.getstate() == global_state


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks = _world(33, ticks=60)
        if analyse:
            analyze_manipulation(ticks, initial_price=sim.coin.starting_price)
        rest = sim.run(40)
        return [(t.tick, t.price, t.volume, t.trader_trades) for t in rest], _rng_states(sim)

    assert run(True) == run(False)


def test_analysis_is_order_independent():
    for seed in range(5):
        sim, ticks = _world(seed, ticks=60)
        shuffled = list(ticks)
        random.Random(seed).shuffle(shuffled)
        assert analyze_manipulation(shuffled, initial_price=sim.coin.starting_price) == \
            analyze_manipulation(ticks, initial_price=sim.coin.starting_price)


def test_the_same_run_always_produces_the_same_report():
    def run():
        sim, ticks = _world(9)
        return analyze_manipulation(ticks, initial_price=sim.coin.starting_price)

    assert run() == run()


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


def test_the_module_only_reads_records():
    imported, used = _names(manipulation_module.__file__)
    assert imported <= {
        "__future__", "math", "dataclasses", "typing",
        "crypto_simulator.analytics._series", "crypto_simulator.analytics.market",
        "crypto_simulator.analytics.traders", "crypto_simulator.core.coin_simulator",
        "crypto_simulator.core.traders.base", "crypto_simulator.core.traders.manipulation",
        "crypto_simulator.core.traders.registry",
    }
    forbidden = {"random", "_rng", "step", "run", "decide", "set_behavior", "set_intent_strength",
                "deposit_cash", "withdraw_cash", "deposit_coins", "withdraw_coins", "buy", "sell",
                "maybe_trade", "phase_at", "intensity_at"}
    assert not used & forbidden, used & forbidden
    assert "random" not in imported


def test_the_module_makes_no_causal_claims():
    text = Path(manipulation_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict",
                  "effective", "coordination", "reaction", "herding", "influence"):
        assert phrase not in text, phrase
