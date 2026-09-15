"""Core market analytics on real simulations (Phase 9, Step 1).

Proves the volume decomposition against the simulator's own data model,
cross-checks the shared definitions against ``analyze_events`` and the
pool's own counters, and checks the analytics stay strictly downstream:
deterministic, order-independent, pure, and invisible to the simulation.
"""

import ast
import copy
import math
import random
from pathlib import Path

import pytest

import crypto_simulator.analytics._series as series_module
import crypto_simulator.analytics.market as market_module
from crypto_simulator.analytics import analyze_events, analyze_market
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES
from crypto_simulator.core.whale import Whale
from crypto_simulator.core.whale_cohort import WhaleCohort
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin

SUPPLY = 1_000_000.0


def _manipulators(seed):
    return [PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                        risk_tolerance=0.5, seed=seed),
            WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                       max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 1)]


def _world(seed, mode="random_walk", ticks=150):
    """A random run using most of what the simulator can do."""
    g = random.Random(seed)
    whales, cohorts = [], None
    if mode == "random_walk":
        whales = [Whale("legacy", 30_000.0, activity_probability=0.5, cooldown_ticks=g.choice([0, 2]), seed=seed),
                  Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
                        activity_probability=0.6, max_trade_fraction=0.01, seed=seed + 1),
                  Whale("m", 20_000.0, starting_cash=150_000.0, activity_probability=0.8, max_trade_fraction=0.004,
                        seed=seed + 2)]
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
                        psychology=g.random() < 0.5, **extras)
    return sim, sim.run(ticks)


# --- the volume decomposition, proved against the data model -------------------------------------------


def test_random_walk_volume_is_exactly_synthetic_plus_every_whale_and_trader_quantity():
    """Replaying the simulator's own accumulation order reproduces every
    tick's volume bit for bit: both wash legs are already in it, so wash
    volume must never be added on top of trader volume. The residual the
    analytics reports as background is the synthetic volume up to rounding."""
    for seed in range(10):
        sim = CoinSimulator(_coin(), seed=seed, whales=[Whale("u", 40_000.0, activity_probability=0.6, seed=seed)],
                            traders=_all_five(seed_base=seed) + _manipulators(seed), reserve_cash=500_000.0)
        synthetic, original = [], sim._volume_model.next_volume

        def recording():
            synthetic.append(original())
            return synthetic[-1]

        sim._volume_model.next_volume = recording
        ticks = sim.run(120)
        for tick, known in zip(ticks, synthetic):
            replay = known
            for trade in tick.whale_trades:
                replay += trade.quantity
            for fill in tick.trader_trades:
                replay += fill.quantity
            assert replay == tick.volume
            assert tick.wash_volume == sum(f.quantity for f in tick.trader_trades if f.wash)
            background = analyze_market(ticks, start_tick=tick.tick, end_tick=tick.tick).volume_breakdown.background_volume
            assert abs(background - known) <= 4 * math.ulp(tick.volume)
        assert sum(t.wash_volume for t in ticks) > 0


def test_amm_volume_is_exactly_the_trader_fills():
    sim, ticks = _world(3, mode="amm")
    for tick in ticks:
        assert tick.whale_trades == ()
        assert tick.volume == sum(f.quantity for f in tick.trader_trades)
    summary = analyze_market(ticks)
    v = summary.volume_breakdown
    assert summary.pricing_mode == "amm" and v.background_volume is None and v.whale_volume == 0.0
    assert math.isclose(v.organic_volume + v.manipulator_volume + v.wash_volume, v.total_volume, rel_tol=1e-12)


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_every_record_is_classified_once_and_the_categories_add_up(mode):
    for seed in range(12):
        sim, ticks = _world(seed, mode=mode)
        v = analyze_market(ticks).volume_breakdown
        records = sum(len(t.whale_trades) + len(t.trader_trades) for t in ticks)
        assert v.fills + v.zero_quantity_whale_trades == records
        wash = [f.quantity for t in ticks for f in t.trader_trades if f.wash]
        manip = [f.quantity for t in ticks for f in t.trader_trades if not f.wash and f.strategy in MANIPULATION_STRATEGIES]
        organic = [f.quantity for t in ticks for f in t.trader_trades if not f.wash and f.strategy not in MANIPULATION_STRATEGIES]
        assert (v.wash_volume, v.manipulator_volume, v.organic_volume) == (math.fsum(wash), math.fsum(manip), math.fsum(organic))
        parts = [v.whale_volume, v.organic_volume, v.manipulator_volume, v.wash_volume]
        if mode == "random_walk":
            parts.append(v.background_volume)
        assert math.isclose(math.fsum(parts), v.total_volume, rel_tol=1e-12)
        assert v.wash_legs > 0 and v.manipulator_fills > 0 and v.organic_fills > 0


