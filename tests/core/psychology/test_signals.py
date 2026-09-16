import ast
import dataclasses
import itertools
import math
import random
from pathlib import Path

import pytest

import crypto_simulator
from crypto_simulator.config import get_settings
from crypto_simulator.core.psychology import MarketSignals, PsychologyState, compute_psychology
from crypto_simulator.core.psychology import signals as signals_module
from crypto_simulator.services.coin_simulation import build_coin_simulator

DIMENSIONS = ("fear", "fomo", "conviction", "uncertainty")


def _psych(**signals):
    return compute_psychology(MarketSignals(**signals))


def _values(state):
    return tuple(getattr(state, d) for d in DIMENSIONS)


# 1 --- neutral --------------------------------------------------------------------------------


def test_neutral_inputs_give_exactly_the_neutral_state():
    state = compute_psychology(MarketSignals())
    assert state == PsychologyState.neutral()
    assert all(math.copysign(1.0, v) == 1.0 for v in _values(state))  # +0.0, never -0.0
    assert repr(state) == repr(PsychologyState.neutral())
    assert _psych(recent_return=-0.0, momentum=-0.0, event_sentiment=-0.0) == PsychologyState.neutral()


def test_the_documented_formula_on_a_simple_case():
    state = _psych(recent_return=0.05)  # exactly one unit of bullish pressure
    assert state == PsychologyState(fear=0.0, fomo=math.tanh(1.0), conviction=math.tanh(1.0), uncertainty=0.0)


# 2-6 --- directions ---------------------------------------------------------------------------


def test_rising_prices_raise_fomo_and_conviction_but_not_fear():
    state = _psych(recent_return=0.04, momentum=0.02)
    assert state.fomo > 0 and state.conviction > 0
    assert (state.fear, state.uncertainty) == (0.0, 0.0)


def test_falling_prices_raise_fear_and_leave_no_fomo_or_conviction():
    state = _psych(recent_return=-0.04, momentum=-0.02)
    assert state.fear > 0
    assert (state.fomo, state.conviction) == (0.0, 0.0)


def test_positive_news_raises_fomo_and_conviction_and_lowers_existing_fear():
    good = _psych(event_sentiment=0.6)
    assert good.fomo > 0 and good.conviction > 0 and good.fear == 0.0
    assert _psych(recent_return=-0.05, event_sentiment=0.4).fear < _psych(recent_return=-0.05).fear


def test_negative_news_raises_fear_and_lowers_existing_fomo_and_conviction():
    bad = _psych(event_sentiment=-0.6)
    assert bad.fear > 0 and bad.fomo == 0.0 and bad.conviction == 0.0
    rally, mixed = _psych(recent_return=0.05), _psych(recent_return=0.05, event_sentiment=-0.4)
    assert mixed.fomo < rally.fomo
    assert mixed.conviction < rally.conviction


def test_volatility_raises_uncertainty_and_erodes_conviction():
    calm, choppy = _psych(recent_return=0.05), _psych(recent_return=0.05, volatility=0.08)
    assert _psych(volatility=0.03).uncertainty > 0
    assert choppy.uncertainty > calm.uncertainty
    assert choppy.conviction < calm.conviction
    assert choppy.fomo == calm.fomo  # volatility is not directional


def test_severity_raises_uncertainty_without_a_direction():
    state = _psych(event_severity=0.8)
    assert state.uncertainty > 0
    assert (state.fear, state.fomo, state.conviction) == (0.0, 0.0, 0.0)


def test_attention_amplifies_news_but_never_acts_alone():
    assert _psych(attention=5.0) == PsychologyState.neutral()
    assert _psych(recent_return=0.03, volatility=0.02, attention=5.0) == _psych(recent_return=0.03, volatility=0.02)
    quiet, loud = _psych(event_sentiment=0.2), _psych(event_sentiment=0.2, attention=2.0)
    assert quiet.fomo < loud.fomo < 1.0
    assert _psych(event_sentiment=-0.2, attention=2.0).fear > _psych(event_sentiment=-0.2).fear
    assert _psych(event_severity=0.3, attention=2.0).uncertainty > _psych(event_severity=0.3).uncertainty


# 7 --- stronger signals, equal-or-greater response ----------------------------------------------


def _monotone(dimension, name, values, **base):
    responses = [getattr(_psych(**{**base, name: v}), dimension) for v in values]
    assert all(a <= b for a, b in zip(responses, responses[1:])), (dimension, name, responses)
    assert responses[0] < responses[-1]


@pytest.mark.parametrize("base", [{}, {"event_sentiment": -0.3}, {"volatility": 0.05}])
def test_stronger_signals_never_weaken_the_matching_response(base):
    rising = [0.0, 0.01, 0.03, 0.1, 0.5, 2.0]
    falling = [0.0, -0.01, -0.03, -0.1, -0.5, -0.99]
    _monotone("fomo", "recent_return", rising, **base)
    _monotone("fomo", "momentum", rising, **base)
    _monotone("fear", "recent_return", falling, **{k: v for k, v in base.items() if k != "event_sentiment"})
    _monotone("uncertainty", "volatility", [0.0, 0.01, 0.05, 0.2, 1.0], **{k: v for k, v in base.items() if k != "volatility"})
    _monotone("uncertainty", "event_severity", [0.0, 0.2, 0.5, 1.0], **{k: v for k, v in base.items() if k != "volatility"})
    _monotone("fomo", "event_sentiment", [0.0, 0.2, 0.5, 1.0], **{k: v for k, v in base.items() if k != "event_sentiment"})
    _monotone("fear", "event_sentiment", [0.0, -0.2, -0.5, -1.0], **{k: v for k, v in base.items() if k != "event_sentiment"})


