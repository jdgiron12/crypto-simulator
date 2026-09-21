"""The bounded crowd-flow participation response (Phase 19, Step 4).

Step 2 put the previous completed tick's organic flow on the context.
Step 4 adds exactly one thing: a trader whose ``crowd_sensitivity`` is
non-zero becomes *likelier to act* when that crowd was loud. Nothing else
moves — not sizing, not direction, not a threshold, not psychology — and
the tests here are mostly about what did NOT change.

Layout follows the mechanism: first the transform on its own (bounded,
saturating, smooth, sign-blind, extreme values), then the participation
layer it feeds, then what the rest of the trader still does, then whole
runs across both pricing modes.
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
    CROWD_FLOW_SCALE,
    CROWD_URGE_CAP,
    MarketContext,
    PsychologyContext,
    TradeAction,
    TraderAgent,
)
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import (
    MANIPULATION_STRATEGIES,
    TRADER_STRATEGIES,
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
SENSITIVE = MomentumTrader.default_crowd_sensitivity


def settings():
    """default.yaml from the file, so CRYPTOSIM_* cannot leak in."""
    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as handle:
        return build_settings(yaml.safe_load(handle), DEFAULT_CONFIG_PATH)


def context(flow, *, price=1.0, history=(1.0,) * 12, attention=1.0, psychology=None):
    fields = dict(
        tick=13, price=price, price_history=history, total_supply=SUPPLY,
        attention_multiplier=attention, crowd_flow=flow,
    )
    if psychology is None:
        return MarketContext(**fields)
    return PsychologyContext(**fields, psychology=psychology)


def momentum(sensitivity=SENSITIVE, **kwargs):
    kwargs.setdefault("trade_probability", 0.7)
    return MomentumTrader("m-1", crowd_sensitivity=sensitivity, **kwargs)


# --- the transform -------------------------------------------------------------------


def test_zero_flow_is_zero_pressure_and_changes_nothing():
    """S. A crowd that netted out is not a crowd."""
    trader = momentum()
    assert trader.crowd_pressure(context(0.0)) == 0.0
    assert trader.crowd_urge(context(0.0)) == 0.0
    assert trader.participation_probability(context(0.0)) == trader.trade_probability


def test_no_observation_is_not_a_flow_of_zero_but_is_treated_as_no_news():
    """The first tick, and every tick with observation off, carry ``None``."""
    trader = momentum()
    assert context(None).crowd_flow is None
    assert trader.crowd_pressure(context(None)) == 0.0
    assert trader.participation_probability(context(None)) == trader.trade_probability


@pytest.mark.parametrize("flow", [-1.0, -0.5, -0.02, -0.01, -0.001, 0.0, 0.001, 0.01, 0.02, 0.5, 1.0])
def test_the_response_is_bounded_by_its_cap_at_every_flow(flow):
    """R. Bounded, including at the observable's own extremes."""
    trader = momentum()
    assert 0.0 <= trader.crowd_pressure(context(flow)) <= 1.0
    assert 0.0 <= trader.crowd_urge(context(flow)) <= CROWD_URGE_CAP


@pytest.mark.parametrize("flow", [0.001, 0.005, 0.01, 0.023, 0.1, 0.5, 1.0])
def test_the_sign_of_the_flow_does_not_matter(flow):
    """T. This term feeds participation only, and a crowd that sold hard is
    exactly as attention-grabbing as one that bought hard. The direction of
    the resulting trade is the strategy's business, not the crowd's."""
    trader = momentum()
    assert trader.crowd_pressure(context(flow)) == trader.crowd_pressure(context(-flow))
    assert trader.crowd_urge(context(flow)) == trader.crowd_urge(context(-flow))
    assert trader.participation_probability(context(flow)) == pytest.approx(
        trader.participation_probability(context(-flow)), rel=0, abs=0
    )


def test_the_transform_is_the_documented_one():
    """B2. tanh(|flow| / CROWD_FLOW_SCALE), stated exactly."""
    trader = momentum()
    for flow in (0.0005, 0.003, 0.0127, 0.4):
        assert trader.crowd_pressure(context(flow)) == math.tanh(abs(flow) / CROWD_FLOW_SCALE)
        assert trader.crowd_urge(context(flow)) == min(
            CROWD_URGE_CAP, SENSITIVE * math.tanh(abs(flow) / CROWD_FLOW_SCALE)
        )


