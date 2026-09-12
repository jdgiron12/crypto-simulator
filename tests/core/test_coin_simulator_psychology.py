"""Market psychology inside the simulation (Phase 7, Step 3).

``CoinSimulator(psychology=True)`` computes one ``PsychologyState`` per tick
from completed closes and the tick's events, and hands it to traders on a
``PsychologyContext``. Off (the default), nothing changes: traders get the
plain ``MarketContext`` and every golden and fingerprinted run is
bit-identical.
"""

import dataclasses
import hashlib
import itertools
import math
import random

import pytest

from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator, live_event_severity
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.psychology import (
    SIGNAL_WINDOW,
    MarketSignals,
    PsychologyState,
    compute_psychology,
    signals_from_closes,
)
from crypto_simulator.core.traders.base import MarketContext, PsychologyContext, TradeDecision, TraderAgent
from crypto_simulator.core.traders.strategies import RetailTrader
from crypto_simulator.services.coin_simulation import DEMO_EVENTS, build_coin_simulator
from tests.core.test_coin_simulator_amm import GOLDEN_FULL_PRICES, GOLDEN_FULL_WALLETS
from tests.core.test_coin_simulator_sentiment import _assert_pool_moved_only_by_swaps, _crowd
from tests.core.test_coin_simulator_traders import _all_five, _coin, _golden_whale

BUILDER_FINGERPRINTS = {"random_walk": "d1218e0e0739f776", "amm": "f853009b5818169e"}


def _event(event_id="news", severity=0.8, start_tick=3, duration=2, decay_ticks=3, sentiment=0.0, attention=0.0):
    return MarketEvent(
        event_id=event_id, category="custom", severity=severity, sentiment=sentiment, volatility_boost=0.0,
        attention=attention, start_tick=start_tick, duration=duration, decay_ticks=decay_ticks,
    )


def _quiet_amm(events=None, traders=None, psychology=True):
    """No traders: the pool never moves, so every price signal is flat."""
    return CoinSimulator(
        _coin(), seed=3, traders=traders, reserve_cash=2_000_000.0, pricing_mode="amm",
        amm_pool_coins=100_000.0, events=events, psychology=psychology,
    )


def _demo_settings():
    settings = get_settings()
    return dataclasses.replace(
        settings, coin=dataclasses.replace(
            settings.coin, events=dataclasses.replace(settings.coin.events, scheduled=list(DEMO_EVENTS)),
        ),
    )


def _build(mode, psychology=True, settings=None):
    return build_coin_simulator(
        settings or _demo_settings(), pricing_mode=mode, include_whales=mode == "random_walk", psychology=psychology,
    )


def _everything(sim, ticks):
    return (
        [(t.tick, t.price, t.volume, t.whale_trades, t.trader_trades, t.pool_state, t.event_state, t.psychology)
         for t in ticks],
        [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders],
        sim.accounting_totals(),
        [t._rng.getstate() for t in sim.traders],
    )


def _other_rng_states(sim):
    """Every RNG stream except the traders' own."""
    return (
        sim._price_engine._rng.getstate(),
        sim._volume_model._rng.getstate(),
        [w._rng.getstate() for w in sim.whales],
        sim.event_generator._rng.getstate() if sim.event_generator else None,
    )


# --- A: event severity -------------------------------------------------------------------------


def test_no_live_event_means_zero_severity():
    engine = EventEngine([_event(start_tick=5)])
    assert live_event_severity(engine.state(4), engine) == 0.0
    assert live_event_severity(engine.state(100), engine) == 0.0
    assert live_event_severity(EventEngine().state(1), EventEngine()) == 0.0


def test_one_active_event_gives_its_severity():
    engine = EventEngine([_event(severity=0.65, start_tick=2, duration=3)])
    assert [live_event_severity(engine.state(t), engine) for t in (2, 3, 4)] == [0.65] * 3


