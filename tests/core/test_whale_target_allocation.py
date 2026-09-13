"""Whale target allocation behavior (Phase 8, Step 2).

A funded accumulate/distribute whale with a ``target_coin_fraction``
manages toward that share of its portfolio value: it trades only in its
configured direction, only while the target lies that way, in bounded
steps that never cross it, and it stops once the remaining allocation gap
is inside ``TARGET_DEAD_ZONE``. None of it draws randomness, and a whale
with no target is untouched by any of it.
"""

import math
import random

import pytest

from crypto_simulator.core.whale import (
    TARGET_DEAD_ZONE,
    Whale,
    WhaleAllocation,
    WhaleBehavior,
)
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0


def _whale(behavior, cash, coins=0.0, target=None, seed=1, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.02)
    kwargs.setdefault("min_trade_fraction", 0.0)
    return Whale("w", coins, starting_cash=cash, behavior=behavior, target_coin_fraction=target,
                 seed=seed, **kwargs)


def _reserve(cash=1e9, coins=1e9):
    return Wallet(cash=cash, coins=coins)


def _run(whale, ticks, price=PRICE, reserve=None):
    reserve = _reserve() if reserve is None else reserve
    return [whale.maybe_trade(SUPPLY, price=price, reserve=reserve) for _ in range(ticks)], reserve


def _fraction(whale, price=PRICE):
    return whale.allocation(price).coin_fraction


class _RecordingRNG:
    """Wraps a ``random.Random`` and records the top-level draws made on
    it, so a test can see exactly how many the whale takes and in what
    order."""

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


# --- observation surface -------------------------------------------------------------------------


def test_allocation_reports_value_composition_and_the_gap():
    whale = _whale("accumulate", cash=10_000.0, coins=10_000.0, target=0.75)
    allocation = whale.allocation(PRICE)
    assert isinstance(allocation, WhaleAllocation)
    assert (allocation.price, allocation.portfolio_value, allocation.coin_value) == (2.0, 30_000.0, 20_000.0)
    assert allocation.coin_fraction == pytest.approx(2 / 3)
    assert allocation.target_coin_fraction == 0.75
    assert allocation.allocation_gap == pytest.approx(0.75 - 2 / 3)  # underweight coins
    assert allocation.target_coins == pytest.approx(0.75 * 30_000.0 / 2.0)
    assert not allocation.at_target


def test_allocation_follows_the_price_it_is_marked_at():
    whale = _whale("distribute", cash=10_000.0, coins=10_000.0, target=0.5)
    assert _fraction(whale, price=1.0) == 0.5  # 10k cash, 10k of coins
    assert whale.allocation(1.0).at_target
    assert _fraction(whale, price=3.0) == 0.75  # the same coins are worth more
    assert whale.allocation(3.0).allocation_gap == pytest.approx(-0.25)


def test_allocation_without_a_target_reports_composition_only():
    allocation = _whale("accumulate", cash=100.0, coins=100.0).allocation(PRICE)
    assert allocation.coin_fraction == pytest.approx(200.0 / 300.0)
    assert (allocation.target_coin_fraction, allocation.allocation_gap, allocation.target_coins) == (None, None, None)
    assert allocation.at_target  # nothing to be away from


def test_an_unfunded_whale_has_no_allocation():
    assert Whale("w", 1_000.0).allocation(PRICE) is None


def test_an_empty_portfolio_has_no_composition():
    allocation = _whale("accumulate", cash=0.0, coins=0.0, target=0.5).allocation(PRICE)
    assert (allocation.portfolio_value, allocation.coin_value, allocation.coin_fraction) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, "2", None, True])
def test_allocation_rejects_an_unusable_price(bad):
    with pytest.raises(ValueError, match="price"):
        _whale("accumulate", cash=100.0, target=0.5).allocation(bad)


# --- 1-7. direction against the target -------------------------------------------------------------


def test_an_underweight_accumulator_buys_toward_its_target():
    whale = _whale("accumulate", cash=100_000.0, target=0.5, min_trade_fraction=0.01, max_trade_fraction=0.01)
    assert whale.allocation(PRICE).allocation_gap == 0.5
    (trade,), _ = _run(whale, 1)
    assert trade.side == "buy" and trade.quantity == 0.01 * SUPPLY
    assert (whale.wallet.cash, whale.wallet.coins) == (80_000.0, 10_000.0)
    assert _fraction(whale) == 0.2  # closer to 0.5, not there yet
    assert not whale.allocation(PRICE).at_target


