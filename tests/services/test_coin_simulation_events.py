"""coin.events configuration → EventEngine → CoinSimulator (Phase 6, Step 4)."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from crypto_simulator.config import (
    EventSettings,
    RandomEventSettings,
    ScheduledEventSettings,
    TraderSettings,
    get_settings,
)
from crypto_simulator.config.settings import build_settings, load_config
from crypto_simulator.core.events import EVENT_CATEGORIES, EventPhase, EventState
from crypto_simulator.services.coin_simulation import DEMO_EVENTS, build_coin_simulator, build_event_engine


def _scheduled(event_id="e1", category="exchange_listing", severity=0.8, start_tick=5, duration=3, **extra):
    return ScheduledEventSettings(id=event_id, category=category, severity=severity, start_tick=start_tick,
                                  duration=duration, **extra)


def _with_events(settings=None, **fields):
    settings = settings or get_settings()
    return replace(settings, coin=replace(settings.coin, events=replace(settings.coin.events, **fields)))


def _with_random(**fields):
    return EventSettings(random=replace(RandomEventSettings(), **fields))


def _build(settings, mode):
    return build_coin_simulator(settings, pricing_mode=mode, include_whales=mode == "random_walk")


def _market_view(sim, ticks=100):
    run = sim.run(ticks)
    view = [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.pool_state) for t in run]
    wallets = [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders]
    return view, wallets, (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals(), run


MODES = ["random_walk", "amm"]


# --- defaults and backward compatibility ------------------------------------------------------


def test_default_config_builds_no_event_engine_and_zero_drift():
    sim = build_coin_simulator(get_settings())
    assert sim.events is None
    assert sim.drift_per_sentiment == 0.0


def _raw_variant(events):
    raw = load_config()
    raw["coin"] = dict(raw["coin"])
    if events == "absent":
        raw["coin"].pop("events")
    else:
        raw["coin"]["events"] = events
    return build_settings(raw, Path("variant.yaml"))


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "variant",
    ["absent", None, {}, {"scheduled": []}, {"random": {"probability": 0.0}}, {"drift_per_sentiment": 0.0}],
    ids=["no-section", "null-section", "empty-section", "empty-schedule", "random-probability-0", "zero-drift"],
)
def test_configurations_without_events_are_bit_identical_to_the_default(variant, mode):
    reference = _market_view(_build(get_settings(), mode))
    sim = _build(_raw_variant(variant), mode)
    assert sim.events is None
    result = _market_view(sim)
    assert result[:4] == reference[:4]
    assert all(t.event_state is None for t in result[4])


@pytest.mark.parametrize("mode", MODES)
def test_event_scheduled_after_the_run_is_bit_identical_and_draws_no_randomness(mode):
    reference_sim = _build(get_settings(), mode)
    reference = _market_view(reference_sim)
    late = _with_events(scheduled=[_scheduled(category="security_incident", severity=1.0, start_tick=101)])
    sim = _build(late, mode)
    result = _market_view(sim)
    assert result[:4] == reference[:4]
    assert all(t.event_state == EventState(tick=t.tick) for t in result[4])
    assert [t._rng.getstate() for t in sim.traders] == [t._rng.getstate() for t in reference_sim.traders]
    assert [w._rng.getstate() for w in sim.whales] == [w._rng.getstate() for w in reference_sim.whales]


# --- scheduled events reach the engine --------------------------------------------------------


def test_scheduled_events_are_built_through_the_catalog_and_reach_the_simulator():
    settings = _with_events(drift_per_sentiment=0.005, scheduled=[
        _scheduled("b-incident", "security_incident", 0.5, start_tick=10, duration=2, decay_ticks=3),
        _scheduled("a-listing", "exchange_listing", 0.8, start_tick=4, duration=5),
        _scheduled("c-custom", "market_uncertainty", 0.4, start_tick=4, duration=1, headline="Fictional rumor",
                   sentiment=-0.3, volatility_boost=2.0, attention=0.0),
    ])
    sim = build_coin_simulator(settings)
    assert sim.drift_per_sentiment == 0.005
    events = {e.event_id: e for e in sim.events.events}
    assert [e.event_id for e in sim.events.events] == ["a-listing", "c-custom", "b-incident"]
    incident = EVENT_CATEGORIES["security_incident"]
    assert (events["b-incident"].sentiment, events["b-incident"].volatility_boost, events["b-incident"].attention) == (
        incident.sentiment * 0.5, incident.volatility_boost * 0.5, incident.attention * 0.5,
    )
    assert (events["b-incident"].start_tick, events["b-incident"].duration, events["b-incident"].decay_ticks) == (10, 2, 3)
    assert events["b-incident"].headline == incident.description
    custom = events["c-custom"]
    assert (custom.headline, custom.sentiment, custom.volatility_boost, custom.attention) == (
        "Fictional rumor", -0.3, 2.0, 0.0,
    )
    ticks = sim.run(12)
    assert [s.event_id for s in ticks[3].event_state.events] == ["a-listing", "c-custom"]
    assert ticks[10].event_state.events[0].phase is EventPhase.ACTIVE  # tick 11: last active tick
    assert ticks[11].event_state.events[0].phase is EventPhase.DECAYING  # tick 12


def test_amm_mode_runs_configured_events_through_traders_with_exact_accounting():
    settings = _with_events(scheduled=[_scheduled("news", "exchange_listing", 1.0, start_tick=3, duration=10)])
    sim = build_coin_simulator(settings, pricing_mode="amm", include_whales=False)
    before = sim.accounting_totals()
    ticks = sim.run(20)
    assert ticks[2].event_state.sentiment == EVENT_CATEGORIES["exchange_listing"].sentiment
    assert sim.accounting_totals() == before
    assert sim.pool.swap_count == sum(len(t.trader_trades) for t in ticks)


def test_demo_schedule_is_valid_and_fits_the_default_demo_run():
    engine = build_event_engine(EventSettings(scheduled=list(DEMO_EVENTS)))
    assert [e.event_id for e in engine.events] == ["demo-listing", "demo-incident"]
    assert all(e.expires_at <= 21 for e in engine.events)
    assert engine.events[0].sentiment > 0 > engine.events[1].sentiment


# --- validation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event, message",
    [
        (_scheduled(category="moon_landing"), "Unknown event category"),
        (_scheduled(severity=1.5), "severity"),
        (_scheduled(severity=0.0), "severity"),
        (_scheduled(severity=math.nan), "severity"),
        (_scheduled(start_tick=0), "start_tick"),
        (_scheduled(duration=0), "duration"),
        (_scheduled(decay_ticks=-1), "decay_ticks"),
        (_scheduled(start_tick=2.5), "start_tick"),
        (_scheduled(sentiment=1.5), "sentiment"),
        (_scheduled(volatility_boost=-1.0), "volatility_boost"),
        (_scheduled(attention=math.inf), "attention"),
        (_scheduled(event_id=""), "event_id"),
    ],
)
def test_invalid_scheduled_events_fail_naming_the_event(event, message):
    with pytest.raises(ValueError, match=rf"Invalid scheduled event .*{message}"):
        build_coin_simulator(_with_events(scheduled=[event]))


def test_duplicate_scheduled_event_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate event_id 'same'"):
        build_coin_simulator(_with_events(scheduled=[_scheduled("same"), _scheduled("same", start_tick=30)]))


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"probability": -0.1}, "probability"),
        ({"probability": 1.5}, "probability"),
        ({"probability": math.nan}, "probability"),
        ({"probability": "0.1"}, "probability"),
        ({"categories": {"moon_landing": 1.0}}, "unknown event category 'moon_landing'"),
        ({"categories": {"product_launch": -1.0}}, "weight"),
        ({"categories": {"product_launch": math.nan}}, "weight"),
        ({"categories": {"product_launch": 0.0}}, "at least one positive weight"),
        ({"categories": ["product_launch"]}, "categories must map"),
        ({"severity": (0.0, 1.0)}, "severity"),
        ({"severity": (0.8, 0.3)}, "severity"),
        ({"severity": (0.3, 1.5)}, "severity"),
        ({"severity": (0.3, math.inf)}, "severity"),
        ({"severity": (0.5,)}, "severity"),
        ({"severity": 0.5}, "severity"),
        ({"duration": (0, 3)}, "duration"),
        ({"duration": (5, 2)}, "duration"),
        ({"duration": (2.5, 4)}, "duration"),
        ({"duration": (True, 3)}, "duration"),
        ({"decay_ticks": (-1, 3)}, "decay_ticks"),
        ({"decay_ticks": (3, 1)}, "decay_ticks"),
        ({"decay_ticks": (0.5, 2)}, "decay_ticks"),
    ],
)
def test_invalid_random_event_settings_fail_clearly(fields, message):
    with pytest.raises(ValueError, match=rf"coin\.events\.random.*{message}"):
        build_event_engine(_with_random(**fields))


def test_valid_random_settings_are_accepted_and_do_nothing_at_probability_zero():
    cfg = _with_random(categories={"product_launch": 2.0, "security_incident": 0.0}, severity=(1.0, 1.0),
                       duration=(1, 1), decay_ticks=(0, 0))
    assert build_event_engine(cfg) is None


def test_nonzero_random_probability_builds_a_generator_instead_of_being_ignored():
    """(Step 4 rejected this until random generation existed.)"""
    assert build_event_engine(_with_random(probability=0.05)) is None  # no scheduled events
    sim = build_coin_simulator(_with_events(random=replace(RandomEventSettings(), probability=0.05)))
    assert sim.event_generator is not None and sim.event_generator.probability == 0.05
    assert sim.events is not None and sim.events.events == ()


def test_drift_is_validated_by_the_simulator_and_rejected_in_amm_mode():
    with pytest.raises(ValueError, match="drift_per_sentiment must be"):
        build_coin_simulator(_with_events(drift_per_sentiment=-0.01))
    with pytest.raises(ValueError, match="drift_per_sentiment only applies"):
        build_coin_simulator(_with_events(drift_per_sentiment=0.01), pricing_mode="amm", include_whales=False)


# --- trader sentiment sensitivity via the existing params ---------------------------------------


def test_default_trader_sensitivities_are_unchanged():
    sim = build_coin_simulator(get_settings())
    assert {t.strategy_name: t.sentiment_sensitivity for t in sim.traders} == {
        "retail": 1.0, "momentum": 0.8, "dip_buyer": 0.0, "panic_seller": 1.0, "long_term_holder": 0.2,
    }


def test_sentiment_sensitivity_passes_through_trader_params_from_yaml():
    raw = load_config()
    raw["coin"] = dict(raw["coin"])
    raw["coin"]["traders"] = [dict(t, params={**t.get("params", {}), "sentiment_sensitivity": 0.25})
                              for t in raw["coin"]["traders"]]
    sim = build_coin_simulator(build_settings(raw, Path("variant.yaml")))
    assert all(t.sentiment_sensitivity == 0.25 for t in sim.traders)


def test_manipulators_reject_a_configured_sensitivity():
    settings = get_settings()
    pump = TraderSettings(id="p", strategy="pump_and_dump", params={"sentiment_sensitivity": 0.5})
    with pytest.raises(ValueError, match="ignores news"):
        build_coin_simulator(replace(settings, coin=replace(settings.coin, manipulators=[pump])))


def test_deaf_traders_and_a_direction_only_event_leave_the_run_unchanged():
    """Zero sensitivity configured for every trader + an event with no
    volatility or attention effect: the run matches the no-event default."""
    reference = _market_view(build_coin_simulator(get_settings()))
    settings = _with_events(scheduled=[_scheduled(severity=1.0, start_tick=1, duration=100, volatility_boost=0.0,
                                                  attention=0.0)])
    deaf = [replace(t, params={**t.params, "sentiment_sensitivity": 0.0}) for t in settings.coin.traders]
    settings = replace(settings, coin=replace(settings.coin, traders=deaf))
    result = _market_view(build_coin_simulator(settings))
    assert result[:4] == reference[:4]
    assert all(t.event_state.sentiment > 0 for t in result[4])


# --- random events (Step 5) -------------------------------------------------------------------


def _random_settings(probability=0.2, settings=None, **fields):
    return _with_events(settings, random=replace(RandomEventSettings(), probability=probability, **fields))


def _random_signature(sim, ticks=80):
    sim.run(ticks)
    return [(e.event_id, e.category, e.severity, e.start_tick, e.duration, e.decay_ticks) for e in sim.events.events]


def test_random_generator_is_seeded_at_simulation_seed_plus_3000():
    from crypto_simulator.core.events import EventEngine, RandomEventGenerator
    from crypto_simulator.services.coin_simulation import RANDOM_EVENT_SEED_OFFSET

    settings = _random_settings(categories={"exchange_listing": 1.0, "product_failure": 2.0})
    assert RANDOM_EVENT_SEED_OFFSET == 3000
    standalone = RandomEventGenerator(
        probability=0.2, categories={"exchange_listing": 1.0, "product_failure": 2.0},
        seed=settings.simulation.random_seed + 3000,
    )
    engine = EventEngine()
    for tick in range(1, 81):
        standalone.maybe_inject(engine, tick)
    expected = [(e.event_id, e.category, e.severity, e.start_tick, e.duration, e.decay_ticks) for e in engine.events]
    assert expected
    assert _random_signature(build_coin_simulator(settings)) == expected


def test_random_event_stream_does_not_depend_on_participants_or_mode():
    settings = _random_settings()
    reference = _random_signature(build_coin_simulator(settings))
    assert _random_signature(build_coin_simulator(settings, include_traders=False, include_whales=False)) == reference
    assert _random_signature(build_coin_simulator(settings, scenario="pump_and_dump")) == reference
    assert _random_signature(build_coin_simulator(settings, pricing_mode="amm", include_whales=False)) == reference


def test_scheduled_and_random_events_are_built_together():
    settings = _random_settings(probability=0.3, settings=_with_events(scheduled=[_scheduled("sched", start_tick=2)]))
    sim = build_coin_simulator(settings)
    sim.run(40)
    ids = [e.event_id for e in sim.events.events]
    assert "sched" in ids and any(i.startswith("random-") for i in ids)


def test_builder_runs_with_random_events_are_deterministic():
    def run():
        sim = build_coin_simulator(_random_settings(probability=0.3))
        return [(t.price, t.volume, t.trader_trades, t.event_state) for t in sim.run(60)]

    assert run() == run()


def test_amm_random_events_through_the_builder_keep_exact_accounting():
    sim = build_coin_simulator(_random_settings(probability=0.3), pricing_mode="amm", include_whales=False)
    before = sim.accounting_totals()
    ticks = sim.run(60)
    assert any(t.event_state.events for t in ticks)
    assert sim.accounting_totals() == before
    assert sim.pool.swap_count == sum(len(t.trader_trades) for t in ticks)
    with pytest.raises(ValueError, match="drift_per_sentiment only applies"):
        build_coin_simulator(_random_settings(settings=_with_events(drift_per_sentiment=0.01)),
                             pricing_mode="amm", include_whales=False)
