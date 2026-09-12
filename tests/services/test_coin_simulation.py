from dataclasses import replace

import pytest

from crypto_simulator.config import TraderSettings, get_settings
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES, TRADER_STRATEGIES
from crypto_simulator.services.coin_simulation import MANIPULATION_SCENARIOS, build_coin_simulator


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


# --- manipulation scenarios --------------------------------------------------------------


def _run_with_pnl(sim, ticks):
    start = sim.coin.starting_price
    equity = {t.trader_id: t.wallet.equity(start) for t in sim.traders}
    result = sim.run(ticks)
    return result, {t.trader_id: t.wallet.equity(result[-1].price) - equity[t.trader_id] for t in sim.traders}


def _rng_states(sim):
    return {t.trader_id: t._rng.getstate() for t in sim.traders}


def test_default_config_has_no_manipulators():
    sim = build_coin_simulator(get_settings())
    assert get_settings().coin.manipulators == []
    assert not any(t.strategy_name in MANIPULATION_STRATEGIES for t in sim.traders)


def test_pump_and_dump_scenario_adds_marks_then_the_manipulator_last():
    settings = get_settings()
    sim = build_coin_simulator(settings, scenario="pump_and_dump")
    preset = MANIPULATION_SCENARIOS["pump_and_dump"]
    assert [t.trader_id for t in sim.traders] == (
        [t.id for t in settings.coin.traders]
        + [t.id for t in preset.followers]
        + [m.id for m in preset.manipulators]
    )
    assert sim.traders[-1].strategy_name == "pump_and_dump"
    assert {t.strategy_name for t in sim.traders[len(settings.coin.traders):-1]} == {"momentum"}


def test_scenarios_never_reseed_organic_traders():
    settings = get_settings()
    plain = _rng_states(build_coin_simulator(settings))
    with_scenario = _rng_states(build_coin_simulator(settings, scenario="pump_and_dump"))
    assert {k: with_scenario[k] for k in plain} == plain
    without_traders = _rng_states(build_coin_simulator(settings, include_traders=False, scenario="pump_and_dump"))
    assert set(without_traders) == {"mark-1", "mark-2", "mark-3", "mark-4", "pump-and-dump-1"}
    assert without_traders == {k: with_scenario[k] for k in without_traders}


def test_manipulators_come_from_config_when_no_scenario_is_given():
    settings = get_settings()
    washer = TraderSettings(id="w", strategy="wash_trader", starting_cash=1_000.0)
    sim = build_coin_simulator(replace(settings, coin=replace(settings.coin, manipulators=[washer])))
    assert sim.traders[-1].trader_id == "w"
    assert sim.traders[-1].strategy_name == "wash_trader"
    # A scenario replaces configured manipulators.
    sim = build_coin_simulator(
        replace(settings, coin=replace(settings.coin, manipulators=[washer])), scenario="wash_trading"
    )
    assert [t.trader_id for t in sim.traders if t.strategy_name == "wash_trader"] == ["wash-trader-1"]


def test_strategies_must_be_configured_in_the_right_list():
    settings = get_settings()
    in_traders = TraderSettings(id="w", strategy="wash_trader")
    with pytest.raises(ValueError, match="coin.manipulators"):
        build_coin_simulator(replace(settings, coin=replace(settings.coin, traders=[in_traders])))
    in_manipulators = TraderSettings(id="m", strategy="momentum")
    with pytest.raises(ValueError, match="Unknown manipulator strategy"):
        build_coin_simulator(replace(settings, coin=replace(settings.coin, manipulators=[in_manipulators])))


def test_unknown_scenario_raises():
    with pytest.raises(ValueError, match="Unknown manipulation scenario"):
        build_coin_simulator(get_settings(), scenario="spoofing")


@pytest.mark.parametrize("scenario", sorted(MANIPULATION_SCENARIOS))
@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_scenarios_are_deterministic_and_conserve(scenario, mode):
    def run():
        sim = build_coin_simulator(get_settings(), pricing_mode=mode, include_whales=mode == "random_walk", scenario=scenario)
        coins_before, cash_before = sim.accounting_totals()
        ticks = sim.run(40)
        coins_after, cash_after = sim.accounting_totals()
        if mode == "amm":
            assert (coins_after, cash_after) == (coins_before, cash_before)
        else:
            assert float(coins_after) == pytest.approx(float(coins_before), rel=1e-12)
            assert float(cash_after) == pytest.approx(float(cash_before), rel=1e-12)
        return [(t.price, t.volume, t.trader_trades, t.pool_state) for t in ticks]

    assert run() == run()


def test_amm_pump_and_dump_scenario_profits_at_the_marks_expense():
    """The preset's documented outcome with the default seed (42)."""
    sim = build_coin_simulator(get_settings(), pricing_mode="amm", include_whales=False, scenario="pump_and_dump")
    ticks, pnl = _run_with_pnl(sim, 30)
    peak = max(ticks, key=lambda t: t.price)
    assert 15 <= peak.tick <= 17  # topped out by the end of the pump
    assert peak.price > 2 * sim.coin.starting_price
    assert sim.traders[-1].wallet.coins == 0.0
    assert pnl["pump-and-dump-1"] > 0
    assert sum(v for k, v in pnl.items() if k.startswith("mark-")) < 0


def test_amm_pump_and_dump_scenario_profits_in_most_seeds():
    """Not a lucky seed: the preset's calibration holds across seeds."""
    settings = get_settings()
    wins = 0
    for seed in range(1, 21):
        seeded = replace(settings, simulation=replace(settings.simulation, random_seed=seed))
        sim = build_coin_simulator(seeded, pricing_mode="amm", include_whales=False, scenario="pump_and_dump")
        _, pnl = _run_with_pnl(sim, 30)
        wins += pnl["pump-and-dump-1"] > 0
    assert wins >= 16


def test_wash_trading_scenario_is_most_of_reported_volume_in_random_walk_mode():
    sim = build_coin_simulator(get_settings(), scenario="wash_trading")
    base = build_coin_simulator(get_settings()).run(40)
    ticks = sim.run(40)
    assert [t.price for t in ticks] == [t.price for t in base]
    assert sum(t.wash_volume for t in ticks) / sum(t.volume for t in ticks) > 0.5
