"""Whale activity analytics on real simulations (Phase 9, Step 3).

Runs the analytics against real ``CoinSimulator`` output — funded and
unfunded whales, targets, cooldown, minimum trade interval, intent
strength, behavior transitions, cycles, cohorts, psychology, scheduled and
random events, pump-and-dump and wash trading — and checks the report
stays a strict downstream read: pure, deterministic, order-independent,
and never feeding back into the simulation. Cross-checks the volume
figures against ``analyze_market`` (Step 1) and the per-whale figures
against ``analyze_whales`` (Step 7), which this module is built on.
"""

import ast
import copy
import math
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics.whale_activity as whale_activity_module
from crypto_simulator.analytics import analyze_market, analyze_whale_activity, analyze_whales
from crypto_simulator.analytics.whale_activity import COVERAGE_COMPLETE, COVERAGE_NONE
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.whale import Whale, WhaleBehavior
from crypto_simulator.core.whale_cohort import WhaleCohort
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _manipulators(seed):
    return [PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                        risk_tolerance=0.5, seed=seed),
            WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                       max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 1)]


def _world(seed, mode="random_walk", ticks=200):
    """A run exercising most of what Phase 8's whales and Phase 9's
    analytics can do together, observed throughout."""
    g = random.Random(seed)
    whales, cohorts = [], None
    if mode == "random_walk":
        whales = [
            Whale("legacy", 30_000.0, activity_probability=0.5, cooldown_ticks=g.choice([0, 2]), seed=seed),
            Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
                 activity_probability=0.6, max_trade_fraction=0.01, min_trade_interval_ticks=1,
                 intent_strength=1.4, seed=seed + 1),
            Whale("m", 20_000.0, starting_cash=150_000.0, activity_probability=0.8, max_trade_fraction=0.004,
                 seed=seed + 2),
        ]
        cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                     {"behavior": "distribute", "duration": 5}], ("m",))]
    extras = {}
    if g.random() < 0.6:
        extras["events"] = EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.6,
                                                    volatility_boost=1.0, attention=1.0, start_tick=10, duration=20)])
        extras["event_generator"] = RandomEventGenerator(probability=0.05, seed=seed)
    sim = CoinSimulator(_coin(), seed=seed, whales=whales, whale_cohorts=cohorts, pricing_mode=mode,
                        traders=_all_five(seed_base=seed) + _manipulators(seed + 7),
                        reserve_cash=2_000_000.0 if mode == "amm" else 500_000.0,
                        psychology=g.random() < 0.5, whale_observation=True, **extras)
    return sim, sim.run(ticks)


# --- shape against a real run ------------------------------------------------------------------------------


def test_a_random_walk_run_reports_every_configured_whale_and_its_cohort():
    sim, ticks = _world(1)
    report = analyze_whale_activity(ticks)
    assert report.coverage == COVERAGE_COMPLETE
    assert report.whale_ids == ("acc", "legacy", "m")
    assert report.cohort_ids == ("k",)
    cohort = report.cohort("k")
    assert cohort.member_count == 1 and cohort.co_fill is None  # one-member cohort


def test_an_amm_run_rejects_whales_so_whale_activity_is_naturally_empty():
    sim, ticks = _world(2, mode="amm")
    for tick in ticks:
        assert tick.whale_trades == () and tick.whale_observations == ()
    report = analyze_whale_activity(ticks)
    assert report.coverage == COVERAGE_NONE
    assert report.whales == () and report.cohorts == ()
    assert report.whale_volume is None
    # Real AMM trader volume still gets a real total, just no whale share of it.
    assert report.total_market_volume > 0.0
    assert report.whale_volume_share_of_total is None


def test_the_default_builder_run_produces_a_report_for_its_one_whale():
    sim = build_coin_simulator(get_settings(), whale_observation=True)
    ticks = sim.run(150)
    report = analyze_whale_activity(ticks)
    assert report.whale_ids == ("whale-1",)
    w = report.whale("whale-1")
    assert w.summary.funded is False
    assert w.allocation_gap is None and w.target_reaching is None


# --- cross-checks against analyze_market / analyze_whales, which this module reuses -------------------------


