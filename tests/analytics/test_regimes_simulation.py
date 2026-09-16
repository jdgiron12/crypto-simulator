"""Descriptive market regimes on real simulations (Phase 9, Step 7).

Runs the analytics against real ``CoinSimulator`` output — traders,
funded whales with cycles and cohorts, scheduled and random events,
psychology, pump-and-dump and wash trading, in both pricing modes — and
checks that every window's figures are ``analyze_market``'s own, that no
window's labels depend on anything after it, and that the analysis stays
strictly downstream: pure, deterministic, order-independent and invisible
to the simulation.
"""

import ast
import copy
import dataclasses
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics.regimes as regimes_module
from crypto_simulator.analytics import analyze_market
from crypto_simulator.analytics.regimes import DIRECTIONS, MARKET_STATES, analyze_regimes
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.whale import Whale
from crypto_simulator.core.whale_cohort import WhaleCohort
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _world(seed, mode="random_walk", ticks=200, psychology=True):
    whales, cohorts = [], None
    if mode == "random_walk":
        whales = [
            Whale("legacy", 30_000.0, activity_probability=0.5, seed=seed),
            Whale("cycler", 10_000.0, starting_cash=200_000.0, activity_probability=0.6, max_trade_fraction=0.005,
                  cycle=[{"behavior": "accumulate", "duration": 6}, {"behavior": "neutral", "duration": 4}],
                  seed=seed + 1),
            Whale("member", 20_000.0, starting_cash=150_000.0, activity_probability=0.8, max_trade_fraction=0.004,
                  seed=seed + 2),
        ]
        cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                     {"behavior": "distribute", "duration": 5}], ("member",))]
    events = EventEngine([
        MarketEvent(event_id="n1", category="custom", severity=0.8, sentiment=-0.6, volatility_boost=1.0,
                    attention=1.0, start_tick=30, duration=15, decay_ticks=5),
        MarketEvent(event_id="n2", category="listing", severity=0.5, sentiment=0.4, volatility_boost=0.3,
                    attention=0.5, start_tick=40, duration=10),
    ])
    manipulators = [
        PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                    risk_tolerance=0.5, seed=seed + 20, start_tick=60),
        WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                   max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 21),
    ]
    sim = CoinSimulator(_coin(), seed=seed, whales=whales, whale_cohorts=cohorts, pricing_mode=mode,
                        traders=_all_five(seed_base=seed) + manipulators,
                        reserve_cash=2_000_000.0 if mode == "amm" else 500_000.0,
                        events=events, event_generator=RandomEventGenerator(probability=0.03, seed=seed),
                        psychology=psychology, whale_observation=mode == "random_walk")
    return sim, sim.run(ticks)


# --- figures and labels on real runs ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_every_window_is_analyze_markets_own_summary(mode):
    for seed in range(4):
        sim, ticks = _world(seed, mode=mode)
        p0 = sim.coin.starting_price
        report = analyze_regimes(ticks, initial_price=p0, total_supply=sim.coin.initial_supply)
        assert report.pricing_mode == mode and report.ticks == len(ticks)
        assert [o.start_tick for o in report.observations] == list(range(1, 201, 20))
        for window in report.observations:
            assert window.market == analyze_market(ticks, initial_price=p0, total_supply=sim.coin.initial_supply,
                                                   start_tick=window.start_tick, end_tick=window.end_tick)
            assert window.direction in (*DIRECTIONS, None)
            assert window.market_state in MARKET_STATES


def test_context_matches_what_the_run_recorded():
    sim, ticks = _world(1)
    report = analyze_regimes(ticks, initial_price=sim.coin.starting_price)
    by_window = {o.window_index: o for o in report.observations}
    live_window = by_window[1]  # ticks 21-40 include n1 from tick 30
    assert live_window.context.event_active is True and "n1" in live_window.context.event_ids
    for window in report.observations:
        assert window.context.psychology_ticks == window.tick_count  # psychology on throughout
        assert window.context.whale_observed_ticks == window.tick_count
        assert window.manipulation_active  # the wash trader trades every tick


def test_amm_runs_have_no_whale_volume_or_whale_context():
    sim, ticks = _world(2, mode="amm")
    for window in analyze_regimes(ticks, initial_price=sim.coin.starting_price).observations:
        assert window.market.volume_breakdown.whale_volume == 0.0
        assert window.context.whale_observed_ticks == 0


def test_a_run_without_psychology_or_events_reports_unknown_context():
    sim = build_coin_simulator(get_settings())
    ticks = sim.run(60)
    for window in analyze_regimes(ticks, initial_price=sim.coin.starting_price).observations:
        assert window.context.psychology_ticks == 0 and window.context.mean_fear is None