def test_an_overweight_accumulator_holds_instead_of_selling_back():
    whale = _whale("accumulate", cash=10_000.0, coins=40_000.0, target=0.5)
    assert whale.allocation(PRICE).allocation_gap < 0
    trades, reserve = _run(whale, 20)
    assert trades == [None] * 20
    assert (whale.wallet.cash, whale.wallet.coins) == (10_000.0, 40_000.0)
    assert (reserve.cash, reserve.coins) == (1e9, 1e9)


def test_an_accumulator_at_its_target_holds():
    whale = _whale("accumulate", cash=50_000.0, coins=25_000.0, target=0.5)
    assert whale.allocation(PRICE).allocation_gap == 0.0
    assert _run(whale, 20)[0] == [None] * 20


def test_an_underweight_distributor_holds_instead_of_buying_up():
    whale = _whale("distribute", cash=80_000.0, coins=10_000.0, target=0.5)
    assert whale.allocation(PRICE).allocation_gap > 0  # the target is the buying way
    trades, reserve = _run(whale, 20)
    assert trades == [None] * 20
    assert (whale.wallet.cash, whale.wallet.coins) == (80_000.0, 10_000.0)
    assert (reserve.cash, reserve.coins) == (1e9, 1e9)


def test_an_overweight_distributor_sells_toward_its_target():
    whale = _whale("distribute", cash=0.0, coins=50_000.0, target=0.4,
                   min_trade_fraction=0.01, max_trade_fraction=0.01)
    assert whale.allocation(PRICE).allocation_gap == pytest.approx(-0.6)
    (trade,), _ = _run(whale, 1)
    assert trade.side == "sell" and trade.quantity == 0.01 * SUPPLY
    assert (whale.wallet.cash, whale.wallet.coins) == (20_000.0, 40_000.0)
    assert _fraction(whale) == 0.8  # closer to 0.4, not there yet


def test_a_distributor_at_its_target_holds():
    whale = _whale("distribute", cash=60_000.0, coins=20_000.0, target=0.4)
    assert whale.allocation(PRICE).allocation_gap == 0.0
    assert _run(whale, 20)[0] == [None] * 20


@pytest.mark.parametrize("behavior", ["accumulate", "distribute"])
def test_sitting_exactly_on_the_target_is_a_hold_in_either_behavior(behavior):
    whale = _whale(behavior, cash=50_000.0, coins=25_000.0, target=0.5)
    allocation = whale.allocation(PRICE)
    assert allocation.coin_fraction == 0.5 and allocation.allocation_gap == 0.0 and allocation.at_target
    assert _run(whale, 30)[0] == [None] * 30


# --- 8-9. bounded, non-crossing approach -----------------------------------------------------------


def test_the_approach_is_bounded_and_takes_many_trades():
    whale = _whale("accumulate", cash=1_000_000.0, target=0.5, min_trade_fraction=0.01, max_trade_fraction=0.02)
    gap = whale.allocation(PRICE).allocation_gap
    trades, _ = _run(whale, 40)
    filled = [t for t in trades if t is not None]
    # Target coins are 0.5 x 1e6 / 2 = 250_000; no single 10k-20k trade
    # gets there, and each one strictly shrinks the gap.
    assert len(filled) > 10
    assert all(0.01 * SUPPLY <= t.quantity <= 0.02 * SUPPLY for t in filled[:-1])
    assert all(t.side == "buy" for t in filled)
    assert whale.allocation(PRICE).at_target and gap == 0.5


def test_the_last_trade_is_sized_down_to_land_on_the_target_not_past_it():
    # Target coins 250_000, reached in twelve 20_000-coin steps plus a
    # 10_000-coin remainder that is smaller than the configured minimum.
    whale = _whale("accumulate", cash=1_000_000.0, target=0.5, min_trade_fraction=0.02, max_trade_fraction=0.02)
    trades, _ = _run(whale, 20)
    filled = [t for t in trades if t is not None]
    assert [t.quantity for t in filled] == [20_000.0] * 12 + [10_000.0]
    assert _fraction(whale) == 0.5
    assert trades[13:] == [None] * 7


