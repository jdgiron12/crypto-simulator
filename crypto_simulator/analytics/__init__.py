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
from crypto_simulator.analytics.psychology import (
    COMPONENTS,
    DEFAULT_PERSISTENCE_THRESHOLD,
    NEUTRAL,
    OCCUPANCY_THRESHOLDS,
    ComponentPeriodMeans,
    ComponentSummary,
    DominantGroup,
    EventPeriodComparison,
    Persistence,
    PsychologyReport,
    ThresholdOccupancy,
    TradingActivity,
    analyze_psychology,
)

__all__ = [
    "COMPONENTS",
    "DEFAULT_BASELINE_WINDOW",
    "DEFAULT_PERSISTENCE_THRESHOLD",
    "DEFAULT_POST_WINDOW",
    "MIN_VOLATILITY_RETURNS",
    "NEUTRAL",
    "OCCUPANCY_THRESHOLDS",
    "ComponentPeriodMeans",
    "ComponentSummary",
    "DominantGroup",
    "EventGroundTruth",
    "EventObservation",
    "EventPeriodComparison",
    "ObservedMarket",
    "ObservedPool",
    "ObservedTrading",
    "Persistence",
    "PsychologyReport",
    "ThresholdOccupancy",
    "TradingActivity",
    "analyze_events",
    "analyze_psychology",
]
