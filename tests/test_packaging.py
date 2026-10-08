"""The packaging configuration covers the package as it is on disk (Phase 23).

An editable install maps ``crypto_simulator`` straight onto the source
tree, so a packaging gap — a subpackage or data file left out of the
wheel — cannot show up anywhere else in this suite. These tests read
``pyproject.toml`` and check it against the repository itself: every
package directory is matched by package discovery, every non-Python file
the package ships is declared as package data, and the declared runtime
dependencies are the ones in ``requirements.txt``.

They build nothing and install nothing, so they stay fast and offline. A
real build-and-install check (wheel into a fresh environment, imports,
a seeded run) is the stronger proof; it needs network access for the
build backend and dependencies, so it belongs in a release or CI check
rather than in every ``pytest`` run.
"""

from __future__ import annotations

import tomllib
from fnmatch import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "crypto_simulator"
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
SETUPTOOLS = PYPROJECT["tool"]["setuptools"]


def _package_dirs() -> list[Path]:
    return sorted(path.parent for path in PACKAGE.rglob("__init__.py") if "__pycache__" not in path.parts)


def _dotted(directory: Path) -> str:
    return ".".join(directory.relative_to(REPO).parts)


def _discovered(name: str) -> bool:
    return any(fnmatch(name, pattern) for pattern in SETUPTOOLS["packages"]["find"]["include"])


def test_a_standard_build_backend_is_declared():
    build = PYPROJECT["build-system"]
    assert build["build-backend"] == "setuptools.build_meta"
    assert any(requirement.startswith("setuptools") for requirement in build["requires"])


def test_package_discovery_includes_every_package_directory():
    packages = [_dotted(directory) for directory in _package_dirs()]
    assert "crypto_simulator" in packages and len(packages) > 1
    missing = [name for name in packages if not _discovered(name)]
    assert missing == [], f"packages left out of the distribution: {missing}"


def test_repository_level_directories_are_not_packaged():
    for name in ("tests", "tests.examples", "examples", "docs", "scripts", "scripts.compat"):
        assert not _discovered(name), name


def test_every_non_python_file_in_the_package_is_declared_package_data():
    package_data = SETUPTOOLS["package-data"]
    shipped = [
        path for path in PACKAGE.rglob("*")
        if path.is_file() and path.suffix not in {".py", ".pyc"} and "__pycache__" not in path.parts
    ]
    assert {path.name for path in shipped} >= {"default.yaml", "schema.sql"}
    for path in shipped:
        patterns = package_data.get(_dotted(path.parent), [])
        assert any(fnmatch(path.name, pattern) for pattern in patterns), f"{path} is not declared package data"


def test_runtime_dependencies_match_requirements_txt():
    lines = (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
    required = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    assert PYPROJECT["project"]["dependencies"] == required


def test_test_tooling_is_not_a_runtime_dependency():
    dependencies = " ".join(PYPROJECT["project"]["dependencies"]).lower()
    assert "pytest" not in dependencies