@pytest.mark.parametrize("behavior, target", [("accumulate", 0.7), ("distribute", 0.3)])
def test_no_trade_ever_crosses_the_target_as_the_price_moves(behavior, target):
    """The price moving between ticks can leave the whale on the far side
    of its target; what it must never do is *trade* past it. (It holds
    there instead: a target never reverses a behavior.)"""
    rng = random.Random(4)
    whale = _whale(behavior, cash=500_000.0, coins=200_000.0, target=target, seed=8,
                   max_trade_fraction=0.05, activity_probability=0.7)
    reserve = _reserve()
    traded = 0
    for _ in range(400):
        price = rng.uniform(0.5, 5.0)
        before = whale.allocation(price).coin_fraction
        trade = whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
        after = whale.allocation(price).coin_fraction
        if trade is None:
            assert after == before
            continue
        traded += 1
        if behavior == "accumulate":
            assert before < target and before < after <= target + TARGET_DEAD_ZONE
        else:
            assert before > target and before > after >= target - TARGET_DEAD_ZONE
    assert traded > 5  # the gap reopens whenever the price moves the whale off target


def test_a_price_move_reopens_a_closed_gap_in_the_configured_direction_only():
    whale = _whale("accumulate", cash=1_000_000.0, target=0.5, max_trade_fraction=1.0)
    _run(whale, 5)
    assert _fraction(whale) == 0.5
    # Price halves: the coins are worth less, so the whale is underweight
    # and buys again. Price doubles instead and it is overweight — and an
    # accumulator holds rather than selling back.
    reopened = _whale("accumulate", cash=500_000.0, coins=250_000.0, target=0.5, max_trade_fraction=1.0)
    assert reopened.maybe_trade(SUPPLY, price=1.0, reserve=_reserve()).side == "buy"
    assert _fraction(reopened, price=1.0) == pytest.approx(0.5)
    overweight = _whale("accumulate", cash=500_000.0, coins=250_000.0, target=0.5, max_trade_fraction=1.0)
    assert overweight.maybe_trade(SUPPLY, price=4.0, reserve=_reserve()) is None


# --- 10. dead zone ----------------------------------------------------------------------------------


def _portfolio_at(fraction, portfolio_value=100_000.0, price=PRICE):
    """Cash and coins worth ``portfolio_value`` with ``fraction`` in coins."""
    coin_value = fraction * portfolio_value
    return portfolio_value - coin_value, coin_value / price


def test_a_gap_inside_the_dead_zone_is_a_hold():
    cash, coins = _portfolio_at(0.5 - TARGET_DEAD_ZONE / 2)
    whale = _whale("accumulate", cash=cash, coins=coins, target=0.5)
    gap = whale.allocation(PRICE).allocation_gap
    assert 0 < gap <= TARGET_DEAD_ZONE and whale.allocation(PRICE).at_target
    trades, reserve = _run(whale, 20)
    assert trades == [None] * 20
    assert (whale.wallet.cash, whale.wallet.coins) == (cash, coins)
    assert (reserve.cash, reserve.coins) == (1e9, 1e9)


def test_a_gap_just_outside_the_dead_zone_still_trades():
    cash, coins = _portfolio_at(0.5 - TARGET_DEAD_ZONE * 5)
    whale = _whale("accumulate", cash=cash, coins=coins, target=0.5)
    assert not whale.allocation(PRICE).at_target
    (trade,), _ = _run(whale, 1)
    assert trade is not None and trade.quantity > 0
    assert whale.allocation(PRICE).at_target  # one bounded step closed it


@pytest.mark.parametrize("behavior, target", [("accumulate", 0.5), ("distribute", 0.5)])
def test_the_dead_zone_ends_the_approach_instead_of_trading_dust_forever(behavior, target):
    cash = 400_000.0 if behavior == "accumulate" else 100_000.0
    whale = _whale(behavior, cash=cash, coins=150_000.0, target=target, max_trade_fraction=0.05)
    trades, _ = _run(whale, 2_000)
    filled = [i for i, t in enumerate(trades) if t is not None]
    assert filled and max(filled) < 20  # it settles quickly and then stops for good
    assert all(t.quantity > 0 for t in trades if t is not None)
    assert whale.allocation(PRICE).at_target


