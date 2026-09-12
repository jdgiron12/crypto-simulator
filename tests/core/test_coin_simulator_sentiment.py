"""News → traders → trades → price (Phase 6, Step 3).

In AMM mode the only way an event can move the price is through traders'
ordinary swaps; in random-walk mode traders' news-driven fills go through
the existing linear impact and nothing else is added on top of Step 2's
random-walk adjustment.
"""

import math
import random
from decimal import Decimal

import pytest

from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import net_flow_price_impact
from crypto_simulator.core.traders.manipulation import PumpAndDump
from crypto_simulator.core.traders.strategies import MomentumTrader, PanicSeller, RetailTrader
from tests.core.test_coin_simulator_traders import SUPPLY, _coin


def _event(sentiment, attention=0.0, volatility_boost=0.0, start_tick=5, duration=30):
    return MarketEvent(
        event_id="news", category="custom", severity=1.0, sentiment=sentiment,
        volatility_boost=volatility_boost, attention=attention, start_tick=start_tick, duration=duration,
    )


def _crowd():
    retail = [
        RetailTrader(f"retail-{i}", starting_cash=20_000.0, starting_coins=10_000.0, trade_probability=0.7,
                     max_trade_size=2_000.0, risk_tolerance=0.3, seed=50 + i)
        for i in range(5)
    ]
    return retail + [
        MomentumTrader("momentum", starting_cash=20_000.0, starting_coins=10_000.0, lookback=3,
                       entry_threshold=0.03, exit_threshold=0.03, trade_probability=0.7,
                       max_trade_size=5_000.0, risk_tolerance=0.3, seed=60),
        PanicSeller("panic", starting_cash=5_000.0, starting_coins=20_000.0, lookback=3,
                    trade_probability=0.8, max_trade_size=5_000.0, risk_tolerance=0.5, seed=61),
    ]


def _amm(traders, events=None):
    return CoinSimulator(
        _coin(), seed=3, traders=traders, reserve_cash=2_000_000.0,
        pricing_mode="amm", amm_pool_coins=100_000.0, events=events,
    )


def _net_flow(ticks):
    return sum(f.quantity if f.side is TradeAction.BUY else -f.quantity for t in ticks for f in t.trader_trades)


def _exact_sum(values):
    total = Decimal(0)
    for value in values:
        total = EXACT.add(total, value)
    return total


def _assert_pool_moved_only_by_swaps(sim, ticks, initial_state):
    """Across the whole run the spot price only ever changes inside a
    recorded swap, the reserves after each tick are exactly the last swap's,
    and fee counters are exactly the sum of per-swap fees."""
    spot = initial_state.spot_price
    previous = initial_state
    swaps = []
    for tick in ticks:
        tick_swaps = [fill.swap for fill in tick.trader_trades]
        assert all(swap is not None for swap in tick_swaps)
        for swap in tick_swaps:
            assert swap.spot_price_before == spot
            spot = swap.spot_price_after
        if tick_swaps:
            assert (tick.pool_state.coin_reserve, tick.pool_state.cash_reserve) == (
                tick_swaps[-1].coin_reserve_after, tick_swaps[-1].cash_reserve_after,
            )
        else:
            assert tick.pool_state == previous
        assert tick.pool_state.spot_price == spot
        assert tick.price == float(spot)
        swaps.extend(tick_swaps)
        previous = tick.pool_state
    assert sim.pool.swap_count == len(swaps)
    assert sim.pool.fees_collected_cash == _exact_sum(s.fee for s in swaps if s.side == "buy")
    assert sim.pool.fees_collected_coins == _exact_sum(s.fee for s in swaps if s.side == "sell")


# --- AMM: news reaches the pool only through swaps -----------------------------------------------


