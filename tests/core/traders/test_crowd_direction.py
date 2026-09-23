"""The directional crowd-flow response (Phase 19, Step 7).

Step 4 gave a trader a reason to *show up* when the previous tick's crowd
was loud; this gives one a reason to take the *side* that crowd took. The
two read the same observation — Step 4 its magnitude, this its sign — and
they are separate terms with separate sensitivities so an experiment can
attribute an effect to one of them.

Only ``retail`` carries a non-zero directional sensitivity, and only
because its direction is a probability evaluated against a draw it already
makes; every other strategy picks its side from a threshold rule. Nothing
here adds a draw, and nothing here touches psychology.
"""

from __future__ import annotations

import dataclasses
import math
import random

import pytest
import yaml

from crypto_simulator.config.settings import DEFAULT_CONFIG_PATH, build_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.psychology.signals import compute_psychology, signals_from_closes
from crypto_simulator.core.traders.base import (
    CROWD_DIRECTION_MAX_SHIFT,
    CROWD_FLOW_SCALE,
    MarketContext,
    PsychologyContext,
    TraderAgent,
)
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import (
    MANIPULATION_STRATEGIES,
    TRADER_STRATEGIES,
    enabled_crowd_direction_sensitivity,
    enabled_crowd_sensitivity,
)
from crypto_simulator.core.traders.strategies import (
    DipBuyer,
    LongTermHolder,
    MomentumTrader,
    PanicSeller,
    RetailTrader,
)
from crypto_simulator.models.coin import Coin
from crypto_simulator.services.coin_simulation import build_coin_simulator
from crypto_simulator.services.market_conditions import apply_market_condition

SUPPLY = 1_000_000.0
SENSITIVE = RetailTrader.default_crowd_direction_sensitivity


def settings():
    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as handle:
        return build_settings(yaml.safe_load(handle), DEFAULT_CONFIG_PATH)


def context(flow, *, sentiment=0.0, attention=1.0, psychology=None):
    fields = dict(
        tick=11, price=1.0, price_history=(1.0,) * 12, total_supply=SUPPLY,
        sentiment=sentiment, attention_multiplier=attention, crowd_flow=flow,
    )
    if psychology is None:
        return MarketContext(**fields)
    return PsychologyContext(**fields, psychology=psychology)


def retail(sensitivity=SENSITIVE, **kwargs):
    kwargs.setdefault("buy_bias", 0.5)
    return RetailTrader("r-1", crowd_direction_sensitivity=sensitivity, **kwargs)


# --- the transform -------------------------------------------------------------------


def test_no_observation_and_zero_flow_both_give_exactly_no_tilt():
    trader = retail()
    assert trader.crowd_direction_tilt(context(None)) == 0.0
    assert trader.crowd_direction_tilt(context(0.0)) == 0.0


@pytest.mark.parametrize("flow", [0.0005, 0.002, 0.005, 0.01, 0.023, 0.5, 1.0])
def test_a_buying_crowd_tilts_up_and_a_selling_crowd_tilts_down(flow):
    trader = retail()
    assert trader.crowd_direction_tilt(context(flow)) > 0.0
    assert trader.crowd_direction_tilt(context(-flow)) < 0.0


@pytest.mark.parametrize("flow", [0.0001, 0.003, 0.0127, 0.4, 1.0])
def test_the_tilt_is_exactly_antisymmetric(flow):
    """Not merely symmetric in magnitude: the sign is the whole point."""
    trader = retail()
    assert trader.crowd_direction_tilt(context(flow)) == -trader.crowd_direction_tilt(context(-flow))


def test_the_transform_is_the_frozen_one():
    trader = retail()
    for flow in (0.0007, 0.004, 0.0169, -0.006, -0.03):
        assert trader.crowd_direction_tilt(context(flow)) == max(
            -CROWD_DIRECTION_MAX_SHIFT,
            min(CROWD_DIRECTION_MAX_SHIFT, SENSITIVE * math.tanh(flow / CROWD_FLOW_SCALE)),
        )


