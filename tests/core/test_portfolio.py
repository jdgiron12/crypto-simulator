from crypto_simulator.core.portfolio import PortfolioCalculator
from crypto_simulator.models.account import Account, Holding


def test_cash_value_returns_balance():
    account = Account(cash_balance=5000.0)
    assert PortfolioCalculator.cash_value(account) == 5000.0


def test_holdings_value_marks_to_market():
    account = Account(cash_balance=0.0)
    account.holdings["BTC"] = Holding(symbol="BTC", quantity=2, average_cost=50000.0)
    value = PortfolioCalculator.holdings_value(account, {"BTC": 60000.0})
    assert value == 120000.0


def test_total_equity_combines_cash_and_holdings():
    account = Account(cash_balance=1000.0)
    account.holdings["ETH"] = Holding(symbol="ETH", quantity=1, average_cost=3000.0)
    equity = PortfolioCalculator.total_equity(account, {"ETH": 3200.0})
    assert equity == 4200.0


def test_unrealized_pnl_per_symbol():
    account = Account(cash_balance=0.0)
    account.holdings["BTC"] = Holding(symbol="BTC", quantity=1, average_cost=50000.0)
    pnl = PortfolioCalculator.unrealized_pnl(account, {"BTC": 55000.0})
    assert pnl["BTC"] == 5000.0
