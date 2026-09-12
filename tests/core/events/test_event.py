import dataclasses
import math

import pytest

from crypto_simulator.core.events.event import EventPhase, MarketEvent


def _event(**overrides):
    fields = dict(
        event_id="e1", category="exchange_listing", severity=0.8, sentiment=0.5,
        volatility_boost=0.25, attention=0.5, start_tick=10, duration=3, decay_ticks=4,
    )
    return MarketEvent(**{**fields, **overrides})


# --- construction and validation -----------------------------------------------------


def test_valid_event_keeps_its_fields_and_defaults():
    event = MarketEvent("e", "custom", 1.0, -1.0, 0.0, 0.0, start_tick=1, duration=1)
    assert (event.decay_ticks, event.headline) == (0, "")
    assert (event.severity, event.sentiment, event.volatility_boost, event.attention) == (1.0, -1.0, 0.0, 0.0)


def test_derived_boundaries():
    event = _event(start_tick=10, duration=3, decay_ticks=4)
    assert event.last_active_tick == 12
    assert event.expires_at == 17


@pytest.mark.parametrize(
    "field, value",
    [
        ("event_id", ""),
        ("event_id", None),
        ("category", ""),
        ("severity", 0.0),
        ("severity", -0.1),
        ("severity", 1.01),
        ("severity", math.nan),
        ("severity", math.inf),
        ("severity", "high"),
        ("severity", True),
        ("sentiment", 1.01),
        ("sentiment", -1.01),
        ("sentiment", math.nan),
        ("volatility_boost", -0.01),
        ("volatility_boost", math.nan),
        ("volatility_boost", math.inf),
        ("attention", -0.01),
        ("attention", math.inf),
        ("start_tick", 0),
        ("start_tick", -5),
        ("start_tick", 2.0),
        ("start_tick", True),
        ("duration", 0),
        ("duration", -1),
        ("duration", 1.5),
        ("decay_ticks", -1),
        ("decay_ticks", 2.0),
        ("headline", None),
    ],
)
def test_invalid_fields_are_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        _event(**{field: value})


def test_boundary_values_are_accepted():
    _event(severity=1.0, sentiment=1.0)
    _event(sentiment=-1.0, volatility_boost=0.0, attention=0.0)
    _event(start_tick=1, duration=1, decay_ticks=0)


def test_events_are_immutable_and_hashable():
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.sentiment = 0.9
    assert event == _event()
    assert len({event, _event()}) == 1


# --- lifecycle --------------------------------------------------------------------------


def test_phase_at_every_boundary():
    event = _event(start_tick=10, duration=3, decay_ticks=4)
    expected = {
        0: EventPhase.SCHEDULED,
        9: EventPhase.SCHEDULED,
        10: EventPhase.ACTIVE,
        12: EventPhase.ACTIVE,
        13: EventPhase.DECAYING,
        16: EventPhase.DECAYING,
        17: EventPhase.EXPIRED,
        1_000: EventPhase.EXPIRED,
    }
    assert {tick: event.phase_at(tick) for tick in expected} == expected


def test_intensity_follows_the_phases_exactly():
    event = _event(start_tick=10, duration=3, decay_ticks=4)
    intensities = [event.intensity_at(tick) for tick in range(8, 19)]
    #              8    9    10   11   12   13   14   15   16   17   18
    assert intensities == [0.0, 0.0, 1.0, 1.0, 1.0, 0.8, 0.6, 0.4, 0.2, 0.0, 0.0]


@pytest.mark.parametrize("decay_ticks", [1, 2, 3, 7, 25])
def test_decay_is_linear_strictly_decreasing_and_never_full_or_zero(decay_ticks):
    event = _event(start_tick=5, duration=2, decay_ticks=decay_ticks)
    decay = [event.intensity_at(tick) for tick in range(7, 7 + decay_ticks)]
    assert all(event.phase_at(tick) is EventPhase.DECAYING for tick in range(7, 7 + decay_ticks))
    assert all(0.0 < i < 1.0 for i in decay)
    assert all(a > b for a, b in zip(decay, decay[1:]))
    steps = [a - b for a, b in zip([1.0, *decay], [*decay, 0.0])]
    assert steps == pytest.approx([1 / (decay_ticks + 1)] * (decay_ticks + 1))
    assert event.intensity_at(7 + decay_ticks) == 0.0


def test_no_decay_expires_right_after_the_active_window():
    event = _event(start_tick=4, duration=2, decay_ticks=0)
    assert [event.phase_at(t) for t in (3, 4, 5, 6)] == [
        EventPhase.SCHEDULED, EventPhase.ACTIVE, EventPhase.ACTIVE, EventPhase.EXPIRED,
    ]
    assert [event.intensity_at(t) for t in (3, 4, 5, 6)] == [0.0, 1.0, 1.0, 0.0]


def test_single_tick_event():
    event = _event(start_tick=1, duration=1, decay_ticks=0)
    assert [event.intensity_at(t) for t in (0, 1, 2)] == [0.0, 1.0, 0.0]


def test_lifecycle_queries_are_pure_and_repeatable():
    event = _event()
    first = [(event.phase_at(t), event.intensity_at(t)) for t in range(30)]
    second = [(event.phase_at(t), event.intensity_at(t)) for t in reversed(range(30))][::-1]
    assert first == second
    assert event == _event()