def test_the_frozen_parameter_table():
    """The values recorded in the Step 7 specification before any result
    existed. If one of these moves, the experiment has been re-parameterised
    and its arms are no longer comparable."""
    trader = retail()
    expected = {
        None: 0.500000, -1.0: 0.375000, -0.01: 0.404801, -0.005: 0.442235,
        0.0: 0.500000, 0.005: 0.557765, 0.01: 0.595199, 1.0: 0.625000,
    }
    for flow, bias in expected.items():
        assert trader.crowd_buy_bias(context(flow), 0.5) == pytest.approx(bias, abs=5e-7)
    assert CROWD_FLOW_SCALE == 0.01
    assert CROWD_DIRECTION_MAX_SHIFT == 0.25
    assert SENSITIVE == 0.25


@pytest.mark.parametrize("flow", [-1.0, -0.5, -0.02, -0.001, 0.0, 0.001, 0.02, 0.5, 1.0, 1e6, -1e6])
def test_the_tilt_stays_inside_its_bound_and_finite(flow):
    tilt = retail().crowd_direction_tilt(context(flow))
    assert -CROWD_DIRECTION_MAX_SHIFT <= tilt <= CROWD_DIRECTION_MAX_SHIFT
    assert math.isfinite(tilt)


def test_the_tilt_rises_with_the_flow_everywhere():
    trader = retail()
    flows = [(i - 400) / 2000 for i in range(801)]
    tilts = [trader.crowd_direction_tilt(context(f)) for f in flows]
    assert tilts == sorted(tilts)
    assert tilts[0] < 0.0 < tilts[-1]


def test_the_tilt_is_continuous_with_no_step_anywhere():
    trader = retail()
    step = 1e-5
    flows = [(i - 10_000) * step for i in range(20_001)]
    tilts = [trader.crowd_direction_tilt(context(f)) for f in flows]
    jumps = [abs(b - a) for a, b in zip(tilts, tilts[1:])]
    assert max(jumps) <= SENSITIVE * step / CROWD_FLOW_SCALE + 1e-12


def test_the_tilt_saturates_rather_than_growing():
    trader = retail()
    assert trader.crowd_direction_tilt(context(0.05)) == pytest.approx(
        CROWD_DIRECTION_MAX_SHIFT, abs=1e-3
    )
    assert trader.crowd_direction_tilt(context(1.0)) == CROWD_DIRECTION_MAX_SHIFT
    assert trader.crowd_direction_tilt(context(-1.0)) == -CROWD_DIRECTION_MAX_SHIFT


def test_the_tilt_is_not_a_sign_only_step():
    """A step function would take three values. This takes a continuum, so
    a barely-one-sided crowd pulls barely at all."""
    trader = retail()
    values = {round(trader.crowd_direction_tilt(context(i / 5000)), 9) for i in range(1, 200)}
    assert len(values) > 150
    assert trader.crowd_direction_tilt(context(0.0002)) < trader.crowd_direction_tilt(context(0.02))


def test_zero_sensitivity_never_evaluates_the_transform():
    assert retail(0.0).crowd_direction_tilt(context(0.03)) == 0.0
    assert retail(0.0).crowd_buy_bias(context(0.03), 0.5) == 0.5


# --- composition ---------------------------------------------------------------------


@pytest.mark.parametrize("bias", [0.05, 0.25, 0.5, 0.75, 0.95])
def test_a_buying_crowd_raises_the_bias_and_a_selling_crowd_lowers_it(bias):
    trader = retail()
    assert trader.crowd_buy_bias(context(0.01), bias) > bias
    assert trader.crowd_buy_bias(context(-0.01), bias) < bias


@pytest.mark.parametrize("bias", [0.0, 0.1, 0.5, 0.9, 1.0])
@pytest.mark.parametrize("flow", [None, 0.0])
def test_no_tilt_returns_the_bias_bit_for_bit(bias, flow):
    """Not approximately: this exactness is what makes a response-off run
    identical to a pre-Step-7 run."""
    assert retail().crowd_buy_bias(context(flow), bias) == bias


