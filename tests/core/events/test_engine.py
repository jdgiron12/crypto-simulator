import ast
import dataclasses
import itertools
from pathlib import Path

import pytest

import crypto_simulator.core.events as events_package
from crypto_simulator.core.events.engine import EventEngine, EventState, EventStatus
from crypto_simulator.core.events.event import EventPhase, MarketEvent


def _event(event_id="e1", sentiment=0.5, volatility_boost=0.5, attention=0.25, start_tick=5,
           duration=3, decay_ticks=2, category="custom"):
    return MarketEvent(
        event_id=event_id, category=category, severity=1.0, sentiment=sentiment,
        volatility_boost=volatility_boost, attention=attention,
        start_tick=start_tick, duration=duration, decay_ticks=decay_ticks,
    )


def _states(engine, ticks=range(0, 40)):
    return [engine.state(t) for t in ticks]


# --- neutral state -----------------------------------------------------------------------


def test_empty_engine_is_neutral_at_every_tick():
    engine = EventEngine()
    assert engine.events == ()
    for tick in range(0, 50):
        assert engine.state(tick) == EventState(tick=tick)
    neutral = EventState(tick=3)
    assert (neutral.sentiment, neutral.volatility_multiplier, neutral.attention_multiplier, neutral.events) == (
        0.0, 1.0, 1.0, (),
    )


# --- single event lifecycle ----------------------------------------------------------------


def test_single_event_state_through_its_lifecycle():
    engine = EventEngine([_event(start_tick=5, duration=3, decay_ticks=2)])  # active 5-7, decay 8-9
    assert engine.state(4) == EventState(tick=4)
    assert engine.state(5) == EventState(
        tick=5, sentiment=0.5, volatility_multiplier=1.5, attention_multiplier=1.25,
        events=(EventStatus("e1", "custom", EventPhase.ACTIVE, 1.0),),
    )
    assert engine.state(7).events[0].phase is EventPhase.ACTIVE
    decaying = engine.state(8)
    assert decaying.events == (EventStatus("e1", "custom", EventPhase.DECAYING, 2 / 3),)
    assert decaying.sentiment == 0.5 * (2 / 3)
    assert decaying.volatility_multiplier == 1.0 + 0.5 * (2 / 3)
    assert decaying.attention_multiplier == 1.0 + 0.25 * (2 / 3)
    assert engine.state(9).events[0].intensity == 1 / 3
    assert engine.state(10) == EventState(tick=10)


def test_expired_events_remain_in_the_timeline():
    event = _event(start_tick=2, duration=1, decay_ticks=0)
    engine = EventEngine([event])
    _states(engine)
    assert engine.state(30) == EventState(tick=30)
    assert engine.events == (event,)
    assert engine.events[0].phase_at(30) is EventPhase.EXPIRED


# --- overlapping events --------------------------------------------------------------------


def test_overlapping_effects_add_and_statuses_list_every_live_event():
    a = _event("a", sentiment=0.25, volatility_boost=0.5, attention=0.25, start_tick=5, duration=10)
    b = _event("b", sentiment=0.5, volatility_boost=0.25, attention=1.0, start_tick=8, duration=10)
    engine = EventEngine([a, b])
    assert engine.state(6).sentiment == 0.25
    both = engine.state(9)
    assert [s.event_id for s in both.events] == ["a", "b"]
    assert both.sentiment == 0.75
    assert both.volatility_multiplier == 1.75
    assert both.attention_multiplier == 2.25


def test_active_and_decaying_events_combine_at_their_intensities():
    fading = _event("fading", sentiment=0.5, volatility_boost=1.0, attention=0.0, start_tick=1, duration=2, decay_ticks=3)
    fresh = _event("fresh", sentiment=-0.25, volatility_boost=0.5, attention=0.0, start_tick=4, duration=5)
    state = EventEngine([fading, fresh]).state(4)  # fading is at decay step 2: intensity 0.5
    assert [(s.event_id, s.phase, s.intensity) for s in state.events] == [
        ("fading", EventPhase.DECAYING, 0.5),
        ("fresh", EventPhase.ACTIVE, 1.0),
    ]
    assert state.sentiment == 0.5 * 0.5 - 0.25
    assert state.volatility_multiplier == 1.0 + 1.0 * 0.5 + 0.5


def test_sentiment_is_clamped_but_volatility_and_attention_are_not():
    good = [_event(f"g{i}", sentiment=0.75, volatility_boost=1.0, attention=1.0, start_tick=1, duration=5) for i in range(3)]
    state = EventEngine(good).state(2)
    assert state.sentiment == 1.0
    assert state.volatility_multiplier == 4.0
    assert state.attention_multiplier == 4.0
    bad = [_event(f"b{i}", sentiment=-0.75, start_tick=1, duration=5) for i in range(3)]
    assert EventEngine(bad).state(2).sentiment == -1.0


