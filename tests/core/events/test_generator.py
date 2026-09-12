import math
import random

import pytest

from crypto_simulator.core.events import (
    EVENT_CATEGORIES,
    EventEngine,
    EventPhase,
    MarketEvent,
    RandomEventGenerator,
    create_event,
)


def _gen(**kwargs):
    return RandomEventGenerator(**{"probability": 1.0, "seed": 1, **kwargs})


def _run(generator, ticks, engine=None):
    engine = EventEngine() if engine is None else engine
    events = [generator.maybe_inject(engine, tick) for tick in range(1, ticks + 1)]
    return engine, events


def _draws(generator, n):
    """``n`` ticks of draws, each into a fresh engine: exercises the
    generator's randomness without growing one engine to thousands of
    events (each injection re-sorts the engine's timeline)."""
    return [generator.maybe_inject(EventEngine(), tick) for tick in range(1, n + 1)]


def _signature(events):
    return [(e.event_id, e.category, e.severity, e.start_tick, e.duration, e.decay_ticks) for e in events if e]


# --- probability ----------------------------------------------------------------------------


def test_probability_zero_creates_nothing_and_draws_nothing():
    generator = _gen(probability=0.0, seed=7)
    engine, events = _run(generator, 500)
    assert not generator.enabled
    assert events == [None] * 500 and engine.events == ()
    assert generator._rng.getstate() == random.Random(7).getstate()


def test_probability_one_starts_exactly_one_event_every_tick():
    engine, events = _run(_gen(), 50)
    assert [e.start_tick for e in events] == list(range(1, 51))
    assert [e.event_id for e in events] == [f"random-{n:06d}" for n in range(1, 51)]
    assert engine.events == tuple(events)


def test_probability_is_a_per_tick_fraction_not_a_percentage():
    _, events = _run(_gen(probability=0.05, seed=3), 20_000)
    assert sum(e is not None for e in events) == pytest.approx(1_000, abs=150)
    with pytest.raises(ValueError, match="probability"):
        _gen(probability=5)


def test_same_seed_same_events_and_different_seed_different_events():
    first = _signature(_run(_gen(probability=0.3, seed=11), 300)[1])
    assert _signature(_run(_gen(probability=0.3, seed=11), 300)[1]) == first
    assert _signature(_run(_gen(probability=0.3, seed=12), 300)[1]) != first


# --- categories --------------------------------------------------------------------------


def test_categories_are_drawn_in_proportion_to_their_weights():
    events = _draws(_gen(categories={"exchange_listing": 3.0, "security_incident": 1.0}), 4_000)
    share = sum(e.category == "exchange_listing" for e in events) / len(events)
    assert share == pytest.approx(0.75, abs=0.03)
    assert {e.category for e in events} == {"exchange_listing", "security_incident"}


def test_zero_weight_categories_are_never_drawn():
    events = _draws(_gen(categories={"exchange_listing": 1.0, "security_incident": 0.0, "product_failure": 0}), 2_000)
    assert {e.category for e in events} == {"exchange_listing"}


def test_weights_are_normalized_and_their_order_does_not_matter():
    reference = _signature(_run(_gen(categories={"exchange_listing": 3.0, "security_incident": 1.0}), 500)[1])
    scaled = {"exchange_listing": 0.75, "security_incident": 0.25}
    reordered = {"security_incident": 1.0, "exchange_listing": 3.0}
    assert _signature(_run(_gen(categories=scaled), 500)[1]) == reference
    assert _signature(_run(_gen(categories=reordered), 500)[1]) == reference


def test_empty_categories_draw_from_the_whole_catalog():
    events = _draws(_gen(categories={}), 3_000)
    assert {e.category for e in events} == set(EVENT_CATEGORIES)
    assert _gen(categories=None).categories == tuple(sorted(EVENT_CATEGORIES))


# --- event parameters ----------------------------------------------------------------------


def test_parameters_stay_within_their_inclusive_ranges():
    events = _draws(_gen(severity=(0.3, 0.6), duration=(2, 3), decay_ticks=(0, 2)), 2_000)
    assert all(0.3 <= e.severity <= 0.6 for e in events)
    assert {e.duration for e in events} == {2, 3}
    assert {e.decay_ticks for e in events} == {0, 1, 2}


def test_degenerate_ranges_give_fixed_values_and_severity_never_exceeds_one():
    events = _draws(_gen(severity=(1.0, 1.0), duration=(4, 4), decay_ticks=(0, 0)), 200)
    assert {(e.severity, e.duration, e.decay_ticks) for e in events} == {(1.0, 4, 0)}
    events = _draws(_gen(severity=(0.999999, 1.0)), 5_000)
    assert all(e.severity <= 1.0 for e in events)