@pytest.mark.parametrize("flow", [-1.0, -0.02, -0.001, 0.001, 0.02, 1.0])
@pytest.mark.parametrize("bias", [0.0, 0.01, 0.3, 0.5, 0.7, 0.99, 1.0])
def test_the_bias_stays_a_probability(flow, bias):
    assert 0.0 <= retail().crowd_buy_bias(context(flow), bias) <= 1.0


def test_a_bias_at_a_bound_can_only_be_moved_off_it_inward():
    """The bounds are *one-sided* fixed points, which is how the two
    pre-existing directional layers (news and psychology) have always
    behaved — ``effective_buy_bias`` moves a 0 bias up on good news too.
    A crowd can pull a never-buys trader toward buying, but can never push
    it below 0 or above 1; that, not two-sided stickiness, is the bound the
    operator guarantees. See the Step 7 note in the report."""
    trader = retail()
    assert trader.crowd_buy_bias(context(-0.05), 0.0) == 0.0      # already at the bound it is pulled to
    assert trader.crowd_buy_bias(context(0.05), 0.0) > 0.0        # pulled inward, off the bound
    assert trader.crowd_buy_bias(context(0.05), 1.0) == 1.0
    assert trader.crowd_buy_bias(context(-0.05), 1.0) < 1.0
    for flow in (-1.0, -0.01, 0.01, 1.0):
        assert 0.0 <= trader.crowd_buy_bias(context(flow), 0.0) <= 1.0
        assert 0.0 <= trader.crowd_buy_bias(context(flow), 1.0) <= 1.0


def test_the_operator_is_the_one_the_other_two_layers_already_use():
    trader = retail()
    for flow, bias in ((0.013, 0.42), (-0.009, 0.66)):
        tilt = trader.crowd_direction_tilt(context(flow))
        expected = bias + (1.0 - bias) * tilt if tilt > 0 else bias * (1.0 + tilt)
        assert trader.crowd_buy_bias(context(flow), bias) == expected


# --- order of composition ------------------------------------------------------------


def test_the_crowd_layer_is_applied_after_news_and_psychology():
    """News, then psychology, then the crowd — and the decision is taken
    against that composed number, reconstructed here from the three public
    layers rather than from a copy of the formula."""
    state = compute_psychology(signals_from_closes([1.0, 1.08, 1.2, 1.35, 1.5]))
    # Funded, or `_buy`/`_sell` would hold for want of cash or coins and the
    # boundary check below would read the wallet rather than the bias.
    trader = retail(
        sensitivity=SENSITIVE, sentiment_sensitivity=1.0,
        starting_cash=5_000.0, starting_coins=5_000.0, max_trade_size=2_000.0,
    )
    ctx = context(0.012, sentiment=0.4, psychology=state)

    after_news = trader.effective_buy_bias(ctx)
    after_psychology = trader.psychological_buy_bias(ctx, after_news)
    after_crowd = trader.crowd_buy_bias(ctx, after_psychology)

    assert after_news != trader.buy_bias          # news moved it
    assert after_psychology != after_news         # psychology moved it again
    assert after_crowd != after_psychology        # the crowd moved it last

    # The decision boundary sits exactly at the fully composed bias.
    class Fixed(random.Random):
        value = 0.0

        def random(self):  # noqa: D102
            return type(self).value

    trader._rng = Fixed()
    Fixed.value = after_crowd - 1e-12
    assert trader._decide(ctx).action.value == "buy"
    Fixed.value = after_crowd + 1e-12
    assert trader._decide(ctx).action.value == "sell"


def test_the_crowd_layer_does_not_disturb_the_layers_before_it():
    state = compute_psychology(signals_from_closes([1.0, 0.93, 0.82, 0.7, 0.6]))
    quiet, loud = retail(0.0, sentiment_sensitivity=1.0), retail(sentiment_sensitivity=1.0)
    ctx = context(0.02, sentiment=-0.5, psychology=state)
    assert quiet.effective_buy_bias(ctx) == loud.effective_buy_bias(ctx)
    assert quiet.psychological_buy_bias(ctx, 0.4) == loud.psychological_buy_bias(ctx, 0.4)


