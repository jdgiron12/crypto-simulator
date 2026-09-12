import pytest

from crypto_simulator.core.whale import Whale, WhaleTrade


def test_whale_never_trades_at_zero_activity_probability():
    whale = Whale("w1", holdings=10_000.0, activity_probability=0.0, seed=1)
    for _ in range(50):
        assert whale.maybe_trade(total_supply=1_000_000.0) is None


def test_whale_always_trades_at_full_activity_probability():
    whale = Whale("w1", holdings=10_000.0, activity_probability=1.0, seed=1)
    trades = [whale.maybe_trade(total_supply=1_000_000.0) for _ in range(20)]
    assert all(isinstance(t, WhaleTrade) for t in trades)


def test_sell_never_exceeds_holdings_at_time_of_sale():
    whale = Whale(
        "w1",
        holdings=100.0,
        activity_probability=1.0,
        max_trade_fraction=1.0,
        seed=3,
    )
    # Small starting holdings relative to supply forces early sells to hit
    # the cap; later sells may be larger since uncapped buys can grow
    # holdings well past the starting 100 — the cap tracks *current*
    # holdings, not the initial value.
    for _ in range(20):
        holdings_before = whale.holdings
        trade = whale.maybe_trade(total_supply=1_000_000.0)
        if trade and trade.side == "sell":
            assert trade.quantity <= holdings_before
    assert whale.holdings >= 0.0


def test_buy_increases_holdings_and_sell_decreases_them():
    whale = Whale("w1", holdings=1_000.0, activity_probability=1.0, seed=1)
    starting_holdings = whale.holdings
    trade = whale.maybe_trade(total_supply=1_000_000.0)
    assert trade is not None
    if trade.side == "buy":
        assert whale.holdings == starting_holdings + trade.quantity
    else:
        assert whale.holdings == starting_holdings - trade.quantity


def test_buy_price_impact_is_greater_than_one_sell_is_less_than_one():
    whale = Whale("w1", holdings=1_000.0, activity_probability=1.0, seed=1)
    for _ in range(30):
        trade = whale.maybe_trade(total_supply=1_000_000.0)
        if trade is None or trade.quantity == 0:
            continue
        if trade.side == "buy":
            assert trade.price_impact >= 1.0
        else:
            assert trade.price_impact <= 1.0


def test_reproducible_given_same_seed():
    a = Whale("w1", holdings=1_000.0, activity_probability=1.0, seed=42)
    b = Whale("w1", holdings=1_000.0, activity_probability=1.0, seed=42)
    trades_a = [a.maybe_trade(1_000_000.0) for _ in range(10)]
    trades_b = [b.maybe_trade(1_000_000.0) for _ in range(10)]
    assert trades_a == trades_b


def test_rejects_invalid_construction_args():
    with pytest.raises(ValueError):
        Whale("", holdings=100.0)
    with pytest.raises(ValueError):
        Whale("w1", holdings=-1.0)
    with pytest.raises(ValueError):
        Whale("w1", holdings=100.0, activity_probability=1.5)
    with pytest.raises(ValueError):
        Whale("w1", holdings=100.0, max_trade_fraction=0.0)
