"""CoinSimulator + RandomEventGenerator (Phase 6, Step 5).

The generator is consulted at the start of each tick, before that tick's
EventState is read, so a random event is live from its first tick. Its
private RNG stream never touches — and is never touched by — the price,
volume, whale or trader streams.
"""

import math
import random

import pytest

from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import (
    EVENT_CATEGORIES,
    EventEngine,
    EventPhase,
    RandomEventGenerator,
    create_event,
)
from crypto_simulator.core.traders.base import TraderAgent, TradeDecision
from crypto_simulator.core.traders.strategies import MomentumTrader, RetailTrader
from tests.core.test_coin_simulator_amm import GOLDEN_FULL_PRICES
from tests.core.test_coin_simulator_events import _assert_golden_full, _full_sim
from tests.core.test_coin_simulator_sentiment import _amm, _assert_pool_moved_only_by_swaps, _crowd
from tests.core.test_coin_simulator_traders import _coin, _golden_whale

START_PRICE = 2.0


def _generator(probability=1.0, seed=77, **kwargs):
    return RandomEventGenerator(probability=probability, seed=seed, **kwargs)


def _signature(engine):
    return [(e.event_id, e.category, e.severity, e.start_tick, e.duration, e.decay_ticks) for e in engine.events]


class _Recorder(TraderAgent):
    strategy_name = "recorder"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contexts = []

    def _decide(self, context):
        self.contexts.append(context)
        return TradeDecision.hold("recording")


# --- baseline ------------------------------------------------------------------------------


def test_probability_zero_generator_leaves_the_golden_run_unchanged_and_draws_nothing():
    generator = _generator(probability=0.0, seed=5)
    sim = _full_sim(event_generator=generator, drift_per_sentiment=0.02)
    ticks = _assert_golden_full(sim)
    assert [t.price for t in ticks] == GOLDEN_FULL_PRICES
    assert sim.events.events == ()
    assert generator._rng.getstate() == random.Random(5).getstate()


# --- ordering -----------------------------------------------------------------------------


def test_random_walk_event_generated_for_a_tick_drives_that_ticks_step():
    """sigma = 0 and no traders: tick 1's price can only differ from the
    start through tick 1's event, so the event was in place before the
    random-walk step."""
    generator = _generator(categories={"exchange_listing": 1.0}, duration=(3, 3), decay_ticks=(0, 0))
    sim = CoinSimulator(_coin(), seed=4, volatility=0.0, event_generator=generator, drift_per_sentiment=0.01)
    ticks = sim.run(3)
    assert [(s.event_id, s.phase) for s in ticks[0].event_state.events] == [("random-000001", EventPhase.ACTIVE)]
    assert ticks[0].event_state.sentiment > 0
    assert ticks[0].price == START_PRICE * math.exp(0.01 * ticks[0].event_state.sentiment)
    price = START_PRICE
    for tick in ticks:
        price *= math.exp(0.01 * tick.event_state.sentiment)
        assert tick.price == price


def test_amm_traders_see_an_event_on_the_tick_it_starts():
    recorder = _Recorder("rec", trade_probability=1.0, seed=1)
    generator = _generator(categories={"security_incident": 1.0})
    ticks = CoinSimulator(_coin(), seed=3, traders=[recorder], reserve_cash=2_000_000.0, pricing_mode="amm",
                          amm_pool_coins=100_000.0, event_generator=generator).run(4)
    assert ticks[0].event_state.sentiment < 0
    assert [c.sentiment for c in recorder.contexts] == [t.event_state.sentiment for t in ticks]
    assert [c.attention_multiplier for c in recorder.contexts] == [t.event_state.attention_multiplier for t in ticks]


def test_scheduled_and_random_events_on_the_same_tick_both_apply():
    scheduled = create_event("exchange_listing", event_id="sched", severity=1.0, start_tick=1, duration=5)
    generator = _generator(categories={"security_incident": 1.0}, severity=(1.0, 1.0), duration=(5, 5))
    ticks = CoinSimulator(_coin(), seed=1, events=EventEngine([scheduled]), event_generator=generator).run(1)
    state = ticks[0].event_state
    assert [s.event_id for s in state.events] == ["random-000001", "sched"]
    expected = EVENT_CATEGORIES["exchange_listing"].sentiment + EVENT_CATEGORIES["security_incident"].sentiment
    assert state.sentiment == max(-1.0, min(1.0, expected))


# --- RNG isolation ------------------------------------------------------------------------