def test_the_response_rises_with_the_crowd_and_never_falls():
    trader = momentum()
    flows = [i / 2000 for i in range(0, 200)]
    urges = [trader.crowd_urge(context(f)) for f in flows]
    assert urges == sorted(urges)
    assert urges[0] == 0.0 and urges[-1] > urges[0]


def test_the_response_is_continuous_with_no_step_anywhere():
    """No threshold triggers: a tiny change in flow makes a tiny change in
    the response, right across the range including where the cap would sit."""
    trader = momentum()
    step = 1e-5
    flows = [i * step for i in range(0, 20_000)]
    urges = [trader.crowd_urge(context(f)) for f in flows]
    jumps = [abs(b - a) for a, b in zip(urges, urges[1:])]
    # The steepest the transform can be is sensitivity/scale at the origin.
    assert max(jumps) <= SENSITIVE * step / CROWD_FLOW_SCALE + 1e-12


def test_the_response_saturates_rather_than_growing_without_bound():
    trader = momentum()
    assert trader.crowd_urge(context(0.05)) == pytest.approx(CROWD_URGE_CAP, abs=1e-3)
    assert trader.crowd_urge(context(1.0)) == CROWD_URGE_CAP
    # No overflow, no NaN, at the bound or beyond it.
    for flow in (1.0, -1.0, 1e6, -1e6):
        urge = trader.crowd_urge(context(flow))
        assert math.isfinite(urge) and urge <= CROWD_URGE_CAP


def test_zero_sensitivity_never_evaluates_the_transform():
    assert momentum(0.0).crowd_pressure(context(0.03)) == 0.0
    assert momentum(0.0).crowd_urge(context(0.03)) == 0.0


# --- the participation layer ---------------------------------------------------------


@pytest.mark.parametrize("probability", [0.0, 0.05, 0.3, 0.5, 0.7, 0.9, 1.0])
@pytest.mark.parametrize("flow", [None, 0.0, 0.004, 0.02, 1.0, -1.0])
def test_participation_probability_stays_a_valid_probability(probability, flow):
    """L. Always in [0, 1], whatever the crowd does."""
    trader = momentum(trade_probability=probability)
    result = trader.participation_probability(context(flow))
    assert 0.0 <= result <= 1.0


@pytest.mark.parametrize("probability", [0.05, 0.3, 0.5, 0.7, 0.9, 0.999])
@pytest.mark.parametrize("flow", [None, 0.0, 0.004, 0.02, 1.0, -1.0])
def test_the_crowd_never_makes_acting_certain(probability, flow):
    """L. Only a trader already certain to act (``trade_probability`` 1)
    ever reaches 1; the crowd cannot carry anyone there."""
    trader = momentum(trade_probability=probability)
    assert trader.participation_probability(context(flow)) < 1.0


def test_a_trader_that_never_acts_still_never_acts():
    trader = momentum(trade_probability=0.0)
    assert trader.participation_probability(context(1.0)) == 0.0


def test_the_maximum_contribution_is_the_documented_fraction():
    """B4. The most the crowd can add is ``CROWD_URGE_CAP × (1 - p)``
    relative — 15% for the shipped momentum trader — and it takes the whole
    supply changing hands in one tick to get there."""
    trader = momentum()
    plain = trader.trade_probability
    loudest = trader.participation_probability(context(1.0))
    assert loudest == plain * (1.0 + CROWD_URGE_CAP * (1.0 - plain))
    assert loudest / plain - 1.0 == pytest.approx(0.15, abs=1e-12)
    assert loudest < 1.0


def test_the_crowd_layer_cannot_exceed_the_psychology_layer():
    """The cap is half psychology's own ceiling, so the crowd is never the
    larger of the two engagement terms at equal strength."""
    assert CROWD_URGE_CAP == 0.5
    trader = momentum()
    p = trader.trade_probability
    crowd_max = TraderAgent._engage(p, CROWD_URGE_CAP)
    psychology_max = TraderAgent._engage(p, 1.0)
    assert crowd_max < psychology_max


def test_the_engagement_operator_is_the_one_psychology_already_used():
    for probability in (0.0, 0.25, 0.7, 1.0):
        assert TraderAgent._engage(probability, 0.0) == probability
    assert TraderAgent._engage(0.5, 1.0) == pytest.approx(0.75)  # 1 - (1 - p)^2
    assert TraderAgent._engage(1.0, 1.0) == 1.0


