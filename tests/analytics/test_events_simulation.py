"""Event analytics on real simulations: non-interference, AMM metrics,
determinism and dependency direction."""

import ast
import random
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import crypto_simulator
import crypto_simulator.analytics as analytics_package
from crypto_simulator.analytics import analyze_events
from crypto_simulator.config import RandomEventSettings, get_settings
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.services.coin_simulation import DEMO_EVENTS, build_coin_simulator


def _settings(probability=0.2):
    settings = get_settings()
    events = replace(settings.coin.events, scheduled=list(DEMO_EVENTS),
                     random=replace(RandomEventSettings(), probability=probability))
    return replace(settings, coin=replace(settings.coin, events=events))


def _build(mode):
    return build_coin_simulator(_settings(), pricing_mode=mode, include_whales=mode == "random_walk")


def _analyze(sim, ticks):
    return analyze_events(ticks, sim.events.events, initial_price=sim.coin.starting_price,
                          trader_count=len(sim.traders))


def _everything(sim, ticks):
    return {
        "ticks": [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.pool_state,
                   t.event_state) for t in ticks],
        "wallets": [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders],
        "reserve": (sim.reserve.cash, sim.reserve.coins),
        "totals": sim.accounting_totals(),
        "pool": sim.pool.state() if sim.pool else None,
        "events": sim.events.events,
        "rng": (
            sim._price_engine._rng.getstate(),
            sim._volume_model._rng.getstate(),
            [w._rng.getstate() for w in sim.whales],
            [t._rng.getstate() for t in sim.traders],
            sim.event_generator._rng.getstate(),
        ),
    }


# --- non-interference -----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_running_analytics_during_and_after_a_run_changes_nothing(mode):
    plain = _build(mode)
    plain_ticks = plain.run(80)

    observed = _build(mode)
    observed_ticks = []
    for _ in range(8):
        observed_ticks += observed.run(10)
        _analyze(observed, observed_ticks)  # interleaved with the run
    report = _analyze(observed, observed_ticks)

    assert _everything(observed, observed_ticks) == _everything(plain, plain_ticks)
    assert len(report) == len(plain.events.events) >= 3


def test_analytics_use_no_global_randomness_and_leave_inputs_intact():
    sim = _build("random_walk")
    ticks = sim.run(60)
    snapshot = (list(ticks), sim.events.events)
    state = random.getstate()
    _analyze(sim, ticks)
    assert random.getstate() == state
    assert (list(ticks), sim.events.events) == snapshot


def test_default_fingerprinted_runs_are_unaffected_by_analysing_them():
    for mode in ("random_walk", "amm"):
        settings = get_settings()
        first = build_coin_simulator(settings, pricing_mode=mode, include_whales=mode == "random_walk")
        ticks = first.run(200)
        assert analyze_events(ticks, []) == ()
        second = build_coin_simulator(settings, pricing_mode=mode, include_whales=mode == "random_walk")
        assert [(t.price, t.volume, t.trader_trades) for t in second.run(200)] == [
            (t.price, t.volume, t.trader_trades) for t in ticks
        ]


# --- report contents --------------------------------------------------------------------------


def test_scheduled_and_random_events_are_both_observed_with_their_ground_truth():
    sim = _build("random_walk")
    ticks = sim.run(80)
    report = _analyze(sim, ticks)
    ids = [o.ground_truth.event_id for o in report]
    assert {"demo-listing", "demo-incident"} <= set(ids)
    assert any(i not in {"demo-listing", "demo-incident"} for i in ids)
    for observation, event in zip(report, sim.events.events):
        assert observation.ground_truth.event_id == event.event_id
        assert (observation.ground_truth.severity, observation.ground_truth.sentiment) == (event.severity, event.sentiment)
        start = next(t for t in ticks if t.tick == event.start_tick)
        assert observation.market.price_at_start == start.price
        assert observation.pool is None


