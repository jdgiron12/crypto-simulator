"""Explicit whale behavior transitions (Phase 8, Step 4).

``Whale.set_behavior`` moves a funded whale between neutral, accumulate
and distribute. Every transition is explicit and is a state change only:
it trades nothing, moves no balance, draws no randomness, and leaves the
target and both pacing counters untouched. What changes is which
direction the next eligible tick trades in, under the unchanged Step 2
and Step 3 rules.
"""

import math
import random

import pytest

from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale, WhaleBehavior, WhaleState
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0
BEHAVIORS = ("neutral", "accumulate", "distribute")


def _funded(behavior="neutral", cash=500_000.0, coins=100_000.0, seed=1, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale("w", coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _reserve(cash=1e12, coins=1e12):
    return Wallet(cash=cash, coins=coins)


def _snapshot(whale):
    """Everything a transition must leave alone."""
    return (
        whale.wallet.cash, whale.wallet.coins, whale.wallet.average_cost,
        whale.target_coin_fraction, whale.min_trade_fraction, whale.max_trade_fraction,
        whale.activity_probability, whale.impact_coefficient,
        whale.cooldown_ticks, whale.min_trade_interval_ticks,
        whale.state().cooldown_remaining, whale.interval_remaining,
        whale._rng.getstate(),
    )


class _RecordingRNG:
    def __init__(self, seed):
        self._inner = random.Random(seed)
        self.calls = []

    def random(self):
        self.calls.append("random")
        return self._inner.random()

    def choice(self, seq):
        self.calls.append("choice")
        return self._inner.choice(seq)

    def uniform(self, a, b):
        self.calls.append("uniform")
        return self._inner.uniform(a, b)

    def getstate(self):
        return self._inner.getstate()


# --- 1. validation -------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["hodl", "HODL", "", "buy", "sell", None, 1, 0, True, 1.5, ["accumulate"]])
def test_an_invalid_behavior_is_rejected_and_changes_nothing(bad):
    whale = _funded("accumulate")
    before = (whale.behavior, _snapshot(whale))
    with pytest.raises(ValueError, match="Unknown whale behavior"):
        whale.set_behavior(bad)
    assert (whale.behavior, _snapshot(whale)) == before


def test_the_enum_and_its_configuration_string_are_interchangeable():
    for value in BEHAVIORS:
        by_string, by_enum = _funded(), _funded()
        by_string.set_behavior(value)
        by_enum.set_behavior(WhaleBehavior(value))
        assert by_string.behavior is by_enum.behavior is WhaleBehavior(value)
        assert by_string.behavior == value  # WhaleBehavior is a str enum, as before


def test_the_transition_returns_the_behavior_it_left():
    whale = _funded("neutral")
    assert whale.set_behavior("accumulate") is WhaleBehavior.NEUTRAL
    assert whale.set_behavior("distribute") is WhaleBehavior.ACCUMULATE
    assert whale.set_behavior("neutral") is WhaleBehavior.DISTRIBUTE


# --- 2-3. every transition, including self-transitions ---------------------------------------------


@pytest.mark.parametrize("start", BEHAVIORS)
@pytest.mark.parametrize("target", BEHAVIORS)
def test_every_transition_between_the_three_behaviors_works(start, target):
    whale = _funded(start)
    before = _snapshot(whale)
    assert whale.set_behavior(target) is WhaleBehavior(start)
    assert whale.behavior is WhaleBehavior(target)
    assert whale.state().behavior is WhaleBehavior(target)
    assert _snapshot(whale) == before  # nothing but the state moved


@pytest.mark.parametrize("behavior", BEHAVIORS)
def test_setting_the_current_behavior_again_is_a_harmless_no_op(behavior):
    whale = _funded(behavior)
    before = _snapshot(whale)
    for _ in range(5):
        assert whale.set_behavior(behavior) is WhaleBehavior(behavior)
    assert whale.behavior is WhaleBehavior(behavior) and _snapshot(whale) == before


def test_a_long_transition_sequence_ends_where_it_should():
    whale = _funded("neutral")
    before = _snapshot(whale)
    seen = [whale.behavior]
    for step in ("accumulate", "distribute", "neutral", "accumulate", "accumulate", "distribute", "neutral"):
        whale.set_behavior(step)
        seen.append(whale.behavior)
    assert seen == [WhaleBehavior.NEUTRAL, WhaleBehavior.ACCUMULATE, WhaleBehavior.DISTRIBUTE,
                    WhaleBehavior.NEUTRAL, WhaleBehavior.ACCUMULATE, WhaleBehavior.ACCUMULATE,
                    WhaleBehavior.DISTRIBUTE, WhaleBehavior.NEUTRAL]
    assert _snapshot(whale) == before


# --- 4-6. a transition is a state change, nothing else ----------------------------------------------


@pytest.mark.parametrize("start, target", [("neutral", "accumulate"), ("accumulate", "distribute"),
                                           ("distribute", "neutral")])
def test_a_transition_places_no_trade_and_moves_no_balance(start, target):
    whale = _funded(start, target_coin_fraction=0.4 if start != "neutral" else None)
    reserve = _reserve()
    before = (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins)
    whale.set_behavior(target)
    assert (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) == before


def test_a_transition_keeps_the_target_configuration():
    whale = _funded("accumulate", target_coin_fraction=0.35, min_trade_fraction=0.002,
                    cooldown_ticks=4, min_trade_interval_ticks=6)
    for step in ("neutral", "distribute", "neutral", "accumulate"):
        whale.set_behavior(step)
        assert whale.target_coin_fraction == 0.35
        assert whale.min_trade_fraction == 0.002
        assert whale.cooldown_ticks == 4 and whale.min_trade_interval_ticks == 6


def test_a_transition_does_not_rebalance_toward_the_target():
    """Becoming an accumulator that is far below its target does not buy —
    the next eligible tick does."""
    whale = _funded("neutral", cash=1_000_000.0, coins=0.0)
    whale.set_behavior("accumulate")
    whale.target_coin_fraction = 0.9
    assert whale.allocation(PRICE).allocation_gap == pytest.approx(0.9)
    assert (whale.wallet.cash, whale.wallet.coins) == (1_000_000.0, 0.0)  # still nothing bought


# --- 7-8. scheduling survives a transition -----------------------------------------------------------


def test_a_transition_during_cooldown_does_not_reset_it():
    whale = _funded("accumulate", cash=1e9, cooldown_ticks=3)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    assert whale.state().cooldown_remaining == 3
    whale.set_behavior("distribute")
    assert whale.state().cooldown_remaining == 3  # the three ticks still stand
    for remaining in (2, 1, 0):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert whale.state().cooldown_remaining == remaining
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).side == "sell"


def test_a_transition_during_the_trade_interval_does_not_reset_it():
    whale = _funded("accumulate", cash=1e9, min_trade_interval_ticks=4)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    assert whale.interval_remaining == 4
    whale.set_behavior("neutral")
    assert whale.interval_remaining == 4
    for remaining in (3, 2, 1, 0):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert whale.interval_remaining == remaining
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


def test_transitioning_repeatedly_while_blocked_never_shortens_the_wait():
    whale = _funded("accumulate", cash=1e9, cooldown_ticks=2, min_trade_interval_ticks=5)
    reserve = _reserve()
    traded = []
    for tick in range(18):
        whale.set_behavior(BEHAVIORS[tick % 3])  # churn the state every single tick
        if whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None:
            traded.append(tick)
    assert traded == [0, 6, 12]  # still paced by max(cooldown, interval) = 5


# --- 9. no randomness ---------------------------------------------------------------------------------


def test_a_transition_consumes_no_randomness():
    whale = _funded("accumulate", cash=1e9)
    whale._rng = _RecordingRNG(3)
    for step in ("neutral", "distribute", "accumulate", "accumulate", "neutral"):
        whale.set_behavior(step)
    assert whale._rng.calls == []
    whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve())
    assert whale._rng.calls == ["random", "choice", "uniform"]