@pytest.mark.parametrize("sentiment, direction", [(0.8, 1), (-0.8, -1)])
def test_amm_news_moves_price_through_trader_swaps(sentiment, direction):
    """The news is live on ticks 5-34. The crowd leans with it at first;
    later in a long event cash (or coins) run out and the move partly
    unwinds, and after the event it keeps unwinding — so direction is
    asserted on price while the news is live, and on flow early on."""
    baseline_sim = _amm(_crowd())
    baseline = baseline_sim.run(40)
    sim = _amm(_crowd(), EventEngine([_event(sentiment, start_tick=5, duration=30)]))
    initial_state, totals = sim.pool.state(), sim.accounting_totals()
    ticks = sim.run(40)

    # Identical until the news breaks.
    assert [(t.trader_trades, t.pool_state) for t in ticks[:4]] == [(t.trader_trades, t.pool_state) for t in baseline[:4]]
    # The crowd's net flow leans with the news over the first half of the event...
    assert direction * (_net_flow(ticks[4:19]) - _net_flow(baseline[4:19])) > 0
    # ...and the price sits on the news' side of the baseline while it is
    # live. (Not necessarily on every tick: a late-event unwind can briefly
    # cross the baseline; across 20 trader-seed sets the share was >= 83%.)
    news_side = [direction * (tick.price - base.price) > 0 for tick, base in zip(ticks[5:34], baseline[5:34])]
    assert sum(news_side) >= 0.8 * len(news_side)

    _assert_pool_moved_only_by_swaps(sim, ticks, initial_state)
    assert sim.accounting_totals() == totals
    for trader in sim.traders:
        assert trader.wallet.cash >= 0.0 and trader.wallet.coins >= 0.0


def test_amm_news_with_no_traders_never_touches_the_pool():
    engine = EventEngine([_event(-1.0, attention=5.0, volatility_boost=5.0, start_tick=1, duration=50)])
    sim = _amm([], engine)
    initial_state = sim.pool.state()
    ticks = sim.run(50)
    assert all(t.pool_state == initial_state for t in ticks)
    assert all(t.price == sim.coin.starting_price for t in ticks)
    assert ticks[0].event_state.sentiment == -1.0


def test_amm_attention_adds_trades_without_setting_their_direction():
    quiet = _amm(_crowd()).run(30)
    busy_sim = _amm(_crowd(), EventEngine([_event(0.0, attention=1.0, start_tick=1, duration=30)]))
    initial_state = busy_sim.pool.state()
    busy = busy_sim.run(30)
    assert sum(len(t.trader_trades) for t in busy) > sum(len(t.trader_trades) for t in quiet)
    assert all(t.event_state.sentiment == 0.0 for t in busy)
    _assert_pool_moved_only_by_swaps(busy_sim, busy, initial_state)


def test_amm_manipulator_schedule_is_unaffected_by_news():
    def run(events):
        pump = PumpAndDump("pump", starting_cash=30_000.0, trade_probability=1.0, max_trade_size=1e9,
                           risk_tolerance=1.0, start_tick=3, accumulate_ticks=5, pump_ticks=2, dump_ticks=3, seed=98)
        return [(t.trader_trades, t.pool_state) for t in _amm([pump], events).run(20)]

    assert run(EventEngine([_event(-1.0, attention=5.0, start_tick=1, duration=20)])) == run(None)


# --- random walk: no extra event price layer ----------------------------------------------------


@pytest.mark.parametrize("drift_per_sentiment", [0.0, 0.01])
def test_random_walk_price_is_step2_walk_times_ordinary_trader_impact(drift_per_sentiment):
    """Every tick: price = previous price × the (event-adjusted) random-walk
    factor × the linear impact of the traders' actual net flow — exactly,
    with nothing else. Traders did react (fills differ from the no-news run)."""
    seed, sigma = 7, 0.02
    event = _event(0.9, attention=1.0, volatility_boost=0.5, start_tick=3, duration=20)
    sim = CoinSimulator(_coin(), seed=seed, volatility=sigma, traders=_crowd(), reserve_cash=2_000_000.0,
                        events=EventEngine([event]), drift_per_sentiment=drift_per_sentiment)
    ticks = sim.run(30)
    quiet = CoinSimulator(_coin(), seed=seed, volatility=sigma, traders=_crowd(), reserve_cash=2_000_000.0).run(30)
    assert [t.trader_trades for t in ticks] != [t.trader_trades for t in quiet]

    z_stream = random.Random(seed)
    previous = sim.coin.starting_price
    for tick in ticks:
        z = z_stream.gauss(0.0, 1.0)
        drift_t = drift_per_sentiment * tick.event_state.sentiment
        sigma_t = sigma * tick.event_state.volatility_multiplier
        walked = previous * math.exp(drift_t - 0.5 * sigma_t**2 + sigma_t * z)
        assert all(fill.price == walked for fill in tick.trader_trades)
        net = sum(f.quantity if f.side is TradeAction.BUY else -f.quantity for f in tick.trader_trades)
        expected = walked * net_flow_price_impact(net, SUPPLY, sim.trader_impact_coefficient) if net else walked
        assert tick.price == expected
        previous = tick.price
