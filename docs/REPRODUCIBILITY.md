# Reproducibility

How to reproduce a simulation exactly, how seeds behave, what determinism
does and does not guarantee, and how the compatibility checks work. For
command syntax see [`CLI.md`](CLI.md); for where these pieces sit in the
code see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## 1. Purpose

"Reproducible" means four different things here:

| Property | Question it answers | Checked by |
|---|---|---|
| **Repeatability** | Does the same configuration and seed give the same run again? | Running it twice; the seed tests in `tests/scripts/` and `tests/dashboard/` |
| **Compatibility** | Does today's code still produce what historical checkpoints produced? | The digest grid in `tests/compat/` and `scripts/compat/compare_checkpoints.py` |
| **Test reproducibility** | Does the test suite pass the same way on a clean checkout? | `pytest` locally and in CI |
| **Cross-platform agreement** | Does the same seed give the same run on another OS? | **Not guaranteed** — see [section 2](#2-supported-environment) |

Reproducibility is an engineering property of a synthetic program: the
same inputs give the same outputs. It says nothing about whether the
simulator resembles a real market. It does not.

## 2. Supported environment

| Requirement | Value | Source |
|---|---|---|
| Python | `>=3.12` | `requires-python` in `pyproject.toml` |
| Python versions tested in CI | 3.12 and 3.13 | `.github/workflows/ci.yml` |
| Authoritative platform for pinned digests | macOS (the pins were produced on macOS arm64) | comment in `ci.yml` |
| Dependencies | Bounded version ranges, not a lock file | `requirements.txt`, `requirements-dev.txt` |

**Why macOS is authoritative.** The random-walk path uses
`random.gauss` and `math.exp`. Their last-bit results can differ between
Apple's libm and glibc, and a multiplicative price walk amplifies that
difference over the ticks. The same seed can therefore give a different
run on Linux. The pinned digests were produced on macOS, so CI runs on
macOS. Linux agreement has not been established, and no cross-platform
fingerprint strategy exists yet.

**Why Python 3.11 is outside the supported range.** Python 3.12 changed
the built-in `sum()` over floats to use compensated summation. Under
3.11, the AMM fingerprint comes out differently from the pinned one,
while the random-walk fingerprint still matches. The project chose to
raise `requires-python` to 3.12 instead of changing the pins or the
numerics. This is a support and compatibility policy. It does not mean
the code cannot run on 3.11. It means a 3.11 run is not expected to
reproduce the pinned results, and installing the package with pip on
3.11 is refused by `requires-python`.

## 3. Seed entry points

A run has exactly **one base seed**. Every random stream in the run is
derived from it (see [section 6](#6-seed-derivation-and-batch-stride)).
These are the ways a base seed can be chosen:

| Entry point | Where it enters | What it sets |
|---|---|---|
| `crypto_simulator/config/default.yaml` | `simulation.random_seed: 42`, read by `get_settings()` | The configured seed used when nothing else names one |
| `CRYPTOSIM_RANDOM_SEED` | `_apply_env_overrides` in `config/settings.py`, applied when the YAML is loaded | Replaces `simulation.random_seed` in the loaded settings. The value is converted with `int()` |
| CLI `--seed N` | `scripts/simulate_coin.py`, which copies settings with `random_seed=N` | The seed for that one command |
| Saved scenario | `random_seed` stored in `coin_scenarios.params_json`. On load it fills `--seed` unless `--seed` is typed | The seed the scenario was saved with |
| `SimulationParams(random_seed=N)` (Python) | `dashboard/data.py` (`_with_seed_override`) | The same as `--seed`. `None` means "use the configured seed" |
| Dashboard seed control | `view.py` → `SimulationParams.random_seed` | The same as `--seed`. Off by default, which means the configured seed |
| Batch base seed | `services/batch.py` (`_effective_base_seed`) | The seed run 0 uses. Later runs are derived from it |
| Comparison base seed (dashboard) | `run_dashboard_comparison(base_seed=...)` | One base seed shared by every compared configuration |
| Stress cases | Fixed in `crypto_simulator/stress/cases.py` (mostly `48291`, plus `0` and `4294967295` at the bounds) | Not user-controlled |
| `build_coin_simulator(settings)` (Python) | `settings.simulation.random_seed` | Whatever the `Settings` object holds |

**Valid range.** `0` to `4294967295` (`MIN_SEED`/`MAX_SEED` in
`services/coin_simulation.py`). `--seed`, `SimulationParams`, saved
scenarios and batches enforce this range. `CRYPTOSIM_RANDOM_SEED` is not
range-checked on the way in. A plain single CLI run uses an
out-of-range environment seed (for example `-5`) without complaint. A
batch or `--save-scenario` refuses it, because both validate the seed
through `SimulationParams`. A non-integer value (for example `abc`) stops
the process with a `ValueError` traceback while the settings load.

**Settings are cached per process.** `get_settings()` reads the YAML and
the environment once (it uses `lru_cache`). Changing
`os.environ["CRYPTOSIM_RANDOM_SEED"]` inside a running Python process has
no effect until `clear_settings_cache()` is called.

## 4. Seed precedence

On the CLI, from strongest to weakest:

| Source | Applies to | Precedence | Notes |
|---|---|---|---|
| `--seed N` typed on the command line | Single run, batch base, saved scenario | **1 (wins)** | Printed in the header as `random seed : N (overrides config)` |
| Seed stored in a `--load-scenario` scenario | Single run, batch base | 2 | Applied only when `--seed` is not typed. A scenario always stores a seed |
| `CRYPTOSIM_RANDOM_SEED` | Anything that reads settings | 3 | Silently replaces the YAML value. No header line is printed for it |
| `simulation.random_seed` in `default.yaml` | Anything that reads settings | 4 | Currently `42` |

These cases were verified by running them:

- `CRYPTOSIM_RANDOM_SEED=7` plus `--seed 48291` produces output identical
  to `--seed 48291` alone. **`--seed` wins.**
- `CRYPTOSIM_RANDOM_SEED=48291` with no `--seed` gives the same run as
  `--seed 48291`. The only difference is that the header does not print
  a `random seed` line.
- `CRYPTOSIM_RANDOM_SEED=1` plus `--load-scenario NAME` runs the
  scenario's stored seed. **The scenario's seed beats the environment.**

In Python, an explicit `SimulationParams.random_seed` or `base_seed`
beats the settings, and the settings already include any environment
override.

## 5. Determinism scope

**Expected to be identical (on the same platform, Python and checkout):**

| Situation | Guarantee | Evidence |
|---|---|---|
| The same CLI command run twice | Identical stdout | `tests/scripts/test_simulate_coin_seed.py`; checked by hand for this document |
| The same `SimulationParams` through `run_simulation` | Equal payloads, including `simulation_id` | `tests/dashboard/` |
| A dashboard run and the CLI run with the same options and seed | The same price path, `SimulationReport` and rendered report, bit for bit | `tests/dashboard/test_integration.py`, `test_a_cli_seed_and_a_dashboard_seed_mean_the_same_thing` |
| Run *i* of a batch and a single run at run *i*'s seed | Equal payloads | `test_one_run_of_a_batch_equals_that_run_on_its_own` (`tests/services/test_batch.py`) |
| A saved scenario, loaded and run again | The same run. On the CLI the only difference is the header line `saved scenario` vs `from scenario` | `test_loading_reproduces_the_run_that_was_saved` |
| A run that is saved or analysed vs one that is not | Identical | `test_a_simulation_is_identical_whether_or_not_it_is_persisted`, analytics provenance tests |
| Market-condition presets | Deterministic. They rewrite settings and draw nothing | `services/market_conditions.py` |
| Each historical checkpoint against the pinned digests | `IDENTICAL` | [section 7](#7-compatibility-fingerprints) |

**Not guaranteed:**

- The same seed on a different OS (in particular Linux) or on Python
  3.11.
- The same seed across commits that deliberately change behavior. See
  [section 9](#9-calibration-boundaries).
- Wall-clock values. `SimulationClock` timestamps are anchored to when
  the run started. They are left out of payloads, digests and
  `simulation_id`, but they appear in the `created_at`/`updated_at`
  columns of the database.
- Timing figures, such as the stress harness's seconds and pytest
  durations.
- Pixel-identical dashboard rendering. The figures are deterministic.
  How Streamlit and Plotly draw them depends on library versions, which
  are ranges, not pins.
- An exact dependency environment. No lock file exists.

## 6. Seed derivation and batch stride

`build_coin_simulator` (`services/coin_simulation.py`) derives every
stream in one run from the base seed with fixed offsets. The price
engine and volume model offsets are set in `CoinSimulator`:

| Stream | Seed |
|---|---|
| Price process (`MarketEngine`) | base |
| Background volume (`VolumeModel`) | base + 1 |
| Whale *i* | base + 100 + *i* (`WHALE_SEED_OFFSET`) |
| Organic trader *i*, then manipulation-preset followers | base + 1000 + *i* (`TRADER_SEED_OFFSET`) |
| Manipulator *i* | base + 2000 + *i* (`MANIPULATOR_SEED_OFFSET`) |
| Random-event generator | base + 3000 (`RANDOM_EVENT_SEED_OFFSET`) |

Each stream is its own `random.Random`, so turning a feature on or off
does not reseed the others. For example, adding manipulators leaves the
organic traders' seeds unchanged.

**Batch derivation** (`services/batch.py`):

```text
batch base = explicit base_seed  → else the request's random_seed
                                 → else settings.simulation.random_seed
seed(i)    = batch base + i × BATCH_SEED_STRIDE,  BATCH_SEED_STRIDE = 10000
```

The stride is wider than any offset inside a run, so no run's price
engine reuses a seed that another run gave to a whale, trader or event
generator. A batch never draws a random seed.

Worked example (`--ticks 50 --batch 5 --seed 48291`, as printed by the
CLI):

```text
base seed = 48291
run 0 = 48291
run 1 = 58291
run 2 = 68291
run 3 = 78291
run 4 = 88291
```

On the CLI the batch base follows the precedence in
[section 4](#4-seed-precedence): `--seed`, then a loaded scenario's
seed, then `CRYPTOSIM_RANDOM_SEED`, then the YAML seed. Verified examples:

- `--load-scenario amm-pump --batch 3` used the scenario's 48291.
- Adding `--seed 7` gave runs 7, 10007 and 20007.
- No seed at all gave base 42.
- `CRYPTOSIM_RANDOM_SEED=1000` gave base 1000.

Every derived seed is validated. `--seed 4294967295 --batch 2` is
refused (exit 2), because run 1's seed would be 4294977295.

To rerun one batch member on its own, pass its seed:
`--seed 58291` reproduces run 1 above. In Python,
`services.batch.batch_seed(base, i)` returns the same number.

## 7. Compatibility fingerprints

The compatibility harness answers one question: *has the behavior of
fixed, seeded runs changed?* It does this by reducing each run to a
16-hex-character SHA-256 digest.

| Item | Location |
|---|---|
| Digest grid (the runs and how they are digested) | `tests/compat/grid.py` |
| Pinned digests | `tests/compat/pinned_digests.json` |
| Tests against the working tree | `tests/compat/test_compat_grid.py` (and `test_compat_isolation.py`) |
| Checkpoint comparison tool | `scripts/compat/compare_checkpoints.py` |
| Reference commit the pins were computed from | `b5a5f87f6b383ebd0a28ddbd8d5851a5155f4716` (`grid.REFERENCE`) |

**What is pinned** (current counts in `pinned_digests.json`):

- **Level groups**: 9 levels × 12 random worlds = 108 digests. Each world
  is a directly built `CoinSimulator` with random whales, traders, news
  and psychology, run for 100 ticks. Each digest covers every tick, the
  final wallets, whale state, reserve, accounting totals and the price and
  volume RNG states.
- **Common group**: 24 digests. `build_coin_simulator` from the default
  YAML in both pricing modes × manipulation presets × psychology on/off,
  random-walk runs with whale observation, and 6 directly built AMM
  worlds.
- **CLI group**: 14 digests of the full stdout of
  `scripts/simulate_coin.py` for fixed flag sets.
- **Two builder fingerprints**, each 200 ticks of the default
  configuration: `random_walk` = `d1218e0e0739f776`, `amm` =
  `f853009b5818169e`. They are pinned in both `grid.FINGERPRINTS` and the
  JSON file.
- **Calibrations**: digests superseded by deliberate behavior changes
  ([section 9](#9-calibration-boundaries)).

The grid reads the YAML directly and strips every `CRYPTOSIM_*`
variable, so environment overrides cannot leak into a digest.

**What is not covered.** The grid predates Phases 10–20, so it does not
exercise any of these:

- market-condition presets;
- batches and aggregate statistics;
- saved scenarios and persistence;
- the analytics report;
- tick series and price-path bands;
- the dashboard;
- the Phase 19 crowd/breadth channels;
- the stress harness.

Those are covered by ordinary tests, not by pinned digests.

**Why it is separate from ordinary tests.** Ordinary tests assert that
behavior is *correct*. The digests assert that behavior is *unchanged*.
`compare_checkpoints.py` also runs code that is not in the working tree:
archived checkpoint source, extracted from git.

**How the comparison works.** For each checkpoint, the tool does three
things:

1. It runs `git archive` on that commit's `crypto_simulator/` and
   `scripts/` into a temporary directory.
2. It runs the grid against that copy in a fresh subprocess, with
   `CRYPTOSIM_*` and `PYTHONPATH` removed from the environment.
3. It compares every digest with the pins. A checkpoint that predates a
   recorded calibration is compared with that calibration's superseded
   digests.

Because it archives historical commits, it **needs the full git
history**. In a shallow clone (`git clone --depth 1`) the tool stops with
a `subprocess.CalledProcessError` traceback from `git archive`. CI checks
out with `fetch-depth: 0` for this reason.

**`IDENTICAL`** means every level digest up to that checkpoint's level
matched exactly with the same case set, every common and CLI digest
matched, and both fingerprints matched. Anything else is printed as
`N DIFFERENCE(S)` followed by up to 20 differing cases, and the tool
exits 1.

## 8. Compatibility levels

There are **9 levels (0–8)**. Each is the checkpoint commit that added a
Phase 8 whale feature (`grid.LEVELS`):

| Level | Checkpoint | Adds |
|---|---|---|
| 0 | `aa213a8` | pre-Phase 8: unfunded whales only |
| 1 | `187b901` | funding, behavior, `min_trade_fraction`, cooldown |
| 2 | `1dca548` | target allocation |
| 3 | `c47b913` | minimum trade interval |
| 4 | `b593fb3` | explicit behavior transitions |
| 5 | `7557aa0` | intent strength |
| 6 | `ca78e62` | behavior cycles |
| 7 | `649bdee` | whale observation |
| 8 | `b5a5f87` | whale cohorts (the reference commit) |

The grid for level *L* uses only features that existed at checkpoint
*L*. A checkpoint must reproduce the pins of every level up to its own.

```bash
python scripts/compat/compare_checkpoints.py              # all 9 checkpoints (what CI runs)
python scripts/compat/compare_checkpoints.py --ref HEAD   # the committed HEAD, at level 8
pytest tests/compat                                       # the working tree (25 tests)
```

Expected output of the first command (about 10 s on the reference
machine):

```text
aa213a8    level 0: IDENTICAL
187b901    level 1: IDENTICAL
...
b5a5f87    level 8: IDENTICAL
```

The default run checks the nine historical checkpoints, **not** your
working tree. `pytest tests/compat` checks the working tree, including
uncommitted changes. `--ref HEAD` checks the latest commit through the
archive path. `--ref` can be repeated, and `--level` overrides the level.

`--write-pins` recomputes and overwrites the pin file from the reference
commit. It is a deliberate act for when the grid itself changes. **It is
never a way to make a failing comparison pass.**

## 9. Calibration boundaries

Some changes are meant to change outputs. Overwriting the pins would make
every earlier checkpoint fail, so a deliberate change is recorded as a
**calibration boundary**:

- `grid.CALIBRATIONS` names the calibration and tells how to detect it
  in source, without using commit hashes.
- `pinned_digests.json` keeps the superseded digests under
  `calibrations`.
- Source without the calibration is compared with the superseded
  digests. Source with it is compared with the main pins.

The one recorded boundary is **`psychology-momentum-horizon` (Phase
18)**. Psychology's momentum term is now scaled by its own horizon
(`PRICE_MOVE_SCALE * sqrt(SIGNAL_WINDOW - 1)`). It moved only
psychology-enabled runs: 51 level digests, 11 common and 4 CLI digests
were superseded. Both builder fingerprints were unaffected. The
calibration tuned a model parameter of a synthetic mechanism. It is not
evidence that the simulator models real human psychology.

**Changes that need a compatibility review** (run `pytest tests/compat`
and `compare_checkpoints.py`, and record a boundary if the change is
intended):

- RNG usage: the number, order or kind of draws;
- seed offsets and the batch stride;
- the order of operations in the tick loop;
- floating-point summation (for example `sum` vs `math.fsum`) and
  settlement arithmetic;
- default configuration values in `default.yaml`;
- the CLI's printed output, which is digested.

## 10. Slow tests

```bash
pytest -m slow
```

`pyproject.toml` sets `addopts = "-ra -m 'not slow'"`, so the default
`pytest` run deselects these tests. There are currently **3**, all in
`tests/stress/test_cases.py`:

- `test_each_heavy_case[heavy-max-ticks-many-traders]`
- `test_each_heavy_case[heavy-batch-maximum]`
- `test_the_largest_batch_loses_nothing`

They run the stress harness's costly cases: the maximum ticks with the
harness's maximum trader population, and the maximum batch of 1000 runs.
They check that those complete, conserve accounting and lose no runs.
`python scripts/stress_test.py --heavy` runs the same heavy cases from
the command line.

## 11. Canonical validation commands

| Command | Validates |
|---|---|
| `pytest` | The full suite except `slow`. This includes `tests/compat` (the working tree against the pins and fingerprints), the structural layering tests and the ordinary stress tier |
| `pytest -m slow` | Only the heavy stress cases |
| `python scripts/compat/compare_checkpoints.py` | Every historical checkpoint against the pins. Needs full history |
| `pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html` | The suite with coverage. Writes `.coverage`, `coverage.xml` and `htmlcov/` (all gitignored). This is exactly the command the CI coverage job runs. No minimum percentage is enforced |

The README shows a shorter coverage command,
`pytest --cov --cov-report=term-missing`. It measures the same thing but
prints only the terminal report. It does not write the XML and HTML
reports that CI produces.

## 12. CI reproducibility

`.github/workflows/ci.yml` runs on every push and pull request to `main`.
Every job runs on **`macos-latest`**, because the pins were produced on
macOS (see [section 2](#2-supported-environment)).

| Job | Python | Command | Notes |
|---|---|---|---|
| Test suite | 3.12, 3.13 (matrix, `fail-fast: false`) | `pytest` | Both versions always report |
| Slow tests | 3.13 | `pytest -m slow` | |
| Compatibility checkpoints | 3.13 | `python scripts/compat/compare_checkpoints.py` | `actions/checkout` with `fetch-depth: 0` |
| Coverage | 3.13 | `pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html` | Totals written to the job summary from `coverage.xml`. `htmlcov/` uploaded as the `coverage-html` artifact |

Every job installs with `pip install -r requirements-dev.txt` from the
version ranges, so CI resolves the newest allowed versions on each run.
The workflow uses `actions/checkout@v4`, `actions/setup-python@v5` and
`actions/upload-artifact@v4`. Dependabot is configured for GitHub
Actions updates, but the workflow above is the one in effect.

## 13. Reproducibility checklist

- [ ] A clean checkout with **full history** (`git clone`, not
      `--depth 1`) if you will run the checkpoint comparison.
- [ ] Python **3.12 or newer** in a fresh virtual environment.
- [ ] `pip install -r requirements-dev.txt` and `pip install -e .`
- [ ] Unset or record any `CRYPTOSIM_*` variables (`env | grep CRYPTOSIM_`).
- [ ] A fixed seed (`--seed N`) and fixed flags, or a saved scenario.
- [ ] An unchanged `crypto_simulator/config/default.yaml`.
- [ ] **macOS** when matching the pinned digests or someone else's run
      bit for bit.
- [ ] `pytest` passes, plus `pytest -m slow` if the heavy paths matter.
- [ ] `python scripts/compat/compare_checkpoints.py` reports `IDENTICAL`
      for every checkpoint.
- [ ] Record `git rev-parse HEAD`, `python --version`, the OS, the exact
      command and the seed alongside any result you report.
