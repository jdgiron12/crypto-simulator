import random

import pytest

from crypto_simulator.core.traders.base import TradeAction, TradeDecision
from crypto_simulator.core.traders.execution import execute_decision, execute_wash, net_flow_price_impact
from crypto_simulator.core.traders.strategies import RetailTrader
from crypto_simulator.models.wallet import Wallet


def _trader(cash=0.0, coins=0.0):
    return RetailTrader("t", starting_cash=cash, starting_coins=coins)


def _buy(quantity):
    return TradeDecision(TradeAction.BUY, quantity, "test")


def _sell(quantity):
    return TradeDecision(TradeAction.SELL, quantity, "test")


def test_buy_moves_cash_to_reserve_and_coins_to_trader():
    trader, reserve = _trader(cash=1_000.0), Wallet(cash=0.0, coins=10_000.0)
    trade = execute_decision(trader, _buy(100.0), 2.0, reserve)
    assert trade.side is TradeAction.BUY
    assert trade.quantity == 100.0
    assert trade.notional == 200.0
    assert (trader.wallet.cash, trader.wallet.coins, trader.wallet.average_cost) == (800.0, 100.0, 2.0)
    assert (reserve.cash, reserve.coins) == (200.0, 9_900.0)


def test_sell_moves_coins_to_reserve_and_cash_to_trader():
    trader, reserve = _trader(coins=500.0), Wallet(cash=10_000.0, coins=0.0)
    trade = execute_decision(trader, _sell(200.0), 3.0, reserve)
    assert trade.quantity == 200.0
    assert (trader.wallet.cash, trader.wallet.coins) == (600.0, 300.0)
    assert (reserve.cash, reserve.coins) == (9_400.0, 200.0)


def test_insufficient_cash_clamps_buy_to_affordable_and_never_goes_negative():
    trader, reserve = _trader(cash=1_000.0), Wallet(cash=0.0, coins=1_000_000.0)
    trade = execute_decision(trader, _buy(10_000.0), 3.0, reserve)
    assert trade.requested_quantity == 10_000.0
    assert trade.quantity == pytest.approx(1_000.0 / 3.0)
    assert trader.wallet.cash == 0.0
    assert trade.notional == 1_000.0
    assert reserve.cash == 1_000.0


def test_buy_with_no_cash_does_nothing():
    trader, reserve = _trader(cash=0.0), Wallet(cash=0.0, coins=1_000.0)
    assert execute_decision(trader, _buy(10.0), 1.0, reserve) is None
    assert (trader.wallet.cash, trader.wallet.coins, reserve.coins) == (0.0, 0.0, 1_000.0)


def test_insufficient_holdings_clamps_sell_to_holdings():
    trader, reserve = _trader(coins=50.0), Wallet(cash=10_000.0, coins=0.0)
    trader.wallet.average_cost = 1.0
    trade = execute_decision(trader, _sell(200.0), 1.0, reserve)
    assert trade.quantity == 50.0
    assert trader.wallet.coins == 0.0
    assert trader.wallet.average_cost == 0.0
    assert trader.wallet.cash == 50.0


def test_sell_with_no_coins_does_nothing():
    trader, reserve = _trader(coins=0.0), Wallet(cash=10_000.0, coins=0.0)
    assert execute_decision(trader, _sell(10.0), 1.0, reserve) is None
    assert (trader.wallet.cash, reserve.cash) == (0.0, 10_000.0)


def test_buy_clamped_by_reserve_coins():
    trader, reserve = _trader(cash=1_000.0), Wallet(cash=0.0, coins=30.0)
    trade = execute_decision(trader, _buy(100.0), 1.0, reserve)
    assert trade.quantity == 30.0
    assert reserve.coins == 0.0
    assert execute_decision(trader, _buy(100.0), 1.0, reserve) is None


def test_sell_clamped_by_reserve_cash():
    trader, reserve = _trader(coins=1_000.0), Wallet(cash=40.0, coins=0.0)
    trade = execute_decision(trader, _sell(100.0), 2.0, reserve)
    assert trade.quantity == 20.0
    assert reserve.cash == 0.0
    assert trader.wallet.cash == 40.0
    assert execute_decision(trader, _sell(100.0), 2.0, reserve) is None


def test_hold_does_nothing():
    trader, reserve = _trader(cash=100.0, coins=100.0), Wallet(cash=100.0, coins=100.0)
    assert execute_decision(trader, TradeDecision.hold(), 1.0, reserve) is None
    assert (trader.wallet.cash, trader.wallet.coins, reserve.cash, reserve.coins) == (100.0, 100.0, 100.0, 100.0)


def test_rejects_non_positive_price():
    with pytest.raises(ValueError):
        execute_decision(_trader(cash=1.0), _buy(1.0), 0.0, Wallet(coins=1.0))


