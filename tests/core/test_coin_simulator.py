import pytest

from crypto_simulator.core.coin_simulator import CoinSimulator, SimulationTick
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.coin import Coin


def _make_coin(**overrides):
    defaults = dict(symbol="FIC", name="FictiCoin (Simulated)", initial_supply=1_000_000.0, starting_price=2.0)
    defaults.update(overrides)
    return Coin(**defaults)


def test_market_cap_before_any_step_uses_starting_price():
    sim = CoinSimulator(_make_coin(), seed=1)
    assert sim.market_cap() == 2.0 * 1_000_000.0


def test_step_returns_a_simulation_tick():
    sim = CoinSimulator(_make_coin(), seed=1)
    tick = sim.step()
    assert isinstance(tick, SimulationTick)
    assert tick.tick == 1
    assert tick.price > 0
    assert tick.volume >= 0
    assert tick.market_cap == pytest.approx(tick.price * 1_000_000.0)


def test_step_appends_to_history():
    sim = CoinSimulator(_make_coin(), seed=1)
    sim.step()
    sim.step()
    assert len(sim.history) == 2
    assert sim.history[-1].tick == 2


def test_run_advances_multiple_ticks_and_returns_them():
    sim = CoinSimulator(_make_coin(), seed=1)
    ticks = sim.run(10)
    assert len(ticks) == 10
    assert [t.tick for t in ticks] == list(range(1, 11))
    assert sim.history == ticks


def test_run_rejects_non_positive_ticks():
    sim = CoinSimulator(_make_coin(), seed=1)
    with pytest.raises(ValueError):
        sim.run(0)


def test_current_price_reflects_latest_step():
    sim = CoinSimulator(_make_coin(), seed=1)
    tick = sim.step()
    assert sim.current_price == tick.price


def test_reproducible_given_same_seed():
    run_a = CoinSimulator(_make_coin(), seed=99).run(20)
    run_b = CoinSimulator(_make_coin(), seed=99).run(20)
    assert [t.price for t in run_a] == [t.price for t in run_b]
    assert [t.volume for t in run_a] == [t.volume for t in run_b]


def test_diverges_with_different_seed():
    run_a = CoinSimulator(_make_coin(), seed=1).run(20)
    run_b = CoinSimulator(_make_coin(), seed=2).run(20)
    assert [t.price for t in run_a] != [t.price for t in run_b]


def test_default_has_no_whales_and_behaves_like_phase_1():
    sim = CoinSimulator(_make_coin(), seed=1)
    assert sim.whales == []
    ticks = sim.run(10)
    assert all(t.whale_trades == () for t in ticks)


def test_construction_rejects_whale_holdings_exceeding_supply():
    whale = Whale("w1", holdings=2_000_000.0, activity_probability=1.0)
    with pytest.raises(ValueError):
        CoinSimulator(_make_coin(), seed=1, whales=[whale])


def test_whale_trades_appear_on_ticks_it_acts():
    whale = Whale("w1", holdings=100_000.0, activity_probability=1.0, seed=7)
    sim = CoinSimulator(_make_coin(), seed=1, whales=[whale])
    ticks = sim.run(5)
    assert all(len(t.whale_trades) == 1 for t in ticks)
    assert all(t.whale_trades[0].whale_id == "w1" for t in ticks)


def test_whale_trade_volume_is_included_in_tick_volume():
    whale = Whale("w1", holdings=100_000.0, activity_probability=1.0, seed=7)
    sim = CoinSimulator(_make_coin(), seed=1, whales=[whale])
    tick = sim.step()
    assert tick.volume >= tick.whale_trades[0].quantity


def test_silent_whale_never_moves_price_beyond_base_walk():
    silent_whale = Whale("w1", holdings=100_000.0, activity_probability=0.0, seed=7)
    with_silent_whale = CoinSimulator(_make_coin(), seed=1, whales=[silent_whale]).run(15)
    without_whale = CoinSimulator(_make_coin(), seed=1).run(15)
    assert [t.price for t in with_silent_whale] == [t.price for t in without_whale]


def test_reproducible_with_whales_given_same_seeds():
    def _run():
        whale = Whale("w1", holdings=100_000.0, activity_probability=0.5, seed=7)
        return CoinSimulator(_make_coin(), seed=1, whales=[whale]).run(20)

    run_a, run_b = _run(), _run()
    assert [t.price for t in run_a] == [t.price for t in run_b]
    assert [len(t.whale_trades) for t in run_a] == [len(t.whale_trades) for t in run_b]