def test_whale_volume_never_exceeds_the_markets_own_participant_volume():
    for seed in range(8):
        _, ticks = _world(seed)
        report = analyze_whale_activity(ticks)
        market = analyze_market(ticks)
        assert report.total_market_volume == market.volume_breakdown.total_volume
        assert report.participant_volume == market.volume_breakdown.participant_volume
        if report.whale_volume is not None and report.participant_volume > 0:
            assert report.whale_volume <= report.participant_volume + 1e-6
            assert 0.0 <= report.whale_volume_share_of_participants <= 1.0 + 1e-9


def test_per_whale_total_volume_matches_analyze_whales_exactly():
    for seed in range(6):
        _, ticks = _world(seed)
        activity = analyze_whale_activity(ticks)
        whales = analyze_whales(ticks)
        for summary in whales.whales:
            assert activity.whale(summary.whale_id).summary == summary


def test_reported_whale_volume_is_the_sum_of_every_whales_total_volume():
    for seed in range(6):
        _, ticks = _world(seed)
        report = analyze_whale_activity(ticks)
        if report.whale_volume is None:
            continue
        assert report.whale_volume == pytest.approx(
            math.fsum(w.summary.total_volume for w in report.whales)
        )


def test_behavior_totals_sum_to_the_reports_whale_volume():
    for seed in range(6):
        _, ticks = _world(seed)
        report = analyze_whale_activity(ticks)
        if report.whale_volume is None:
            continue
        assert math.isclose(
            math.fsum(b.total_volume for b in report.behaviors), report.whale_volume, rel_tol=1e-9, abs_tol=1e-9
        )


def test_cohort_totals_are_a_subset_of_the_reports_whale_volume():
    for seed in range(6):
        _, ticks = _world(seed)
        report = analyze_whale_activity(ticks)
        if report.whale_volume is None or not report.cohorts:
            continue
        cohort_total = math.fsum(c.total_volume for c in report.cohorts)
        assert cohort_total <= report.whale_volume + 1e-6


def test_target_reaching_is_consistent_with_the_existing_allocation_path():
    """The accumulator's own AllocationPath (Step 7) already records
    whether it crossed its target; this module's TargetReaching adds only
    the first-tick-at-target figure and must agree it happened at all."""
    for seed in range(8):
        _, ticks = _world(seed)
        report = analyze_whale_activity(ticks)
        acc = report.whale("acc")
        path = acc.summary.allocation
        if path is not None and path.ticks_at_target and path.ticks_at_target > 0:
            assert acc.target_reaching is not None
            assert acc.target_reaching.first_tick_at_target is not None


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
           [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_repeatable_and_draws_no_randomness():
    sim, ticks = _world(21)
    snapshot, states, global_state = copy.deepcopy(ticks), _rng_states(sim), random.getstate()
    first = analyze_whale_activity(ticks)
    second = analyze_whale_activity(ticks)
    assert first == second
    assert ticks == snapshot and _rng_states(sim) == states and random.getstate() == global_state


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks = _world(33, ticks=80)
        if analyse:
            analyze_whale_activity(ticks)
        rest = sim.run(60)
        return [(t.tick, t.price, t.volume, t.whale_trades, t.whale_observations) for t in rest], _rng_states(sim)

    assert run(True) == run(False)


def test_analysis_is_order_independent():
    for seed in range(5):
        _, ticks = _world(seed, ticks=60)
        ticks = list(ticks)
        shuffled = list(ticks)
        random.Random(seed).shuffle(shuffled)
        assert analyze_whale_activity(shuffled) == analyze_whale_activity(ticks)


def test_the_same_run_always_produces_the_same_report():
    def run():
        _, ticks = _world(9)
        return analyze_whale_activity(ticks)

    assert run() == run()


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


def test_the_module_only_reads_records():
    imported, used = _names(whale_activity_module.__file__)
    assert imported <= {
        "__future__", "math", "dataclasses", "typing",
        "crypto_simulator.analytics._series", "crypto_simulator.analytics.market",
        "crypto_simulator.analytics.whales", "crypto_simulator.core.coin_simulator",
        "crypto_simulator.core.whale",
    }
    forbidden = {"random", "_rng", "step", "run", "set_price", "maybe_trade", "decide", "set_behavior",
                "set_intent_strength", "deposit_cash", "withdraw_cash", "deposit_coins", "withdraw_coins",
                "buy", "sell", "observe", "complete_observation", "psychology"}
    assert not used & forbidden, used & forbidden
    assert "random" not in imported


def test_the_module_makes_no_causal_claims():
    text = Path(whale_activity_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict"):
        assert phrase not in text, phrase
