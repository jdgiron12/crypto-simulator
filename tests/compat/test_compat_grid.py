"""The working tree against the pinned compatibility digests (Phase 9, Step 0).

The pins were computed from the reference commit and verified identical
against every Phase 8 checkpoint with ``scripts/compat/compare_checkpoints.py``
(each checkpoint reproduces every level up to its own). Matching them here
means the working tree still runs every historical feature combination —
and the CLI — exactly as those checkpoints did.
"""

import json
import random
from pathlib import Path

import pytest

import crypto_simulator.core.coin_simulator as simulator_module
import crypto_simulator.core.volume_model as volume_module
from crypto_simulator.config import get_settings
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.compat import grid
from tests.core.test_coin_simulator_psychology import BUILDER_FINGERPRINTS, _builder_fingerprint

PINS = json.loads((Path(__file__).parent / "pinned_digests.json").read_text())
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


def test_the_pins_belong_to_the_reference_commit_and_are_complete():
    assert PINS["reference"] == grid.REFERENCE == "b5a5f87f6b383ebd0a28ddbd8d5851a5155f4716"
    assert set(PINS["levels"]) == {str(level) for level in grid.LEVELS}
    assert all(len(cases) == grid.QUICK_CASES for cases in PINS["levels"].values())
    level_digests = [d for cases in PINS["levels"].values() for d in cases.values()]
    assert len(set(level_digests)) == len(level_digests)  # every case is a genuinely different run
    assert not any(str(d).startswith("ERR") for d in level_digests + list(PINS["common"].values()))
    assert set(PINS["cli"]) == {" ".join(flags) for flags, _ in grid.CLI_RUNS}


@pytest.mark.parametrize("level", sorted(grid.LEVELS))
def test_every_level_matches_its_pinned_digests(level):
    assert grid.level_group(level) == PINS["levels"][str(level)]


def test_builder_and_amm_runs_match_their_pinned_digests():
    assert grid.common_group(max(grid.LEVELS)) == PINS["common"]


def test_both_fingerprints_are_unchanged_and_computed_the_established_way():
    assert grid.fingerprints() == PINS["fingerprints"] == grid.FINGERPRINTS == BUILDER_FINGERPRINTS
    assert grid.FINGERPRINTS == {"random_walk": "d1218e0e0739f776", "amm": "f853009b5818169e"}
    for mode in ("random_walk", "amm"):
        make = lambda: build_coin_simulator(get_settings(), pricing_mode=mode,  # noqa: E731
                                            include_whales=mode == "random_walk")
        assert grid.builder_fingerprint(make()) == _builder_fingerprint(make())


def test_the_cli_output_matches_its_pinned_digests():
    assert grid.cli_digests(SCRIPT, max(grid.LEVELS)) == PINS["cli"]


def test_the_grid_is_deterministic_and_draws_no_global_randomness():
    state = random.getstate()
    first = grid.level_group(8)
    assert grid.level_group(8) == first
    assert random.getstate() == state


def test_the_top_level_really_exercises_cohorts_and_observation(monkeypatch):
    seen = []
    original = simulator_module.CoinSimulator.__init__

    def recording(self, *args, **kwargs):
        seen.append(kwargs)
        original(self, *args, **kwargs)

    monkeypatch.setattr(simulator_module.CoinSimulator, "__init__", recording)
    grid.level_group(8)
    assert any(kw.get("whale_cohorts") for kw in seen)
    assert any(kw.get("whale_observation") for kw in seen)
    assert any(kw.get("psychology") for kw in seen) and any(kw.get("event_generator") for kw in seen)


def test_the_grid_notices_a_changed_simulation(monkeypatch):
    """The harness has teeth: nudging the synthetic volume by one part in a
    billion changes every digest."""
    original = volume_module.VolumeModel.next_volume
    monkeypatch.setattr(volume_module.VolumeModel, "next_volume", lambda self: original(self) * (1 + 1e-9))
    changed = grid.level_group(0)
    assert all(changed[name] != pinned for name, pinned in PINS["levels"]["0"].items())


# --- calibration boundaries (Phase 18) ---------------------------------------------------------------------


def test_the_pins_record_superseded_digests_for_every_known_calibration():
    """A deliberate behaviour change moves the digests of the runs it
    affects. The new values are pinned; the old ones are recorded, so a
    checkpoint that predates the change is still compared — against what
    its own source should produce."""
    assert set(PINS["calibrations"]) == set(grid.CALIBRATIONS)
    for name, record in PINS["calibrations"].items():
        assert record["summary"] and record["affects"], name
        superseded = record["superseded"]
        assert superseded["levels"] or superseded["common"] or superseded["cli"], name


def test_the_current_source_implements_every_recorded_calibration():
    assert grid.calibrations() == list(grid.CALIBRATIONS)


def test_a_superseded_digest_differs_from_the_pin_it_replaced():
    """If these ever matched, the calibration would not have changed that
    run and the record would be noise."""
    superseded = PINS["calibrations"]["psychology-momentum-horizon"]["superseded"]
    for level, cases in superseded["levels"].items():
        for case, digest in cases.items():
            assert digest != PINS["levels"][level][case], f"level {level} {case}"
    for group in ("common", "cli"):
        for case, digest in superseded[group].items():
            assert digest != PINS[group][case], f"{group} {case}"


def test_only_psychology_runs_were_superseded_by_this_calibration():
    """The calibration touches psychology and nothing else, so no
    psychology-free case may appear among the superseded digests."""
    superseded = PINS["calibrations"]["psychology-momentum-horizon"]["superseded"]
    assert all("psychology" in case for case in superseded["cli"])
    assert not any(case.endswith("p0") for case in superseded["common"])


def test_the_number_of_superseded_digests_is_recorded_exactly():
    """66 digests moved: 51 across the nine levels, 11 common, 4 CLI."""
    superseded = PINS["calibrations"]["psychology-momentum-horizon"]["superseded"]
    levels = sum(len(cases) for cases in superseded["levels"].values())
    assert (levels, len(superseded["common"]), len(superseded["cli"])) == (51, 11, 4)


def test_fingerprints_were_not_superseded():
    """The builder fingerprints are psychology-free, so the calibration
    must not have touched them."""
    assert PINS["fingerprints"] == grid.FINGERPRINTS
    assert "fingerprints" not in PINS["calibrations"]["psychology-momentum-horizon"]["superseded"]