def test_transitions_do_not_shift_the_rng_sequence():
    """The same seed draws the same numbers in the same order whether or
    not the whale is being transitioned between them."""
    def draws(transitions):
        whale = _funded("neutral", cash=1e9, coins=1e6, seed=9, activity_probability=0.5)
        whale._rng = _RecordingRNG(9)
        reserve = _reserve()
        for tick in range(200):
            if transitions:
                whale.set_behavior(BEHAVIORS[tick % 3])
            whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
        return whale._rng.calls, whale._rng.getstate()

    assert draws(False) == draws(True)


# --- 10. post-transition behavior is the pre-existing implementation -------------------------------------


def test_after_becoming_an_accumulator_a_whale_only_buys():
    whale = _funded("distribute", cash=500_000.0, coins=200_000.0, seed=4)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).side == "sell"
    whale.set_behavior("accumulate")
    sides = {whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).side for _ in range(50)}
    assert sides == {"buy"}


def test_after_becoming_a_distributor_a_whale_only_sells():
    whale = _funded("accumulate", cash=500_000.0, coins=200_000.0, seed=4)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).side == "buy"
    whale.set_behavior("distribute")
    sides = {whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).side for _ in range(15)}
    assert sides == {"sell"}


def test_after_becoming_neutral_a_whale_draws_both_sides_again():
    whale = _funded("accumulate", cash=1e9, coins=1e6, seed=4)
    whale.set_behavior("neutral")
    reserve = _reserve()
    sides = {whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).side for _ in range(60)}
    assert sides == {"buy", "sell"}