def test_psychology_and_crowd_compose_without_either_being_lost():
    """H/C. The crowd is applied *after* psychology, on psychology's result,
    and does not disturb it."""
    state = compute_psychology(signals_from_closes([1.0, 1.1, 1.25, 1.4, 1.6]))
    trader = PanicSeller("p-1", trade_probability=0.8, crowd_sensitivity=0.4)
    quiet = context(0.0, psychology=state)
    loud = context(0.05, psychology=state)
    after_psychology = TraderAgent._engage(
        trader.trade_probability, trader.participation_urge(quiet)
    )
    assert trader.participation_probability(quiet) == after_psychology
    assert trader.participation_probability(loud) == TraderAgent._engage(
        after_psychology, trader.crowd_urge(loud)
    )


def test_attention_psychology_and_crowd_all_still_apply_together():
    state = compute_psychology(signals_from_closes([1.0, 0.9, 0.78, 0.66, 0.5]))
    trader = PanicSeller("p-1", trade_probability=0.5, crowd_sensitivity=0.4)
    ctx = context(0.03, attention=1.4, psychology=state)
    assert trader.participation_probability(ctx) > trader.participation_probability(
        context(0.0, attention=1.4, psychology=state)
    )
    assert trader.participation_probability(ctx) < 1.0


# --- what the crowd must NOT touch ---------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda s: MomentumTrader("t", starting_cash=40_000.0, starting_coins=10_000.0,
                                 max_trade_size=15_000.0, risk_tolerance=0.5,
                                 lookback=5, entry_threshold=0.03, exit_threshold=0.03,
                                 crowd_sensitivity=s),
        lambda s: PanicSeller("t", starting_cash=5_000.0, starting_coins=30_000.0,
                              max_trade_size=20_000.0, risk_tolerance=0.8,
                              crowd_sensitivity=s),
        lambda s: DipBuyer("t", starting_cash=40_000.0, max_trade_size=15_000.0,
                           risk_tolerance=0.5, crowd_sensitivity=s),
    ],
)
@pytest.mark.parametrize("flow", [0.0, 0.004, 0.03, 1.0, -1.0])
def test_the_decision_itself_is_untouched(build, flow):
    """J/K. Same context, same strategy, crowd on and off: the trade the
    strategy would make — side, size, reason — is identical. The crowd
    changes *whether* the trader is asked, never what it answers."""
    history = (1.0, 1.05, 1.12, 1.2, 1.3, 1.45, 1.3, 1.1, 0.95, 0.9, 0.88, 0.85)
    ctx = context(flow, price=0.85, history=history)
    quiet, loud = build(0.0), build(SENSITIVE)
    assert quiet._decide(ctx) == loud._decide(ctx)


@pytest.mark.parametrize("flow", [0.0, 0.02, 1.0])
def test_the_crowd_does_not_bend_momentums_thresholds(flow):
    trader = momentum()
    ctx = context(flow)
    assert trader.effective_thresholds(ctx) == (trader.entry_threshold, trader.exit_threshold)
    assert trader.psychological_thresholds(ctx, 0.03, 0.03) == (0.03, 0.03)


@pytest.mark.parametrize("flow", [0.0, 0.02, 1.0])
def test_the_crowd_does_not_reach_sentiment_pressure(flow):
    trader = momentum()
    assert trader.sentiment_pressure(context(flow)) == 0.0


def test_the_crowd_never_reaches_psychology():
    """H/I. ``compute_psychology`` is a function of prices and events. Its
    inputs have no crowd field, and a loud crowd cannot change its output
    because it is never offered one."""
    fields = {f.name for f in dataclasses.fields(signals_from_closes([1.0, 1.1]))}
    assert not any("crowd" in name for name in fields)
    assert not any("flow" in name for name in fields)
    closes = [1.0, 1.05, 1.13, 1.2, 1.31]
    assert compute_psychology(signals_from_closes(closes)) == compute_psychology(
        signals_from_closes(closes)
    )


def test_psychology_state_has_no_crowd_component():
    state = compute_psychology(signals_from_closes([1.0, 1.1, 1.2]))
    assert {f.name for f in dataclasses.fields(state)} == {
        "fear", "fomo", "conviction", "uncertainty"
    }


# --- who may react -------------------------------------------------------------------


def test_only_momentum_is_given_a_response_by_default():
    """B3/B5/Q. Retail and the long-term holder stay at zero — they showed
    no conditional association in Step 3 — and so does every manipulator."""
    assert enabled_crowd_sensitivity("momentum") == 0.5
    for strategy in ("retail", "long_term_holder", "dip_buyer", "panic_seller"):
        assert enabled_crowd_sensitivity(strategy) == 0.0
    for strategy in MANIPULATION_STRATEGIES:
        assert enabled_crowd_sensitivity(strategy) == 0.0