def test_amm_pool_metrics_match_the_recorded_snapshots_and_swaps():
    sim = _build("amm")
    ticks = sim.run(80)
    by_tick = {t.tick: t for t in ticks}
    pool_before = sim.pool.state()
    report = _analyze(sim, ticks)
    assert sim.pool.state() == pool_before
    checked = 0
    for observation in report:
        truth, pool = observation.ground_truth, observation.pool
        start, end = truth.start_tick, truth.last_active_tick
        window = [by_tick[t] for t in range(start, end + 1) if t in by_tick]
        swaps = [f.swap for t in window for f in t.trader_trades]
        assert pool.swap_count == len(swaps) == observation.trading.trade_count
        assert pool.spot_price_at_start == by_tick[start].pool_state.spot_price
        if start - 1 not in by_tick or end not in by_tick:
            assert pool.coin_reserve_change is None
            continue
        pre, post = by_tick[start - 1].pool_state, by_tick[end].pool_state
        assert pool.spot_price_at_end == post.spot_price
        assert pool.coin_reserve_change == EXACT.subtract(post.coin_reserve, pre.coin_reserve)
        assert pool.cash_reserve_change == EXACT.subtract(post.cash_reserve, pre.cash_reserve)
        fees_cash, fees_coins = Decimal(0), Decimal(0)
        for swap in swaps:
            if swap.side == "buy":
                fees_cash = EXACT.add(fees_cash, swap.fee)
            else:
                fees_coins = EXACT.add(fees_coins, swap.fee)
        assert (pool.fees_cash, pool.fees_coins) == (fees_cash, fees_coins)
        assert float(pool.coin_reserve_change) == pytest.approx(-observation.trading.net_flow, abs=1e-6)
        if swaps:
            assert pool.largest_price_impact == max(abs(s.price_impact) for s in swaps)
        checked += 1
    assert checked >= 2


def test_reports_are_deterministic():
    def report():
        sim = _build("amm")
        return _analyze(sim, sim.run(80))

    assert report() == report()


# --- dependency direction ---------------------------------------------------------------------


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_analytics_reads_core_types_and_the_standard_library_only():
    imported = set()
    for module in Path(analytics_package.__file__).parent.glob("*.py"):
        imported |= _imports(module)
    project = {m for m in imported if m.startswith("crypto_simulator")}
    assert all(m.startswith(("crypto_simulator.core.", "crypto_simulator.analytics")) for m in project)
    assert {m.split(".")[0] for m in imported} - {"crypto_simulator"} <= {
        "__future__", "dataclasses", "decimal", "math", "statistics", "typing",
    }


def test_nothing_in_the_simulator_imports_analytics():
    package = Path(crypto_simulator.__file__).parent
    for layer in ("core", "services", "config", "models", "data"):
        for module in (package / layer).rglob("*.py"):
            assert not any(m.startswith("crypto_simulator.analytics") for m in _imports(module)), module


# --- provenance -----------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_real_runs_tell_scheduled_from_random_events_without_changing_anything(mode):
    plain = _build(mode)
    plain_ticks = plain.run(80)
    sim = _build(mode)
    ticks = sim.run(80)
    generated = sim.event_generator.generated_events
    report = analyze_events(ticks, sim.events.events, initial_price=sim.coin.starting_price,
                            trader_count=len(sim.traders), random_event_ids=[e.event_id for e in generated])
    provenance = {o.ground_truth.event_id: o.ground_truth.randomly_generated for o in report}
    assert provenance == {e.event_id: e in generated for e in sim.events.events}
    assert provenance["demo-listing"] is False and provenance["demo-incident"] is False
    assert sum(provenance.values()) == len(generated) >= 3
    # Metrics are exactly those of the provenance-free report...
    untagged = _analyze(sim, ticks)
    assert [(o.market, o.trading, o.pool, o.overlapping_event_ids) for o in report] == [
        (o.market, o.trading, o.pool, o.overlapping_event_ids) for o in untagged
    ]
    # ...and the run itself, RNG streams included, is untouched.
    assert _everything(sim, ticks) == _everything(plain, plain_ticks)
