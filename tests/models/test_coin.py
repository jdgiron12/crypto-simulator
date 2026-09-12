import pytest

from crypto_simulator.models.coin import Coin


def _make_coin(**overrides):
    defaults = dict(symbol="FIC", name="FictiCoin (Simulated)", initial_supply=1_000_000.0, starting_price=1.0)
    defaults.update(overrides)
    return Coin(**defaults)


def test_coin_holds_configured_values():
    coin = _make_coin()
    assert coin.symbol == "FIC"
    assert coin.initial_supply == 1_000_000.0
    assert coin.starting_price == 1.0


def test_coin_rejects_empty_symbol():
    with pytest.raises(ValueError):
        _make_coin(symbol="")


def test_coin_rejects_non_positive_supply():
    with pytest.raises(ValueError):
        _make_coin(initial_supply=0)
    with pytest.raises(ValueError):
        _make_coin(initial_supply=-100)


def test_coin_rejects_non_positive_starting_price():
    with pytest.raises(ValueError):
        _make_coin(starting_price=0)
    with pytest.raises(ValueError):
        _make_coin(starting_price=-1.0)
