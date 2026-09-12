import ast
import dataclasses
import math
import random
from pathlib import Path

import pytest

import crypto_simulator.core.psychology as psychology_package
from crypto_simulator.config import get_settings
from crypto_simulator.core.psychology import PsychologyState
from crypto_simulator.services.coin_simulation import build_coin_simulator

DIMENSIONS = ("fear", "fomo", "conviction", "uncertainty")


def test_neutral_state_is_all_zeros_and_is_the_default():
    neutral = PsychologyState.neutral()
    assert (neutral.fear, neutral.fomo, neutral.conviction, neutral.uncertainty) == (0.0, 0.0, 0.0, 0.0)
    assert neutral == PsychologyState()
    assert [f.name for f in dataclasses.fields(PsychologyState)] == list(DIMENSIONS)


def test_valid_values_are_kept_as_given():
    state = PsychologyState(fear=0.25, fomo=0.8, conviction=0.5, uncertainty=0.1)
    assert (state.fear, state.fomo, state.conviction, state.uncertainty) == (0.25, 0.8, 0.5, 0.1)
    assert PsychologyState(fomo=0.3) == PsychologyState(0.0, 0.3, 0.0, 0.0)


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_both_bounds_are_accepted(dimension):
    assert getattr(PsychologyState(**{dimension: 0.0}), dimension) == 0.0
    assert getattr(PsychologyState(**{dimension: 1.0}), dimension) == 1.0
    assert getattr(PsychologyState(**{dimension: 1}), dimension) == 1


@pytest.mark.parametrize("dimension", DIMENSIONS)
@pytest.mark.parametrize("value", [-0.01, 1.01, -1.0, 2.0, 1e308])
def test_values_outside_the_unit_interval_are_rejected(dimension, value):
    with pytest.raises(ValueError, match=rf"{dimension} must be within \[0, 1\]"):
        PsychologyState(**{dimension: value})


@pytest.mark.parametrize("dimension", DIMENSIONS)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "0.5", None, True, False, [0.5]])
def test_non_finite_and_non_numeric_values_are_rejected(dimension, value):
    with pytest.raises(ValueError, match=rf"{dimension} must be a finite number"):
        PsychologyState(**{dimension: value})


def test_state_is_immutable():
    state = PsychologyState(fear=0.4)
    for dimension in DIMENSIONS:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(state, dimension, 0.9)
    assert state == PsychologyState(fear=0.4)


def test_equality_and_hashing_are_value_based_and_deterministic():
    a = PsychologyState(fear=0.1, fomo=0.2, conviction=0.3, uncertainty=0.4)
    b = PsychologyState(fear=0.1, fomo=0.2, conviction=0.3, uncertainty=0.4)
    assert a == b and hash(a) == hash(b) and len({a, b}) == 1
    assert a != PsychologyState(fear=0.1, fomo=0.2, conviction=0.3, uncertainty=0.5)
    assert PsychologyState.neutral() is not PsychologyState.neutral()  # fresh value each call
    assert repr(a) == repr(b)


def test_creating_states_touches_no_randomness():
    state = random.getstate()
    for step in range(1_000):
        PsychologyState(fear=step / 1_000, fomo=1 - step / 1_000)
        PsychologyState.neutral()
    assert random.getstate() == state


def test_psychology_depends_only_on_itself_and_the_standard_library():
    imported = set()
    for module in Path(psychology_package.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
    project = {m for m in imported if m.startswith("crypto_simulator")}
    assert project and all(m.startswith("crypto_simulator.core.psychology") for m in project)
    assert {m.split(".")[0] for m in imported} - {"crypto_simulator"} <= {"__future__", "dataclasses", "math", "typing"}


def test_creating_states_does_not_affect_a_simulation():
    def fingerprint(mode):
        sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk")
        ticks = sim.run(100)
        return [(t.price, t.volume, t.whale_trades, t.trader_trades, t.pool_state) for t in ticks], [
            t._rng.getstate() for t in sim.traders
        ]

    for mode in ("random_walk", "amm"):
        before = fingerprint(mode)
        states = [PsychologyState(fear=i / 10, uncertainty=1 - i / 10) for i in range(11)]
        assert fingerprint(mode) == before
        assert len(states) == 11
