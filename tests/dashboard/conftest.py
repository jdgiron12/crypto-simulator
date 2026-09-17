"""Shared runs for the dashboard tests.

Module-scoped because a dashboard run is deterministic: the same
parameters always produce the same payload, so one run per module is the
same object every test would have built for itself.
"""

from __future__ import annotations

import pytest

from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation

#: A small run with every optional feature on, so the payload exercises
#: events, psychology, whale observation and the trader population.
FULL_PARAMS = SimulationParams(
    ticks=20, events=True, random_events=True, psychology=True, whale_observation=True
)


@pytest.fixture(scope="module")
def payload():
    return run_simulation(FULL_PARAMS)


@pytest.fixture(scope="module")
def payload_dict(payload):
    return payload_to_dict(payload)