def _rng_states(sim):
    return {
        "price": sim._price_engine._rng.getstate(),
        "volume": sim._volume_model._rng.getstate(),
        "whales": [w._rng.getstate() for w in sim.whales],
        "traders": [t._rng.getstate() for t in sim.traders],
    }


def test_random_events_consume_no_price_volume_whale_or_trader_randomness():
    """Momentum draws once per decision, and an always-active retail trader
    twice, whatever the news — so every other stream must end exactly where
    it would without any events."""
    def sim(generator=None):
        traders = [
            MomentumTrader("m", starting_cash=50_000.0, starting_coins=50_000.0, trade_probability=0.4, seed=21),
            RetailTrader("r", starting_cash=50_000.0, starting_coins=50_000.0, trade_probability=1.0, seed=22),
        ]
        return CoinSimulator(_coin(), seed=9, whales=[_golden_whale()], traders=traders,
                             reserve_cash=500_000.0, event_generator=generator)

    quiet, newsy = sim(), sim(_generator(probability=0.5))
    quiet.run(150)
    newsy.run(150)
    assert len(newsy.events.events) > 30
    assert _rng_states(newsy) == _rng_states(quiet)


def test_the_random_event_stream_ignores_the_market_and_its_participants():
    def events_of(sim):
        sim.run(80)
        return _signature(sim.events)

    config = dict(probability=0.25, seed=31)
    standalone = EventEngine()
    generator = _generator(**config)
    for tick in range(1, 81):
        generator.maybe_inject(standalone, tick)
    reference = _signature(standalone)
    assert reference
    assert events_of(CoinSimulator(_coin(), seed=1, event_generator=_generator(**config))) == reference
    assert events_of(_full_sim(event_generator=_generator(**config))) == reference
    amm = CoinSimulator(_coin(), seed=3, traders=_crowd(), reserve_cash=2_000_000.0, pricing_mode="amm",
                        amm_pool_coins=100_000.0, event_generator=_generator(**config))
    assert events_of(amm) == reference


# --- mechanisms ---------------------------------------------------------------------------


def test_amm_random_events_move_price_only_through_trader_swaps():
    sim = CoinSimulator(_coin(), seed=3, traders=_crowd(), reserve_cash=2_000_000.0, pricing_mode="amm",
                        amm_pool_coins=100_000.0, event_generator=_generator(probability=0.2, seed=5))
    initial_state, totals = sim.pool.state(), sim.accounting_totals()
    ticks = sim.run(60)
    quiet = _amm(_crowd()).run(60)
    assert any(t.event_state.sentiment != 0 for t in ticks)
    assert [t.trader_trades for t in ticks] != [t.trader_trades for t in quiet]
    _assert_pool_moved_only_by_swaps(sim, ticks, initial_state)
    assert sim.accounting_totals() == totals
    assert all(t.wallet.cash >= 0 and t.wallet.coins >= 0 for t in sim.traders)


def test_amm_random_events_without_traders_never_touch_the_pool():
    sim = CoinSimulator(_coin(), seed=3, reserve_cash=2_000_000.0, pricing_mode="amm", amm_pool_coins=100_000.0,
                        event_generator=_generator())
    initial_state = sim.pool.state()
    ticks = sim.run(50)
    assert len(sim.events.events) == 50
    assert all(t.pool_state == initial_state for t in ticks)


def test_random_walk_random_events_act_only_through_the_step2_process():
    """sigma = 0, no traders: the price path is exactly the accumulated
    drift of whatever sentiment the random events produced."""
    sim = CoinSimulator(_coin(), seed=4, volatility=0.0, drift_per_sentiment=0.01,
                        event_generator=_generator(probability=0.3, seed=8))
    ticks = sim.run(60)
    assert len(sim.events.events) > 5
    accumulated = 0.0
    price = START_PRICE
    for tick in ticks:
        accumulated += 0.01 * tick.event_state.sentiment
        price *= math.exp(0.01 * tick.event_state.sentiment)
        assert tick.price == price
    assert ticks[-1].price == pytest.approx(START_PRICE * math.exp(accumulated), rel=1e-12)


def test_runs_with_random_events_are_deterministic():
    def run():
        sim = _full_sim(event_generator=_generator(probability=0.3, seed=2), drift_per_sentiment=0.01)
        ticks = [(t.price, t.volume, t.whale_trades, t.trader_trades, t.event_state) for t in sim.run(60)]
        return ticks, [(t.trader_id, t.wallet.cash, t.wallet.coins) for t in sim.traders]

    assert run() == run()
