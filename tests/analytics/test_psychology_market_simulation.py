"""Psychology-market co-movement analytics on real simulations (Phase 9,
Step 5).

Runs the analytics against real ``CoinSimulator`` output — psychology
on/off, traders, funded whales, cohorts, scheduled and random events,
pump-and-dump, wash trading, both pricing modes — and checks the report
stays a strict downstream read: pure, deterministic, order-independent,
and never feeding back into the simulation. Cross-checks the embedded
component/event-period figures against ``analyze_psychology`` directly
and the pricing mode against ``analyze_market``, since this module is
built on both.
"""

import ast
import copy
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics.psychology_market as psychology_market_module
from crypto_simulator.analytics import analyze_market, analyze_psychology, analyze_psychology_market
from crypto_simulator.analytics.psychology_market import COVERAGE_NONE
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


def _world(seed, mode="random_walk", psychology=True, ticks=120):
    g = random.Random(seed)
    whales, cohorts = [], None
    if mode == "random_walk":
        whales = [
            Whale("legacy", 30_000.0, activity_probability=0.5, seed=seed),
            Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
                 activity_probability=0.6, max_trade_fraction=0.01, seed=seed + 1),
        ]
        cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                     {"behavior": "distribute", "duration": 5}], ("acc",))]
    events = [MarketEvent(event_id="n1", category="custom", severity=0.8, sentiment=-0.6, volatility_boost=1.0,
                          attention=1.0, start_tick=10, duration=8, decay_ticks=4)]
    engine = EventEngine(events)
    generator = RandomEventGenerator(probability=0.03, seed=seed)
    sim = CoinSimulator(_coin(), seed=seed, whales=whales, whale_cohorts=cohorts, pricing_mode=mode,
                        traders=_all_five(seed_base=seed) + _manipulators(seed + 7),
                        reserve_cash=2_000_000.0 if mode == "amm" else 500_000.0,
                        events=engine, event_generator=generator, psychology=psychology,
                        whale_observation=True)
    return sim, sim.run(ticks)


# --- shape against a real run ------------------------------------------------------------------------------


def test_psychology_disabled_reports_no_coverage():
    sim, ticks = _world(1, psychology=False)
    report = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    assert report.coverage == COVERAGE_NONE
    assert report.observations == ()


def test_psychology_enabled_reports_full_coverage_and_all_correlation_slots():
    sim, ticks = _world(2, psychology=True)
    report = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    assert report.ticks_with_psychology == len(ticks)
    # 8 same-tick pairs + 4 lag-1 pairs, always present (value may be None).
    assert len(report.correlations) == 12


def test_an_amm_run_has_no_whale_volume_in_any_observation():
    sim, ticks = _world(3, mode="amm", psychology=True)
    report = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    for observation in report.observations:
        assert observation.whale_volume == 0.0


# --- cross-checks against analyze_psychology / analyze_market, which this module reuses ---------------------


def test_components_and_event_periods_match_analyze_psychology_exactly():
    for seed in range(6):
        sim, ticks = _world(seed)
        report = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
        direct = analyze_psychology(ticks)
        assert report.components == direct.components
        assert report.event_periods == direct.event_periods
        assert report.ticks_with_psychology == direct.ticks_with_psychology


def test_pricing_mode_matches_analyze_market():
    for seed in range(4):
        sim, ticks = _world(seed)
        report = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
        market = analyze_market(ticks, initial_price=sim.coin.starting_price)
        assert report.pricing_mode == market.pricing_mode


def test_per_tick_volume_matches_a_single_tick_analyze_market_call():
    sim, ticks = _world(4)
    report = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    by_tick = {t.tick: t for t in ticks}
    for observation in report.observations[:20]:
        direct = analyze_market([by_tick[observation.tick]]).volume_breakdown
        assert observation.participant_volume == direct.participant_volume
        assert observation.whale_volume == direct.whale_volume
        assert observation.volume == by_tick[observation.tick].volume


def test_returns_never_bridge_a_gap_in_a_real_run():
    sim, ticks = _world(5, ticks=60)
    trimmed = [t for t in ticks if t.tick != 30]
    report = analyze_psychology_market(trimmed, initial_price=sim.coin.starting_price)
    if any(o.tick == 31 for o in report.observations):
        assert report.observation(31).log_return is None


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
           [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_repeatable_and_draws_no_randomness():
    sim, ticks = _world(21)
    snapshot, states, global_state = copy.deepcopy(ticks), _rng_states(sim), random.getstate()
    first = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    second = analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
    assert first == second
    assert ticks == snapshot and _rng_states(sim) == states and random.getstate() == global_state


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks = _world(33, ticks=60)
        if analyse:
            analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)
        rest = sim.run(40)
        return [(t.tick, t.price, t.volume, t.psychology) for t in rest], _rng_states(sim)

    assert run(True) == run(False)


def test_analysis_is_order_independent():
    for seed in range(5):
        sim, ticks = _world(seed, ticks=60)
        shuffled = list(ticks)
        random.Random(seed).shuffle(shuffled)
        assert analyze_psychology_market(shuffled, initial_price=sim.coin.starting_price) == \
            analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)


def test_the_same_run_always_produces_the_same_report():
    def run():
        sim, ticks = _world(9)
        return analyze_psychology_market(ticks, initial_price=sim.coin.starting_price)

    assert run() == run()


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


def test_the_module_only_reads_records():
    imported, used = _names(psychology_market_module.__file__)
    assert imported <= {
        "__future__", "math", "statistics", "dataclasses", "typing",
        "crypto_simulator.analytics._series", "crypto_simulator.analytics.market",
        "crypto_simulator.analytics.psychology", "crypto_simulator.core.coin_simulator",
    }
    forbidden = {"random", "_rng", "step", "run", "set_price", "maybe_trade", "decide", "set_behavior",
                "set_intent_strength", "deposit_cash", "withdraw_cash", "deposit_coins", "withdraw_coins",
                "buy", "sell", "inject"}
    assert not used & forbidden, used & forbidden
    assert "random" not in imported


def test_the_module_makes_no_causal_claims():
    text = Path(psychology_market_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict",
                  "influenced", "triggered", "effective"):
        assert phrase not in text, phrase
