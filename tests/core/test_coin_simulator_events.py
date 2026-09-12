"""CoinSimulator + news events, random-walk mode (Phase 6, Step 2).

Events act on the random walk itself: volatility is scaled by the tick's
``EventState.volatility_multiplier`` and, only when ``drift_per_sentiment``
is nonzero, a drift of ``drift_per_sentiment * sentiment`` is added. The
golden values from the earlier phases pin that "no effective event" runs
are bit-for-bit unchanged.
"""

import math
import random

import pytest

from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, EventPhase, EventState, EventStatus, MarketEvent
from tests.core.test_coin_simulator_amm import (
    GOLDEN_FULL_FILLS_SHA256,
    GOLDEN_FULL_PRICES,
    GOLDEN_FULL_RESERVE,
    GOLDEN_FULL_VOLUMES_SHA256,
    GOLDEN_FULL_WALLETS,
    GOLDEN_FULL_WHALES_SHA256,
    _sha,
)
from tests.core.test_coin_simulator_traders import (
    GOLDEN_PLAIN_PRICES,
    GOLDEN_PLAIN_VOLUMES,
    _all_five,
    _coin,
    _golden_whale,
)

START_PRICE = 2.0  # _coin()'s starting price


def _event(event_id="e", sentiment=0.0, volatility_boost=0.0, start_tick=1, duration=1_000, decay_ticks=0):
    return MarketEvent(
        event_id=event_id, category="custom", severity=1.0, sentiment=sentiment,
        volatility_boost=volatility_boost, attention=0.0,
        start_tick=start_tick, duration=duration, decay_ticks=decay_ticks,
    )


def _full_sim(**kwargs):
    """The whale + five-trader random-walk run pinned by GOLDEN_FULL_*."""
    return CoinSimulator(
        _coin(), seed=3, whales=[_golden_whale()], traders=_all_five(), reserve_cash=500_000.0, **kwargs
    )


def _assert_golden_full(sim):
    ticks = sim.run(60)
    fills = [
        (t.tick, f.trader_id, f.side.value, f.requested_quantity, f.quantity, f.price, f.notional)
        for t in ticks for f in t.trader_trades
    ]
    whales = [(t.tick, w.side, w.quantity, w.price_impact) for t in ticks for w in t.whale_trades]
    assert [t.price for t in ticks] == GOLDEN_FULL_PRICES
    assert _sha([t.volume for t in ticks]) == GOLDEN_FULL_VOLUMES_SHA256
    assert _sha(fills) == GOLDEN_FULL_FILLS_SHA256
    assert _sha(whales) == GOLDEN_FULL_WHALES_SHA256
    assert [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders] == GOLDEN_FULL_WALLETS
    assert (sim.reserve.cash, sim.reserve.coins) == GOLDEN_FULL_RESERVE
    return ticks


def _assert_golden_plain(sim):
    ticks = sim.run(10)
    assert [t.price for t in ticks] == GOLDEN_PLAIN_PRICES
    assert [t.volume for t in ticks] == GOLDEN_PLAIN_VOLUMES
    return ticks


def _gauss_stream(seed, n):
    """The exact normal draws the simulator's price engine makes for ``seed``."""
    rng = random.Random(seed)
    return [rng.gauss(0.0, 1.0) for _ in range(n)]


# --- baseline: no effective event is bit-identical -----------------------------------------


def test_without_an_event_engine_output_is_unchanged_and_event_state_is_none():
    ticks = _assert_golden_full(_full_sim())
    assert all(t.event_state is None for t in ticks)
    assert all(t.event_state is None for t in _assert_golden_plain(CoinSimulator(_coin(), seed=1)))


@pytest.mark.parametrize("drift_per_sentiment", [0.0, 0.02])
def test_empty_event_engine_is_bit_identical_to_the_baseline(drift_per_sentiment):
    ticks = _assert_golden_full(_full_sim(events=EventEngine(), drift_per_sentiment=drift_per_sentiment))
    assert [t.event_state for t in ticks] == [EventState(tick=t.tick) for t in ticks]
    _assert_golden_plain(CoinSimulator(_coin(), seed=1, events=EventEngine(), drift_per_sentiment=drift_per_sentiment))