def test_overlapping_events_give_the_strongest_bounded_severity():
    engine = EventEngine([_event("a", 0.9, start_tick=1, duration=5), _event("b", 0.8, start_tick=2, duration=5),
                          _event("c", 1.0, start_tick=3, duration=1, decay_ticks=0)])
    severities = [live_event_severity(engine.state(t), engine) for t in range(1, 8)]
    assert severities == [0.9, 0.9, 1.0, 0.9, 0.9, 0.8, 0.8 * 0.75]
    assert all(0.0 <= s <= 1.0 for s in severities)


def test_a_stronger_event_gives_a_stronger_severity():
    values = []
    for severity in (0.2, 0.5, 0.9):
        engine = EventEngine([_event(severity=severity)])
        values.append(live_event_severity(engine.state(3), engine))
    assert values == [0.2, 0.5, 0.9]


def test_decay_fades_the_effective_severity():
    engine = EventEngine([_event(severity=0.8, start_tick=3, duration=2, decay_ticks=3)])
    severities = [live_event_severity(engine.state(t), engine) for t in range(1, 9)]
    assert severities == [0.0, 0.0, 0.8, 0.8, 0.8 * 0.75, 0.8 * 0.5, 0.8 * 0.25, 0.0]


def test_event_order_does_not_change_the_severity():
    events = [_event("a", 0.3, start_tick=1, duration=4, decay_ticks=4), _event("b", 0.9, start_tick=3, decay_ticks=5),
              _event("c", 0.6, start_tick=2, duration=6)]
    reference = None
    for order in itertools.permutations(events):
        engine = EventEngine(order)
        severities = [live_event_severity(engine.state(t), engine) for t in range(1, 15)]
        reference = reference or severities
        assert severities == reference


def test_the_simulator_feeds_decaying_severity_into_psychology_rather_than_zero():
    """A pure-severity event (no sentiment, attention or volatility) over a
    flat market: uncertainty is exactly tanh(severity × intensity)."""
    sim = _quiet_amm(EventEngine([_event(severity=0.8, start_tick=3, duration=2, decay_ticks=3)]))
    ticks = sim.run(9)
    intensities = [0.0, 0.0, 1.0, 1.0, 0.75, 0.5, 0.25, 0.0, 0.0]
    assert [t.psychology for t in ticks] == [PsychologyState(uncertainty=math.tanh(0.8 * i)) for i in intensities]
    assert ticks[2].psychology.uncertainty > 0.0


# --- B: psychology signals ---------------------------------------------------------------------


def test_neutral_signals_give_neutral_psychology_every_tick():
    sim = _quiet_amm()
    ticks = sim.run(20)
    assert all(t.psychology == PsychologyState.neutral() for t in ticks)
    assert sim.market_signals(None) == MarketSignals()


def test_identical_inputs_give_identical_psychology():
    runs = [[t.psychology for t in _build("random_walk").run(80)] for _ in range(2)]
    assert runs[0] == runs[1]
    assert any(p != PsychologyState.neutral() for p in runs[0])


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("with_events", [False, True])
def test_psychology_at_tick_n_uses_completed_closes_and_that_ticks_news(mode, with_events):
    sim = _build(mode, settings=_demo_settings() if with_events else get_settings())
    opening = sim.current_price
    ticks = sim.run(30)
    closes = [opening] + [t.price for t in ticks]
    for i, tick in enumerate(ticks):
        window = closes[max(0, i - SIGNAL_WINDOW): i + 1]  # through tick i-1 only: closes[i] is its close
        news = {}
        if tick.event_state is not None:
            news = dict(event_sentiment=tick.event_state.sentiment, attention=tick.event_state.attention_multiplier,
                        event_severity=live_event_severity(tick.event_state, sim.events))
        assert tick.psychology == compute_psychology(signals_from_closes(window, **news))
    assert any(t.event_state and t.event_state.events for t in ticks) is with_events