def test_conviction_grows_with_net_bullish_signals_and_shrinks_with_bearish_ones():
    _monotone("conviction", "recent_return", [0.0, 0.01, 0.03, 0.1], event_sentiment=-0.1)
    more_bearish = [_psych(recent_return=0.08, event_sentiment=s).conviction for s in (0.0, -0.2, -0.5, -1.0)]
    assert all(a >= b for a, b in zip(more_bearish, more_bearish[1:]))


# 8-9 --- bounds and extremes ---------------------------------------------------------------------


GRID = {
    "recent_return": [-1.0, -0.5, -0.01, 0.0, 0.01, 0.5, 10.0, 1e308],
    "momentum": [-1.0, -0.2, 0.0, 0.2, 1e308],
    "volatility": [0.0, 0.03, 1.0, 1e308],
    "event_sentiment": [-1.0, -0.4, 0.0, 0.4, 1.0],
    "event_severity": [0.0, 0.5, 1.0],
    "attention": [1.0, 3.0, 1e308],
}


def test_every_output_is_finite_and_within_the_unit_interval_across_extreme_inputs():
    for combo in itertools.product(*GRID.values()):
        state = compute_psychology(MarketSignals(**dict(zip(GRID, combo))))
        for value in _values(state):
            assert math.isfinite(value) and 0.0 <= value <= 1.0, (combo, state)


@pytest.mark.parametrize(
    "field, value",
    [
        ("recent_return", math.nan), ("recent_return", math.inf), ("recent_return", -1.01),
        ("momentum", -math.inf), ("momentum", -2.0),
        ("volatility", -0.01), ("volatility", math.inf),
        ("event_sentiment", 1.5), ("event_sentiment", math.nan),
        ("event_severity", -0.1), ("event_severity", 1.1),
        ("attention", 0.5), ("attention", math.inf),
        ("attention", True), ("volatility", "0.1"),
    ],
)
def test_invalid_or_non_finite_inputs_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        MarketSignals(**{field: value})


def test_signals_are_immutable_value_objects():
    signals = MarketSignals(recent_return=0.02)
    with pytest.raises(dataclasses.FrozenInstanceError):
        signals.recent_return = 0.5
    assert signals == MarketSignals(recent_return=0.02)


# 10 --- opposite signals --------------------------------------------------------------------------


def test_opposite_signals_damp_each_other_and_raise_uncertainty():
    up, down = _psych(recent_return=0.05), _psych(event_sentiment=-0.8)
    both = _psych(recent_return=0.05, event_sentiment=-0.8)
    assert 0 < both.fomo < up.fomo
    assert 0 < both.fear < down.fear
    assert both.uncertainty > max(up.uncertainty, down.uncertainty)
    assert both.conviction < up.conviction


def test_mirrored_signals_give_mirrored_emotions():
    up = _psych(recent_return=0.03, momentum=0.01, event_sentiment=0.4, attention=1.5)
    down = _psych(recent_return=-0.03, momentum=-0.01, event_sentiment=-0.4, attention=1.5)
    assert up.fomo == pytest.approx(down.fear) and up.fear == pytest.approx(down.fomo)
    assert up.uncertainty == down.uncertainty


# 11-13 --- determinism, randomness, dependencies ----------------------------------------------------


def test_identical_inputs_give_identical_states():
    signals = MarketSignals(recent_return=0.013, momentum=-0.002, volatility=0.031, event_sentiment=0.27,
                            event_severity=0.6, attention=1.4)
    first = compute_psychology(signals)
    assert all(compute_psychology(signals) == first for _ in range(100))
    assert repr(compute_psychology(MarketSignals(**dataclasses.asdict(signals)))) == repr(first)


def test_computing_psychology_touches_no_randomness():
    state = random.getstate()
    for combo in itertools.islice(itertools.product(*GRID.values()), 500):
        compute_psychology(MarketSignals(**dict(zip(GRID, combo))))
    assert random.getstate() == state


def _imports(path):
    imported = set()
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


def test_the_calculator_imports_nothing_from_the_simulator():
    assert _imports(signals_module.__file__) == {
        "__future__", "math", "dataclasses", "typing", "crypto_simulator.core.psychology.state",
    }


def test_only_the_simulator_traders_and_psychology_analytics_import_psychology():
    """Step 3 wires psychology into the simulator and the trader strategies;
    Step 4's read-only analytics module reads the recorded states, and
    Phase 9 Step 5's co-movement analytics reads that module's own public
    results in turn. Events and everything else stay independent of it."""
    package = Path(crypto_simulator.__file__).parent
    importers = {
        module.relative_to(package).as_posix()
        for module in package.rglob("*.py")
        if "psychology" not in module.parts and any("psychology" in name for name in _imports(module))
    }
    assert importers == {
        "core/coin_simulator.py", "core/traders/base.py", "core/traders/strategies.py",
        "analytics/__init__.py", "analytics/psychology.py", "analytics/psychology_market.py",
    }


# 14 --- existing simulations unchanged ---------------------------------------------------------------


def test_computing_psychology_from_a_run_leaves_the_run_unchanged():
    def run(mode, observe):
        sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk")
        ticks, states, previous = [], [], sim.coin.starting_price
        for _ in range(100):
            tick = sim.step()
            ticks.append((tick.price, tick.volume, tick.whale_trades, tick.trader_trades, tick.pool_state))
            if observe:
                states.append(compute_psychology(MarketSignals(recent_return=tick.price / previous - 1)))
            previous = tick.price
        return ticks, [t._rng.getstate() for t in sim.traders], sim.accounting_totals()

    for mode in ("random_walk", "amm"):
        assert run(mode, observe=True) == run(mode, observe=False)
