"""Post-processing over finished simulations. Reads simulation output;
never feeds back into it."""

from crypto_simulator.analytics.events import (
    DEFAULT_BASELINE_WINDOW,
    DEFAULT_POST_WINDOW,
    MIN_VOLATILITY_RETURNS,
    EventGroundTruth,
    EventObservation,
    ObservedMarket,
    ObservedPool,
    ObservedTrading,
    analyze_events,
)

__all__ = [
    "DEFAULT_BASELINE_WINDOW",
    "DEFAULT_POST_WINDOW",
    "MIN_VOLATILITY_RETURNS",
    "EventGroundTruth",
    "EventObservation",
    "ObservedMarket",
    "ObservedPool",
    "ObservedTrading",
    "analyze_events",
]