def test_every_strategy_is_off_unless_a_caller_asks():
    """Opt-in: instantiating a trader the ordinary way gives it no response,
    momentum included."""
    for cls in list(TRADER_STRATEGIES.values()) + list(MANIPULATION_STRATEGIES.values()):
        assert cls("t").crowd_sensitivity == 0.0


@pytest.mark.parametrize("cls", [PumpAndDump, WashTrader])
def test_a_manipulator_cannot_be_given_a_crowd_response(cls):
    """F. The exclusion Step 2 built into the signal would leak straight
    back in if a manipulator could follow the crowd it helped make."""
    with pytest.raises(ValueError, match="crowd_sensitivity must be 0"):
        cls("bad", crowd_sensitivity=0.3)


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), "0.5", True, None])
def test_an_invalid_sensitivity_is_rejected(value):
    with pytest.raises(ValueError, match="crowd_sensitivity"):
        MomentumTrader("m", crowd_sensitivity=value)


def test_a_reactive_trader_without_an_observation_is_refused():
    """A sensitivity with nothing to read would be silently inert."""
    coin = Coin("FIC", "FictiCoin (Simulated)", SUPPLY, 1.0)
    with pytest.raises(ValueError, match="crowd_observation=True"):
        CoinSimulator(coin, seed=1, traders=[momentum()], crowd_observation=False)


def test_the_stabilisers_participation_is_bit_for_bit_unchanged():
    """Q. Whatever the crowd does, the dip buyer and the long-term holder
    decide to show up exactly as often as they did before Step 4."""
    for cls in (DipBuyer, LongTermHolder, RetailTrader):
        trader = cls("t", trade_probability=0.6)
        plain = trader.participation_probability(context(None))
        for flow in (0.0, 0.01, 0.05, 1.0, -1.0):
            assert trader.participation_probability(context(flow)) == plain


# --- whole runs ----------------------------------------------------------------------


def _digest(sim, ticks):
    return [
        (t.tick, t.price, t.volume, tuple(
            (f.trader_id, f.strategy, f.side.value, f.quantity, f.price, f.wash)
            for f in t.trader_trades
        ), t.psychology)
        for t in ticks
    ], [(x.trader_id, x.wallet.cash, x.wallet.coins) for x in sim.traders]


def _build(*, mode, psychology, observation, response, condition=None, events=None, seed=4242):
    base = apply_market_condition(settings(), condition, pricing_mode=mode)
    if events is not None:
        base = events(base)
    base = dataclasses.replace(
        base, simulation=dataclasses.replace(base.simulation, random_seed=seed)
    )
    return build_coin_simulator(
        base, pricing_mode=mode, psychology=psychology,
        include_whales=(mode == "random_walk"),
        crowd_observation=observation, crowd_response=response,
    )


def _run(*, ticks=200, **kwargs):
    sim = _build(**kwargs)
    return sim, sim.run(ticks)


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("psychology", [False, True])
def test_a0_and_a1_are_identical(mode, psychology):
    """A/B. Crowd off, and crowd observed but ignored, are the same run."""
    a0 = _digest(*_run(mode=mode, psychology=psychology, observation=False, response=False))
    a1 = _digest(*_run(mode=mode, psychology=psychology, observation=True, response=False))
    assert a0 == a1


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("psychology", [False, True])
def test_a2_differs_from_a1(mode, psychology):
    """M/N. The mechanism does something, in both pricing modes, with
    psychology off and on."""
    a1 = _digest(*_run(mode=mode, psychology=psychology, observation=True, response=False))
    a2 = _digest(*_run(mode=mode, psychology=psychology, observation=True, response=True))
    assert a1 != a2


def test_attention_can_leave_the_crowd_no_room_and_that_is_the_correct_bound():
    """Each engagement layer can only close the *remaining* gap to 1, so a
    trader that attention has already carried to certainty cannot be moved
    further by the crowd. This is the composed bound doing its job, not the
    response failing, and it is why the Phase 17 conditions below are
    asserted the way they are rather than simply expected to differ."""
    trader = momentum(trade_probability=0.7)
    saturating = context(0.05, attention=2.0)   # 0.7 x 2.0 -> capped at 1.0
    assert trader.participation_probability(context(None, attention=2.0)) == 1.0
    assert trader.crowd_urge(saturating) > 0.0          # the crowd IS loud
    assert trader.participation_probability(saturating) == 1.0  # and has no room