def test_the_dead_zone_is_a_gap_threshold_not_a_minimum_trade_size():
    """A whale whose smallest configured trade dwarfs its whole gap still
    closes that gap — sized down — rather than sitting out forever."""
    whale = _whale("accumulate", cash=1_000_000.0, target=0.3, min_trade_fraction=1.0, max_trade_fraction=1.0)
    (trade,), _ = _run(whale, 1)
    assert trade.quantity == 150_000.0 < 1.0 * SUPPLY  # below the configured minimum, by design
    assert _fraction(whale) == pytest.approx(0.3)


# --- 11. cooldown -----------------------------------------------------------------------------------


def test_a_target_whale_on_cooldown_makes_no_trade_and_no_draw():
    whale = _whale("accumulate", cash=1_000_000.0, target=0.5, cooldown_ticks=3)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    for remaining in (3, 2, 1):
        assert whale.state().cooldown_remaining == remaining
        before = (whale._rng.getstate(), whale.wallet.cash, whale.wallet.coins)
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert (whale._rng.getstate(), whale.wallet.cash, whale.wallet.coins) == before
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


def test_holding_at_the_target_starts_no_cooldown():
    whale = _whale("accumulate", cash=100_000.0, target=0.5, cooldown_ticks=5, max_trade_fraction=1.0)
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) is not None
    assert whale.state().cooldown_remaining == 5
    _run(whale, 5)  # sit out the cooldown; now at target
    assert whale.state().cooldown_remaining == 0 and whale.allocation(PRICE).at_target
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) is None
    assert whale.state().cooldown_remaining == 0  # a hold is not a trade


def test_cooldown_only_slows_the_approach_it_does_not_change_where_it_lands():
    def final(cooldown):
        whale = _whale("accumulate", cash=1_000_000.0, target=0.4, cooldown_ticks=cooldown, seed=12)
        _run(whale, 400)
        return whale.wallet.cash, whale.wallet.coins

    assert final(0) == final(4)


# --- 12-14. balances and the reserve -----------------------------------------------------------------


def test_the_target_cap_keeps_a_buy_affordable_even_at_a_full_allocation():
    """``room x price`` is ``target x portfolio - coin_value``, never more
    than the cash on hand, so a targeted accumulator cannot overdraw."""
    whale = _whale("accumulate", cash=100_000.0, target=1.0, max_trade_fraction=1.0)
    (trade,), _ = _run(whale, 1)
    assert trade.quantity == 50_000.0
    assert whale.wallet.cash == 0.0 and whale.wallet.coins == 50_000.0
    assert _fraction(whale) == 1.0 and whale.allocation(PRICE).at_target
    assert _run(whale, 5)[0] == [None] * 5


def test_insufficient_cash_clamps_the_fill_and_leaves_the_whale_short_of_target():
    whale = _whale("accumulate", cash=1_000.0, coins=100_000.0, target=1.0, max_trade_fraction=1.0)
    (trade,), _ = _run(whale, 1)
    assert trade.quantity == 500.0  # everything the cash covers
    assert whale.wallet.cash == 0.0
    assert _fraction(whale) == 1.0


def test_a_distributor_can_sell_down_to_nothing_when_the_target_is_zero():
    whale = _whale("distribute", cash=0.0, coins=40_000.0, target=0.0, max_trade_fraction=1.0)
    (trade,), _ = _run(whale, 1)
    assert trade.quantity == 40_000.0
    assert whale.wallet.coins == 0.0 and whale.wallet.cash == 80_000.0
    assert _fraction(whale) == 0.0 and whale.allocation(PRICE).at_target
    assert _run(whale, 5)[0] == [None] * 5


def test_insufficient_coins_means_no_sell_however_far_from_target():
    whale = _whale("distribute", cash=500.0, coins=0.0, target=0.5)
    assert whale.allocation(PRICE).allocation_gap == 0.5  # underweight; a distributor holds anyway
    assert _run(whale, 10)[0] == [None] * 10


