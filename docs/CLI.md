# CLI reference

The technical reference for the command-line tools. The
[README](../README.md) is the entry point. Seed and determinism details
are in [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md).

## 1. Overview

| Tool | Path | Purpose |
|---|---|---|
| Coin-simulation CLI | `scripts/simulate_coin.py` | Runs the active coin-economy simulation: single runs, analytics report, saved scenarios, batches with aggregate statistics |
| Stress-test CLI | `scripts/stress_test.py` | Runs the stress cases in `crypto_simulator/stress/` |
| Compatibility tool | `scripts/compat/compare_checkpoints.py` | Compares historical checkpoints with the pinned digests (developer tool; options `--ref`, `--level`, `--write-pins` are covered in [`REPRODUCIBILITY.md` §8](REPRODUCIBILITY.md#8-compatibility-levels)) |

`scripts/simulate_coin.py` drives the same code as the dashboard's
**🪙 Coin Simulation** tab. Both build the simulator with
`build_coin_simulator`. Batch mode calls the dashboard's `run_simulation`
directly. A seeded CLI run and a seeded dashboard run with the same
options are the same run (see
[`ARCHITECTURE.md`](ARCHITECTURE.md#5-active-coin-economy-data-flow)).

Everything is synthetic and educational. No command touches a real
exchange, real money or real market data, and no output is a forecast or
advice.

## 2. Installation and invocation

The project has **no console-script entry point**: `pyproject.toml`
defines none. Run the scripts with Python from the repository root.

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12+
pip install .             # or `pip install -e .` for development

python scripts/simulate_coin.py --help
```

- The package must be installed (normally or in editable mode). The
  scripts import `crypto_simulator` and do not add the repository to
  `sys.path` themselves.
- Run from the repository root. The default database path
  `data/simulator.db` is relative to the working directory. The
  configuration file is located relative to the package, so it does not
  depend on the working directory.
- All output goes to stdout. Errors go to stderr (see
  [section 13](#13-output-and-exit-behavior)).

## 3. Options — `scripts/simulate_coin.py`

Every option the parser defines:

| Option | Type | Default | Range / choices | Meaning |
|---|---|---|---|---|
| `-h`, `--help` | flag | — | — | Print help and exit 0 |
| `--ticks TICKS` | int | `20` | ≥ 1. No upper bound for a single run. 1–2000 when combined with `--batch` or `--save-scenario` (which validate the request) | Number of ticks to simulate |
| `--no-traders` | flag | off | — | Drop `coin.traders`. Participants from a manipulation preset are still added |
| `--no-whales` | flag | off | — | Drop `coin.whales`. Required for AMM with the default config |
| `--pricing-mode` | choice | config (`coin.pricing_mode`, `random_walk`) | `random_walk`, `amm` | Override the pricing mode |
| `--scenario` | choice | none | `pump_and_dump`, `wash_trading` | A manipulation preset. Replaces `coin.manipulators` |
| `--market-condition` | choice | none | `bear`, `bull`, `meme` | A market-condition configuration preset |
| `--events` | flag | off | — | A two-event demo news schedule. Replaces `coin.events.scheduled` |
| `--random-events` | flag | off | — | Random news with probability `0.1` per tick. Sets `coin.events.random.probability` |
| `--psychology` | flag | off | — | Turn on participant psychology and print psychology observations |
| `--whale-observation` | flag | off | — | Record each whale's state and fills every tick and print a whale summary |
| `--report` | flag | off | — | After the run, print the descriptive analytics report. Not allowed with `--batch` |
| `--seed SEED` | int | config (`simulation.random_seed`, `42`) | `0`–`4294967295` | Base seed for this command |
| `--save-scenario NAME` | string | — | Non-blank name | Save this command's configuration under `NAME` before running |
| `--load-scenario NAME` | string | — | An existing name | Start from a saved configuration. Typed flags override it |
| `--batch RUNS` | int | — (single run) | `1`–`1000` | Run the configuration `RUNS` times under derived seeds and print a summary instead of ticks |

The options are independent flags. There are no subcommands.

## 4. Seed and configuration precedence

Configuration is resolved in this order. Later steps override earlier
ones.

1. `crypto_simulator/config/default.yaml`.
2. `CRYPTOSIM_*` environment variables (see
   [section 14](#14-environment-variables)), applied when the YAML is
   loaded.
3. `--load-scenario NAME`: every stored field becomes the starting value
   for the matching flag.
4. Flags typed on the command line. A typed flag beats the scenario even
   if you type its default value.

The run is then assembled as follows:

1. The market-condition preset is applied.
2. `--events` and `--random-events` are applied on top. For example,
   `--random-events` replaces a preset's news rate with 0.1.
3. The seed is applied.
4. `build_coin_simulator` builds the simulator. `--pricing-mode`,
   `--no-traders`/`--no-whales`, `--scenario`, `--psychology` and
   `--whale-observation` are passed to it.

**Seed:** `--seed` > a loaded scenario's seed > `CRYPTOSIM_RANDOM_SEED` >
`default.yaml`. **Pricing mode:** `--pricing-mode` > a loaded scenario's
mode > `CRYPTOSIM_PRICING_MODE` > `default.yaml`. Both orders were
verified by running them. Details and edge cases are in
[`REPRODUCIBILITY.md` §4](REPRODUCIBILITY.md#4-seed-precedence).

## 5. Pricing modes

| Value | Price path | Constraints |
|---|---|---|
| `random_walk` (default) | A seeded GBM random walk plus background volume. Whale trades and the traders' net flow apply multiplicative price impact. Trades settle against a market-reserve wallet at one price per tick | Whales allowed |
| `amm` | No random walk and no background volume. A constant-product `x · y = k` pool, seeded from the market reserve, sets the price. Traders swap through it in list order, with fees and slippage. Exact `Decimal` accounting | **Whales are refused.** Use `--no-whales` with the default config, or the command exits 2 |

AMM runs add an `AMM pool:` summary (reserves, spot price, `k`, fees,
swaps, worst slippage) and an exact-`Decimal` accounting check.

## 6. Market conditions

`--market-condition` selects a named **configuration preset**
(`services/market_conditions.py`). A preset changes only existing
settings and adds no mechanism. It changes the odds of how a run unfolds,
not the outcome. Any single seeded run can still move against the
preset's tilt.

| Value | Settings it writes |
|---|---|
| `bull` | Random news probability 0.15 per tick, weighted to positive categories (`exchange_listing`, `partnership_announcement`, `product_launch`, `adoption_growth`, `positive_regulation`). `drift_per_sentiment` 0.004 (random walk only) |
| `bear` | Probability 0.15, weighted to negative categories (`security_incident`, `regulatory_restriction`, `product_failure`, `supply_concern`, `competitor_announcement`). `drift_per_sentiment` 0.004 (random walk only), so negative sentiment becomes downward drift |
| `meme` | Probability 0.30, both tones, severity 0.6–1.0. `drift_per_sentiment` 0.002 (random walk only). Base `volatility` 0.09. A volatility regime, not a direction |

- In `amm` mode the drift is not applied, because the simulator refuses a
  nonzero drift in AMM. The preset still changes which news arrives and
  how often, and price moves only through trader reactions.
- A preset is a different setting from `--scenario` (participants). The
  two can be combined.
- The header prints `market condition: NAME` and the resulting
  `news events` line.

## 7. Psychology controls

`--psychology` is the only psychology option. It is an on/off flag,
default off, and it is not a config field. When on:

- every trader receives a market-wide psychology state each tick (fear,
  FOMO, conviction, uncertainty, computed from completed closes and news)
  that shifts its strategy's own rules within bounds;
- the header shows `psychology : on`, and a
  `Psychology observations` section is printed after the run;
- with `--report`, the report includes its `PSYCHOLOGY` section.

The model's momentum term was calibrated in Phase 18. That calibration
adjusted a synthetic mechanism and is not evidence of realistic human
behavior.

The Phase 19 crowd-flow and breadth channels have **no CLI option**. They
exist only as experimental `build_coin_simulator` arguments (see
[`PHASE_19_FINAL.md`](PHASE_19_FINAL.md)).

> **Wording kept for compatibility.** At runtime the header prints
> `psychology : on (calibration deferred)` and the observations heading
> says "calibration deferred". Both predate the Phase 18 calibration.
> They are left as they are because that stdout is part of four pinned
> CLI compatibility digests (see
> [`REPRODUCIBILITY.md` §7](REPRODUCIBILITY.md#7-compatibility-fingerprints)).
> The flag behaves as described above.

## 8. Manipulation, events and participants

| Option | Effect |
|---|---|
| `--scenario pump_and_dump` | Adds one `pump_and_dump` manipulator (accumulates on ticks 5–14, pumps on 15–16, dumps on 17–19) and four momentum-chasing followers (`mark-1`…`mark-4`) |
| `--scenario wash_trading` | Adds one `wash_trader` that trades with itself to inflate reported volume |
| `--events` | A demo schedule: `exchange_listing` at tick 4 and `security_incident` at tick 13 |
| `--random-events` | A random-event chance of 0.1 per tick (its own seeded stream) |
| `--no-traders` / `--no-whales` | Remove the configured traders / whales |
| `--whale-observation` | Records whale state each tick. Read-only: the run is otherwise identical. Random-walk only, since AMM has no whales |

With a manipulation preset, the CLI prints a `Manipulation:` summary:
manipulator and organic P&L, the peak price, and the wash share of
volume. With events it prints an `Event analysis` section. These schemes
are educational models of manipulation patterns inside a synthetic
market. They do not reproduce any real-world case. Whale cohorts and the
other configuration details are set in `default.yaml` or the Python API,
not with flags.

## 9. Single-run commands

Each of these was run for this document and exited 0:

```bash
python scripts/simulate_coin.py                                    # 20 ticks, configured seed (42)
python scripts/simulate_coin.py --ticks 20 --seed 48291            # seeded
python scripts/simulate_coin.py --ticks 20 --pricing-mode amm --no-whales --seed 48291
python scripts/simulate_coin.py --ticks 200 --market-condition bull --seed 48291
python scripts/simulate_coin.py --ticks 60 --events --psychology --seed 48291
python scripts/simulate_coin.py --ticks 40 --pricing-mode amm --no-whales --scenario pump_and_dump --seed 48291
python scripts/simulate_coin.py --ticks 30 --whale-observation --seed 48291
python scripts/simulate_coin.py --ticks 60 --scenario pump_and_dump --market-condition bear \
    --events --psychology --report --seed 48291                    # everything, plus the report
```

## 10. Scenario save/load

```bash
# Save (the run also executes and prints as usual)
python scripts/simulate_coin.py --ticks 40 --pricing-mode amm --no-whales \
    --scenario pump_and_dump --seed 48291 --save-scenario amm-pump

# Load and rerun
python scripts/simulate_coin.py --load-scenario amm-pump

# Load with one field changed for this run only
python scripts/simulate_coin.py --load-scenario amm-pump --ticks 100
```

- **Storage.** The `coin_scenarios` table in the SQLite database at
  `database.path` (default `data/simulator.db`, or `CRYPTOSIM_DB_PATH`).
  The table is created on first use. `data/*.db` is gitignored. Each
  scenario is one row holding the request as JSON (`params_json`) plus
  `created_at`/`updated_at` timestamps.
- **What is saved.** The configuration that actually ran:
  - ticks;
  - pricing mode (the resolved one, even if not typed);
  - traders and whales on/off;
  - manipulation preset;
  - market condition;
  - events and random events;
  - psychology and whale observation;
  - the seed (the resolved one, even if not typed).

  No results are saved. `--batch` and `--report` are not saved.
- **What loading does.** It rebuilds that request and runs it from
  tick 1. It does not resume anything. The output is identical to the
  saving run except for the header line, which says `from scenario`
  instead of `saved scenario`.
- **Saving validates first.** The configuration is checked and written
  before the run. Anything outside the request bounds is refused with
  exit 2 (for example, ticks above 2000).
- **The same name overwrites.** Saving under an existing name replaces
  its configuration silently and exits 0.
- **Limitations:**
  - The CLI cannot list or delete scenarios. That is Python API only
    (`ScenarioService.list_scenarios` and `.delete`).
  - On/off flags can only turn a feature **on** over a loaded scenario.
    There is no flag to turn off, for example, the psychology a scenario
    saved as on, or to bring back the whales it removed.
  - The dashboard has no save/load.
  - A command with neither scenario flag never opens the database.
    `--load-scenario` creates an empty database file if none exists,
    even when the name is not found.

## 11. Batch simulation

```bash
python scripts/simulate_coin.py --ticks 50 --batch 5 --seed 48291
python scripts/simulate_coin.py --load-scenario amm-pump --batch 3   # a saved scenario, as a batch
```

Output of the first command, shortened:

```text
Batch of 5 runs
  configuration  : 50 ticks, random_walk
  base seed      : 48291
  seed stride    : 10000

 run          seed  simulation id     ticks  result
------------------------------------------------------------
   0         48291  7e806a4d73f2889e     50  ok
   1         58291  07bfe3fb74a74aa1     50  ok
   ...
  completed      : 5 of 5

Aggregate statistics
  runs           : 5 of 5 succeeded
  percentiles    : linear interpolation at rank p/100 x (n-1); p50 is the median
  std dev        : sample (n-1), blank below two observations

  metric                    n         mean       median        stdev          min          p05 ...
  close_price               5      1.18169      1.23767     0.184636     0.870792     0.931126 ...
```

- **Seeds.** Run *i* uses `base + i × 10000`. The base is `--seed`, else
  the loaded scenario's seed, else the configured seed. It is never
  random. `--seed 58291` alone reproduces run 1. See
  [`REPRODUCIBILITY.md` §6](REPRODUCIBILITY.md#6-seed-derivation-and-batch-stride).
- **Request bounds.** `RUNS` must be 1–1000. Ticks must be 1–2000 in
  batch mode. Every derived seed must stay ≤ 4294967295, so a base near
  the top of the range is refused (exit 2).
- **Aggregate statistics** come from each run's own market summary:
  - prices: open, close, high, low, mean;
  - returns: cumulative, log, mean;
  - volatility and realized volatility;
  - drawdown: max and end;
  - market cap at start and end;
  - total volume, turnover and participant turnover;
  - average trade size and trader VWAP.

  Each is shown as n, mean, median, sample stdev, min, P05, P25, P75, P95
  and max. `n/a` marks an undefined value.
- **Failures.** A run that raises is listed as `FAILED <error>`. The
  other runs continue, and the command exits 1.
- **Ephemeral.** A batch writes nothing to the database. Results exist
  only in the printed output. `--save-scenario` with `--batch` saves the
  configuration, but not the batch size or the results.
- `--report` is refused with `--batch` (exit 2).

## 12. Stress testing

```bash
python scripts/stress_test.py            # the 22 ordinary cases (~1-2 s)
python scripts/stress_test.py --heavy    # plus the 2 costly ones (24 cases)
python scripts/stress_test.py --list     # print the selected cases, run nothing
python scripts/stress_test.py --only amm # only cases whose name contains "amm"
```

| Option | Meaning |
|---|---|
| `--heavy` | Also run the heavy cases (maximum ticks × many traders, maximum batch) |
| `--only TEXT` | Run only cases whose name contains `TEXT`. No match is a parser error (exit 2) |
| `--list` | List the selected cases with tier and description, then exit 0 |

Each case is a configuration the simulator already accepts, at its
validated limits, or one it must refuse. Each runs through
`run_simulation`/`run_batch`. A case passes when all of these hold:

- it completes the requested ticks;
- its report has no non-finite values;
- its prices are valid;
- its volumes and counts are non-negative;
- its ticks are in order;
- coins and cash are conserved (exactly in AMM mode; within 1e-9 relative
  in random-walk mode).

Selected cases are run twice and must match. Invalid cases count as
`refused` when they are refused as expected. Output is a per-case line
and a summary (`completed`, `refused`, `failed`). **Nothing is written to
disk.** Exit 0 when no case failed, 1 otherwise. This checks robustness
within the simulator's limits. It does not measure realism or
performance against real markets.

## 13. Output and exit behavior

**stdout** for a single run, in order:

1. A header: coin, supply, participants, pricing mode, plus any seed,
   market condition, news, psychology, observation and scenario lines.
2. A per-tick table: price, market cap, volume, whale and trader
   activity, news.
3. The final price, market cap, average volume and trade counts.
4. Any of these sections, as the run's features call for them:
   - news schedule and `Event analysis`;
   - `Whale observations`;
   - `Psychology observations`;
   - a per-trader wallet/P&L table;
   - `Manipulation:`;
   - `AMM pool:`;
   - an accounting check showing coins and cash before and after.
5. With `--report`, a `SIMULATION REPORT` block with the sections
   MARKET, TRADERS, WHALE ACTIVITY, EVENT WINDOWS, PSYCHOLOGY,
   MANIPULATION and REGIMES. It is descriptive only.

A normal run writes nothing to stderr and creates no files, unless a
scenario flag opens the database.

**Exit codes** (verified by running each case):

| Situation | Exit | Stream |
|---|---|---|
| Success (single run, batch, save, load) | `0` | stdout |
| Unknown option, bad choice or non-integer value | `2` | argparse usage + `error:` on stderr |
| `--seed` out of range | `2` | `error: --seed must be between 0 and 4294967295` |
| Configuration the builder refuses (e.g. whales with `amm`, an unknown `CRYPTOSIM_PRICING_MODE`) | `2` | `error:` with the simulator's message |
| `--load-scenario` name not found | `2` | `error: no scenario named 'NAME'` |
| Stored scenario that this version cannot run | `2` | `error: scenario 'NAME' cannot be run: ...` |
| Configuration that cannot be saved (e.g. `--ticks 2001 --save-scenario X`) | `2` | `error: cannot save scenario: ...` |
| `--batch` out of range, bad batch request, `--report` with `--batch` | `2` | `error: ...` |
| A batch in which some run failed | `1` | Summary on stdout |
| `--ticks` below 1 (`0`, a negative value) | `2` | `error: argument --ticks: ticks must be at least 1 (got N)` |
| Non-integer `CRYPTOSIM_RANDOM_SEED` | `1` | Python traceback while loading settings |
| `--help` | `0` | stdout |

## 14. Environment variables

These are read by `crypto_simulator/config/settings.py` (`_ENV_OVERRIDES`)
from the **process environment** when settings are first loaded:

| Variable | Overrides | Format | Example |
|---|---|---|---|
| `CRYPTOSIM_RANDOM_SEED` | `simulation.random_seed` | Integer (`int()`). Not range-checked for a plain single run | `CRYPTOSIM_RANDOM_SEED=48291` |
| `CRYPTOSIM_PRICING_MODE` | `coin.pricing_mode` | `random_walk` or `amm` | `CRYPTOSIM_PRICING_MODE=amm` |
| `CRYPTOSIM_DB_PATH` | `database.path` | A file path (parent directories are created) | `CRYPTOSIM_DB_PATH=data/demo.db` |
| `CRYPTOSIM_LOG_LEVEL` | `logging.level` | A logging level name | `CRYPTOSIM_LOG_LEVEL=DEBUG` |
| `CRYPTOSIM_STARTING_BALANCE` | `simulation.starting_balance` (dormant trading-platform track) | Float | `CRYPTOSIM_STARTING_BALANCE=50000` |

```bash
CRYPTOSIM_RANDOM_SEED=48291 python scripts/simulate_coin.py --ticks 20
CRYPTOSIM_PRICING_MODE=amm python scripts/simulate_coin.py --ticks 20 --no-whales
```

- Environment values sit below CLI flags and loaded scenarios
  ([section 4](#4-seed-and-configuration-precedence)). An environment
  seed changes the run but prints **no** `random seed` header line. Only
  `--seed` (or a loaded scenario) prints one.
- **`.env` files are not loaded.** Nothing in the project reads a `.env`
  file. `.env.example` is only a template that lists the variables. To
  use a copy, export it into your shell first:

  ```bash
  cp .env.example .env    # then uncomment / edit values
  set -a; source .env; set +a
  ```

## 15. Reproducible CLI recipes

Each recipe was executed as written for this document. Recipe 3 uses
`data/demo.db`, which is gitignored and separate from the default
database. Delete it afterwards if you like.

**1. Deterministic single run.** Same command, same output:

```bash
python scripts/simulate_coin.py --ticks 20 --seed 48291 > run-a.txt
python scripts/simulate_coin.py --ticks 20 --seed 48291 > run-b.txt
cmp run-a.txt run-b.txt && echo identical
rm run-a.txt run-b.txt
```

**2. Deterministic batch.** Prints each run's seed and `simulation id`:

```bash
python scripts/simulate_coin.py --ticks 50 --batch 5 --seed 48291
python scripts/simulate_coin.py --ticks 50 --seed 58291      # run 1 of that batch, on its own
```

**3. Scenario save/load:**

```bash
CRYPTOSIM_DB_PATH=data/demo.db python scripts/simulate_coin.py --ticks 40 \
    --pricing-mode amm --no-whales --scenario pump_and_dump --seed 48291 --save-scenario amm-pump
CRYPTOSIM_DB_PATH=data/demo.db python scripts/simulate_coin.py --load-scenario amm-pump
rm data/demo.db
```

**4. Stress validation:**

```bash
python scripts/stress_test.py             # expect "failed : 0" and exit 0
```

**5. Compatibility verification** (needs full git history):

```bash
python scripts/compat/compare_checkpoints.py   # expect IDENTICAL for all 9 checkpoints
pytest tests/compat                            # the working tree against the same pins
```

## 16. Limitations and known issues

These are left unchanged in this documentation step:

- **Psychology wording.** "calibration deferred" in the run header and
  the observations heading predates the Phase 18 calibration. It is kept
  because it is part of the pinned CLI output
  ([section 7](#7-psychology-controls)).
- **No upper bound on `--ticks` for a single run.** Values below 1 are a
  parser error. Batches and saved scenarios check 1–2000.
- **`CRYPTOSIM_RANDOM_SEED` is not range-checked** for a plain single
  run, and a non-integer value ends in a traceback.
- **Saved scenarios cannot be listed or deleted** from the CLI, and
  on/off flags cannot be turned off over a loaded scenario.
- **No CLI access** to the Phase 19 crowd/breadth channels, whale
  cohorts, or saving finished runs (`CoinRunRepository`). These are
  Python API only.
- **`.env` is never loaded automatically.** Variables must be in the
  process environment.