def test_opposite_events_cancel_sentiment_but_not_uncertainty():
    up = _event("up", sentiment=0.5, volatility_boost=0.5, start_tick=1, duration=5)
    down = _event("down", sentiment=-0.5, volatility_boost=0.5, start_tick=1, duration=5)
    state = EventEngine([up, down]).state(3)
    assert state.sentiment == 0.0
    assert state.volatility_multiplier == 2.0
    assert len(state.events) == 2


# --- ordering and determinism ------------------------------------------------------------


def _mixed_timeline():
    return [
        _event("c", sentiment=0.3, volatility_boost=0.1, attention=0.7, start_tick=3, duration=4, decay_ticks=5),
        _event("a", sentiment=-0.9, volatility_boost=1.3, attention=0.2, start_tick=6, duration=2, decay_ticks=7),
        _event("b", sentiment=0.7, volatility_boost=0.3, attention=0.9, start_tick=6, duration=6, decay_ticks=1),
        _event("d", sentiment=0.1, volatility_boost=0.0, attention=0.0, start_tick=20, duration=1, decay_ticks=0),
    ]


def test_timeline_is_ordered_by_start_tick_then_id():
    engine = EventEngine(_mixed_timeline())
    assert [e.event_id for e in engine.events] == ["c", "a", "b", "d"]
    assert [s.event_id for s in engine.state(7).events] == ["c", "a", "b"]


def test_state_does_not_depend_on_the_order_events_were_supplied():
    reference = _states(EventEngine(_mixed_timeline()))
    for permutation in itertools.permutations(_mixed_timeline()):
        assert _states(EventEngine(permutation)) == reference


def test_state_queries_are_pure_and_deterministic():
    engine = EventEngine(_mixed_timeline())
    forward = _states(engine)
    backward = [engine.state(t) for t in reversed(range(0, 40))][::-1]
    assert forward == backward
    assert _states(EventEngine(_mixed_timeline())) == forward
    assert engine.events == EventEngine(_mixed_timeline()).events


def test_states_and_statuses_are_immutable():
    state = EventEngine(_mixed_timeline()).state(7)
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.sentiment = 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.events[0].intensity = 1.0
    assert isinstance(state.events, tuple)


# --- validation and manual injection --------------------------------------------------------


def test_duplicate_event_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate event_id 'a'"):
        EventEngine([_event("a"), _event("a", start_tick=9)])
    engine = EventEngine([_event("a")])
    with pytest.raises(ValueError, match="Duplicate event_id 'a'"):
        engine.inject(_event("a", start_tick=50), current_tick=10)


def test_only_market_events_are_accepted():
    with pytest.raises(TypeError, match="MarketEvent"):
        EventEngine([{"event_id": "a"}])
    with pytest.raises(TypeError, match="MarketEvent"):
        EventEngine().inject("breaking news", current_tick=0)


def test_injected_event_joins_the_timeline_and_applies_from_its_start():
    engine = EventEngine([_event("scheduled", start_tick=2, duration=2)])
    injected = _event("late", sentiment=-0.5, start_tick=11, duration=2, decay_ticks=0)
    engine.inject(injected, current_tick=10)
    assert [e.event_id for e in engine.events] == ["scheduled", "late"]
    assert engine.state(10) == EventState(tick=10)  # "scheduled" expired at tick 6; "late" not started
    assert engine.state(11).events == (EventStatus("late", "custom", EventPhase.ACTIVE, 1.0),)
    assert engine.state(11).sentiment == -0.5


@pytest.mark.parametrize("start_tick", [1, 9, 10])
def test_injection_cannot_backdate_an_event(start_tick):
    engine = EventEngine()
    with pytest.raises(ValueError, match="can't be backdated"):
        engine.inject(_event(start_tick=start_tick), current_tick=10)
    assert engine.events == ()


@pytest.mark.parametrize("current_tick", [-1, 1.5, None, True])
def test_injection_requires_a_valid_current_tick(current_tick):
    with pytest.raises(ValueError, match="current_tick"):
        EventEngine().inject(_event(start_tick=50), current_tick=current_tick)


def test_injection_never_changes_states_already_produced():
    engine = EventEngine(_mixed_timeline())
    history = _states(engine, range(0, 13))
    engine.inject(_event("breaking", sentiment=-1.0, volatility_boost=3.0, start_tick=13, duration=5), current_tick=12)
    assert _states(engine, range(0, 13)) == history
    assert "breaking" in [s.event_id for s in engine.state(13).events]


# --- architecture ------------------------------------------------------------------------


def test_event_package_depends_only_on_itself_and_the_standard_library():
    package_dir = Path(events_package.__file__).parent
    imported = set()
    for module in package_dir.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
    project = {name for name in imported if name.split(".")[0] == "crypto_simulator"}
    assert project and all(name.startswith("crypto_simulator.core.events") for name in project)
    assert not {name.split(".")[0] for name in imported} - {
        "crypto_simulator", "__future__", "dataclasses", "enum", "math", "random", "types", "typing",
    }