def test_the_reserve_limits_a_targeted_trade_and_the_whale_tries_again():
    whale = _whale("accumulate", cash=1_000_000.0, target=0.5,
                   min_trade_fraction=1.0, max_trade_fraction=1.0)
    thin = _reserve(coins=1_000.0)
    trade = whale.maybe_trade(SUPPLY, price=PRICE, reserve=thin)
    assert trade.quantity == 1_000.0 < 250_000.0  # the reserve, not the target, bound this fill
    assert thin.coins == 0.0 and not whale.allocation(PRICE).at_target
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=thin) is None  # reserve exhausted
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == pytest.approx(249_000.0)
    assert _fraction(whale) == pytest.approx(0.5)


def test_an_empty_reserve_leaves_the_whale_and_its_target_untouched():
    whale = _whale("accumulate", cash=1_000_000.0, target=0.5)
    empty = _reserve(coins=0.0)
    before = whale.allocation(PRICE)
    assert _run(whale, 10, reserve=empty)[0] == [None] * 10
    assert whale.allocation(PRICE) == before
    assert whale.state().cooldown_remaining == 0


# --- 15-18. determinism -------------------------------------------------------------------------------


def test_target_sizing_is_deterministic_arithmetic():
    """Same balances, same price, same target: the same quantity, every
    time and for every seed."""
    quantities = set()
    for seed in range(20):
        whale = _whale("accumulate", cash=300_000.0, coins=50_000.0, target=0.6, seed=seed,
                       min_trade_fraction=1.0, max_trade_fraction=1.0)
        (trade,), _ = _run(whale, 1)
        quantities.add(trade.quantity)
    # portfolio 400_000; target coins 0.6 x 400_000 / 2 = 120_000; held 50_000.
    assert quantities == {70_000.0}


def test_the_target_adds_no_draws_to_any_tick():
    def record(target, ticks, **kwargs):
        kwargs.setdefault("activity_probability", 0.5)
        whale = _whale("accumulate", cash=1_000_000.0, target=target, seed=3, **kwargs)
        whale._rng = _RecordingRNG(3)
        _run(whale, ticks)
        return whale._rng.calls

    # Identical call sequences whether or not a target is configured, both
    # while approaching and long after the approach has finished.
    assert record(None, 300) == record(0.5, 300) == record(0.05, 300)
    # One activity draw on a skipped tick; activity + side + size on an
    # active one; nothing at all while cooling down.
    cooling = record(0.5, 12, cooldown_ticks=2, activity_probability=1.0)
    assert cooling == ["random", "choice", "uniform"] * 4


def test_a_dead_zone_hold_still_draws_exactly_like_an_active_tick():
    whale = _whale("accumulate", cash=50_000.0, coins=25_000.0, target=0.5)
    whale._rng = _RecordingRNG(3)
    assert whale.allocation(PRICE).at_target
    assert _run(whale, 4)[0] == [None] * 4
    assert whale._rng.calls == ["random", "choice", "uniform"] * 4


@pytest.mark.parametrize("behavior, target", [("accumulate", 0.65), ("distribute", 0.25)])
def test_the_same_seed_replays_the_same_targeted_run(behavior, target):
    def run():
        whale = _whale(behavior, cash=250_000.0, coins=150_000.0, target=target, seed=17,
                       activity_probability=0.4, cooldown_ticks=2)
        trades, reserve = _run(whale, 200)
        return trades, whale.state(), whale.allocation(PRICE), (reserve.cash, reserve.coins), whale._rng.getstate()

    assert run() == run()


def test_different_seeds_give_different_targeted_runs():
    def run(seed):
        whale = _whale("accumulate", cash=1_000_000.0, target=0.9, seed=seed, activity_probability=0.4)
        return _run(whale, 200)[0]

    assert run(1) != run(2)


# --- 19. unfunded whales ------------------------------------------------------------------------------


def test_an_unfunded_whale_is_untouched_by_step_2():
    plain = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    twin = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    reserve = _reserve(cash=10.0, coins=10.0)
    assert [plain.maybe_trade(SUPPLY) for _ in range(100)] == [
        twin.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) for _ in range(100)
    ]
    assert (reserve.cash, reserve.coins) == (10.0, 10.0)
    assert twin.allocation(PRICE) is None


