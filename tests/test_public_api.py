"""The supported Python import surface (Phase 23).

The README's "Python API" section names the import paths a user of the
package is meant to rely on. These tests keep that promise checkable:
every documented name is importable from its documented path, the
aliases are the same objects (one implementation, several doors), and
the headless entry points stay free of the UI libraries.

They check where names live, not what they compute: simulation results
are covered by the rest of the suite and by the compatibility pins.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The supported surface, exactly as the README documents it.
SUPPORTED: dict[str, tuple[str, ...]] = {
    "crypto_simulator": ("__version__",),
    "crypto_simulator.dashboard.data": ("SimulationParams", "run_simulation", "payload_to_dict", "DashboardPayload"),
    "crypto_simulator.dashboard": ("SimulationParams", "run_simulation", "payload_to_dict", "DashboardPayload"),
    "crypto_simulator.services.batch": ("run_batch", "batch_seed", "BatchResult"),
    "crypto_simulator.analytics": ("aggregate_batch", "build_report", "render_report", "analyze_market"),
    "crypto_simulator.services": ("build_coin_simulator",),
    "crypto_simulator.services.scenarios": ("ScenarioService", "ScenarioNotFound"),
    "crypto_simulator.services.market_conditions": ("MARKET_CONDITIONS", "apply_market_condition"),
    "crypto_simulator.data": ("CoinRunRepository", "connect", "init_db", "get_connection"),
    "crypto_simulator.config": ("get_settings",),
}


@pytest.mark.parametrize("path", sorted(SUPPORTED))
def test_every_documented_name_imports_from_its_documented_path(path):
    module = importlib.import_module(path)
    missing = [name for name in SUPPORTED[path] if not hasattr(module, name)]
    assert missing == [], f"{path} lacks {missing}"


def test_the_readme_documents_each_supported_path():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Python API", 1)[1].split("\n## ", 1)[0]
    for path in SUPPORTED:
        assert f"`{path}`" in section, path


def test_aliases_are_the_same_objects_as_their_implementations():
    from crypto_simulator import analytics, dashboard, services
    from crypto_simulator.analytics.aggregate import aggregate_batch
    from crypto_simulator.analytics.report import build_report
    from crypto_simulator.dashboard import data
    from crypto_simulator.services.coin_simulation import build_coin_simulator
    from crypto_simulator.services.simulation_params import SimulationParams

    for name in ("SimulationParams", "run_simulation", "payload_to_dict", "DashboardPayload"):
        assert getattr(dashboard, name) is getattr(data, name), name
    assert data.SimulationParams is SimulationParams
    assert services.build_coin_simulator is build_coin_simulator
    assert analytics.aggregate_batch is aggregate_batch
    assert analytics.build_report is build_report


def test_the_package_version_matches_the_project_metadata():
    import crypto_simulator

    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert crypto_simulator.__version__ == project["version"]


@pytest.mark.parametrize(
    "path", ["crypto_simulator", "crypto_simulator.dashboard", "crypto_simulator.dashboard.data",
             "crypto_simulator.services.batch", "crypto_simulator.analytics"],
)
def test_the_headless_entry_points_import_no_ui_library(path):
    """Checked in a fresh interpreter: this test process already has the
    dashboard's Streamlit and Plotly imports loaded from other tests."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("CRYPTOSIM_")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO), env.get("PYTHONPATH"))))
    probe = f"import sys, {path}; print(sorted(m for m in ('streamlit', 'plotly') if m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
