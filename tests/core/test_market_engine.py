import pytest

from crypto_simulator.core.clock import SimulationClock
from crypto_simulator.core.market_engine import MarketEngine


def test_market_engine_holds_configured_symbols():
    engine = MarketEngine(["BTC", "ETH"], SimulationClock())
    assert engine.symbols == ["BTC", "ETH"]


def test_current_price_uses_configured_initial_prices():
    engine = MarketEngine(
        ["BTC", "ETH"], SimulationClock(), initial_prices={"BTC": 60000.0, "ETH": 3000.0}
    )
    assert engine.current_price("BTC") == 60000.0
    assert engine.current_price("ETH") == 3000.0


def test_current_price_defaults_when_not_configured():
    engine = MarketEngine(["SOL"], SimulationClock())
    assert engine.current_price("SOL") == 100.0


def test_current_price_unknown_symbol_raises():
    engine = MarketEngine(["BTC"], SimulationClock())
    with pytest.raises(ValueError):
        engine.current_price("DOGE")


def test_step_advances_clock_and_returns_all_symbols():
    clock = SimulationClock()
    engine = MarketEngine(["BTC", "ETH"], clock, seed=1)
    prices = engine.step()
    assert clock.tick == 1
    assert set(prices) == {"BTC", "ETH"}
    assert all(price > 0 for price in prices.values())


def test_set_price_overrides_current_price():
    engine = MarketEngine(["BTC"], SimulationClock(), seed=1)
    engine.set_price("BTC", 12345.0)
    assert engine.current_price("BTC") == 12345.0


def test_set_price_unknown_symbol_raises():
    engine = MarketEngine(["BTC"], SimulationClock())
    with pytest.raises(ValueError):
        engine.set_price("DOGE", 1.0)


def test_set_price_rejects_non_positive_price():
    engine = MarketEngine(["BTC"], SimulationClock())
    with pytest.raises(ValueError):
        engine.set_price("BTC", 0)
    with pytest.raises(ValueError):
        engine.set_price("BTC", -5.0)


def test_step_updates_current_price():
    engine = MarketEngine(["BTC"], SimulationClock(), seed=1)
    new_prices = engine.step()
    assert engine.current_price("BTC") == new_prices["BTC"]


def test_step_is_reproducible_given_same_seed():
    prices_a = _run_ticks(seed=7, ticks=10)
    prices_b = _run_ticks(seed=7, ticks=10)
    assert prices_a == prices_b


def test_step_diverges_with_different_seed():
    prices_a = _run_ticks(seed=7, ticks=10)
    prices_b = _run_ticks(seed=8, ticks=10)
    assert prices_a != prices_b


def _run_ticks(*, seed: int, ticks: int) -> dict[str, float]:
    engine = MarketEngine(["BTC", "ETH"], SimulationClock(), seed=seed, volatility=0.02)
    for _ in range(ticks):
        prices = engine.step()
    return prices
