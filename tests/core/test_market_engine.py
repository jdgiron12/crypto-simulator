import math
import random
import statistics

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


# --- drift / volatility_scale (news events) ---------------------------------------------


def _gauss_stream(seed, n):
    """The exact normal draws a MarketEngine seeded with ``seed`` makes."""
    rng = random.Random(seed)
    return [rng.gauss(0.0, 1.0) for _ in range(n)]


def test_explicit_default_arguments_are_bit_identical_to_plain_step():
    plain = MarketEngine(["BTC", "ETH"], SimulationClock(), seed=5, volatility=0.03)
    explicit = MarketEngine(["BTC", "ETH"], SimulationClock(), seed=5, volatility=0.03)
    for _ in range(300):
        assert explicit.step(drift=0.0, volatility_scale=1.0) == plain.step()
    assert explicit.step(drift=-0.0) == plain.step()  # negative zero is still "no drift"
    assert explicit._rng.getstate() == plain._rng.getstate()


def test_adjusted_steps_consume_exactly_one_normal_draw_per_symbol():
    plain = MarketEngine(["A", "B", "C"], SimulationClock(), seed=9)
    adjusted = MarketEngine(["A", "B", "C"], SimulationClock(), seed=9)
    for i in range(100):
        plain.step()
        adjusted.step(drift=0.001 * (i % 3 - 1), volatility_scale=1.0 + i % 4)
    assert adjusted._rng.getstate() == plain._rng.getstate()
    assert adjusted.clock.tick == plain.clock.tick == 100


def test_adjusted_step_matches_the_formula_exactly():
    engine = MarketEngine(["X"], SimulationClock(), seed=11, volatility=0.05, initial_prices={"X": 10.0})
    price = 10.0
    for tick, z in enumerate(_gauss_stream(11, 50)):
        drift, scale = 0.002 * math.sin(tick), 1.0 + (tick % 5) / 4
        sigma = 0.05 * scale
        price *= math.exp(drift - 0.5 * sigma**2 + sigma * z)
        assert engine.step(drift=drift, volatility_scale=scale)["X"] == price


def test_volatility_scale_alone_does_not_move_the_expected_price():
    engine = MarketEngine(["X"], SimulationClock(), seed=3, volatility=0.1, initial_prices={"X": 1.0})
    factors = []
    for _ in range(50_000):
        engine.set_price("X", 1.0)  # independent one-step factors, no compounding
        factors.append(engine.step(volatility_scale=3.0)["X"])
    # Without the -0.5*s^2 correction the mean factor would be exp(0.045) ~ 1.046.
    assert statistics.fmean(factors) == pytest.approx(1.0, abs=0.006)


def test_drift_moves_price_deterministically_when_volatility_is_scaled_to_zero():
    engine = MarketEngine(["X"], SimulationClock(), seed=1, volatility=0.2, initial_prices={"X": 4.0})
    assert engine.step(drift=0.01, volatility_scale=0.0)["X"] == 4.0 * math.exp(0.01)


@pytest.mark.parametrize(
    "kwargs", [{"drift": math.nan}, {"drift": math.inf}, {"volatility_scale": -0.5}, {"volatility_scale": math.nan}]
)
def test_invalid_adjustments_are_rejected_before_anything_moves(kwargs):
    engine = MarketEngine(["X"], SimulationClock(), seed=1)
    with pytest.raises(ValueError):
        engine.step(**kwargs)
    assert engine.clock.tick == 0
    assert engine.current_price("X") == 100.0


@pytest.mark.parametrize("drift", [-800.0, 800.0])
def test_extreme_drift_raises_instead_of_producing_a_zero_or_infinite_price(drift):
    engine = MarketEngine(["X"], SimulationClock(), seed=1)
    with pytest.raises(ValueError, match="must stay positive and finite"):
        engine.step(drift=drift)
    assert engine.current_price("X") == 100.0
