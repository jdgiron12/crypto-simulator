"""Compare git checkpoints against the pinned compatibility digests.

Developer tool only (Phase 9, Step 0) — not part of the package, not run
by pytest. For each ref it extracts ``crypto_simulator/`` and ``scripts/``
with ``git archive`` into a temporary directory and, in a fresh
subprocess with that copy first on ``sys.path``, runs the digest grid in
``tests/compat/grid.py`` at the ref's level. The results must equal
``tests/compat/pinned_digests.json``.

    python scripts/compat/compare_checkpoints.py                  # every Phase 8 checkpoint
    python scripts/compat/compare_checkpoints.py --ref HEAD       # one ref (level 8 unless --level)
    python scripts/compat/compare_checkpoints.py --ref 7557aa0 --level 5
    python scripts/compat/compare_checkpoints.py --write-pins     # re-pin from the reference commit

``--write-pins`` is a deliberate act: it recomputes the pins from the
reference commit in ``grid.REFERENCE`` (or ``--ref``) and overwrites the
file. Only do it when the grid itself changes, never to make a failing
comparison pass.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GRID = REPO / "tests" / "compat" / "grid.py"
PINS = REPO / "tests" / "compat" / "pinned_digests.json"

RUNNER = """
import importlib.util, json, sys
from pathlib import Path
root, grid_path, level = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location("compat_grid", grid_path)
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)
result = grid.compute(level, script=root / "scripts" / "simulate_coin.py")
assert Path(result["package"]).resolve().is_relative_to(root.resolve()), result["package"]
print(json.dumps(result, sort_keys=True))
"""


def _load_grid():
    import importlib.util

    spec = importlib.util.spec_from_file_location("compat_grid", GRID)
    grid = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grid)
    return grid


def run_ref(ref: str, level: int) -> dict:
    """The grid's digests for ``ref``, computed from an archived copy."""
    archive = subprocess.run(["git", "archive", "--format=tar", ref, "crypto_simulator", "scripts"],
                             cwd=REPO, check=True, capture_output=True).stdout
    with tempfile.TemporaryDirectory(prefix="compat-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        env = {k: v for k, v in os.environ.items() if not k.startswith("CRYPTOSIM_") and k != "PYTHONPATH"}
        proc = subprocess.run([sys.executable, "-c", RUNNER, tmp, str(GRID), str(level)],
                              cwd=tmp, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"grid failed for {ref}:\n{proc.stderr}")
        return json.loads(proc.stdout)


def compare(ref: str, level: int, pins: dict, grid) -> list[str]:
    """Differences between ``ref`` at ``level`` and the pins (empty if none)."""
    result = run_ref(ref, level)
    problems = []
    for lv in range(level + 1):
        problems += _diff(f"level {lv}", result["levels"][str(lv)], pins["levels"][str(lv)], exact=True)
    problems += _diff("common", result["common"], pins["common"], exact=False)
    problems += _diff("cli", result["cli"], pins["cli"], exact=False)
    for mode, value in result["fingerprints"].items():
        if value != grid.FINGERPRINTS[mode] or value != pins["fingerprints"][mode]:
            problems.append(f"fingerprint {mode}: {value} (expected {grid.FINGERPRINTS[mode]})")
    return problems


def _diff(label: str, got: dict, pinned: dict, *, exact: bool) -> list[str]:
    problems = [f"{label} {k}: {v} != pinned {pinned.get(k)}" for k, v in got.items() if pinned.get(k) != v]
    if exact and set(got) != set(pinned):
        problems.append(f"{label}: case set differs from the pins")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", action="append", help="git ref to check (repeatable); default: every checkpoint")
    parser.add_argument("--level", type=int, help="level to run the ref(s) at; default: the checkpoint's own")
    parser.add_argument("--write-pins", action="store_true", help="recompute and overwrite the pinned digests")
    args = parser.parse_args()
    grid = _load_grid()
    by_ref = {ref: level for level, (ref, _) in grid.LEVELS.items()}

    if args.write_pins:
        ref = (args.ref or [grid.REFERENCE])[0]
        result = run_ref(ref, max(grid.LEVELS))
        pins = {"reference": grid.REFERENCE, "levels": result["levels"], "common": result["common"],
                "fingerprints": result["fingerprints"], "cli": result["cli"]}
        PINS.write_text(json.dumps(pins, indent=1, sort_keys=True) + "\n")
        print(f"pinned {sum(len(v) for v in pins['levels'].values())} level cases, {len(pins['common'])} common "
              f"cases and {len(pins['cli'])} CLI runs from {ref}")
        return 0

    pins = json.loads(PINS.read_text())
    targets = [(ref, args.level if args.level is not None else by_ref.get(ref, max(grid.LEVELS)))
               for ref in (args.ref or [ref for ref, _ in grid.LEVELS.values()])]
    failed = False
    for ref, level in targets:
        problems = compare(ref, level, pins, grid)
        status = "IDENTICAL" if not problems else f"{len(problems)} DIFFERENCE(S)"
        print(f"{ref:<10} level {level}: {status}")
        for problem in problems[:20]:
            print(f"    {problem}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