def test_randomized_fills_conserve_totals_and_never_go_negative():
    rng = random.Random(123)
    traders = [_trader(cash=rng.uniform(0, 5_000), coins=rng.uniform(0, 5_000)) for _ in range(5)]
    reserve = Wallet(cash=20_000.0, coins=20_000.0)
    total_cash = reserve.cash + sum(t.wallet.cash for t in traders)
    total_coins = reserve.coins + sum(t.wallet.coins for t in traders)

    for _ in range(3_000):
        trader = rng.choice(traders)
        price = rng.uniform(0.01, 50.0)
        decision = (_buy if rng.random() < 0.5 else _sell)(rng.uniform(0, 10_000))
        execute_decision(trader, decision, price, reserve)
        for wallet in (reserve, *(t.wallet for t in traders)):
            assert wallet.cash >= 0.0
            assert wallet.coins >= 0.0

    assert reserve.cash + sum(t.wallet.cash for t in traders) == pytest.approx(total_cash, rel=1e-9)
    assert reserve.coins + sum(t.wallet.coins for t in traders) == pytest.approx(total_coins, rel=1e-9)


def test_net_flow_price_impact():
    assert net_flow_price_impact(0.0, 1_000_000.0, 2.0) == 1.0
    assert net_flow_price_impact(1_000.0, 1_000_000.0, 2.0) == pytest.approx(1.002)
    assert net_flow_price_impact(-1_000.0, 1_000_000.0, 2.0) == pytest.approx(1 / 1.002)
    buy = net_flow_price_impact(5_000.0, 1_000_000.0, 2.0)
    sell = net_flow_price_impact(-5_000.0, 1_000_000.0, 2.0)
    assert buy * sell == pytest.approx(1.0)
    assert net_flow_price_impact(5_000.0, 1_000_000.0, 0.0) == 1.0


# --- wash trades ------------------------------------------------------------------------


def _wash(quantity):
    return TradeDecision(TradeAction.WASH, quantity, "wash trade")


def test_wash_is_a_buy_leg_then_a_sell_leg_that_returns_the_same_coins():
    trader, reserve = _trader(cash=1_000.0), Wallet(cash=5_000.0, coins=5_000.0)
    legs = execute_wash(trader, _wash(100.0), 2.0, reserve)
    assert [leg.side for leg in legs] == [TradeAction.BUY, TradeAction.SELL]
    assert all(leg.wash for leg in legs)
    assert [leg.quantity for leg in legs] == [100.0, 100.0]
    assert [leg.notional for leg in legs] == [200.0, 200.0]
    assert [leg.reason for leg in legs] == ["wash trade: buy leg", "wash trade: sell leg"]
    assert (trader.wallet.cash, trader.wallet.coins) == (1_000.0, 0.0)
    assert (reserve.cash, reserve.coins) == (5_000.0, 5_000.0)


def test_wash_is_clamped_to_what_the_trader_can_fund():
    trader, reserve = _trader(cash=100.0), Wallet(cash=5_000.0, coins=5_000.0)
    legs = execute_wash(trader, _wash(1_000.0), 2.0, reserve)
    assert [leg.quantity for leg in legs] == [50.0, 50.0]
    assert legs[0].requested_quantity == 1_000.0
    assert trader.wallet.cash == 100.0


def test_wash_with_nothing_to_fill_returns_no_legs():
    assert execute_wash(_trader(cash=0.0), _wash(10.0), 1.0, Wallet(cash=10.0, coins=10.0)) == ()
    assert execute_wash(_trader(cash=10.0), _wash(10.0), 1.0, Wallet(cash=10.0, coins=0.0)) == ()


def test_randomized_washes_leave_positions_and_reserve_unchanged_to_float_precision():
    rng = random.Random(7)
    trader, reserve = _trader(cash=5_000.0, coins=300.0), Wallet(cash=20_000.0, coins=20_000.0)
    for _ in range(2_000):
        legs = execute_wash(trader, _wash(rng.uniform(0, 5_000)), rng.uniform(0.01, 50.0), reserve)
        assert sum(leg.quantity if leg.side is TradeAction.BUY else -leg.quantity for leg in legs) == 0.0
    assert trader.wallet.cash == pytest.approx(5_000.0, rel=1e-9)
    assert trader.wallet.coins == pytest.approx(300.0, rel=1e-9)
    assert (reserve.cash, reserve.coins) == (pytest.approx(20_000.0, rel=1e-9), pytest.approx(20_000.0, rel=1e-9))


def test_wash_and_plain_execution_reject_each_others_decisions():
    with pytest.raises(ValueError, match="execute_wash"):
        execute_decision(_trader(cash=10.0), _wash(1.0), 1.0, Wallet(coins=10.0))
    with pytest.raises(ValueError, match="expected a WASH decision"):
        execute_wash(_trader(cash=10.0), _buy(1.0), 1.0, Wallet(coins=10.0))