# --- who may react -------------------------------------------------------------------


def test_only_retail_carries_a_directional_sensitivity():
    assert enabled_crowd_direction_sensitivity("retail") == 0.25
    for strategy in ("momentum", "dip_buyer", "panic_seller", "long_term_holder"):
        assert enabled_crowd_direction_sensitivity(strategy) == 0.0
    for strategy in MANIPULATION_STRATEGIES:
        assert enabled_crowd_direction_sensitivity(strategy) == 0.0


def test_the_two_crowd_channels_are_separate_fields():
    """Reusing one sensitivity for both would hand momentum a directional
    response and make the two channels impossible to tell apart."""
    assert enabled_crowd_sensitivity("momentum") == 0.5
    assert enabled_crowd_direction_sensitivity("momentum") == 0.0
    assert enabled_crowd_sensitivity("retail") == 0.0
    assert enabled_crowd_direction_sensitivity("retail") == 0.25
    assert MomentumTrader.default_crowd_sensitivity == 0.5
    assert MomentumTrader.default_crowd_direction_sensitivity == 0.0
    assert RetailTrader.default_crowd_sensitivity == 0.0
    assert RetailTrader.default_crowd_direction_sensitivity == 0.25


def test_setting_one_channel_leaves_the_other_at_zero():
    trader = RetailTrader("r", crowd_direction_sensitivity=0.25)
    assert trader.crowd_direction_sensitivity == 0.25
    assert trader.crowd_sensitivity == 0.0
    other = MomentumTrader("m", crowd_sensitivity=0.5)
    assert other.crowd_sensitivity == 0.5
    assert other.crowd_direction_sensitivity == 0.0


def test_every_strategy_is_off_unless_a_caller_asks():
    for cls in list(TRADER_STRATEGIES.values()) + list(MANIPULATION_STRATEGIES.values()):
        assert cls("t").crowd_direction_sensitivity == 0.0


@pytest.mark.parametrize("cls", [PumpAndDump, WashTrader])
def test_a_manipulator_cannot_be_given_a_directional_response(cls):
    with pytest.raises(ValueError, match="crowd_direction_sensitivity must be 0"):
        cls("bad", crowd_direction_sensitivity=0.2)


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), "0.25", True, None])
def test_an_invalid_directional_sensitivity_is_rejected(value):
    with pytest.raises(ValueError, match="crowd_direction_sensitivity"):
        RetailTrader("r", crowd_direction_sensitivity=value)


def test_a_directional_trader_without_an_observation_is_refused():
    coin = Coin("FIC", "FictiCoin (Simulated)", SUPPLY, 1.0)
    with pytest.raises(ValueError, match="crowd_observation=True"):
        CoinSimulator(coin, seed=1, traders=[retail()], crowd_observation=False)


def test_the_other_strategies_directions_are_untouched():
    """Every non-retail strategy decides its side from a threshold rule the
    crowd never sees."""
    history = (1.0, 1.06, 1.15, 1.25, 1.35, 1.5, 1.32, 1.14, 0.98, 0.9, 0.86, 0.84)
    for build in (
        lambda: MomentumTrader("t", starting_cash=40_000.0, starting_coins=10_000.0,
                               max_trade_size=15_000.0, risk_tolerance=0.5),
        lambda: DipBuyer("t", starting_cash=40_000.0, max_trade_size=15_000.0, risk_tolerance=0.5),
        lambda: PanicSeller("t", starting_cash=5_000.0, starting_coins=30_000.0,
                            max_trade_size=20_000.0, risk_tolerance=0.8),
        lambda: LongTermHolder("t", starting_cash=20_000.0, starting_coins=60_000.0,
                               max_trade_size=5_000.0, risk_tolerance=0.25),
    ):
        trader = build()
        ctx = dataclasses.replace(context(0.9), price=0.84, price_history=history)
        flat = dataclasses.replace(ctx, crowd_flow=None)
        assert trader._decide(ctx) == trader._decide(flat)


# --- RNG ------------------------------------------------------------------------------


