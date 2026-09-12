import pytest

from crypto_simulator.models.wallet import InsufficientBalanceError, Wallet


def test_wallet_rejects_negative_starting_balances():
    with pytest.raises(ValueError):
        Wallet(cash=-1.0)
    with pytest.raises(ValueError):
        Wallet(coins=-1.0)


def test_withdraw_cash_beyond_balance_raises_and_leaves_balance_unchanged():
    wallet = Wallet(cash=100.0)
    with pytest.raises(InsufficientBalanceError):
        wallet.withdraw_cash(100.01)
    assert wallet.cash == 100.0


def test_withdraw_coins_beyond_holdings_raises_and_leaves_holdings_unchanged():
    wallet = Wallet(coins=10.0)
    with pytest.raises(InsufficientBalanceError):
        wallet.withdraw_coins(10.5)
    assert wallet.coins == 10.0


def test_negative_amounts_are_rejected():
    wallet = Wallet(cash=10.0, coins=10.0)
    for method in (wallet.withdraw_cash, wallet.deposit_cash, wallet.withdraw_coins, wallet.deposit_coins):
        with pytest.raises(ValueError):
            method(-1.0)


def test_deposit_coins_with_cost_blends_average_cost():
    wallet = Wallet()
    wallet.deposit_coins(100.0, cost=100.0)
    wallet.deposit_coins(100.0, cost=300.0)
    assert wallet.coins == 200.0
    assert wallet.average_cost == pytest.approx(2.0)


def test_withdrawing_all_coins_resets_average_cost():
    wallet = Wallet(coins=50.0, average_cost=3.0)
    wallet.withdraw_coins(20.0)
    assert wallet.average_cost == 3.0
    wallet.withdraw_coins(30.0)
    assert wallet.coins == 0.0
    assert wallet.average_cost == 0.0


def test_equity_marks_coins_to_price():
    assert Wallet(cash=100.0, coins=10.0).equity(2.5) == 125.0
