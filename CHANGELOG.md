# Changelog

All notable changes to this project are recorded here. The phase-by-phase
design record is in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## [Unreleased]

### Changed

- **App navigation** (Phase 24, Step 3). The app now opens on the coin
  simulator (**Simulate**) and uses Streamlit's native page navigation.
  The dormant multi-asset experiment moved to its own page under
  **Legacy → Multi-asset sandbox**, with a note on what it is. The Trade,
  Portfolio and History placeholders ("coming soon") are no longer shown;
  their underlying code is unchanged. Run, batch and comparison controls
  keep their values when you visit another page
  (`dashboard.view.retain_control_state`). The disclaimer now appears on
  every page under the title. No simulation output, widget key, control
  default or public API changed.

- **Dashboard theme** (Phase 24, Step 2). One dark theme for the whole
  dashboard: `.streamlit/config.toml` sets the page colors and hides
  Streamlit's developer menu and Deploy button, and the new
  `crypto_simulator/visualization/style.py` holds the design tokens and the
  one Plotly template every chart builder applies. Charts are rendered
  with Streamlit's own chart theme turned off so the template is what you
  see. Styling only: no simulation output, trace value, widget, layout or
  public API changed.

## [1.0.0] - 2026-10-08

The first versioned release of the coin-economy simulator: a fictional,
synthetic market for learning and experimentation. It does not connect to
any exchange, place real trades or move real money, and nothing it
produces is a forecast or financial advice.

### Added

- **Coin-economy simulation.** One fictional coin traded by rule-based
  traders (retail, momentum, dip buyer, panic seller, long-term holder) and
  whales, with conserved coins and cash, run tick by tick by
  `CoinSimulator` from one base seed.
- **Pricing modes.** A seeded random walk, or a constant-product AMM pool
  with fees, slippage and exact `Decimal` accounting.
- **Manipulation scenarios.** Pump-and-dump and wash-trading presets,
  played by ordinary wallet-holding participants.
- **News events.** Scheduled and random events that shift sentiment,
  participation and random-walk volatility, without setting prices.
- **Participant psychology** (opt-in), with the momentum term calibrated in
  Phase 18.
- **Market-condition presets** (`bull`, `bear`, `meme`) that reconfigure
  the news mix and, in random-walk mode, sentiment drift.
- **Analytics and report.** Descriptive market, trader, whale, event,
  psychology, manipulation and regime analytics in one `SimulationReport`.
- **Persistence.** Finished runs can be saved to SQLite (Python API).
- **Scenario save/load.** Whole run configurations saved and rerun by name
  from the CLI.
- **Batch simulation and aggregate statistics.** Many runs from one base
  seed, with per-metric distributions (mean, median, sample standard
  deviation, percentiles).
- **Stress testing.** A harness of demanding and deliberately invalid
  configurations (`scripts/stress_test.py`).
- **Streamlit dashboard.** Single-run report views, tick-level views
  (synthetic OHLC, volume composition, AMM pool state, event state), batch
  views, cross-run price-path bands and a scenario-comparison panel.
- **Command-line interface** (`scripts/simulate_coin.py`) for single runs,
  reports, saved scenarios and batches.
- **Continuous integration** on GitHub Actions (macOS; Python 3.12 and
  3.13): the test suite, slow tests, the checkpoint comparison and a
  coverage report.
- **Documentation.** Architecture, reproducibility, CLI and dashboard
  guides in `docs/`, a documented public Python API in the README, and
  three executable examples in `examples/`.
- **Installable package** with declared runtime dependencies and project
  metadata.

### Changed

- The package installs as a normal, non-editable distribution
  (`pip install .`); editable installs remain available for development.
- Runtime dependencies are declared in `pyproject.toml`. The unused
  `python-dotenv` dependency was removed (`.env` files were never loaded).
- The CLI's `--psychology` help no longer calls psychology "uncalibrated",
  and `--help` keeps its usage examples on separate lines.
- Documentation was consolidated into the README and the guides in
  `docs/`.

### Fixed

- Built distributions previously contained only the top-level package:
  every subpackage, `config/default.yaml`, `data/schema.sql` and the
  dependency metadata were missing, so a non-editable install could not
  be imported. All are now included.
- `--ticks` values below 1 are now a clean argument error (exit 2) instead
  of a Python traceback.
- Documentation inconsistencies found during the Phase 22 audit.

### Compatibility

- The historical compatibility checks are unchanged: all nine checkpoint
  levels still compare `IDENTICAL`, and the random-walk and AMM builder
  fingerprints are as pinned. The Phase 18 psychology calibration is
  recorded as a calibration boundary rather than by re-pinning.
- Bit-for-bit reproduction is verified on macOS with Python 3.12 and 3.13.
  Other platforms and Python versions are not guaranteed to reproduce the
  same runs from the same seed. See
  [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

### Known limitations

- A synthetic, educational model. It does not reproduce real markets and
  has not been validated against them.
- No exchange connectivity and no real trading of any kind.
- Compatibility fingerprints are verified only on the documented macOS /
  Python environment.
- The CLI's run header and psychology-observations heading still say
  "calibration deferred". The wording predates the Phase 18 calibration and
  is kept because that output is part of the pinned CLI compatibility
  digests.
- The dashboard has documented limits (no single-run market-condition
  control, no scenario save/load, no run saving); see
  [`docs/DASHBOARD.md`](docs/DASHBOARD.md).
- The Phase 19 crowd/breadth channels are experimental, off by default and
  Python API only; herding was not established.
- No license has been granted for this repository. Its public visibility
  does not make it open source.