def test_the_directional_term_never_draws():
    class Forbidden(random.Random):
        def random(self):  # noqa: D102
            raise AssertionError("the directional crowd term must not draw")

    trader = retail()
    trader._rng = Forbidden()
    for i in range(2000):
        flow = (i - 1000) / 1000
        trader.crowd_direction_tilt(context(flow))
        trader.crowd_buy_bias(context(flow), 0.5)


def test_the_transform_is_deterministic():
    trader = retail()
    for flow in (-0.7, -0.004, 0.0, 0.004, 0.7):
        values = {trader.crowd_direction_tilt(context(flow)) for _ in range(50)}
        assert len(values) == 1


def test_retail_draws_exactly_as_often_as_it_always_did():
    """Retail has always drawn twice on a tick it acts — once for the
    participation gate in ``decide``, once for buy-versus-sell in
    ``_decide``. Step 7 changes the number the second draw is compared
    against and nothing about when either is taken, so the count is
    identical with the directional term on and off."""

    class Counting(random.Random):
        def __init__(self, seed):
            super().__init__(seed)
            self.draws = 0

        def random(self):  # noqa: D102
            self.draws += 1
            return super().random()

    flows = [(i - 100) / 5000 for i in range(200)]
    counts = []
    for sensitivity in (0.0, SENSITIVE):
        trader = retail(
            sensitivity, trade_probability=1.0,
            starting_cash=5_000.0, starting_coins=5_000.0, max_trade_size=2_000.0,
        )
        trader._rng = Counting(5)
        for flow in flows:
            trader.decide(context(flow))
        counts.append(trader._rng.draws)

    assert counts[0] == counts[1] == 2 * len(flows)  # one gate + one direction, always


# --- psychology independence ----------------------------------------------------------


def test_the_directional_term_never_reaches_psychology():
    fields = {f.name for f in dataclasses.fields(signals_from_closes([1.0, 1.1]))}
    assert not any("crowd" in name or "flow" in name for name in fields)
    state = compute_psychology(signals_from_closes([1.0, 1.05, 1.13, 1.2, 1.31]))
    assert {f.name for f in dataclasses.fields(state)} == {
        "fear", "fomo", "conviction", "uncertainty"
    }


def test_psychology_sources_have_never_heard_of_the_crowd():
    from pathlib import Path

    from crypto_simulator.core.psychology import signals, state

    for module in (signals, state):
        assert "crowd" not in Path(module.__file__).read_text(), module.__name__


# --- whole runs ------------------------------------------------------------------------


def _digest(sim, ticks):
    return [
        (t.tick, t.price, t.volume, tuple(
            (f.trader_id, f.strategy, f.side.value, f.quantity, f.price, f.wash)
            for f in t.trader_trades
        ), t.psychology)
        for t in ticks
    ], [(x.trader_id, x.wallet.cash, x.wallet.coins) for x in sim.traders]


def _build(*, mode, psychology, observation, response, direction, condition=None, seed=4242):
    base = apply_market_condition(settings(), condition, pricing_mode=mode)
    base = dataclasses.replace(
        base, simulation=dataclasses.replace(base.simulation, random_seed=seed)
    )
    return build_coin_simulator(
        base, pricing_mode=mode, psychology=psychology,
        include_whales=(mode == "random_walk"),
        crowd_observation=observation, crowd_response=response, crowd_direction=direction,
    )