@pytest.mark.parametrize("condition", ["bull", "bear", "meme"])
def test_the_response_applies_under_every_market_condition_where_it_has_room(condition):
    """O. The Phase 17 conditions raise attention to ~2-3x, which on its own
    saturates this trader's participation on most ticks. So the honest
    assertion is not "the run differs" but "wherever there was room, the
    crowd used it, and wherever there was none, it changed nothing" —
    checked tick by tick against the arm's own contexts."""
    sim = _build(mode="random_walk", psychology=True, observation=True,
                 response=True, condition=condition)
    trader = next(t for t in sim.traders if t.strategy_name == "momentum")
    plain = momentum(0.0, trade_probability=trader.trade_probability)
    original = sim._market_context
    room, used, saturated = 0, 0, 0

    def recording(price, event_state, psychology):
        nonlocal room, used, saturated
        ctx = original(price, event_state, psychology)
        before = plain.participation_probability(ctx)
        after = trader.participation_probability(ctx)
        if before >= 1.0:
            saturated += 1
            assert after == before
        elif trader.crowd_urge(ctx) > 0.0:
            room += 1
            used += after > before
        return ctx

    sim._market_context = recording
    sim.run(200)
    assert saturated > 0, "expected attention to saturate some ticks here"
    assert room > 0, "expected some ticks with room for the crowd term"
    assert used == room, "the crowd must raise participation on every tick it has room"


def _scheduled(base):
    from crypto_simulator.services.coin_simulation import DEMO_EVENTS
    coin = base.coin
    return dataclasses.replace(base, coin=dataclasses.replace(
        coin, events=dataclasses.replace(coin.events, scheduled=list(DEMO_EVENTS))
    ))


def _random_events(base):
    from crypto_simulator.services.coin_simulation import DEMO_RANDOM_EVENT_PROBABILITY
    coin = base.coin
    return dataclasses.replace(base, coin=dataclasses.replace(
        coin, events=dataclasses.replace(
            coin.events,
            random=dataclasses.replace(
                coin.events.random, probability=DEMO_RANDOM_EVENT_PROBABILITY
            ),
        )
    ))


@pytest.mark.parametrize("events", [None, _scheduled, _random_events])
def test_the_response_works_under_every_event_setting(events):
    """P."""
    a1 = _digest(*_run(mode="random_walk", psychology=True, observation=True,
                       response=False, events=events))
    a2 = _digest(*_run(mode="random_walk", psychology=True, observation=True,
                       response=True, events=events))
    assert a1 != a2


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_only_the_momentum_trader_is_reactive_in_a_built_run(mode):
    """C. The response reaches exactly the class it was given to."""
    sim, _ = _run(mode=mode, psychology=True, observation=True, response=True)
    assert {t.strategy_name: t.crowd_sensitivity for t in sim.traders} == {
        "retail": 0.0, "momentum": 0.5, "dip_buyer": 0.0,
        "panic_seller": 0.0, "long_term_holder": 0.0,
    }


