from pathlib import Path

from crypto_simulator.config.settings import build_settings, get_settings, load_config


def test_load_config_returns_expected_sections():
    raw = load_config()
    assert {"simulation", "market", "coin", "database", "ui", "logging"} <= raw.keys()


def test_get_settings_returns_typed_settings():
    settings = get_settings()
    assert settings.simulation.starting_balance > 0
    assert "BTC" in settings.market.assets
    assert settings.coin.symbol
    assert settings.coin.initial_supply > 0
    assert settings.coin.starting_price > 0
    assert isinstance(settings.coin.whales, list)
    assert settings.database.path


def test_coin_traders_are_parsed_as_typed_settings():
    from crypto_simulator.config import TraderSettings
    from crypto_simulator.core.traders.registry import TRADER_STRATEGIES

    settings = get_settings()
    assert settings.coin.traders
    for trader in settings.coin.traders:
        assert isinstance(trader, TraderSettings)
        assert trader.strategy in TRADER_STRATEGIES
        assert isinstance(trader.params, dict)
    assert settings.coin.market_reserve_cash > 0
    assert settings.coin.trader_impact_coefficient >= 0


def test_coin_section_without_traders_defaults_to_none():
    raw = load_config()
    raw["coin"] = {k: v for k, v in raw["coin"].items() if k not in {"traders", "market_reserve_cash", "trader_impact_coefficient"}}
    settings = build_settings(raw, Path("dummy.yaml"))
    assert settings.coin.traders == []
    assert settings.coin.market_reserve_cash is None


def test_pricing_mode_and_amm_settings_are_parsed():
    from crypto_simulator.config import AMMSettings

    settings = get_settings()
    assert settings.coin.pricing_mode == "random_walk"
    assert isinstance(settings.coin.amm, AMMSettings)
    assert settings.coin.amm.pool_coin_reserve > 0
    assert 0 <= settings.coin.amm.fee_rate < 1


def test_coin_section_without_amm_defaults_to_random_walk():
    raw = load_config()
    raw["coin"] = {k: v for k, v in raw["coin"].items() if k not in {"pricing_mode", "amm"}}
    settings = build_settings(raw, Path("dummy.yaml"))
    assert settings.coin.pricing_mode == "random_walk"
    assert settings.coin.amm.pool_coin_reserve is None
    assert settings.coin.amm.fee_rate == 0.003


def test_pricing_mode_env_override(monkeypatch):
    monkeypatch.setenv("CRYPTOSIM_PRICING_MODE", "amm")
    settings = build_settings(load_config(), Path("dummy.yaml"))
    assert settings.coin.pricing_mode == "amm"


def test_coin_whales_are_parsed_as_typed_settings():
    settings = get_settings()
    assert len(settings.coin.whales) >= 1
    whale = settings.coin.whales[0]
    assert whale.id
    assert whale.holdings > 0
    assert 0.0 <= whale.activity_probability <= 1.0


def test_build_settings_from_raw_dict():
    raw = load_config()
    settings = build_settings(raw, Path("dummy.yaml"))
    assert settings.ui.page_title
    assert isinstance(settings.market.initial_prices, dict)


def test_manipulators_default_to_empty_and_parse_as_trader_settings():
    from crypto_simulator.config import TraderSettings

    assert get_settings().coin.manipulators == []
    raw = load_config()
    raw["coin"] = {k: v for k, v in raw["coin"].items() if k != "manipulators"}
    assert build_settings(raw, Path("dummy.yaml")).coin.manipulators == []
    raw["coin"]["manipulators"] = [
        {"id": "pd", "strategy": "pump_and_dump", "starting_cash": 10.0, "params": {"pump_ticks": 2}}
    ]
    (manipulator,) = build_settings(raw, Path("dummy.yaml")).coin.manipulators
    assert manipulator == TraderSettings(id="pd", strategy="pump_and_dump", starting_cash=10.0, params={"pump_ticks": 2})
