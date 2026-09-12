from pathlib import Path

import pytest

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


# --- coin.events -------------------------------------------------------------------------


_NO_SECTION = object()


def _raw_with_events(events):
    raw = load_config()
    raw["coin"] = dict(raw["coin"])
    if events is _NO_SECTION:
        raw["coin"].pop("events", None)
    else:
        raw["coin"]["events"] = events
    return raw


def test_default_event_settings_mean_no_events():
    from crypto_simulator.config import EventSettings, RandomEventSettings

    events = get_settings().coin.events
    assert events == EventSettings()
    assert (events.drift_per_sentiment, events.scheduled) == (0.0, [])
    assert events.random == RandomEventSettings(
        probability=0.0, categories={}, severity=(0.3, 1.0), duration=(2, 8), decay_ticks=(5, 20),
    )


def test_missing_or_empty_events_sections_fall_back_to_defaults():
    from crypto_simulator.config import EventSettings

    for events in (_NO_SECTION, None, {}, {"scheduled": None, "random": None}, {"random": {"categories": None}}):
        assert build_settings(_raw_with_events(events), Path("dummy.yaml")).coin.events == EventSettings()


def test_scheduled_events_parse_with_optional_overrides():
    from crypto_simulator.config import ScheduledEventSettings

    events = build_settings(_raw_with_events({
        "drift_per_sentiment": 0.005,
        "scheduled": [
            {"id": "listing-1", "category": "exchange_listing", "severity": 0.8, "start_tick": 20, "duration": 5,
             "decay_ticks": 10},
            {"id": "custom-1", "category": "market_uncertainty", "severity": 0.5, "start_tick": 3, "duration": 2,
             "headline": "Fictional rumor", "sentiment": -0.2, "volatility_boost": 1.5, "attention": 0.0},
        ],
    }), Path("dummy.yaml")).coin.events
    assert events.drift_per_sentiment == 0.005
    assert events.scheduled == [
        ScheduledEventSettings(id="listing-1", category="exchange_listing", severity=0.8, start_tick=20,
                               duration=5, decay_ticks=10),
        ScheduledEventSettings(id="custom-1", category="market_uncertainty", severity=0.5, start_tick=3,
                               duration=2, headline="Fictional rumor", sentiment=-0.2, volatility_boost=1.5,
                               attention=0.0),
    ]
    assert (events.scheduled[0].headline, events.scheduled[0].sentiment) == ("", None)


def test_random_event_ranges_parse_as_tuples():
    random_cfg = build_settings(_raw_with_events({
        "random": {"probability": 0.0, "categories": {"security_incident": 2.0}, "severity": [0.5, 0.9],
                   "duration": [1, 3], "decay_ticks": [0, 4]},
    }), Path("dummy.yaml")).coin.events.random
    assert random_cfg.categories == {"security_incident": 2.0}
    assert (random_cfg.severity, random_cfg.duration, random_cfg.decay_ticks) == ((0.5, 0.9), (1, 3), (0, 4))


def test_unknown_or_missing_event_fields_fail_like_other_config_sections():
    bad_field = {"scheduled": [{"id": "x", "category": "product_launch", "severity": 0.5, "start_tick": 1,
                                "duration": 1, "strength": 9}]}
    with pytest.raises(TypeError, match="strength"):
        build_settings(_raw_with_events(bad_field), Path("dummy.yaml"))
    with pytest.raises(TypeError, match="severity"):
        build_settings(_raw_with_events({"scheduled": [{"id": "x", "category": "product_launch", "start_tick": 1,
                                                        "duration": 1}]}), Path("dummy.yaml"))
    with pytest.raises(TypeError, match="enabled"):
        build_settings(_raw_with_events({"enabled": True}), Path("dummy.yaml"))
    with pytest.raises(TypeError, match="rate"):
        build_settings(_raw_with_events({"random": {"rate": 0.1}}), Path("dummy.yaml"))