def test_a_neutral_whale_matches_one_configured_neutral_from_the_start():
    """A transition leaves no trace: the whale is indistinguishable from
    one built in that state with the same seed and balances."""
    transitioned = _funded("accumulate", cash=1e9, coins=1e6, seed=12)
    transitioned.set_behavior("neutral")
    native = _funded("neutral", cash=1e9, coins=1e6, seed=12)
    a, b = _reserve(), _reserve()
    assert [transitioned.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(200)] == [
        native.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(200)
    ]
    assert _snapshot(transitioned) == _snapshot(native)


def test_a_transitioned_accumulator_matches_one_configured_that_way():
    transitioned = _funded("neutral", cash=800_000.0, coins=50_000.0, seed=15, max_trade_fraction=0.005)
    transitioned.set_behavior("accumulate")
    transitioned.target_coin_fraction = 0.6
    native = _funded("accumulate", cash=800_000.0, coins=50_000.0, seed=15, max_trade_fraction=0.005,
                     target_coin_fraction=0.6)
    a, b = _reserve(), _reserve()
    assert [transitioned.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(200)] == [
        native.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(200)
    ]


# --- target interaction ---------------------------------------------------------------------------------


def test_a_target_is_dormant_while_a_whale_is_neutral():
    """The constructor refuses target + neutral, so only a transition can
    reach that state. There the target is kept but ignored: a target
    steers one direction, which means nothing to a whale trading both."""
    whale = _funded("accumulate", cash=50_000.0, coins=25_000.0, target_coin_fraction=0.5, seed=6,
                    max_trade_fraction=0.0005)
    reserve = _reserve()
    assert whale.allocation(PRICE).at_target
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None  # dead-zone hold
    whale.set_behavior("neutral")
    trades = [whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) for _ in range(40)]
    assert all(t is not None for t in trades)  # sitting on the target no longer stops it
    assert {t.side for t in trades} == {"buy", "sell"}
    assert whale.target_coin_fraction == 0.5  # kept, not discarded
    assert whale.allocation(PRICE).target_coin_fraction == 0.5


def test_a_target_is_authoritative_again_once_the_whale_is_directional():
    # Overweight coins at 0.8 against a 0.5 target, and neutral, so the
    # target is dormant; becoming a distributor puts it back in force.
    whale = _funded("accumulate", cash=20_000.0, coins=40_000.0, target_coin_fraction=0.5, seed=6,
                    max_trade_fraction=0.005)
    whale.set_behavior("neutral")
    assert whale.allocation(PRICE).coin_fraction == pytest.approx(0.8)
    reserve = _reserve()
    whale.set_behavior("distribute")
    trades = [whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) for _ in range(40)]
    assert {t.side for t in trades if t is not None} == {"sell"}
    assert whale.allocation(PRICE).at_target
    assert whale.allocation(PRICE).coin_fraction >= 0.5 - TARGET_DEAD_ZONE
    assert trades[-1] is None  # settled on the target and stopped


