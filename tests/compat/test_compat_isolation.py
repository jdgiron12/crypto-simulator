"""The compatibility tooling stays outside the product (Phase 9, Step 0).

The package must never import test or developer tooling, and the tooling
must stay self-contained: the grid may import only the standard library,
PyYAML and the package under test (so it can run against an archived
checkpoint), and the comparison script only the standard library.
"""

import ast
import sys
from pathlib import Path

import crypto_simulator

REPO = Path(crypto_simulator.__file__).resolve().parents[1]
GRID = REPO / "tests" / "compat" / "grid.py"
TOOL = REPO / "scripts" / "compat" / "compare_checkpoints.py"


def _imports(path):
    tree = ast.parse(path.read_text())
    found = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    found |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    return found


def test_the_package_never_imports_tests_or_scripts():
    package = Path(crypto_simulator.__file__).parent
    for module in package.rglob("*.py"):
        imported = _imports(module)
        assert not any(m == top or m.startswith(top + ".") for m in imported for top in ("tests", "scripts")), module


def test_the_grid_imports_only_the_stdlib_yaml_and_the_package():
    for module in _imports(GRID):
        top = module.split(".")[0]
        assert top in sys.stdlib_module_names or top in {"yaml", "crypto_simulator"}, module


def test_the_comparison_tool_imports_only_the_stdlib():
    for module in _imports(TOOL):
        assert module.split(".")[0] in sys.stdlib_module_names, module