def test_a_target_still_needs_a_funded_directional_whale():
    for kwargs, message in (
        ({"target_coin_fraction": 0.5, "behavior": "accumulate"}, "needs starting_cash"),
        ({"target_coin_fraction": 0.5, "behavior": "distribute"}, "needs starting_cash"),
        ({"target_coin_fraction": 0.5}, "accumulate or distribute"),
        ({"target_coin_fraction": 0.5, "starting_cash": 1.0}, "accumulate or distribute"),
        ({"target_coin_fraction": 1.5, "starting_cash": 1.0, "behavior": "accumulate"}, "target_coin_fraction"),
        ({"target_coin_fraction": -0.1, "starting_cash": 1.0, "behavior": "accumulate"}, "target_coin_fraction"),
    ):
        with pytest.raises(ValueError, match=message):
            Whale("w", 100.0, **kwargs)


@pytest.mark.parametrize("target", [0.0, 1.0])
def test_the_extremes_of_the_target_range_are_valid(target):
    assert _whale("accumulate", cash=100.0, target=target).target_coin_fraction == target


# --- 20. accounting -----------------------------------------------------------------------------------


def test_targeted_whales_conserve_coins_and_cash_and_never_cross():
    rng = random.Random(0)
    for case in range(200):
        behavior = rng.choice([WhaleBehavior.ACCUMULATE, WhaleBehavior.DISTRIBUTE])
        target = rng.random()
        whale = Whale(
            "w", rng.choice([0.0, rng.uniform(0, 2e5)]), starting_cash=rng.choice([0.0, rng.uniform(0, 5e5)]),
            behavior=behavior, target_coin_fraction=target, activity_probability=rng.random(),
            max_trade_fraction=rng.uniform(0.001, 0.2), min_trade_fraction=rng.choice([0.0, 0.0005]),
            cooldown_ticks=rng.randint(0, 3), seed=case,
        )
        reserve = _reserve(cash=rng.uniform(0, 3e5), coins=rng.uniform(0, 3e5))
        coins = whale.wallet.coins + reserve.coins
        cash = whale.wallet.cash + reserve.cash
        for _ in range(60):
            price = rng.uniform(0.5, 4.0)
            before = whale.allocation(price).coin_fraction
            trade = whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
            assert min(whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) >= 0.0
            after = whale.allocation(price).coin_fraction
            if trade is not None and trade.quantity > 0:
                # It moved the right way, and stopped at the target unless
                # a balance or the reserve stopped it sooner.
                if behavior is WhaleBehavior.ACCUMULATE:
                    assert after > before and after <= max(target, before) + TARGET_DEAD_ZONE
                else:
                    assert after < before and after >= min(target, before) - TARGET_DEAD_ZONE
        assert whale.wallet.coins + reserve.coins == pytest.approx(coins, rel=1e-12, abs=1e-6)
        assert whale.wallet.cash + reserve.cash == pytest.approx(cash, rel=1e-12, abs=1e-6)


def test_no_new_coins_or_cash_appear_when_several_targeted_whales_share_a_reserve():
    whales = [
        _whale("accumulate", cash=300_000.0, target=0.8, seed=1, activity_probability=0.6),
        _whale("distribute", cash=0.0, coins=120_000.0, target=0.2, seed=2, activity_probability=0.6),
        _whale("accumulate", cash=50_000.0, coins=50_000.0, target=0.55, seed=3, cooldown_ticks=2),
    ]
    reserve = _reserve(cash=250_000.0, coins=250_000.0)
    coins = math.fsum([w.wallet.coins for w in whales] + [reserve.coins])
    cash = math.fsum([w.wallet.cash for w in whales] + [reserve.cash])
    rng = random.Random(9)
    for _ in range(300):
        price = rng.uniform(0.8, 3.0)
        for whale in whales:
            whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
            assert whale.wallet.cash >= 0.0 and whale.wallet.coins >= 0.0
        assert reserve.cash >= 0.0 and reserve.coins >= 0.0
    assert math.fsum([w.wallet.coins for w in whales] + [reserve.coins]) == pytest.approx(coins, abs=1e-6)
    assert math.fsum([w.wallet.cash for w in whales] + [reserve.cash]) == pytest.approx(cash, abs=1e-6)
