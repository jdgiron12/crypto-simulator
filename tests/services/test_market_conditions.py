"""Named market-condition presets (Phase 17).

What matters here: a preset only rewrites configuration the simulator
already validates, it leaves an unnamed request untouched, its sentiment
drift is applied to the random walk and withheld from AMM (which refuses
it), and it changes the *distribution* of runs rather than decreeing any
one of them.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from crypto_simulator.analytics.aggregate import aggregate_batch
from crypto_simulator.config import get_settings
from crypto_simulator.core.events.catalog import EVENT_CATEGORIES
from crypto_simulator.core.events.generator import validate_random_event_parameters
from crypto_simulator.dashboard.data import payload_to_dict, run_simulation
from crypto_simulator.services.batch import run_batch
from crypto_simulator.services.coin_simulation import MANIPULATION_SCENARIOS
from crypto_simulator.services.market_conditions import (
    MARKET_CONDITION_NAMES,
    MARKET_CONDITIONS,
    MarketCondition,
    apply_market_condition,
)
from crypto_simulator.services.simulation_params import SimulationParams


@pytest.fixture
def settings():
    return get_settings()


# --- the registry ----------------------------------------------------------------------------------------


def test_the_registry_holds_exactly_the_three_presets():
    assert MARKET_CONDITION_NAMES == ("bear", "bull", "meme")
    assert set(MARKET_CONDITIONS) == set(MARKET_CONDITION_NAMES)


def test_every_preset_describes_itself():
    for name, condition in MARKET_CONDITIONS.items():
        assert condition.name == name
        assert len(condition.description) > 20


def test_the_registry_cannot_be_edited():
    with pytest.raises(TypeError):
        MARKET_CONDITIONS["new"] = MARKET_CONDITIONS["bull"]


def test_a_preset_cannot_be_edited():
    with pytest.raises(FrozenInstanceError):
        MARKET_CONDITIONS["bull"].name = "other"


def test_a_presets_categories_cannot_be_edited():
    with pytest.raises(TypeError):
        MARKET_CONDITIONS["bull"].event_categories["exchange_listing"] = 99.0


def test_every_preset_names_real_event_categories():
    for condition in MARKET_CONDITIONS.values():
        for category in condition.event_categories:
            assert category in EVENT_CATEGORIES, category


def test_every_presets_event_parameters_pass_the_simulators_own_validation(settings):
    """A preset may only choose values a user could have configured."""
    for name in MARKET_CONDITION_NAMES:
        applied = apply_market_condition(settings, name, pricing_mode="random_walk")
        random_events = applied.coin.events.random
        validate_random_event_parameters(
            random_events.probability,
            random_events.categories,
            random_events.severity,
            random_events.duration,
            random_events.decay_ticks,
        )


def test_a_negative_drift_coefficient_is_refused():
    """Sentiment is signed; the coefficient is not — the simulator's rule."""
    with pytest.raises(ValueError, match="drift_per_sentiment must be >= 0"):
        MarketCondition(name="x", description="y", drift_per_sentiment=-0.1)


def test_a_negative_volatility_is_refused():
    with pytest.raises(ValueError, match="volatility must be >= 0"):
        MarketCondition(name="x", description="y", volatility=-1.0)


# --- applying a preset -----------------------------------------------------------------------------------


def test_naming_no_condition_leaves_the_settings_untouched(settings):
    assert apply_market_condition(settings, None, pricing_mode="random_walk") is settings


def test_an_unknown_condition_is_refused(settings):
    with pytest.raises(ValueError, match="unknown market condition"):
        apply_market_condition(settings, "moon", pricing_mode="random_walk")


def test_a_preset_does_not_mutate_the_settings_it_was_given(settings):
    before = (settings.coin.volatility, settings.coin.events.random.probability,
              settings.coin.events.drift_per_sentiment)
    apply_market_condition(settings, "meme", pricing_mode="random_walk")
    assert (settings.coin.volatility, settings.coin.events.random.probability,
            settings.coin.events.drift_per_sentiment) == before
    assert get_settings() is settings, "the application's settings are untouched"