# --- cross-checks against the simulator and existing analytics ------------------------------------------


def test_amm_fees_equal_the_pools_own_fee_counters_exactly():
    for seed in range(6):
        sim, ticks = _world(seed, mode="amm")
        pool = analyze_market(ticks).pool_activity
        last = ticks[-1].pool_state
        assert pool.fees_cash == last.fees_collected_cash and pool.fees_coins == last.fees_collected_coins
        assert pool.swap_count == last.swap_count == sum(len(t.trader_trades) for t in ticks)
        swaps = [f.swap for t in ticks for f in t.trader_trades]
        # Exact: abs() would round a Decimal to the default 28-digit context.
        assert pool.max_abs_price_impact == max(s.price_impact.copy_abs() for s in swaps)


def test_volatility_and_returns_agree_with_event_analytics_exactly():
    for seed in range(6):
        sim, ticks = _world(seed)
        starting = sim.coin.starting_price
        events = [MarketEvent(event_id="a", category="custom", severity=0.5, sentiment=0.1, volatility_boost=0.0,
                              attention=1.0, start_tick=1, duration=40),
                  MarketEvent(event_id="b", category="custom", severity=0.5, sentiment=0.1, volatility_boost=0.0,
                              attention=1.0, start_tick=60, duration=30)]
        a, b = analyze_events(ticks, events, initial_price=starting)
        from_one = analyze_market(ticks, initial_price=starting, end_tick=a.ground_truth.last_active_tick)
        assert from_one.volatility == a.market.volatility
        later = analyze_market(ticks, start_tick=59, end_tick=b.ground_truth.last_active_tick)
        assert later.volatility == b.market.volatility
        during = analyze_market(ticks, start_tick=60, end_tick=b.ground_truth.last_active_tick)
        assert during.cumulative_return == b.market.event_return


def test_market_cap_matches_the_recorded_market_cap():
    sim, ticks = _world(4)
    summary = analyze_market(ticks, initial_price=sim.coin.starting_price, total_supply=sim.coin.initial_supply)
    assert summary.market_cap_end == ticks[-1].market_cap
    assert summary.market_cap_start == sim.coin.starting_price * sim.coin.initial_supply


def test_the_default_builder_run_in_both_modes():
    for mode in ("random_walk", "amm"):
        sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk")
        ticks = sim.run(100)
        summary = analyze_market(ticks, initial_price=sim.coin.starting_price, total_supply=sim.coin.initial_supply)
        assert summary.ticks == 100 and summary.return_count == 100 and summary.pricing_mode == mode
        assert (summary.pool_activity is None) == (mode == "random_walk")


# --- properties over many runs -----------------------------------------------------------------------------


