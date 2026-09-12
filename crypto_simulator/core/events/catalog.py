"""Generic, fictional event categories and their default effect profiles.

A profile gives an event's effects at severity 1; ``create_event`` scales
it by the event's severity. The numbers are illustrative defaults chosen
to be plausible relative to each other (a security incident is worse and
more volatile than a competitor announcement), not calibrated to any real
market. No category refers to a real company, coin, exchange or regulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from crypto_simulator.core.events.event import MarketEvent


class EventTone(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"


@dataclass(frozen=True)
class EventProfile:
    """Default effects of a category at severity 1 (see ``MarketEvent``)."""

    tone: EventTone
    sentiment: float
    volatility_boost: float
    attention: float
    description: str


_P, _N, _M = EventTone.POSITIVE, EventTone.NEGATIVE, EventTone.MIXED

EVENT_CATEGORIES: Mapping[str, EventProfile] = MappingProxyType({
    # Positive
    "partnership_announcement": EventProfile(_P, 0.6, 0.2, 0.5, "A major partnership is announced"),
    "product_launch": EventProfile(_P, 0.5, 0.3, 0.6, "A product launches successfully"),
    "exchange_listing": EventProfile(_P, 0.7, 0.4, 1.0, "The coin is listed on a large venue"),
    "adoption_growth": EventProfile(_P, 0.5, 0.1, 0.4, "Adoption grows faster than expected"),
    "positive_regulation": EventProfile(_P, 0.6, 0.3, 0.5, "A favorable regulatory development"),
    # Negative
    "security_incident": EventProfile(_N, -0.9, 1.0, 1.0, "A security incident is disclosed"),
    "product_failure": EventProfile(_N, -0.6, 0.5, 0.6, "A product fails publicly"),
    "regulatory_restriction": EventProfile(_N, -0.8, 0.8, 0.8, "A restrictive regulatory development"),
    "competitor_announcement": EventProfile(_N, -0.4, 0.3, 0.4, "A major competitor announces a rival"),
    "supply_concern": EventProfile(_N, -0.5, 0.6, 0.5, "Unexpected concern about coin supply"),
    # Mixed / neutral: little direction, mostly uncertainty
    "leadership_change": EventProfile(_M, -0.1, 0.4, 0.4, "Leadership changes unexpectedly"),
    "ambiguous_announcement": EventProfile(_M, 0.0, 0.5, 0.6, "An announcement open to interpretation"),
    "delayed_launch": EventProfile(_M, -0.2, 0.3, 0.3, "A planned launch is delayed"),
    "market_uncertainty": EventProfile(_M, 0.0, 0.8, 0.2, "General uncertainty grips the market"),
})


def create_event(
    category: str,
    *,
    event_id: str,
    severity: float,
    start_tick: int,
    duration: int,
    decay_ticks: int = 0,
    headline: str = "",
    sentiment: float | None = None,
    volatility_boost: float | None = None,
    attention: float | None = None,
) -> MarketEvent:
    """Build a ``MarketEvent`` from a catalog category.

    Each effect is the category's profile value × ``severity`` unless
    overridden; overrides are final values (not scaled by severity) and
    are validated like any other. ``headline`` defaults to the category's
    description.
    """
    try:
        profile = EVENT_CATEGORIES[category]
    except (KeyError, TypeError):
        raise ValueError(
            f"Unknown event category {category!r}; expected one of {sorted(EVENT_CATEGORIES)}"
        ) from None
    if isinstance(severity, bool) or not isinstance(severity, (int, float)):
        raise ValueError(f"severity must be a finite number (got {severity!r})")
    return MarketEvent(
        event_id=event_id,
        category=category,
        severity=severity,
        sentiment=profile.sentiment * severity if sentiment is None else sentiment,
        volatility_boost=(
            profile.volatility_boost * severity if volatility_boost is None else volatility_boost
        ),
        attention=profile.attention * severity if attention is None else attention,
        start_tick=start_tick,
        duration=duration,
        decay_ticks=decay_ticks,
        headline=headline or profile.description,
    )
