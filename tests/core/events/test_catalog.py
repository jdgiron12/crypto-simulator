import re

import pytest

from crypto_simulator.core.events.catalog import EVENT_CATEGORIES, EventProfile, EventTone, create_event
from crypto_simulator.core.events.event import MarketEvent

POSITIVE = {"partnership_announcement", "product_launch", "exchange_listing", "adoption_growth", "positive_regulation"}
NEGATIVE = {"security_incident", "product_failure", "regulatory_restriction", "competitor_announcement", "supply_concern"}
MIXED = {"leadership_change", "ambiguous_announcement", "delayed_launch", "market_uncertainty"}


def _create(category="exchange_listing", **overrides):
    kwargs = dict(event_id="e1", severity=1.0, start_tick=1, duration=2)
    return create_event(category, **{**kwargs, **overrides})


def test_catalog_covers_positive_negative_and_mixed_categories():
    assert set(EVENT_CATEGORIES) == POSITIVE | NEGATIVE | MIXED
    by_tone = {tone: {k for k, p in EVENT_CATEGORIES.items() if p.tone is tone} for tone in EventTone}
    assert by_tone == {EventTone.POSITIVE: POSITIVE, EventTone.NEGATIVE: NEGATIVE, EventTone.MIXED: MIXED}


@pytest.mark.parametrize("category", sorted(EVENT_CATEGORIES))
def test_profiles_are_consistent_with_their_tone(category):
    profile = EVENT_CATEGORIES[category]
    assert isinstance(profile, EventProfile)
    assert profile.description
    assert re.fullmatch(r"[a-z]+(_[a-z]+)*", category)
    assert profile.volatility_boost >= 0 and profile.attention >= 0
    if profile.tone is EventTone.POSITIVE:
        assert profile.sentiment > 0
    elif profile.tone is EventTone.NEGATIVE:
        assert profile.sentiment < 0
    else:
        assert abs(profile.sentiment) <= 0.2
        assert profile.volatility_boost > abs(profile.sentiment)


@pytest.mark.parametrize("category", sorted(EVENT_CATEGORIES))
def test_every_category_builds_a_valid_event_at_full_severity(category):
    event = _create(category)
    profile = EVENT_CATEGORIES[category]
    assert isinstance(event, MarketEvent)
    assert event.category == category
    assert (event.sentiment, event.volatility_boost, event.attention) == (
        profile.sentiment, profile.volatility_boost, profile.attention,
    )
    assert event.headline == profile.description


def test_catalog_is_read_only():
    with pytest.raises(TypeError):
        EVENT_CATEGORIES["new_category"] = EVENT_CATEGORIES["product_launch"]


def test_severity_scales_every_effect():
    profile = EVENT_CATEGORIES["security_incident"]
    event = _create("security_incident", severity=0.5)
    assert event.severity == 0.5
    assert event.sentiment == profile.sentiment * 0.5
    assert event.volatility_boost == profile.volatility_boost * 0.5
    assert event.attention == profile.attention * 0.5


def test_overrides_are_final_values_and_still_validated():
    event = _create("exchange_listing", severity=0.5, sentiment=0.1, volatility_boost=2.0, attention=0.0)
    assert (event.sentiment, event.volatility_boost, event.attention) == (0.1, 2.0, 0.0)
    assert _create(headline="Custom fictional headline").headline == "Custom fictional headline"
    with pytest.raises(ValueError, match="sentiment"):
        _create(sentiment=1.5)
    with pytest.raises(ValueError, match="volatility_boost"):
        _create(volatility_boost=-1.0)


def test_timing_is_passed_through_and_validated():
    event = _create(start_tick=7, duration=4, decay_ticks=2)
    assert (event.start_tick, event.duration, event.decay_ticks) == (7, 4, 2)
    with pytest.raises(ValueError, match="duration"):
        _create(duration=0)


@pytest.mark.parametrize("severity", [0.0, 1.5, -0.5, float("nan"), float("inf"), "big", None, True])
def test_bad_severity_is_reported_as_severity(severity):
    with pytest.raises(ValueError, match="severity"):
        _create("security_incident", severity=severity)


def test_unknown_category_is_rejected_with_the_valid_list():
    with pytest.raises(ValueError, match="Unknown event category 'moon_landing'.*exchange_listing"):
        _create("moon_landing")
    with pytest.raises(ValueError, match="Unknown event category"):
        _create(None)


def test_create_event_is_deterministic():
    assert _create(severity=0.3) == _create(severity=0.3)
