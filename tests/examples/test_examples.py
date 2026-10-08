"""The executable examples run, and say what they are about (Phase 22).

Each script in ``examples/`` runs in its own interpreter, as a reader
would run it. Only the exit status and a few stable output markers are
checked; the figures themselves are the simulator's, covered elsewhere,
so no price or statistic is asserted here.

The repository root is put on ``PYTHONPATH`` so the examples import the
package without an editable install (CI installs requirements only), and
``CRYPTOSIM_*`` overrides are removed so a developer's environment cannot
change what an example runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"


def _run(name: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("CRYPTOSIM_")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(REPO), env.get("PYTHONPATH"))))
    return subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    ("name", "markers"),
    [
        ("basic_simulation.py", ("Seed            : 48291", "Final price", "Repeated run matches: True")),
        ("scenario_comparison.py", ("Market-condition comparison", "neutral", "bull", "bear", "not a forecast")),
        ("batch_statistics.py", ("Base seed       : 48291", "Successful runs : 20 of 20", "Close price across runs")),
    ],
)
def test_each_example_runs_and_reports(name, markers):
    result = _run(name)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    for marker in markers:
        assert marker in result.stdout, f"{name}: {marker!r} missing from\n{result.stdout}"