def test_the_mechanism_itself_never_draws():
    """D. ``crowd_pressure``, ``crowd_urge`` and the engagement operator are
    arithmetic on the context. Called thousands of times against an RNG that
    refuses to be used, they never reach for it."""

    class Forbidden(random.Random):
        def random(self):  # noqa: D102
            raise AssertionError("the crowd response must not draw")

    trader = momentum()
    trader._rng = Forbidden()
    for i in range(2000):
        flow = (i - 1000) / 1000
        trader.crowd_pressure(context(flow))
        trader.crowd_urge(context(flow))
        trader.participation_probability(context(flow))


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_with_psychology_off_every_rng_stream_ends_identical(mode):
    """D. The clean isolation. With psychology off and no events, every
    trader's participation probability is a constant except the reactive
    one's, so nothing downstream can change how often anybody draws. A1 and
    A2 then leave every RNG stream — each trader's, each whale's, the price
    engine's, the volume model's — in *exactly* the same state, while the
    price path diverges. The mechanism consumes the identical random
    numbers and only moves the threshold they are compared against."""
    a1, a1_ticks = _run(mode=mode, psychology=False, observation=True, response=False)
    a2, a2_ticks = _run(mode=mode, psychology=False, observation=True, response=True)

    assert [t._rng.getstate() for t in a1.traders] == [t._rng.getstate() for t in a2.traders]
    assert [w._rng.getstate() for w in a1.whales] == [w._rng.getstate() for w in a2.whales]
    assert a1._price_engine._rng.getstate() == a2._price_engine._rng.getstate()
    assert a1._volume_model._rng.getstate() == a2._volume_model._rng.getstate()
    assert [t.price for t in a1_ticks] != [t.price for t in a2_ticks]


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("response", [False, True])
def test_draws_per_trader_per_tick_are_what_they_always_were(mode, response):
    """D. With psychology ON a different price path can flip *retail's*
    gate, and retail has always drawn a second number — its buy/sell bias —
    only on the ticks it acts. That pre-existing conditional draw is the one
    thing whose count can move, and it moves because the price moved, not
    because the crowd added a source. The contract this pins is the old one,
    unchanged by Step 4: one gate draw per trader per tick, plus retail's
    own second draw on the ticks it acts, and nothing else."""

    counts: dict[str, int] = {}

    class Counting(random.Random):
        def __init__(self, name, seed):
            super().__init__(seed)
            self.name = name

        def random(self):  # noqa: D102
            counts[self.name] = counts.get(self.name, 0) + 1
            return super().random()

    sim = _build(mode=mode, psychology=True, observation=True, response=response)
    for trader in sim.traders:
        trader._rng = Counting(trader.strategy_name, 7)
    ticks = sim.run(60)

    acted = {
        name: sum(
            1 for t in ticks for f in t.trader_trades if f.strategy == name
        )
        for name in counts
    }
    for name, drawn in counts.items():
        if name == "retail":
            assert 60 <= drawn <= 120, name
            assert drawn >= 60 + acted[name]
        else:
            assert drawn == 60, name


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_a_crowd_response_run_touches_no_global_randomness(mode):
    state = random.getstate()
    _run(mode=mode, psychology=True, observation=True, response=True)
    assert random.getstate() == state


def test_exactly_one_draw_per_trader_per_tick_with_the_response_on():
    """D. Counted, not inferred."""

    class Counting(random.Random):
        draws = 0

        def random(self):  # noqa: D102
            type(self).draws += 1
            return super().random()

    sim = _build(mode="amm", psychology=False, observation=True, response=True)
    for trader in sim.traders:
        trader._rng = Counting(1)
    Counting.draws = 0
    sim.run(40)
    # Psychology off and no events, so retail's gate never flips and its
    # second draw fires on exactly the ticks it would have anyway.
    retail = sum(1 for t in sim.history for f in t.trader_trades if f.strategy == "retail")
    assert Counting.draws == 40 * len(sim.traders) + retail


def test_the_observation_is_still_lag_one_with_the_response_on():
    """E. Step 4 changed what a trader does with the number, not when it
    arrives: a tick still sees the previous completed tick and never itself."""
    from crypto_simulator.core.coin_simulator import organic_crowd_flow

    seen = []
    sim = _build(mode="random_walk", psychology=False, observation=True, response=True)
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


def test_whales_never_reach_the_signal_a_trader_reacts_to():
    """G. Whale trades are not ``TraderTrade``s, so a tick whose only
    activity was a whale is observed as a flow of exactly zero — and a zero
    flow is zero pressure."""
    from crypto_simulator.core.coin_simulator import organic_crowd_flow

    sim, ticks = _run(mode="random_walk", psychology=False, observation=True, response=True)
    whale_only = [
        t for t in ticks if t.whale_trades and not t.trader_trades
    ]
    assert whale_only, "expected at least one whale-only tick in this run"
    for tick in whale_only:
        flow = organic_crowd_flow(tick.trader_trades, sim.coin.initial_supply)
        assert flow == 0.0
        assert momentum().crowd_urge(context(flow)) == 0.0


def test_manipulator_and_wash_activity_never_reaches_the_response():
    """F. On a real manipulated market, the flow a reactive trader sees
    still holds only the organic crowd."""
    from crypto_simulator.core.coin_simulator import organic_crowd_flow

    base = dataclasses.replace(
        settings(), simulation=dataclasses.replace(settings().simulation, random_seed=99)
    )
    sim = build_coin_simulator(
        base, pricing_mode="random_walk", psychology=True, scenario="wash_trading",
        crowd_observation=True, crowd_response=True,
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
    assert all(t.crowd_sensitivity == 0.0 for t in sim.traders
               if t.strategy_name in MANIPULATION_STRATEGIES)