def test_a_transition_cannot_make_a_whale_cross_its_target():
    whale = _funded("accumulate", cash=1_000_000.0, coins=0.0, target_coin_fraction=0.5, seed=7,
                    max_trade_fraction=0.05)
    reserve = _reserve()
    rng = random.Random(2)
    for tick in range(400):
        price = rng.uniform(0.5, 4.0)
        if tick % 37 == 0:
            whale.set_behavior("accumulate" if tick % 74 == 0 else "distribute")
        before = whale.allocation(price).coin_fraction
        trade = whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
        after = whale.allocation(price).coin_fraction
        if trade is None:
            continue
        if whale.behavior is WhaleBehavior.ACCUMULATE:
            assert before < after <= 0.5 + TARGET_DEAD_ZONE
        else:
            assert before > after >= 0.5 - TARGET_DEAD_ZONE


def test_transitioning_at_the_dead_zone_does_not_start_churn():
    whale = _funded("accumulate", cash=50_000.0, coins=25_000.0, target_coin_fraction=0.5,
                    cooldown_ticks=3, min_trade_interval_ticks=3)
    assert whale.allocation(PRICE).at_target
    reserve = _reserve()
    for step in ("distribute", "accumulate", "distribute", "neutral", "accumulate"):
        whale.set_behavior(step)
        if step == "neutral":
            continue  # neutral ignores the target and would trade
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert whale.state().cooldown_remaining == 0 and whale.interval_remaining == 0


# --- 11. funded / unfunded boundary ----------------------------------------------------------------------


@pytest.mark.parametrize("behavior", ["accumulate", "distribute"])
def test_an_unfunded_whale_cannot_be_given_a_directional_behavior(behavior):
    whale = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    with pytest.raises(ValueError, match="unfunded whale cannot become"):
        whale.set_behavior(behavior)
    assert whale.behavior is WhaleBehavior.NEUTRAL and whale.wallet is None and not whale.funded


def test_setting_an_unfunded_whale_to_neutral_is_allowed_and_changes_nothing():
    whale = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    twin = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    assert whale.set_behavior("neutral") is WhaleBehavior.NEUTRAL
    assert not whale.funded and whale.wallet is None
    assert [whale.maybe_trade(SUPPLY) for _ in range(150)] == [twin.maybe_trade(SUPPLY) for _ in range(150)]


def test_a_rejected_transition_leaves_an_unfunded_whale_untouched():
    whale = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    twin = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    with pytest.raises(ValueError):
        whale.set_behavior("accumulate")
    with pytest.raises(ValueError):
        whale.set_behavior("nonsense")
    assert [whale.maybe_trade(SUPPLY) for _ in range(100)] == [twin.maybe_trade(SUPPLY) for _ in range(100)]
    assert whale.holdings == twin.holdings


def test_a_transition_never_changes_whether_a_whale_is_funded():
    funded = _funded("accumulate")
    for step in ("neutral", "distribute", "neutral"):
        funded.set_behavior(step)
        assert funded.funded and funded.wallet is not None
    unfunded = Whale("w", 10.0)
    unfunded.set_behavior("neutral")
    assert not unfunded.funded and unfunded.wallet is None


# --- observability -----------------------------------------------------------------------------------------


def test_whale_state_reports_the_current_behavior_and_keeps_its_shape():
    whale = _funded("accumulate", cash=1_000.0, coins=0.0, target_coin_fraction=0.4, cooldown_ticks=2)
    assert whale.state() == WhaleState("w", WhaleBehavior.ACCUMULATE, True, 1_000.0, 0.0, 0.4, 0)
    whale.set_behavior("distribute")
    assert whale.state() == WhaleState("w", WhaleBehavior.DISTRIBUTE, True, 1_000.0, 0.0, 0.4, 0)
    # Still seven positional fields, as Step 2 and Step 3 callers expect.
    assert len(whale.state().__dataclass_fields__) == 7


# --- determinism and accounting ------------------------------------------------------------------------------