def test_event_scheduled_after_the_run_is_bit_identical_to_the_baseline():
    late = _event(sentiment=-1.0, volatility_boost=3.0, start_tick=61, duration=5)
    engine = EventEngine([late])
    ticks = _assert_golden_full(_full_sim(events=engine, drift_per_sentiment=0.02))
    assert all(t.event_state == EventState(tick=t.tick) for t in ticks)
    assert engine.events == (late,)
    _assert_golden_plain(CoinSimulator(_coin(), seed=1, events=EventEngine([late]), drift_per_sentiment=0.02))


@pytest.mark.parametrize("sentiment", [0.9, -1.0])
def test_zero_drift_sentiment_only_event_changes_nothing(sentiment):
    """drift_per_sentiment=0 (the default): a live sentiment-only event has
    no price channel of its own — with every trader's sentiment
    sensitivity at 0, the whole run, whales and traders included, is
    unchanged bit for bit. (Traders that do react are Step 3's tests.)"""
    engine = EventEngine([_event(sentiment=sentiment, start_tick=1, duration=60)])
    sim = _full_sim(events=engine)
    for trader in sim.traders:
        trader.sentiment_sensitivity = 0.0
    ticks = _assert_golden_full(sim)
    assert all(t.event_state.sentiment == sentiment for t in ticks)
    assert all(t.event_state.events[0].phase is EventPhase.ACTIVE for t in ticks)
    _assert_golden_plain(CoinSimulator(_coin(), seed=1, events=EventEngine([_event(sentiment=sentiment)])))


def test_default_drift_per_sentiment_is_zero():
    assert CoinSimulator(_coin()).drift_per_sentiment == 0.0


# --- exact event math -----------------------------------------------------------------------


def test_sentiment_drift_with_zero_volatility_is_exactly_exponential():
    event = _event(sentiment=0.6, start_tick=3, duration=5, decay_ticks=4)
    sim = CoinSimulator(_coin(), seed=4, volatility=0.0, events=EventEngine([event]), drift_per_sentiment=0.01)
    ticks = sim.run(15)
    drifts = [0.01 * t.event_state.sentiment for t in ticks]
    assert [t.event_state.sentiment for t in ticks] == [0.6 * event.intensity_at(t.tick) for t in ticks]
    price = START_PRICE
    for tick, drift in zip(ticks, drifts):
        price *= math.exp(drift)
        assert tick.price == price
    assert ticks[-1].price == pytest.approx(START_PRICE * math.exp(sum(drifts)), rel=1e-12)


def test_event_return_matches_the_formula_exactly_using_the_baseline_normal_draws():
    seed, sigma = 21, 0.03
    event = _event(sentiment=-0.5, volatility_boost=1.5, start_tick=4, duration=3, decay_ticks=3)
    z_stream = _gauss_stream(seed, 12)

    baseline = CoinSimulator(_coin(), seed=seed, volatility=sigma).run(12)
    price = START_PRICE
    for tick, z in zip(baseline, z_stream):
        price *= math.exp(-0.5 * sigma**2 + sigma * z)
        assert tick.price == price

    with_event = CoinSimulator(
        _coin(), seed=seed, volatility=sigma, events=EventEngine([event]), drift_per_sentiment=0.01
    ).run(12)
    price = START_PRICE
    for tick, z in zip(with_event, z_stream):
        drift_t = 0.01 * tick.event_state.sentiment
        sigma_t = sigma * tick.event_state.volatility_multiplier
        price *= math.exp(drift_t - 0.5 * sigma_t**2 + sigma_t * z)
        assert tick.price == price
    assert [t.volume for t in with_event] == [t.volume for t in baseline]


def test_decaying_intensity_drives_drift_and_volatility_tick_by_tick():
    event = _event(sentiment=0.5, volatility_boost=2.0, start_tick=2, duration=2, decay_ticks=3)
    ticks = CoinSimulator(
        _coin(), seed=8, volatility=0.0, events=EventEngine([event]), drift_per_sentiment=0.04
    ).run(8)
    intensities = [0.0, 1.0, 1.0, 0.75, 0.5, 0.25, 0.0, 0.0]
    phases = [t.event_state.events[0].phase if t.event_state.events else None for t in ticks]
    assert phases == [None, EventPhase.ACTIVE, EventPhase.ACTIVE, *[EventPhase.DECAYING] * 3, None, None]
    assert [t.event_state.volatility_multiplier for t in ticks] == [1.0 + 2.0 * i for i in intensities]
    prices = [t.price for t in ticks]
    log_returns = [math.log(b / a) for a, b in zip([START_PRICE, *prices], prices)]
    assert log_returns == pytest.approx([0.04 * 0.5 * i for i in intensities], abs=1e-15)


