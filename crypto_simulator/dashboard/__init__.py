"""The dashboard layer: a read-only observer of a finished simulation.

    simulator -> analytics -> SimulationReport -> payload -> dashboard

``data`` runs one simulation and builds one ``SimulationReport`` and one
payload from it; ``serialization`` turns that payload into JSON-compatible
Python; ``view`` displays it in the existing Streamlit app. The report
stays the analytical source of truth — nothing in this package recomputes
an analytical figure, and nothing in ``core``, ``services`` or
``analytics`` imports it.

``view`` is imported on demand (it pulls in Streamlit) rather than here,
so the data contract can be used without a UI.
"""

from crypto_simulator.dashboard.data import (
    MAX_TICKS,
    PRICING_MODES,
    SCENARIOS,
    DashboardPayload,
    PricePoint,
    SimulationMeta,
    SimulationParams,
    payload_to_dict,
    run_simulation,
)
from crypto_simulator.dashboard.serialization import report_to_dict, to_jsonable

__all__ = [
    "MAX_TICKS",
    "PRICING_MODES",
    "SCENARIOS",
    "DashboardPayload",
    "PricePoint",
    "SimulationMeta",
    "SimulationParams",
    "payload_to_dict",
    "report_to_dict",
    "run_simulation",
    "to_jsonable",
]