def _run(*, ticks=200, **kwargs):
    sim = _build(**kwargs)
    return sim, sim.run(ticks)


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("psychology", [False, True])
def test_a0_and_a1_are_identical(mode, psychology):
    """A0 (no observation) and A1 (observation present, both responses off)
    must remain the same run."""
    a0 = _digest(*_run(mode=mode, psychology=psychology,
                       observation=False, response=False, direction=False))
    a1 = _digest(*_run(mode=mode, psychology=psychology,
                       observation=True, response=False, direction=False))
    assert a0 == a1


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("psychology", [False, True])
def test_a2d_differs_from_a1(mode, psychology):
    a1 = _digest(*_run(mode=mode, psychology=psychology,
                       observation=True, response=False, direction=False))
    a2d = _digest(*_run(mode=mode, psychology=psychology,
                        observation=True, response=False, direction=True))
    assert a1 != a2d


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_a2d_enables_only_the_directional_channel(mode):
    sim = _build(mode=mode, psychology=True, observation=True, response=False, direction=True)
    assert {t.strategy_name: t.crowd_direction_sensitivity for t in sim.traders} == {
        "retail": 0.25, "momentum": 0.0, "dip_buyer": 0.0,
        "panic_seller": 0.0, "long_term_holder": 0.0,
    }
    assert all(t.crowd_sensitivity == 0.0 for t in sim.traders)


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_the_two_channels_can_be_switched_on_independently(mode):
    only_direction = _build(mode=mode, psychology=True, observation=True,
                            response=False, direction=True)
    only_participation = _build(mode=mode, psychology=True, observation=True,
                                response=True, direction=False)
    both = _build(mode=mode, psychology=True, observation=True, response=True, direction=True)
    assert [t.crowd_sensitivity for t in only_direction.traders] == [0.0] * 5
    assert [t.crowd_direction_sensitivity for t in only_participation.traders] == [0.0] * 5
    assert {t.strategy_name for t in both.traders if t.crowd_sensitivity} == {"momentum"}
    assert {t.strategy_name for t in both.traders if t.crowd_direction_sensitivity} == {"retail"}


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_the_directional_run_touches_no_global_randomness(mode):
    state = random.getstate()
    _run(mode=mode, psychology=True, observation=True, response=False, direction=True)
    assert random.getstate() == state


def test_the_observation_is_still_lag_one_with_the_directional_response_on():
    from crypto_simulator.core.coin_simulator import organic_crowd_flow

    seen = []
    sim = _build(mode="random_walk", psychology=False, observation=True,
                 response=False, direction=True)
    original = sim._market_context

    def recording(price, event_state, psychology):
        ctx = original(price, event_state, psychology)
        seen.append(ctx.crowd_flow)
        return ctx

    sim._market_context = recording
    ticks = sim.run(40)
    assert seen[0] is None
    for i in range(1, len(seen)):
        assert seen[i] == organic_crowd_flow(ticks[i - 1].trader_trades, sim.coin.initial_supply)


def test_manipulator_and_wash_activity_never_reaches_the_directional_signal():
    from crypto_simulator.core.coin_simulator import organic_crowd_flow
    from crypto_simulator.core.traders.base import TradeAction

    base = dataclasses.replace(
        settings(), simulation=dataclasses.replace(settings().simulation, random_seed=99)
    )
    sim = build_coin_simulator(
        base, pricing_mode="random_walk", psychology=True, scenario="wash_trading",
        crowd_observation=True, crowd_direction=True,
    )
    ticks = sim.run(80)
    assert sum(f.quantity for t in ticks for f in t.trader_trades if f.wash) > 0
    for tick in ticks:
        organic = [
            f for f in tick.trader_trades
            if not f.wash and f.strategy not in MANIPULATION_STRATEGIES
        ]
        expected = sum(
            f.quantity if f.side is TradeAction.BUY else -f.quantity for f in organic
        ) / sim.coin.initial_supply
        assert organic_crowd_flow(tick.trader_trades, sim.coin.initial_supply) == pytest.approx(
            expected, abs=1e-15
        )
    assert all(t.crowd_direction_sensitivity == 0.0 for t in sim.traders
               if t.strategy_name in MANIPULATION_STRATEGIES)


def test_whale_only_ticks_are_observed_as_zero_flow_and_tilt_nothing():
    from crypto_simulator.core.coin_simulator import organic_crowd_flow

    sim, ticks = _run(mode="random_walk", psychology=False, observation=True,
                      response=False, direction=True)
    whale_only = [t for t in ticks if t.whale_trades and not t.trader_trades]
    assert whale_only, "expected at least one whale-only tick in this run"
    for tick in whale_only:
        flow = organic_crowd_flow(tick.trader_trades, sim.coin.initial_supply)
        assert flow == 0.0
        assert retail().crowd_direction_tilt(context(flow)) == 0.0
