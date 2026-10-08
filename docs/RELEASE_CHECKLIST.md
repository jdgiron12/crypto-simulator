# Release checklist

Steps to verify and publish a release of `crypto-simulator`. Work through
them in order on a clean checkout of `main`. Commands run from the
repository root with the development environment active
(`pip install -r requirements-dev.txt && pip install -e .`).

This is a checklist, not a script: nothing here runs automatically, and
publishing steps are taken only after everything above them passes.

## Version

- [ ] `version` in `pyproject.toml` and `__version__` in
      `crypto_simulator/__init__.py` agree (`pytest tests/test_release.py`
      checks this, along with the changelog and README).
- [ ] `CHANGELOG.md` has an entry for the version, with the release date,
      compatibility notes and known limitations.
- [ ] The README's version line names the version.

## Packaging

Build and install from a copy of the tracked files outside the repository,
because setuptools writes `build/` and `*.egg-info` next to the source:

```bash
SCRATCH=$(mktemp -d)
mkdir "$SCRATCH/src"
git ls-files -z | xargs -0 tar -cf - | tar -xf - -C "$SCRATCH/src"
python -m venv "$SCRATCH/build-env" && "$SCRATCH/build-env/bin/pip" install build
(cd "$SCRATCH/src" && "$SCRATCH/build-env/bin/python" -m build --outdir "$SCRATCH/dist" .)
python -m venv "$SCRATCH/install-env" && "$SCRATCH/install-env/bin/pip" install "$SCRATCH"/dist/*.whl
"$SCRATCH/install-env/bin/pip" check
```

- [ ] The wheel and the sdist both build.
- [ ] The wheel contains every `crypto_simulator` package plus
      `config/default.yaml` and `data/schema.sql`.
- [ ] A fresh, non-editable install of the wheel succeeds and installs the
      runtime dependencies.
- [ ] `pip check` reports no broken requirements.
- [ ] `importlib.metadata.version("crypto-simulator")` in the installed
      environment reports the release version.

## Testing

- [ ] `pytest` passes.
- [ ] `pytest -m slow` passes.
- [ ] `python scripts/compat/compare_checkpoints.py` reports `IDENTICAL`
      for every checkpoint (needs full git history).
- [ ] Deterministic smoke test: `run_simulation(SimulationParams(ticks=50,
      random_seed=48291))` gives run id `7e806a4d73f2889e` (close price
      about 1.2854888).
- [ ] Installed-wheel smoke test: from outside the repository, with
      `python -I` and no `PYTHONPATH`, the documented imports resolve to
      `site-packages`, the same seeded run gives the same run id, and
      `examples/basic_simulation.py` runs against the installed package.
- [ ] CI on `main` is green on GitHub Actions (macOS; Python 3.12 and 3.13).

## Documentation

- [ ] `README.md`: version, installation, quickstart, Python API section.
- [ ] `docs/ARCHITECTURE.md`, `docs/REPRODUCIBILITY.md`, `docs/CLI.md`,
      `docs/DASHBOARD.md` still describe the code as it is.
- [ ] The public Python API in the README matches the code
      (`pytest tests/test_public_api.py`).
- [ ] The three `examples/` scripts run (`pytest tests/examples`).
- [ ] All internal Markdown links resolve.
- [ ] Nothing claims a license, real-market accuracy, exchange
      connectivity or cross-platform bit-for-bit reproduction.

## Repository

- [ ] `git status` is clean, and `main` equals `origin/main`.
- [ ] No build artifacts (`build/`, `dist/`, wheels, sdists) and no
      generated databases are tracked.
- [ ] No secrets or local configuration (`.env`) are tracked.

## Release

Only after every item above passes:

- [ ] Create an annotated tag, e.g. `git tag -a v1.0.0 -m "Version 1.0.0"`,
      and push it (`git push origin v1.0.0`).
- [ ] Create a GitHub release from the tag, with the changelog entry as
      its notes.
- [ ] Attach the built wheel and sdist to the release, if desired.
- [ ] Verify installation from the published artifacts in a fresh
      environment.
- [ ] Announce the release, if desired.
