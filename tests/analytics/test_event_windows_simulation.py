"""Event-window market path analytics on real simulations (Phase 9, Step 4).

Runs the analytics against real ``CoinSimulator`` output — traders,
whales, cohorts, psychology, scheduled and random events, pump-and-dump,
wash trading, both pricing modes — and checks the report stays a strict
downstream read: pure, deterministic, order-independent, and never
feeding back into the simulation. Cross-checks the embedded per-window
figures against ``analyze_market`` directly, and ground truth/overlap
against ``analyze_events`` directly, since this module is built on both.
"""

import ast
import copy
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics.event_windows as event_windows_module
from crypto_simulator.analytics import analyze_event_windows, analyze_events, analyze_market
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.whale import Whale
from crypto_simulator.core.whale_cohort import WhaleCohort
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _manipulators(seed):
    return [PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                        risk_tolerance=0.5, seed=seed),
            WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                       max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 1)]


def _events(seed):
    g = random.Random(seed)
    return [
        MarketEvent(event_id="n1", category="custom", severity=0.8, sentiment=-0.6, volatility_boost=1.0,
                   attention=1.0, start_tick=10, duration=8, decay_ticks=4),
        MarketEvent(event_id="n2", category="regulatory", severity=0.5, sentiment=g.choice([-0.3, 0.3]),
                   volatility_boost=0.3, attention=0.4, start_tick=25, duration=5, decay_ticks=2),
    ]


def _world(seed, mode="random_walk", ticks=120):
    g = random.Random(seed)
    whales, cohorts = [], None
    if mode == "random_walk":
        whales = [
            Whale("legacy", 30_000.0, activity_probability=0.5, seed=seed),
            Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
                 activity_probability=0.6, max_trade_fraction=0.01, seed=seed + 1),
            Whale("m", 20_000.0, starting_cash=150_000.0, activity_probability=0.8, max_trade_fraction=0.004,
                 seed=seed + 2),
        ]
        cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                     {"behavior": "distribute", "duration": 5}], ("m",))]
    events = _events(seed)
    engine = EventEngine(events)
    generator = RandomEventGenerator(probability=0.03, seed=seed)
    sim = CoinSimulator(_coin(), seed=seed, whales=whales, whale_cohorts=cohorts, pricing_mode=mode,
                        traders=_all_five(seed_base=seed) + _manipulators(seed + 7),
                        reserve_cash=2_000_000.0 if mode == "amm" else 500_000.0,
                        events=engine, event_generator=generator,
                        psychology=g.random() < 0.5, whale_observation=True)
    all_events = list(engine.events)
    return sim, sim.run(ticks), all_events, {e.event_id for e in generator.generated_events}


# --- shape against a real run ------------------------------------------------------------------------------


def test_a_random_walk_run_reports_every_scheduled_and_random_event():
    sim, ticks, events, random_ids = _world(1)
    report = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price,
                                   random_event_ids=random_ids)
    started = {e.event_id for e in events if e.start_tick <= ticks[-1].tick}
    assert set(report.event_ids) == started
    for path in report.events:
        assert path.ground_truth.randomly_generated == (path.event_id in random_ids)


def test_an_amm_run_has_no_whale_volume_in_any_window():
    sim, ticks, events, random_ids = _world(2, mode="amm")
    report = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price)
    for path in report.events:
        for window in (path.pre_event, path.active, path.decay, path.post_event, path.effect):
            if window is not None:
                assert window.market.volume_breakdown.whale_volume == 0.0


# --- cross-checks against analyze_market / analyze_events, which this module reuses -------------------------


def test_each_windows_market_summary_matches_a_direct_analyze_market_call():
    for seed in range(6):
        sim, ticks, events, _ = _world(seed)
        report = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price)
        for path in report.events:
            for window in (path.active, path.post_event, path.effect):
                direct = analyze_market(
                    [t for t in ticks if window.requested_start <= t.tick <= window.requested_end],
                    initial_price=sim.coin.starting_price,
                )
                assert window.market == direct


def test_ground_truth_and_overlap_match_analyze_events_exactly():
    for seed in range(6):
        sim, ticks, events, random_ids = _world(seed)
        windows = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price,
                                        random_event_ids=random_ids)
        direct = analyze_events(ticks, events, initial_price=sim.coin.starting_price,
                                random_event_ids=random_ids)
        by_id = {obs.ground_truth.event_id: obs for obs in direct}
        for path in windows.events:
            observation = by_id[path.event_id]
            assert path.ground_truth == observation.ground_truth
            assert path.overlapping_event_ids == observation.overlapping_event_ids


def test_no_window_tick_range_overlaps_another_within_the_same_event():
    for seed in range(6):
        sim, ticks, events, _ = _world(seed)
        report = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price)
        for path in report.events:
            spans = []
            for window in (path.pre_event, path.active, path.decay, path.post_event):
                if window is not None:
                    spans.append(set(range(window.requested_start, window.requested_end + 1)))
            seen = set()
            for span in spans:
                assert not (span & seen)
                seen |= span


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
           [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_repeatable_and_draws_no_randomness():
    sim, ticks, events, random_ids = _world(21)
    snapshot, states, global_state = copy.deepcopy(ticks), _rng_states(sim), random.getstate()
    first = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price,
                                  random_event_ids=random_ids)
    second = analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price,
                                   random_event_ids=random_ids)
    assert first == second
    assert ticks == snapshot and _rng_states(sim) == states and random.getstate() == global_state
    # Events themselves are frozen dataclasses; confirm they weren't rebuilt/mutated either.
    assert events == copy.deepcopy(events)


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks, events, random_ids = _world(33, ticks=60)
        if analyse:
            analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price,
                                  random_event_ids=random_ids)
        rest = sim.run(40)
        return [(t.tick, t.price, t.volume, t.event_state) for t in rest], _rng_states(sim)

    assert run(True) == run(False)


def test_analysis_is_order_independent():
    for seed in range(5):
        sim, ticks, events, _ = _world(seed, ticks=60)
        shuffled_ticks = list(ticks)
        random.Random(seed).shuffle(shuffled_ticks)
        shuffled_events = list(reversed(events))
        assert analyze_event_windows(shuffled_ticks, shuffled_events, initial_price=sim.coin.starting_price) == \
            analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price)


def test_the_same_run_always_produces_the_same_report():
    def run():
        sim, ticks, events, random_ids = _world(9)
        return analyze_event_windows(ticks, events, initial_price=sim.coin.starting_price,
                                     random_event_ids=random_ids)

    assert run() == run()


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


def test_the_module_only_reads_records():
    imported, used = _names(event_windows_module.__file__)
    assert imported <= {
        "__future__", "math", "dataclasses", "typing",
        "crypto_simulator.analytics._series", "crypto_simulator.analytics.events",
        "crypto_simulator.analytics.market", "crypto_simulator.core.coin_simulator",
        "crypto_simulator.core.events.event",
    }
    forbidden = {"random", "_rng", "step", "run", "set_price", "maybe_trade", "decide", "set_behavior",
                "set_intent_strength", "deposit_cash", "withdraw_cash", "deposit_coins", "withdraw_coins",
                "buy", "sell", "inject", "state", "phase_at", "intensity_at"}
    assert not used & forbidden, used & forbidden
    assert "random" not in imported


def test_the_module_makes_no_causal_claims():
    text = Path(event_windows_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict"):
        assert phrase not in text, phrase
