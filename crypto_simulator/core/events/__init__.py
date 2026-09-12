"""Fictional news/external events for the coin economy simulation.

Pure data and arithmetic: this package depends on nothing else in the
simulator. ``MarketEvent`` (one event and its lifecycle), the generic
category catalog, and ``EventEngine`` (the timeline and its combined
per-tick ``EventState``).
"""

from crypto_simulator.core.events.catalog import (
    EVENT_CATEGORIES,
    EventProfile,
    EventTone,
    create_event,
)
from crypto_simulator.core.events.engine import EventEngine, EventState, EventStatus
from crypto_simulator.core.events.event import EventPhase, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator, validate_random_event_parameters

__all__ = [
    "EVENT_CATEGORIES",
    "EventEngine",
    "EventPhase",
    "EventProfile",
    "EventState",
    "EventStatus",
    "EventTone",
    "MarketEvent",
    "RandomEventGenerator",
    "create_event",
    "validate_random_event_parameters",
]
