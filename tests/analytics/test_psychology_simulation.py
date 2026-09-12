"""Psychology analytics on real simulations: it reads what the run recorded
and changes nothing about the run."""

import hashlib
import math
import random
from dataclasses import replace

import pytest

from crypto_simulator.analytics import COMPONENTS, NEUTRAL, analyze_psychology
from crypto_simulator.config import RandomEventSettings, get_settings
from crypto_simulator.services.coin_simulation import DEMO_EVENTS, build_coin_simulator

BUILDER_FINGERPRINTS = {"random_walk": "d1218e0e0739f776", "amm": "f853009b5818169e"}


def _settings(probability=0.2):
    settings = get_settings()
    events = replace(settings.coin.events, scheduled=list(DEMO_EVENTS),
                     random=replace(RandomEventSettings(), probability=probability))
    return replace(settings, coin=replace(settings.coin, events=events))


def _build(mode, psychology=True, settings=None):
    return build_coin_simulator(settings or _settings(), pricing_mode=mode, include_whales=mode == "random_walk",
                                psychology=psychology)


def _everything(sim, ticks):
    return {
        "ticks": [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.pool_state,
                   t.event_state, t.psychology) for t in ticks],
        "wallets": [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders],
        "reserve": (sim.reserve.cash, sim.reserve.coins),
        "totals": sim.accounting_totals(),
        "pool": sim.pool.state() if sim.pool else None,  # reserves and cumulative fees
        "events": sim.events.events,
        "rng": (
            sim._price_engine._rng.getstate(),
            sim._volume_model._rng.getstate(),
            [w._rng.getstate() for w in sim.whales],
            [t._rng.getstate() for t in sim.traders],
            sim.event_generator._rng.getstate(),
        ),
    }


# --- reads what was recorded ------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_the_report_describes_the_recorded_psychology(mode):
    sim = _build(mode)
    ticks = sim.run(120)
    report = analyze_psychology(ticks, trader_count=len(sim.traders))
    assert (report.ticks, report.ticks_with_psychology) == (120, 120)
    for name in COMPONENTS:
        values = [getattr(t.psychology, name) for t in ticks]
        summary = report.component(name)
        assert summary.mean == math.fsum(values) / len(values)
        assert (summary.minimum, summary.maximum) == (min(values), max(values))
        assert summary.occupancy[1].ticks == sum(v >= 0.5 for v in values)
    assert sum(g.ticks for g in report.dominant) == 120
    assert report.activity.fills == sum(len(t.trader_trades) for t in ticks)
    live = sum(bool(t.event_state.events) for t in ticks)
    periods = report.event_periods
    assert (periods.source, periods.event_period_ticks, periods.other_period_ticks) == ("event_state", live, 120 - live)
    assert 0 < live < 120


def test_a_run_without_psychology_reports_none_rather_than_neutral_states():
    sim = _build("random_walk", psychology=False)
    report = analyze_psychology(sim.run(50))
    assert (report.ticks, report.ticks_with_psychology) == (50, 0)
    assert report.components == () and report.event_periods is None


def test_a_flat_market_reports_neutral_ticks_as_neutral():
    sim = _build("amm", settings=get_settings(), psychology=True)
    for trader in sim.traders:
        trader.trade_probability = 0.0  # nobody trades: flat pool, neutral psychology
    report = analyze_psychology(sim.run(20))
    assert [(g.dominant, g.ticks) for g in report.dominant if g.ticks] == [(NEUTRAL, 20)]
    assert all(c.maximum == 0.0 for c in report.components)


# --- changes nothing --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_analysing_during_and_after_a_run_changes_nothing(mode):
    plain = _build(mode)
    plain_ticks = plain.run(80)

    observed = _build(mode)
    observed_ticks = []
    for _ in range(8):
        observed_ticks += observed.run(10)
        analyze_psychology(observed_ticks, trader_count=len(observed.traders))  # interleaved with the run
    analyze_psychology(observed_ticks, event_ticks=range(1, 40), persistence_threshold=0.5)

    assert _everything(observed, observed_ticks) == _everything(plain, plain_ticks)


def test_analysis_uses_no_global_randomness_and_leaves_inputs_intact():
    sim = _build("amm")
    ticks = sim.run(60)
    snapshot = list(ticks)
    state = random.getstate()
    analyze_psychology(ticks, trader_count=len(sim.traders))
    assert random.getstate() == state
    assert ticks == snapshot


def _fingerprint(sim, ticks):
    view = [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades,
             [(f.trader_id, f.side.value, f.requested_quantity, f.quantity, f.price, f.notional, f.reason)
              for f in t.trader_trades],
             t.pool_state) for t in ticks]
    view.append([(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders])
    view.append((sim.reserve.cash, sim.reserve.coins, sim.accounting_totals()))
    return hashlib.sha256(repr(view).encode()).hexdigest()[:16]


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_default_fingerprinted_runs_are_unaffected_by_analysing_them(mode):
    sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk")
    ticks = []
    for _ in range(10):
        ticks += sim.run(20)
        assert analyze_psychology(ticks).ticks_with_psychology == 0
    assert _fingerprint(sim, ticks) == BUILDER_FINGERPRINTS[mode]


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_reports_on_psychology_runs_are_deterministic(mode):
    def report():
        sim = _build(mode)
        return analyze_psychology(sim.run(80), trader_count=len(sim.traders))

    assert report() == report()


def test_a_long_run_is_analysed_in_one_pass_per_statistic():
    """20,000 ticks: every tick is read a fixed number of times, so this
    stays fast; guards against accidental quadratic work."""
    sim = _build("random_walk", settings=get_settings())
    ticks = sim.run(20_000)
    report = analyze_psychology(ticks, trader_count=len(sim.traders))
    assert report.ticks_with_psychology == 20_000