@pytest.mark.parametrize("sentiment, direction", [(0.8, 1), (-0.8, -1)])
def test_positive_and_negative_events_push_price_in_their_direction(sentiment, direction):
    seed, start = 13, 5
    baseline = CoinSimulator(_coin(), seed=seed).run(20)
    engine = EventEngine([_event(sentiment=sentiment, start_tick=start, duration=10)])
    shocked = CoinSimulator(_coin(), seed=seed, events=engine, drift_per_sentiment=0.01).run(20)

    # Nothing changes before the event's first tick; everything after is
    # the baseline scaled by exp(accumulated drift), with the same draws.
    assert [t.price for t in shocked[: start - 1]] == [t.price for t in baseline[: start - 1]]
    assert shocked[start - 1].price != baseline[start - 1].price
    accumulated = 0.0
    for base, tick in zip(baseline, shocked):
        accumulated += 0.01 * tick.event_state.sentiment
        assert tick.price / base.price == pytest.approx(math.exp(accumulated), rel=1e-12)
    assert direction * (shocked[-1].price - baseline[-1].price) > 0
    assert shocked[-1].price / baseline[-1].price == pytest.approx(math.exp(direction * 0.08), rel=1e-12)


def test_prices_stay_positive_and_finite_under_a_long_severe_shock():
    engine = EventEngine([_event(sentiment=-1.0, volatility_boost=2.0, start_tick=1, duration=3_000)])
    ticks = CoinSimulator(_coin(), seed=2, volatility=0.03, events=engine, drift_per_sentiment=0.02).run(3_000)
    assert all(0.0 < t.price < math.inf for t in ticks)
    assert ticks[-1].price < 1e-20  # it really did crash, without reaching zero


def test_a_drift_that_would_zero_the_price_raises_instead():
    engine = EventEngine([_event(sentiment=-1.0, start_tick=1)])
    sim = CoinSimulator(_coin(), seed=2, events=engine, drift_per_sentiment=1_000.0)
    with pytest.raises(ValueError, match="must stay positive and finite"):
        sim.step()


# --- SimulationTick.event_state ------------------------------------------------------------


def test_event_state_is_this_ticks_ground_truth():
    event = _event("listing", sentiment=0.4, volatility_boost=0.5, start_tick=3, duration=2, decay_ticks=1)
    ticks = CoinSimulator(_coin(), seed=1, events=EventEngine([event])).run(7)
    assert [t.event_state.tick for t in ticks] == [t.tick for t in ticks] == list(range(1, 8))
    live = {t.tick: t.event_state.events for t in ticks if t.event_state.events}
    assert live == {
        3: (EventStatus("listing", "custom", EventPhase.ACTIVE, 1.0),),
        4: (EventStatus("listing", "custom", EventPhase.ACTIVE, 1.0),),
        5: (EventStatus("listing", "custom", EventPhase.DECAYING, 0.5),),
    }
    assert all(t.event_state == EventState(tick=t.tick) for t in ticks if t.tick not in live)


def test_event_runs_are_deterministic():
    def run():
        engine = EventEngine([_event(sentiment=-0.7, volatility_boost=1.0, start_tick=10, duration=20, decay_ticks=10)])
        return [(t.price, t.volume, t.whale_trades, t.trader_trades, t.event_state)
                for t in _full_sim(events=engine, drift_per_sentiment=0.01).run(60)]

    assert run() == run()


# --- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-0.01, math.nan, math.inf, True, "0.01"])
def test_invalid_drift_per_sentiment_is_rejected(value):
    with pytest.raises(ValueError, match="drift_per_sentiment"):
        CoinSimulator(_coin(), drift_per_sentiment=value)


def test_amm_mode_accepts_events_but_rejects_a_random_walk_drift():
    sim = CoinSimulator(_coin(), reserve_cash=1_000_000.0, pricing_mode="amm", events=EventEngine())
    assert sim.run(3)[-1].event_state == EventState(tick=3)
    with pytest.raises(ValueError, match="drift_per_sentiment only applies"):
        CoinSimulator(
            _coin(), reserve_cash=1_000_000.0, pricing_mode="amm", events=EventEngine(), drift_per_sentiment=0.01
        )