def test_events_are_built_through_the_catalog():
    _, events = _run(_gen(), 300)
    for event in events:
        profile = EVENT_CATEGORIES[event.category]
        assert isinstance(event, MarketEvent)
        assert event == create_event(
            event.category, event_id=event.event_id, severity=event.severity, start_tick=event.start_tick,
            duration=event.duration, decay_ticks=event.decay_ticks,
        )
        assert event.sentiment == profile.sentiment * event.severity
        assert event.headline == profile.description


def test_ids_are_unique_and_skip_ids_already_taken():
    _, events = _run(_gen(), 500)
    assert len({e.event_id for e in events}) == 500
    taken = create_event("product_launch", event_id="random-000001", severity=0.5, start_tick=50, duration=1)
    engine, events = _run(_gen(), 3, EventEngine([taken]))
    assert [e.event_id for e in events] == ["random-000002", "random-000003", "random-000004"]


# --- timing -------------------------------------------------------------------------------


def test_an_event_generated_for_a_tick_is_live_on_that_tick():
    engine = EventEngine()
    generator = _gen(duration=(2, 2), decay_ticks=(0, 0))
    first = generator.maybe_inject(engine, 1)
    assert [(s.event_id, s.phase) for s in engine.state(1).events] == [(first.event_id, EventPhase.ACTIVE)]
    second = generator.maybe_inject(engine, 2)
    assert [s.event_id for s in engine.state(2).events] == [first.event_id, second.event_id]


def test_random_events_can_start_during_and_after_existing_events():
    scheduled = create_event("exchange_listing", event_id="sched", severity=1.0, start_tick=1, duration=5)
    engine = EventEngine([scheduled])
    generator = _gen(duration=(1, 1), decay_ticks=(0, 0))
    during = generator.maybe_inject(engine, 3)
    after = generator.maybe_inject(engine, 9)
    assert {s.event_id for s in engine.state(3).events} == {"sched", during.event_id}
    assert [s.event_id for s in engine.state(9).events] == [after.event_id]


def test_random_events_overlap_freely():
    engine, events = _run(_gen(duration=(5, 5), decay_ticks=(0, 0)), 3)
    assert [s.event_id for s in engine.state(3).events] == [e.event_id for e in events]


def test_scheduled_events_do_not_change_the_random_stream():
    scheduled = [create_event("product_failure", event_id=f"s{i}", severity=0.5, start_tick=i, duration=2)
                 for i in range(1, 40, 7)]
    alone = _signature(_run(_gen(probability=0.4, seed=5), 60)[1])
    beside = _signature(_run(_gen(probability=0.4, seed=5), 60, EventEngine(scheduled))[1])
    assert beside == alone


# --- validation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"probability": -0.1}, "probability"),
        ({"probability": math.nan}, "probability"),
        ({"probability": True}, "probability"),
        ({"categories": {"moon_landing": 1.0}}, "unknown event category"),
        ({"categories": {"product_launch": -1.0}}, "weight"),
        ({"categories": {"product_launch": math.inf}}, "weight"),
        ({"categories": {"product_launch": 0.0, "security_incident": 0.0}}, "at least one positive weight"),
        ({"categories": ["product_launch"]}, "categories must map"),
        ({"severity": (0.0, 0.5)}, "severity"),
        ({"severity": (0.5, 1.1)}, "severity"),
        ({"duration": (0, 2)}, "duration"),
        ({"duration": (3, 2)}, "duration"),
        ({"decay_ticks": (-1, 2)}, "decay_ticks"),
        ({"decay_ticks": (1.5, 2)}, "decay_ticks"),
    ],
)
def test_invalid_parameters_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _gen(**kwargs)


# --- provenance record ------------------------------------------------------------------------


def test_generated_events_record_exactly_what_the_generator_started():
    scheduled = create_event("product_failure", event_id="sched", severity=0.5, start_tick=3, duration=2)
    generator = _gen(probability=0.4, seed=9)
    engine, events = _run(generator, 60, EventEngine([scheduled]))
    started = tuple(e for e in events if e is not None)
    assert started and generator.generated_events == started
    assert set(engine.events) == set(started) | {scheduled}
    assert scheduled not in generator.generated_events


def test_generated_events_are_read_only_and_empty_when_disabled():
    generator = _gen(probability=0.0)
    _run(generator, 100)
    assert generator.generated_events == ()
    record = _gen().generated_events
    assert isinstance(record, tuple)
    with pytest.raises(AttributeError):
        generator.generated_events = ()


def test_generated_event_ids_are_deterministic_and_reading_them_draws_nothing():
    def ids(read_every_tick):
        generator, engine = _gen(probability=0.3, seed=4), EventEngine()
        for tick in range(1, 80):
            generator.maybe_inject(engine, tick)
            if read_every_tick:
                generator.generated_events
        return [e.event_id for e in generator.generated_events], generator._rng.getstate()

    assert ids(True) == ids(False)
    assert ids(False)[0] == [f"random-{n:06d}" for n in range(1, len(ids(False)[0]) + 1)]