def test_psychology_adds_no_random_draws_to_the_simulation():
    """With no traders to react, psychology changes nothing at all."""
    def run(psychology):
        sim = CoinSimulator(_coin(), seed=3, whales=[_golden_whale()], psychology=psychology,
                            events=EventEngine([_event(sentiment=-0.8, attention=2.0)]))
        ticks = sim.run(40)
        return [(t.price, t.volume, t.whale_trades, t.event_state) for t in ticks], _other_rng_states(sim)

    assert run(True) == run(False)


# --- F: integration ------------------------------------------------------------------------------


def _check_wallets(sim):
    for wallet in (sim.reserve, *(t.wallet for t in sim.traders)):
        assert wallet.cash >= 0.0 and wallet.coins >= 0.0


def test_random_walk_simulation_runs_with_psychology_and_it_changes_trading():
    sim = _build("random_walk")
    coins, cash = sim.reserve.coins + sum(t.wallet.coins for t in sim.traders), sim.reserve.cash + sum(t.wallet.cash for t in sim.traders)
    ticks = []
    for _ in range(200):
        ticks.append(sim.step())
        _check_wallets(sim)
    assert all(isinstance(t.psychology, PsychologyState) and t.price > 0 for t in ticks)
    assert {"fear", "fomo"} <= {f for t in ticks for f in ("fear", "fomo", "conviction") if getattr(t.psychology, f) > 0.1}
    assert sim.reserve.coins + sum(t.wallet.coins for t in sim.traders) == pytest.approx(coins, rel=1e-12)
    assert sim.reserve.cash + sum(t.wallet.cash for t in sim.traders) == pytest.approx(cash, rel=1e-12)
    baseline = _build("random_walk", psychology=False).run(200)
    assert [t.trader_trades for t in ticks] != [t.trader_trades for t in baseline]


def test_amm_simulation_runs_with_psychology_and_accounting_stays_exact():
    sim = _build("amm")
    initial_state, totals = sim.pool.state(), sim.accounting_totals()
    ticks = []
    for _ in range(200):
        ticks.append(sim.step())
        _check_wallets(sim)
        assert sim.accounting_totals() == totals
    assert all(isinstance(t.psychology, PsychologyState) for t in ticks)
    _assert_pool_moved_only_by_swaps(sim, ticks, initial_state)
    baseline = _build("amm", psychology=False).run(200)
    assert [t.trader_trades for t in ticks] != [t.trader_trades for t in baseline]


def test_amm_psychology_moves_price_only_through_swaps_with_a_crowd_and_bad_news():
    engine = EventEngine([_event(severity=1.0, sentiment=-0.8, attention=1.0, start_tick=5, duration=20, decay_ticks=5)])
    sim = CoinSimulator(_coin(), seed=3, traders=_crowd(), reserve_cash=2_000_000.0, pricing_mode="amm",
                        amm_pool_coins=100_000.0, events=engine, psychology=True)
    initial_state, totals = sim.pool.state(), sim.accounting_totals()
    ticks = sim.run(40)
    assert max(t.psychology.fear for t in ticks) > 0.5
    _assert_pool_moved_only_by_swaps(sim, ticks, initial_state)
    assert sim.accounting_totals() == totals
    _check_wallets(sim)


def test_random_walk_psychology_never_sets_the_price_directly():
    """Traders that never act: psychology on or off, prices are identical."""
    def prices(psychology):
        traders = _all_five(trade_probability=0.0)
        sim = CoinSimulator(_coin(), seed=3, whales=[_golden_whale()], traders=traders, reserve_cash=500_000.0,
                            events=EventEngine([_event(sentiment=0.9, attention=3.0)]), psychology=psychology)
        return [t.price for t in sim.run(40)]

    assert prices(True) == prices(False)


# --- G: determinism --------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_same_seed_and_configuration_give_identical_results(mode):
    first, second = _build(mode), _build(mode)
    assert _everything(first, first.run(120)) == _everything(second, second.run(120))


