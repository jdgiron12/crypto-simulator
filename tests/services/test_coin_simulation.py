from dataclasses import replace

import pytest

from crypto_simulator.config import TraderSettings, get_settings
from crypto_simulator.core.traders.registry import TRADER_STRATEGIES
from crypto_simulator.services.coin_simulation import build_coin_simulator


def test_builds_whales_and_one_trader_per_strategy_from_default_config():
    settings = get_settings()
    sim = build_coin_simulator(settings)
    assert len(sim.whales) == len(settings.coin.whales)
    assert {t.strategy_name for t in sim.traders} == set(TRADER_STRATEGIES)
    assert [t.trader_id for t in sim.traders] == [t.id for t in settings.coin.traders]
    assert sim.reserve.cash == settings.coin.market_reserve_cash


def test_trader_characteristics_and_params_come_from_config():
    settings = get_settings()
    sim = build_coin_simulator(settings)
    for cfg, trader in zip(settings.coin.traders, sim.traders):
        assert trader.wallet.cash == cfg.starting_cash
        assert trader.wallet.coins == cfg.starting_coins
        assert trader.trade_probability == cfg.trade_probability
        assert trader.max_trade_size == cfg.max_trade_size
        assert trader.risk_tolerance == cfg.risk_tolerance
    momentum = next(t for t in sim.traders if t.strategy_name == "momentum")
    momentum_cfg = next(t for t in settings.coin.traders if t.strategy == "momentum")
    assert momentum.lookback == momentum_cfg.params["lookback"]


def test_include_traders_false_builds_whale_only_simulation():
    sim = build_coin_simulator(get_settings(), include_traders=False)
    assert sim.traders == []
    assert len(sim.whales) == 1


def test_built_simulation_is_deterministic():
    def view():
        return [(t.price, t.volume, t.whale_trades, t.trader_trades) for t in build_coin_simulator(get_settings()).run(100)]

    assert view() == view()


def test_default_config_builds_random_walk_mode():
    sim = build_coin_simulator(get_settings())
    assert sim.pricing_mode.value == "random_walk"
    assert sim.pool is None


def test_amm_mode_uses_configured_pool_and_fee():
    settings = get_settings()
    sim = build_coin_simulator(settings, pricing_mode="amm", include_whales=False)
    assert sim.pricing_mode.value == "amm"
    assert sim.whales == []
    assert sim.pool.coin_reserve == settings.coin.amm.pool_coin_reserve
    assert float(sim.pool.fee_rate) == settings.coin.amm.fee_rate
    assert float(sim.pool.spot_price()) == settings.coin.starting_price


def test_amm_mode_with_configured_whales_raises_instead_of_dropping_them():
    with pytest.raises(ValueError, match="Whales are not supported"):
        build_coin_simulator(get_settings(), pricing_mode="amm")


def test_amm_mode_from_settings_is_deterministic_and_conserves():
    def run():
        sim = build_coin_simulator(get_settings(), pricing_mode="amm", include_whales=False)
        before = sim.accounting_totals()
        ticks = sim.run(100)
        assert sim.accounting_totals() == before
        return [(t.price, t.volume, t.trader_trades, t.pool_state) for t in ticks]

    assert run() == run()


def test_unknown_strategy_in_config_raises():
    settings = get_settings()
    bad = replace(settings, coin=replace(settings.coin, traders=[TraderSettings(id="x", strategy="nope")]))
    with pytest.raises(ValueError, match="Unknown trader strategy"):
        build_coin_simulator(bad)
