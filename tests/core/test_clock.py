import pytest

from crypto_simulator.core.clock import SimulationClock


def test_clock_starts_at_zero():
    clock = SimulationClock()
    assert clock.tick == 0


def test_advance_increments_tick_and_returns_new_value():
    clock = SimulationClock()
    assert clock.advance() == 1
    assert clock.advance(steps=4) == 5


def test_advance_rejects_non_positive_steps():
    clock = SimulationClock()
    with pytest.raises(ValueError):
        clock.advance(steps=0)


def test_simulated_time_advances_with_tick_interval():
    clock = SimulationClock(tick_interval=60.0)
    before = clock.simulated_time
    clock.advance(steps=1)
    after = clock.simulated_time
    assert (after - before).total_seconds() == 60.0