def _path_prices(summary, ticks, initial_price):
    return ([initial_price] if initial_price is not None and ticks[0].tick == 1 else []) + [t.price for t in ticks]


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_invariants_hold_across_many_runs(mode):
    for seed in range(15):
        sim, ticks = _world(100 + seed, mode=mode)
        p0 = sim.coin.starting_price
        g = random.Random(seed)
        start, end = sorted(g.sample(range(1, len(ticks) + 1), 2))
        for window in ({}, {"start_tick": start, "end_tick": end}):
            summary = analyze_market(ticks, initial_price=p0, total_supply=SUPPLY, **window)
            analysed = [t for t in ticks if window.get("start_tick", 1) <= t.tick <= window.get("end_tick", 10**9)]
            prices = _path_prices(summary, analysed, p0)
            assert summary.high_price == max(prices) and summary.low_price == min(prices)
            assert summary.return_count == len(prices) - 1  # no gaps in a simulated run
            growth = math.prod(b / a for a, b in zip(prices, prices[1:]))
            assert math.isclose(summary.cumulative_return, growth - 1.0, rel_tol=1e-9, abs_tol=1e-12)
            assert math.isclose(summary.log_return, math.fsum(math.log(b / a) for a, b in zip(prices, prices[1:])),
                                rel_tol=1e-9, abs_tol=1e-12)
            assert 0.0 <= summary.max_drawdown < 1.0 and 0.0 <= summary.end_drawdown < 1.0
            if summary.max_drawdown > 0:
                by_tick = dict(zip([0] * (len(prices) - len(analysed)) + [t.tick for t in analysed], prices))
                peak, trough = by_tick[summary.drawdown_peak_tick], by_tick[summary.drawdown_trough_tick]
                assert summary.drawdown_trough_tick > summary.drawdown_peak_tick
                assert summary.max_drawdown == 1.0 - trough / peak
                if summary.recovery_tick is not None:
                    assert summary.recovery_tick > summary.drawdown_trough_tick and by_tick[summary.recovery_tick] >= peak
            assert (summary.volatility is None) == (summary.return_count < 2)
            fills = [f for t in analysed for f in t.trader_trades if not f.wash]
            if fills:
                assert min(f.price for f in fills) - 1e-12 <= summary.trader_vwap <= max(f.price for f in fills) + 1e-12
            assert summary.participant_turnover <= summary.turnover
        shuffled = list(ticks)
        g.shuffle(shuffled)
        assert analyze_market(shuffled, initial_price=p0, total_supply=SUPPLY) == analyze_market(
            ticks, initial_price=p0, total_supply=SUPPLY)


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
            [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_repeatable_and_draws_no_randomness():
    sim, ticks = _world(21)
    snapshot, states, global_state = copy.deepcopy(ticks), _rng_states(sim), random.getstate()
    first = analyze_market(ticks, initial_price=1.0, total_supply=SUPPLY)
    second = analyze_market(ticks, initial_price=1.0, total_supply=SUPPLY)
    assert first == second
    assert ticks == snapshot and _rng_states(sim) == states and random.getstate() == global_state


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks = _world(33, ticks=60)
        if analyse:
            analyze_market(ticks, initial_price=1.0, total_supply=SUPPLY)
            analyze_market(ticks, start_tick=10, end_tick=30)
        rest = sim.run(60)
        return [(t.tick, t.price, t.volume, t.whale_trades, t.trader_trades, t.psychology) for t in rest], _rng_states(sim)

    assert run(True) == run(False)


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


@pytest.mark.parametrize("module", [market_module, series_module])
def test_the_analytics_only_read_records(module):
    imported, used = _names(module.__file__)
    assert imported <= {"__future__", "math", "statistics", "dataclasses", "decimal", "typing",
                        "crypto_simulator.analytics._series", "crypto_simulator.analytics.events",
                        "crypto_simulator.core.coin_simulator", "crypto_simulator.core.liquidity.amounts",
                        "crypto_simulator.core.liquidity.pool", "crypto_simulator.core.traders.registry"}
    # Nothing that could run, steer, trade or reseed a simulation. (Reading
    # a fill's recorded ``swap`` is fine; calling a pool's buy/sell is not.)
    forbidden = {"random", "_rng", "step", "run", "set_price", "maybe_trade", "decide", "set_behavior",
                 "set_intent_strength", "deposit_cash", "withdraw_cash", "deposit_coins", "withdraw_coins",
                 "buy", "sell", "quote_buy", "quote_sell", "add_liquidity", "remove_liquidity"}
    assert not used & forbidden, used & forbidden
    assert "random" not in imported


@pytest.mark.parametrize("module", [market_module, series_module])
def test_the_analytics_make_no_causal_claims(module):
    text = Path(module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict"):
        assert phrase not in text, phrase
