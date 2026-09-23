"""The participation-breadth directional response (Phase 19, Step 14).

A third crowd channel, preregistered in Step 13 and separate from both
Step 4 (flow magnitude -> participation) and Step 7 (flow sign ->
direction): the *number* of other participants on each side of the previous
completed tick tilts retail's direction, through the same bounded operator,
as the outermost layer, against the same single draw. These tests pin the
transform, the operator, the composition order, the configuration, the
absence of any participation or RNG effect, and that exactly one place reads
``crowd_breadth``.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from pathlib import Path

import pytest

from crypto_simulator.core.traders import base, manipulation, strategies
from crypto_simulator.core.traders.base import (
    BREADTH_DIRECTION_MAX_SHIFT,
    MarketContext,
    PsychologyContext,
    TradeAction,
)
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import (
    MANIPULATION_STRATEGIES,
    TRADER_STRATEGIES,
    enabled_breadth_direction_sensitivity,
    enabled_crowd_direction_sensitivity,
)
from crypto_simulator.core.traders.strategies import RetailTrader

SENSITIVE = RetailTrader.default_breadth_direction_sensitivity


def context(breadth=None, *, flow=None, sentiment=0.0, attention=1.0, psychology=None):
    fields = dict(tick=11, price=1.0, price_history=(1.0,) * 12, total_supply=1_000_000.0,
                  sentiment=sentiment, attention_multiplier=attention, crowd_flow=flow,
                  crowd_breadth=breadth)
    if psychology is None:
        return MarketContext(**fields)
    return PsychologyContext(**fields, psychology=psychology)


def retail(sensitivity=SENSITIVE, **kwargs):
    kwargs.setdefault("buy_bias", 0.5)
    return RetailTrader("r-1", breadth_direction_sensitivity=sensitivity, **kwargs)


# --- constants and configuration ------------------------------------------------------


def test_the_frozen_constants():
    assert BREADTH_DIRECTION_MAX_SHIFT == 0.25
    assert SENSITIVE == 0.25


def test_only_retail_has_a_breadth_sensitivity():
    got = {name: enabled_breadth_direction_sensitivity(name) for name in TRADER_STRATEGIES}
    assert got == {name: (0.25 if name == "retail" else 0.0) for name in TRADER_STRATEGIES}
    assert all(enabled_breadth_direction_sensitivity(name) == 0.0 for name in MANIPULATION_STRATEGIES)
    assert enabled_breadth_direction_sensitivity("no-such-strategy") == 0.0


def test_the_breadth_and_flow_channels_are_separate_settings():
    # Step 7's sensitivity is untouched by Step 14 and vice versa.
    assert enabled_crowd_direction_sensitivity("retail") == 0.25
    assert RetailTrader("r").breadth_direction_sensitivity == 0.0  # off unless asked
    assert RetailTrader("r").crowd_direction_sensitivity == 0.0
    assert retail().crowd_direction_sensitivity == 0.0


@pytest.mark.parametrize("value", [-0.1, math.inf, math.nan, True, "0.25"])
def test_invalid_sensitivities_are_refused(value):
    with pytest.raises(ValueError):
        RetailTrader("r", breadth_direction_sensitivity=value)


@pytest.mark.parametrize("cls", [PumpAndDump, WashTrader])
def test_manipulators_refuse_a_breadth_sensitivity(cls):
    assert cls("m").breadth_direction_sensitivity == 0.0
    with pytest.raises(ValueError, match="ignores news"):
        cls("m", breadth_direction_sensitivity=0.25)


# --- the transform ---------------------------------------------------------------------


def test_no_observation_zero_breadth_and_zero_sensitivity_give_exactly_no_tilt():
    assert retail().breadth_direction_tilt(context(None)) == 0.0
    assert retail().breadth_direction_tilt(context(0.0)) == 0.0
    assert retail(0.0).breadth_direction_tilt(context(1.0)) == 0.0


def test_the_tilt_is_linear_signed_bounded_monotone_and_antisymmetric():
    trader = retail()
    grid = [i / 100 for i in range(-100, 101)]
    tilts = [trader.breadth_direction_tilt(context(b)) for b in grid]
    assert all(math.isfinite(t) and abs(t) <= BREADTH_DIRECTION_MAX_SHIFT for t in tilts)
    assert all(a <= b for a, b in zip(tilts, tilts[1:]))
    for b, t in zip(grid, tilts):
        assert t == pytest.approx(SENSITIVE * b, abs=1e-15)
        assert math.copysign(1, t) == math.copysign(1, b) or b == 0
        assert trader.breadth_direction_tilt(context(-b)) == -t
    assert trader.breadth_direction_tilt(context(1.0)) == 0.25
    assert trader.breadth_direction_tilt(context(-1.0)) == -0.25


def test_the_clamp_holds_for_any_sensitivity_a_caller_supplies():
    assert retail(10.0).breadth_direction_tilt(context(1.0)) == BREADTH_DIRECTION_MAX_SHIFT
    assert retail(10.0).breadth_direction_tilt(context(-1.0)) == -BREADTH_DIRECTION_MAX_SHIFT


# --- the operator ------------------------------------------------------------------------


@pytest.mark.parametrize("bias", [0.0, 0.2, 0.5, 0.8, 1.0])
@pytest.mark.parametrize("breadth", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_the_operator_is_the_step_7_interpolation(bias, breadth):
    trader = retail()
    tilt = SENSITIVE * breadth
    got = trader.breadth_buy_bias(context(breadth), bias)
    if tilt > 0:
        assert got == bias + (1.0 - bias) * tilt
    elif tilt < 0:
        assert got == bias * (1.0 + tilt)
    else:
        assert got is bias or got == bias
    assert 0.0 <= got <= 1.0


def test_a_zero_tilt_returns_the_bias_bit_for_bit():
    trader = retail()
    for bias in (0.1, 0.1234567890123, 0.5, 0.987654321):
        assert trader.breadth_buy_bias(context(None), bias) == bias
        assert trader.breadth_buy_bias(context(0.0), bias) == bias


def test_bias_zero_and_one_stay_put_in_the_direction_they_bound():
    trader = retail()
    assert trader.breadth_buy_bias(context(1.0), 1.0) == 1.0
    assert trader.breadth_buy_bias(context(-1.0), 0.0) == 0.0


# --- composition, participation and RNG ------------------------------------------------


class _Draws:
    """A stand-in stream that returns scripted values (test-only)."""

    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_breadth_is_the_outermost_layer_over_the_crowd_flow_layer():
    trader = retail(crowd_direction_sensitivity=0.25, trade_probability=1.0,
                    starting_cash=1_000.0, starting_coins=1_000.0)
    ctx = context(-1.0, flow=0.02)
    inner = trader.crowd_buy_bias(ctx, trader.psychological_buy_bias(ctx, trader.effective_buy_bias(ctx)))
    composed = trader.breadth_buy_bias(ctx, inner)
    swapped = trader.crowd_buy_bias(ctx, trader.breadth_buy_bias(ctx, 0.5))
    assert composed != swapped  # the order is observable, so this test can tell
    trader._rng = _Draws([0.0, math.nextafter(composed, 0.0)])
    assert trader.decide(ctx).action is TradeAction.BUY
    trader._rng = _Draws([0.0, composed])
    assert trader.decide(ctx).action is TradeAction.SELL


def test_participation_probability_never_reads_breadth():
    trader = retail(trade_probability=0.6)
    for b in (None, -1.0, 0.0, 0.5, 1.0):
        assert trader.participation_probability(context(b, attention=1.7)) == \
            trader.participation_probability(context(None, attention=1.7))
    assert "breadth" not in inspect.getsource(base.TraderAgent.participation_probability)


@pytest.mark.parametrize("seed", range(20))
def test_breadth_changes_no_draw_count(seed):
    on, off = retail(trade_probability=0.6, seed=seed), retail(trade_probability=0.6, seed=seed)
    for tick in range(30):
        b = [-1.0, -0.5, 0.0, 0.5, 1.0][tick % 5]
        on.decide(context(b))
        off.decide(context(None))
        assert on._rng.getstate() == off._rng.getstate()


def test_sizing_is_untouched():
    trader = retail(trade_probability=1.0, starting_cash=1_000.0, starting_coins=1_000.0)
    trader._rng = _Draws([0.0, 0.0])
    with_breadth = trader.decide(context(1.0))
    trader._rng = _Draws([0.0, 0.0])
    without = trader.decide(context(None))
    assert with_breadth.quantity == without.quantity


# --- the reader-count guard ------------------------------------------------------------


def test_exactly_one_place_reads_crowd_breadth():
    from crypto_simulator.core import coin_simulator
    from crypto_simulator.core.liquidity import settlement
    from crypto_simulator.core.psychology import signals, state
    from crypto_simulator.core.traders import execution

    base_source = Path(base.__file__).read_text()
    assert "crowd_breadth: float | None" in base_source
    assert base_source.count(".crowd_breadth") == 1, "crowd_breadth must have exactly one reader"
    assert inspect.getsource(base.TraderAgent.breadth_direction_tilt).count(".crowd_breadth") == 1
    for module in (strategies, manipulation, coin_simulator, execution, settlement, signals, state):
        assert ".crowd_breadth" not in Path(module.__file__).read_text(), module.__name__
    assert "breadth_direction_sensitivity" not in Path(manipulation.__file__).read_text()
    for fn in (base.TraderAgent.participation_probability, base.TraderAgent._buy,
               base.TraderAgent._sell, base.TraderAgent.crowd_urge, base.TraderAgent.crowd_direction_tilt):
        assert "breadth" not in inspect.getsource(fn), fn.__name__


def test_the_only_new_context_field_is_crowd_breadth():
    names = [f.name for f in dataclasses.fields(MarketContext)]
    assert names[-2:] == ["crowd_flow", "crowd_breadth"]
    assert MarketContext(1, 1.0, (1.0,), 1.0).crowd_breadth is None
