import pytest

from crypto_simulator.models.account import Account, Holding
from crypto_simulator.models.asset import Asset
from crypto_simulator.models.order import Order, OrderSide, OrderType
from crypto_simulator.models.trade import Trade


def test_asset_requires_symbol():
    with pytest.raises(ValueError):
        Asset(symbol="", name="Nothing")


def test_order_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        Order(
            account_id="acc-1",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0,
        )


def test_limit_order_requires_limit_price():
    with pytest.raises(ValueError):
        Order(
            account_id="acc-1",
            symbol="BTC",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1,
        )


def test_trade_notional_calculation():
    trade = Trade(
        order_id="order-1",
        account_id="acc-1",
        symbol="BTC",
        side=OrderSide.BUY,
        quantity=2,
        price=100.0,
    )
    assert trade.notional == 200.0


def test_account_defaults_to_empty_holdings():
    account = Account(cash_balance=1000.0)
    assert account.holdings == {}
    account.holdings["ETH"] = Holding(symbol="ETH", quantity=1, average_cost=3000)
    assert account.holdings["ETH"].quantity == 1
