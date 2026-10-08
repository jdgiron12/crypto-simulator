"""The release version is stated once and agreed on everywhere (Phase 23).

The version is written by hand in two places — ``pyproject.toml`` (the
package metadata) and ``crypto_simulator.__version__`` — and announced in
the changelog and the README. These checks are static: they read the files
rather than build or install anything, so they cost nothing in an ordinary
``pytest`` run. The installed wheel's metadata is checked as part of the
release checklist (``docs/RELEASE_CHECKLIST.md``).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import crypto_simulator

REPO = Path(__file__).resolve().parents[1]
RELEASE = "1.0.0"


def _pyproject_version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_the_package_and_its_metadata_declare_the_release_version():
    assert crypto_simulator.__version__ == RELEASE
    assert _pyproject_version() == RELEASE


def test_the_newest_changelog_entry_is_the_package_version():
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
    assert entries, "CHANGELOG.md has no dated version entry"
    assert entries[0] == crypto_simulator.__version__


def test_the_readme_names_the_package_version():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert f"**Version {crypto_simulator.__version__}**" in readme