def test_a_preset_changes_only_what_it_names(settings):
    applied = apply_market_condition(settings, "bull", pricing_mode="random_walk")
    assert applied.coin.symbol == settings.coin.symbol
    assert applied.coin.initial_supply == settings.coin.initial_supply
    assert applied.coin.traders == settings.coin.traders
    assert applied.coin.whales == settings.coin.whales
    assert applied.simulation == settings.simulation
    assert applied.coin.events.scheduled == settings.coin.events.scheduled


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_each_preset_raises_the_news_rate(settings, name):
    applied = apply_market_condition(settings, name, pricing_mode="random_walk")
    assert applied.coin.events.random.probability > settings.coin.events.random.probability


def test_bull_weights_positive_categories(settings):
    categories = apply_market_condition(settings, "bull", pricing_mode="random_walk").coin.events.random.categories
    assert all(EVENT_CATEGORIES[c].sentiment > 0 for c in categories), categories


def test_bear_weights_negative_categories(settings):
    categories = apply_market_condition(settings, "bear", pricing_mode="random_walk").coin.events.random.categories
    assert all(EVENT_CATEGORIES[c].sentiment < 0 for c in categories), categories


def test_meme_mixes_both_tones_and_raises_volatility(settings):
    applied = apply_market_condition(settings, "meme", pricing_mode="random_walk")
    categories = applied.coin.events.random.categories
    sentiments = [EVENT_CATEGORIES[c].sentiment for c in categories]
    assert any(s > 0 for s in sentiments) and any(s < 0 for s in sentiments)
    assert applied.coin.volatility > settings.coin.volatility
    assert applied.coin.events.random.severity[0] > settings.coin.events.random.severity[0]


def test_the_presets_differ_from_one_another(settings):
    applied = [
        apply_market_condition(settings, name, pricing_mode="random_walk").coin
        for name in MARKET_CONDITION_NAMES
    ]
    assert len({tuple(sorted(coin.events.random.categories)) for coin in applied}) == 3


# --- the AMM caveat, which is a hard constraint ------------------------------------------------------------


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_sentiment_drift_reaches_a_random_walk_run(settings, name):
    applied = apply_market_condition(settings, name, pricing_mode="random_walk")
    assert applied.coin.events.drift_per_sentiment > 0


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_sentiment_drift_is_withheld_from_an_amm_run(settings, name):
    """The simulator refuses a nonzero coefficient in AMM mode, so a
    preset must not set one there."""
    applied = apply_market_condition(settings, name, pricing_mode="amm")
    assert applied.coin.events.drift_per_sentiment == 0.0


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_an_amm_run_under_every_preset_still_runs(name):
    """If the drift leaked into AMM this would raise rather than fail an
    assertion, which is exactly what must not happen."""
    payload = run_simulation(
        SimulationParams(ticks=20, pricing_mode="amm", include_whales=False,
                         market_condition=name, random_seed=48291)
    )
    assert payload.simulation.completed_ticks == 20


def test_an_amm_preset_still_changes_the_news(settings):
    """What AMM keeps: the news mix and its rate. What it loses: drift."""
    applied = apply_market_condition(settings, "bull", pricing_mode="amm")
    assert applied.coin.events.random.probability == 0.15
    assert applied.coin.events.random.categories
    assert applied.coin.events.drift_per_sentiment == 0.0


# --- as part of a request --------------------------------------------------------------------------------


def test_the_default_request_names_no_condition():
    assert SimulationParams().market_condition is None


def test_a_request_validates_the_condition_against_the_registry():
    with pytest.raises(ValueError, match="unknown market_condition"):
        SimulationParams(market_condition="moon")


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_a_request_accepts_every_preset(name):
    assert SimulationParams(market_condition=name).market_condition == name