def _quartiles(values):
    ordered = sorted(values)

    def at(percent):
        low, remainder = divmod(percent * (len(ordered) - 1), 100)
        return ordered[low] if remainder == 0 else ordered[low] + (ordered[low + 1] - ordered[low]) * remainder / 100

    return at(25), at(75)


def test_each_reference_is_exactly_the_earlier_complete_windows():
    sim, ticks = _world(5, ticks=400)
    report = analyze_regimes(ticks, initial_price=sim.coin.starting_price, window_size=10)
    for i, window in enumerate(report.observations):
        earlier = [o for o in report.observations[:i] if o.complete]
        volumes = [o.volume_per_tick for o in earlier]
        volatilities = [o.market.volatility for o in earlier if o.market.volatility is not None]
        expected_volume = _quartiles(volumes) if len(volumes) >= 4 else None
        expected_volatility = _quartiles(volatilities) if len(volatilities) >= 4 else None
        assert window.volume_reference == (pytest.approx(expected_volume) if expected_volume else None)
        assert window.volatility_reference == (pytest.approx(expected_volatility) if expected_volatility else None)


# --- no look-ahead on real runs -----------------------------------------------------------------------------


def test_truncating_a_real_run_never_changes_earlier_windows():
    sim, ticks = _world(7)
    p0 = sim.coin.starting_price
    full = analyze_regimes(ticks, initial_price=p0).observations
    for cut in (40, 100, 160):
        assert analyze_regimes(ticks[:cut], initial_price=p0).observations == full[:cut // 20]


def test_rewriting_the_future_never_changes_earlier_windows():
    sim, ticks = _world(8)
    p0 = sim.coin.starting_price
    before = analyze_regimes(ticks, initial_price=p0).observations
    g = random.Random(8)
    rewritten = [dataclasses.replace(t, price=t.price * g.uniform(0.2, 5.0), volume=t.volume * g.uniform(0.0, 50.0))
                 if t.tick > 100 else t for t in ticks]
    after = analyze_regimes(rewritten, initial_price=p0).observations
    assert after[:5] == before[:5]
    assert after[5:] != before[5:]  # the rewrite really did change the later windows


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
            [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_repeatable_and_draws_no_randomness():
    sim, ticks = _world(21)
    snapshot, states, global_state = copy.deepcopy(ticks), _rng_states(sim), random.getstate()
    first = analyze_regimes(ticks, initial_price=sim.coin.starting_price, window_size=15)
    assert first == analyze_regimes(ticks, initial_price=sim.coin.starting_price, window_size=15)
    assert ticks == snapshot and _rng_states(sim) == states and random.getstate() == global_state


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks = _world(33, ticks=80)
        if analyse:
            analyze_regimes(ticks, initial_price=sim.coin.starting_price)
        rest = sim.run(60)
        return [(t.tick, t.price, t.volume, t.trader_trades, t.whale_trades, t.psychology) for t in rest], \
            _rng_states(sim)

    assert run(True) == run(False)


def test_analysis_is_order_independent():
    for seed in range(4):
        sim, ticks = _world(seed, ticks=90)
        shuffled = list(ticks)
        random.Random(seed).shuffle(shuffled)
        assert analyze_regimes(shuffled, initial_price=sim.coin.starting_price, window_size=10) == \
            analyze_regimes(ticks, initial_price=sim.coin.starting_price, window_size=10)


def test_the_same_run_always_produces_the_same_report():
    def run():
        sim, ticks = _world(9)
        return analyze_regimes(ticks, initial_price=sim.coin.starting_price)

    assert run() == run()


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


def test_the_module_only_reads_records():
    imported, used = _names(regimes_module.__file__)
    assert imported <= {
        "__future__", "math", "dataclasses", "typing",
        "crypto_simulator.analytics._series", "crypto_simulator.analytics.events",
        "crypto_simulator.analytics.market", "crypto_simulator.analytics.psychology",
        "crypto_simulator.core.coin_simulator",
    }
    forbidden = {"random", "_rng", "step", "run", "maybe_trade", "decide", "execute_decision", "execute_wash",
                 "settle_against_reserve", "simulate", "set_price", "set_behavior", "inject", "phase_at",
                 "intensity_at", "compute_psychology"}
    assert not used & forbidden, used & forbidden


def test_the_module_makes_no_causal_or_forecasting_claims():
    text = Path(regimes_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict",
                   "bullish", "bearish", "breakout", "opportunity", "likely"):
        assert phrase not in text, phrase