def test_the_same_transition_schedule_replays_identically():
    def run():
        whale = _funded("neutral", cash=600_000.0, coins=120_000.0, seed=21, activity_probability=0.5,
                        cooldown_ticks=2, min_trade_interval_ticks=3)
        reserve = _reserve(cash=2e6, coins=2e6)
        trades = []
        for tick in range(300):
            if tick % 25 == 0:
                whale.set_behavior(BEHAVIORS[(tick // 25) % 3])
            trades.append(whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve))
        return trades, whale.state(), whale.interval_remaining, (reserve.cash, reserve.coins), whale._rng.getstate()

    assert run() == run()


def test_different_transition_schedules_can_give_different_runs():
    def run(period):
        whale = _funded("neutral", cash=600_000.0, coins=120_000.0, seed=21, activity_probability=0.6)
        reserve = _reserve(cash=2e6, coins=2e6)
        out = []
        for tick in range(300):
            if tick % period == 0:
                whale.set_behavior(BEHAVIORS[(tick // period) % 3])
            trade = whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
            out.append(None if trade is None else (trade.side, trade.quantity))
        return out

    assert run(10) != run(50)


def test_transitions_never_break_conservation_or_produce_a_negative_balance():
    rng = random.Random(0)
    for case in range(200):
        target = rng.choice([None, rng.random()])
        start = "neutral" if target is None else rng.choice(["accumulate", "distribute"])
        whale = Whale(
            "w", rng.choice([0.0, rng.uniform(0, 2e5)]), starting_cash=rng.choice([0.0, rng.uniform(0, 5e5)]),
            behavior=start, target_coin_fraction=target, activity_probability=rng.random(),
            max_trade_fraction=rng.uniform(0.001, 0.2), cooldown_ticks=rng.randint(0, 3),
            min_trade_interval_ticks=rng.randint(0, 4), seed=case,
        )
        reserve = Wallet(cash=rng.uniform(0, 3e5), coins=rng.uniform(0, 3e5))
        coins = whale.wallet.coins + reserve.coins
        cash = whale.wallet.cash + reserve.cash
        for _ in range(60):
            if rng.random() < 0.2:
                whale.set_behavior(rng.choice(BEHAVIORS))
            whale.maybe_trade(SUPPLY, price=rng.uniform(0.5, 4.0), reserve=reserve)
            assert min(whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) >= 0.0
        assert whale.wallet.coins + reserve.coins == pytest.approx(coins, rel=1e-12, abs=1e-6)
        assert whale.wallet.cash + reserve.cash == pytest.approx(cash, rel=1e-12, abs=1e-6)


def test_several_transitioning_whales_share_a_reserve_safely():
    whales = [_funded("accumulate", cash=300_000.0, coins=20_000.0, seed=1, target_coin_fraction=0.7,
                      activity_probability=0.6),
              _funded("distribute", cash=50_000.0, coins=150_000.0, seed=2, target_coin_fraction=0.2,
                      activity_probability=0.6, min_trade_interval_ticks=3),
              _funded("neutral", cash=100_000.0, coins=100_000.0, seed=3, cooldown_ticks=2)]
    reserve = Wallet(cash=400_000.0, coins=400_000.0)
    coins = math.fsum([w.wallet.coins for w in whales] + [reserve.coins])
    cash = math.fsum([w.wallet.cash for w in whales] + [reserve.cash])
    rng = random.Random(9)
    for tick in range(400):
        price = rng.uniform(0.8, 3.0)
        for i, whale in enumerate(whales):
            if tick % (7 + i) == 0:
                whale.set_behavior(BEHAVIORS[(tick + i) % 3])
            whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
            assert whale.wallet.cash >= 0.0 and whale.wallet.coins >= 0.0
        assert reserve.cash >= 0.0 and reserve.coins >= 0.0
    assert math.fsum([w.wallet.coins for w in whales] + [reserve.coins]) == pytest.approx(coins, abs=1e-6)
    assert math.fsum([w.wallet.cash for w in whales] + [reserve.cash]) == pytest.approx(cash, abs=1e-6)


def test_a_run_without_transitions_is_unchanged_by_the_feature_existing():
    """No transition, no difference: the whale behaves exactly as a Step 3
    whale with the same seed does."""
    for behavior in BEHAVIORS:
        for kwargs in ({}, {"cooldown_ticks": 3}, {"min_trade_interval_ticks": 4}):
            a = _funded(behavior, cash=1e9, coins=1e6, seed=33, activity_probability=0.45, **kwargs)
            b = _funded(behavior, cash=1e9, coins=1e6, seed=33, activity_probability=0.45, **kwargs)
            ra, rb = _reserve(), _reserve()
            assert [a.maybe_trade(SUPPLY, price=PRICE, reserve=ra) for _ in range(300)] == [
                b.maybe_trade(SUPPLY, price=PRICE, reserve=rb) for _ in range(300)
            ]
            assert _snapshot(a) == _snapshot(b)