def test_a_condition_composes_with_a_manipulation_scenario():
    """Different axes: a pump can run in a bear market."""
    payload = run_simulation(
        SimulationParams(ticks=30, pricing_mode="amm", include_whales=False,
                         scenario="pump_and_dump", market_condition="bear", random_seed=48291)
    )
    assert payload.report.manipulation is not None
    assert payload.simulation.params.scenario == "pump_and_dump"
    assert payload.simulation.params.market_condition == "bear"
    assert "pump_and_dump" in MANIPULATION_SCENARIOS


def test_an_explicit_event_request_still_applies_on_top_of_a_preset():
    """The preset sets the weather; an explicit flag overrules it."""
    plain = run_simulation(SimulationParams(ticks=20, market_condition="bull", random_seed=1))
    with_events = run_simulation(
        SimulationParams(ticks=20, market_condition="bull", events=True, random_seed=1)
    )
    assert with_events.report.event_windows is not None
    assert plain.price_series != with_events.price_series


# --- determinism -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_the_same_request_under_a_preset_gives_the_same_run(name):
    params = SimulationParams(ticks=40, market_condition=name, random_seed=48291)
    assert payload_to_dict(run_simulation(params)) == payload_to_dict(run_simulation(params))


def test_a_preset_draws_no_randomness_of_its_own(settings):
    """Applying one is pure configuration: twice gives the same settings."""
    first = apply_market_condition(settings, "meme", pricing_mode="random_walk")
    second = apply_market_condition(settings, "meme", pricing_mode="random_walk")
    assert first.coin.events.random.categories == second.coin.events.random.categories
    assert first.coin.volatility == second.coin.volatility


def test_a_preset_changes_the_run_it_is_applied_to():
    base = run_simulation(SimulationParams(ticks=40, random_seed=48291))
    bull = run_simulation(SimulationParams(ticks=40, market_condition="bull", random_seed=48291))
    assert bull.price_series != base.price_series


# --- what a preset does across a batch, stated honestly ----------------------------------------------------


def _median_return(condition, runs=30, ticks=120):
    batch = run_batch(
        SimulationParams(ticks=ticks, market_condition=condition),
        runs, runner=run_simulation, base_seed=48291,
    )
    return aggregate_batch(batch).metric("cumulative_return").median


def test_bull_shifts_the_distribution_up_relative_to_bear():
    """A tilt in the odds, measured across a batch — *not* a promise
    about any single run, which is why this compares medians of thirty
    runs rather than one run's direction."""
    assert _median_return("bull") > _median_return("bear")


def test_bull_shifts_the_distribution_up_relative_to_no_condition():
    assert _median_return("bull") > _median_return(None)


def test_bear_shifts_the_distribution_down_relative_to_no_condition():
    assert _median_return("bear") < _median_return(None)


def test_meme_widens_the_spread_far_more_than_it_moves_the_middle():
    """meme is a volatility regime. Its realised volatility rises sharply;
    the median falls only because a multiplicative walk drags it, not
    because the news mix points down."""
    batches = {}
    for condition in (None, "meme"):
        batch = run_batch(
            SimulationParams(ticks=120, market_condition=condition),
            30, runner=run_simulation, base_seed=48291,
        )
        batches[condition] = aggregate_batch(batch)
    assert batches["meme"].metric("volatility").median > 3 * batches[None].metric("volatility").median
    spread = batches["meme"].metric("cumulative_return")
    assert spread.maximum - spread.minimum > 1.0


def test_a_single_run_is_never_claimed_to_follow_its_condition():
    """Documenting the honest limit: under bull, some seeded runs fall.
    If this ever stopped being true the presets would have become a
    guarantee, which they are not."""
    batch = run_batch(
        SimulationParams(ticks=120, market_condition="bull"),
        30, runner=run_simulation, base_seed=48291,
    )
    falling = [p for p in batch.payloads if p.report.market.cumulative_return < 0]
    assert falling, "a bull batch that never falls would overstate what a preset does"