def test_a_psychology_run_touches_no_global_randomness():
    state = random.getstate()
    for mode in ("random_walk", "amm"):
        _build(mode).run(60)
    assert random.getstate() == state


def test_non_trader_rng_streams_are_the_same_with_psychology_on_or_off():
    settings = _demo_settings()
    settings = dataclasses.replace(settings, coin=dataclasses.replace(
        settings.coin, events=dataclasses.replace(
            settings.coin.events, random=dataclasses.replace(settings.coin.events.random, probability=0.1)),
    ))
    on, off = _build("random_walk", True, settings), _build("random_walk", False, settings)
    on_ticks, off_ticks = on.run(150), off.run(150)
    assert _other_rng_states(on) == _other_rng_states(off)
    assert on.events.events == off.events.events
    assert [t.whale_trades for t in on_ticks] == [t.whale_trades for t in off_ticks]


# --- H: regression ---------------------------------------------------------------------------------


class _ContextRecorder(TraderAgent):
    strategy_name = "recorder"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def _decide(self, context):
        self.seen.append(context)
        return TradeDecision.hold("recording")


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_psychology_is_off_by_default_and_traders_get_the_plain_market_context(mode):
    recorder = _ContextRecorder("rec", trade_probability=1.0)
    sim = CoinSimulator(_coin(), seed=3, traders=[recorder], reserve_cash=2_000_000.0, pricing_mode=mode)
    ticks = sim.run(10)
    assert sim.psychology_enabled is False
    assert all(t.psychology is None for t in ticks)
    assert {type(c) for c in recorder.seen} == {MarketContext}


def test_with_psychology_on_traders_get_a_psychology_context_matching_the_tick():
    recorder = _ContextRecorder("rec", trade_probability=1.0)
    sim = CoinSimulator(_coin(), seed=3, traders=[recorder, RetailTrader("r", starting_cash=1e4, seed=1)],
                        psychology=True)
    ticks = sim.run(10)
    assert all(type(c) is PsychologyContext for c in recorder.seen)
    assert [c.psychology for c in recorder.seen] == [t.psychology for t in ticks]
    # The psychology window (SIGNAL_WINDOW + 1 closes) doesn't widen the
    # price history traders see: still sized by their longest lookback.
    assert {len(c.price_history) for c in recorder.seen} == {1}


def test_explicit_psychology_false_reproduces_the_golden_run():
    sim = CoinSimulator(_coin(), seed=3, whales=[_golden_whale()], traders=_all_five(), reserve_cash=500_000.0,
                        psychology=False)
    assert [t.price for t in sim.run(60)] == GOLDEN_FULL_PRICES
    assert [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders] == GOLDEN_FULL_WALLETS


def _builder_fingerprint(sim):
    ticks = sim.run(200)
    view = [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades,
             [(f.trader_id, f.side.value, f.requested_quantity, f.quantity, f.price, f.notional, f.reason)
              for f in t.trader_trades],
             t.pool_state) for t in ticks]
    view.append([(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders])
    view.append((sim.reserve.cash, sim.reserve.coins, sim.accounting_totals()))
    return hashlib.sha256(repr(view).encode()).hexdigest()[:16]


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("kwargs", [{}, {"psychology": False}])
def test_200_tick_builder_fingerprints_are_unchanged(mode, kwargs):
    sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk", **kwargs)
    assert _builder_fingerprint(sim) == BUILDER_FINGERPRINTS[mode]


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_psychology_on_does_change_the_builder_fingerprint(mode):
    sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk", psychology=True)
    assert _builder_fingerprint(sim) != BUILDER_FINGERPRINTS[mode]


@pytest.mark.parametrize("value", [1, "yes", None])
def test_psychology_flag_must_be_a_bool(value):
    with pytest.raises(ValueError, match="psychology"):
        CoinSimulator(_coin(), psychology=value)


def test_market_signals_need_psychology_enabled():
    with pytest.raises(RuntimeError, match="psychology=True"):
        CoinSimulator(_coin()).market_signals(None)
