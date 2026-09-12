"""Participant psychology for the coin economy simulation.

Pure and standalone: nothing here depends on the rest of the simulator.
``CoinSimulator`` (when built with ``psychology=True``) computes a
``PsychologyState`` each tick and traders read it from ``MarketContext``.
"""

from crypto_simulator.core.psychology.signals import (
    SIGNAL_WINDOW,
    MarketSignals,
    aggregate_event_severity,
    compute_psychology,
    signals_from_closes,
)
from crypto_simulator.core.psychology.state import PsychologyState

__all__ = [
    "SIGNAL_WINDOW",
    "MarketSignals",
    "PsychologyState",
    "aggregate_event_severity",
    "compute_psychology",
    "signals_from_closes",
]
