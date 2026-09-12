import pytest

from crypto_simulator.core.traders.base import TraderAgent
from crypto_simulator.core.traders.registry import TRADER_STRATEGIES, create_trader


def test_registry_has_all_initial_strategies():
    assert set(TRADER_STRATEGIES) == {"retail", "momentum", "dip_buyer", "panic_seller", "long_term_holder"}


@pytest.mark.parametrize("strategy", sorted(TRADER_STRATEGIES))
def test_create_trader_builds_each_strategy(strategy):
    trader = create_trader(strategy, f"{strategy}-1", starting_cash=100.0, starting_coins=50.0, seed=1)
    assert isinstance(trader, TraderAgent)
    assert trader.strategy_name == strategy
    assert (trader.wallet.cash, trader.wallet.coins) == (100.0, 50.0)


def test_create_trader_passes_strategy_params():
    trader = create_trader("momentum", "m", params={"lookback": 7, "entry_threshold": 0.05})
    assert trader.lookback == 7
    assert trader.entry_threshold == 0.05


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="Unknown trader strategy"):
        create_trader("martingale", "x")


def test_unknown_param_raises_value_error():
    with pytest.raises(ValueError, match="Invalid parameters"):
        create_trader("retail", "r", params={"not_a_param": 1})
