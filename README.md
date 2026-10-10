# Crypto Market Simulator

A **fictional, educational** cryptocurrency market simulator.

**Version 1.0.0** — the coin-economy development roadmap is complete
through Phase 23. See [`CHANGELOG.md`](CHANGELOG.md) for what the release
contains and its known limitations.

> ⚠️ **This project is a simulation only.** It does not connect to any real
> exchange, does not execute real trades, and does not move real money. All
> prices, order books, and balances are synthetically generated for learning
> and experimentation purposes.

## Purpose and status

A sandbox for exploring market mechanics — price formation, liquidity,
participant behavior, news shocks and manipulation schemes — without any
financial risk, built entirely on synthetic data. The "no real exchange"
guarantee is structural: every price is generated inside the simulator, and
there is no network client anywhere in the codebase.

The repository holds **two related tracks** that share the
`crypto_simulator` package:

- **Coin-economy simulator — the active track.** A single fictional coin
  (`FIC`, "FictiCoin") traded by rule-based traders, whales and
  manipulators, priced by a random walk or a constant-product AMM, with
  news events, participant psychology, analytics, persistence, scenarios,
  batch runs, aggregate statistics, stress testing and a Streamlit
  dashboard. It has been developed phase by phase from Phase 6 onward and
  is the focus of the project: Phases 6–23 are complete, and it is
  released as version 1.0.0.
  Everything under [Quickstart](#quickstart) and
  [Capabilities](#capabilities) is this track.
- **Trading-platform track — dormant and incomplete.** The project's
  original multi-asset architecture: `core/market_engine.py`
  (`MarketEngine`, a seeded GBM price process per asset), `core/order_engine.py`
  (`OrderEngine`), the portfolio/trading services, the SQLite trading
  tables, and the Streamlit app's **Multi-asset sandbox** page (under
  "Legacy"). Only synthetic price generation works (the sandbox advances
  the market one tick at a time and draws a candlestick chart); order
  execution, portfolio P&L and trade history are **not implemented** and
  have no page in the app. The code remains in the repository and its
  tests still run, but it is not being developed.

The two tracks share configuration, the SQLite connection layer and the
Streamlit app, and never call into each other. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for the phase-by-phase record.

## Installation

**Requirements:** Python **3.12 or newer** (`requires-python = ">=3.12"`;
CI tests 3.12 and 3.13 — see [Reproducibility](#reproducibility) for why
3.11 is not supported) and git.

| Concern     | Choice                                           |
|-------------|--------------------------------------------------|
| Language    | Python ≥ 3.12                                    |
| Persistence | SQLite (standard library)                        |
| Charts      | Plotly                                           |
| UI          | Streamlit                                        |
| Data        | pandas, PyYAML                                   |
| Testing     | pytest, pytest-cov                               |

Runtime dependencies are declared in `pyproject.toml` (and mirrored in
`requirements.txt`); `requirements-dev.txt` adds the test tools and
includes the runtime set. Versions are bounded ranges, not pinned.

```bash
git clone https://github.com/jdgiron12/crypto-simulator.git
cd crypto-simulator

python3 -m venv .venv              # python3 must be 3.12 or newer
source .venv/bin/activate

pip install .                      # the package and its runtime dependencies
```

The CLI scripts, the examples and `streamlit run` all import the installed
`crypto_simulator` package; none of them adds the repository to the import
path itself, so some installation is needed. Run them from the repository
root, since `scripts/` and `examples/` are not part of the package.

**For development** (editing the source, running the tests), install in
editable mode with the test tools instead:

```bash
pip install -r requirements-dev.txt   # runtime + test dependencies
pip install -e .                      # source edits take effect without reinstalling
```

(`pytest` uses the repository source directly, since `pyproject.toml` puts
the repository root on pytest's path.)

## Quickstart

From the repository root, with the virtual environment active:

```bash
# 1. A seeded simulation: 20 ticks, reproducible exactly from the seed
python scripts/simulate_coin.py --ticks 20 --seed 48291

# 2. A scenario: a pump-and-dump manipulation preset in a bear market,
#    with the descriptive analytics report printed after the run
python scripts/simulate_coin.py --ticks 60 --scenario pump_and_dump \
    --market-condition bear --seed 48291 --report

# 3. A batch: the same configuration 20 times under derived seeds,
#    followed by aggregate statistics across the runs
python scripts/simulate_coin.py --ticks 50 --batch 20 --seed 48291

# 4. The dashboard: it opens on the coin simulator (the "Simulate" page)
streamlit run crypto_simulator/app.py

# 5. The tests
pytest
```

Each simulation prints its configuration, every tick, a per-trader
wallet/P&L table and an accounting check showing total coins and cash
unchanged. Run `python scripts/simulate_coin.py --help` for every flag.
The [Capabilities](#capabilities) section explains each feature.

## Examples

Short, runnable Python scripts that use the package directly (after the
installation steps above; each finishes in about a second and writes no
files):

| Script | Shows |
|---|---|
| [`examples/basic_simulation.py`](examples/basic_simulation.py) | One seeded run, a few figures from its report, and that rerunning it reproduces it exactly |
| [`examples/scenario_comparison.py`](examples/scenario_comparison.py) | The same seeded run under the neutral, `bull` and `bear` market-condition presets, side by side |
| [`examples/batch_statistics.py`](examples/batch_statistics.py) | A 20-run batch from one base seed and its aggregate statistics |

```bash
python examples/basic_simulation.py
```

## Python API

The supported import paths for the coin-economy simulator. These are the
names the examples and documentation use, and the intended stable surface
for v1.0; other modules are internal and may change.

| Import from | Names | For |
|---|---|---|
| `crypto_simulator.dashboard.data` (also `crypto_simulator.dashboard`) | `SimulationParams`, `run_simulation`, `payload_to_dict`, `DashboardPayload` | One validated, seeded run and its report. Headless: no Streamlit or Plotly is imported |
| `crypto_simulator.services.batch` | `run_batch`, `batch_seed`, `BatchResult` | Many seeded runs of one request |
| `crypto_simulator.analytics` | `aggregate_batch`, `build_report`, `render_report`, the `analyze_*` functions and their result types | Reading finished runs |
| `crypto_simulator.services` | `build_coin_simulator` | Building a `CoinSimulator` directly from `Settings` |
| `crypto_simulator.services.scenarios` | `ScenarioService`, `ScenarioNotFound` | Saved scenarios (save, load, list, delete) |
| `crypto_simulator.services.market_conditions` | `MARKET_CONDITIONS`, `apply_market_condition` | Market-condition presets |
| `crypto_simulator.data` | `CoinRunRepository`, `connect`, `init_db`, `get_connection` | Saving finished runs to SQLite |
| `crypto_simulator.config` | `get_settings` | The loaded configuration |
| `crypto_simulator` | `__version__` | The package version |

```python
from crypto_simulator.analytics import aggregate_batch
from crypto_simulator.dashboard.data import SimulationParams, run_simulation
from crypto_simulator.services.batch import run_batch

payload = run_simulation(SimulationParams(ticks=50, random_seed=48291))
print(payload.simulation.simulation_id, payload.report.market.close_price)

batch = run_batch(SimulationParams(ticks=50), 20, runner=run_simulation, base_seed=48291)
print(aggregate_batch(batch).metric("close_price").median)
```

`run_simulation` lives in the dashboard's data layer for historical
reasons, but it is the shared single-run entry point (the CLI's batch
mode, the stress harness and the examples all use it). Everything under
`crypto_simulator.core`, the dashboard's view and section modules,
`crypto_simulator.stress`, `crypto_simulator.visualization`, names
starting with `_`, and the dormant trading-platform services
(`MarketService`, `TradingService`, `PortfolioService`) are internal.

## Capabilities

### The coin economy

Every run is built from the `coin:` section of
`crypto_simulator/config/default.yaml` by
`services.coin_simulation.build_coin_simulator`, and runs in
`core.coin_simulator.CoinSimulator`.

```bash
python scripts/simulate_coin.py --ticks 20                    # default config
python scripts/simulate_coin.py --ticks 20 --no-traders       # whales only
python scripts/simulate_coin.py --ticks 20 --pricing-mode amm --no-whales
python scripts/simulate_coin.py --ticks 30 --scenario wash_trading
python scripts/simulate_coin.py --ticks 40 --events           # demo news schedule
python scripts/simulate_coin.py --ticks 40 --random-events    # random news events
python scripts/simulate_coin.py --ticks 40 --events --psychology
python scripts/simulate_coin.py --ticks 40 --whale-observation
python scripts/simulate_coin.py --ticks 60 --events --psychology --report
```

- **Coin economics** — symbol, supply, starting price, volatility.
- **Trader agents** — rule-based participants (`retail`, `momentum`,
  `dip_buyer`, `panic_seller`, `long_term_holder`), each with starting
  cash/coins, a per-tick trade probability, a max trade size, a risk
  tolerance (fraction of balance committed per trade) and
  strategy-specific `params`. Their trades settle directly against a
  market reserve (`market_reserve_cash` plus all unallocated coins) — no
  order book — so no coins or cash are ever created, and their net flow
  moves price. To add a strategy, subclass `TraderAgent` in
  `crypto_simulator/core/traders/` and register it in `TRADER_STRATEGIES`.
- **Whales** — large holders that can move price with one outsized trade.
  Optionally funded (`starting_cash`, random-walk mode): the whale then
  settles against the market reserve and can `accumulate` or `distribute`
  toward a `target_coin_fraction`. Funded whales can also be paced
  (`cooldown_ticks`, `min_trade_interval_ticks`), lean harder or softer
  (`intent_strength`), follow a fixed behavior timetable (`cycle`), and
  be moved between behaviors explicitly (`Whale.set_behavior`). Several
  funded whales can share one timetable as a **cohort** — Python API only
  (`CoinSimulator(whale_cohorts=[WhaleCohort(...)])`) — which is a fixed
  schedule, not whales reacting to the market or to each other.
  `--whale-observation` records what each whale did each tick and prints
  a descriptive summary. Whales read no news or psychology.
- **Pricing mode** — `random_walk` (default: GBM random walk plus linear
  whale/trader price impact) or `amm` (a constant-product `x · y = k`
  liquidity pool seeded by the market reserve; traders swap through it
  with fees and slippage, and price moves only on trades, with exact
  `Decimal` accounting). Configure the pool under `amm:`
  (`pool_coin_reserve`, `fee_rate`). **Whales are not supported in AMM
  mode** — the simulator rejects them, so AMM runs need `--no-whales`
  with the default config.
- **Manipulators** (educational) — `coin.manipulators` (empty by default)
  takes the same fields as `traders`, with manipulation strategies
  registered in `MANIPULATION_STRATEGIES`: `pump_and_dump` (accumulate →
  pump → dump on a tick schedule) and `wash_trader` (trades with itself to
  inflate reported volume). They are ordinary wallet-holding traders, so
  conservation still holds. `--scenario pump_and_dump|wash_trading` swaps
  in a ready-made setup (the pump-and-dump preset also adds the
  momentum-chasing "marks" it sells to); the CLI then prints the
  manipulators' P&L, the organic traders' combined P&L, the peak price and
  the wash share of reported volume.
- **News events** — `coin.events` (none by default): scheduled events
  and/or random ones (`random.probability` per tick). `--events` runs a
  small demo schedule; `--random-events` sets a probability of 0.1 per
  tick. Events never set a price; they shift traders' sentiment and
  participation (both modes) and random-walk volatility. Runs with events
  print a descriptive "Event analysis" table.
- **Participant psychology** — off by default and not part of the config:
  `--psychology` (or `build_coin_simulator(..., psychology=True)`) gives
  traders a per-tick fear/FOMO/conviction/uncertainty state that bends
  each strategy's own rules, and prints descriptive "Psychology
  observations". Its momentum term was calibrated in Phase 18; open
  model-shape questions (component saturation) are recorded in the
  roadmap. (The CLI's run header and observations heading still say
  "calibration deferred"; that wording predates the calibration and is
  kept because it is part of the pinned CLI compatibility output.)
- **Crowd-flow and breadth channels — experimental, off by default.**
  `build_coin_simulator` accepts `crowd_observation`, `crowd_response`,
  `crowd_direction`, `breadth_observation` and `breadth_response`
  (Python API only; no CLI flag, dashboard control or config field).
  They were built for the Phase 19 realism experiments, which established
  individual responses to crowd information but **not**
  participant-to-participant propagation or herding. They are research
  switches, not a validated behavioral mechanism — see
  [`docs/PHASE_19_FINAL.md`](docs/PHASE_19_FINAL.md).

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the AMM math, the
fee/slippage/liquidity model, how each manipulation scheme plays out in
each pricing mode, and the news-event, psychology and whale models.

### Analytics and the report

Post-run analytics (`crypto_simulator/analytics/`) read a finished run's
recorded ticks and never feed back into the simulation. Each is a Python
function over `sim.history`:

| Function | Describes |
|---|---|
| `analyze_market` | returns, volatility, drawdown, market cap, volume decomposition (background, whale, organic, manipulator, wash — each counted once), turnover, AMM pool activity |
| `analyze_traders` | per-trader and per-strategy fills, volumes, VWAP, flows, fees, equity and P&L |
| `analyze_whales` / `analyze_whale_activity` | per-whale behavior, volume shares, allocation gaps, cohort co-fill (needs whale observation) |
| `analyze_events` / `analyze_event_windows` | each event's pre/active/decay/post windows, each summarised by `analyze_market` |
| `analyze_psychology` / `analyze_psychology_market` | psychology components alongside price, return and volume; declared same-tick and lag-1 associations (needs psychology) |
| `analyze_manipulation` | pump-and-dump phases and wash trading, identified only from the simulator's own recorded labels |
| `analyze_regimes` | descriptive labels for fixed tick windows (direction, volatility, volume, market state) |
| `build_report` / `render_report` | one frozen `SimulationReport` holding all of the above over one tick scope, and its plain-text rendering |

`--report` prints the rendered report after a CLI run and changes nothing
about the run. All analytics are **descriptive only**: associations, never
causes; observed windows, never forecasts or trading signals; and an
unavailable figure is `None` ("n/a"), never a manufactured zero. The full
definitions are in the Phase 9 section of the roadmap.

### Market conditions

A **market condition** is a named configuration preset — a set of values
a user could have written in `default.yaml` themselves:

```bash
python scripts/simulate_coin.py --ticks 200 --market-condition bull
python scripts/simulate_coin.py --ticks 200 --market-condition bear --scenario pump_and_dump
python scripts/simulate_coin.py --ticks 200 --market-condition meme --batch 50
```

| Preset | What it configures |
|---|---|
| `bull` | random news weighted to the catalog's **positive** categories, arriving more often, with the random walk reading sentiment as upward drift |
| `bear` | weighted to the **negative** categories; the same positive drift coefficient turns their negative sentiment into downward drift |
| `meme` | frequent, severe, high-attention news of **both** tones over a much noisier walk |

- **It tilts the odds; it does not decree an outcome.** Across a batch,
  `bull` runs sit above `bear` runs and above no-condition runs. Any
  single seeded run may still fall — a test asserts that some `bull` runs
  *do*, because a preset that never fell would be overstating itself.
- **`meme` is a volatility regime, not a direction.** Its realized
  volatility is several times the baseline. Its median outcome is lower
  too, but that is volatility drag under a multiplicative walk, not a
  downward tilt in the news.
- **AMM caveat (a hard constraint).** `CoinSimulator` *rejects* a nonzero
  `drift_per_sentiment` in AMM mode, so a preset applies drift only to a
  random-walk run. In AMM the preset still changes which news arrives and
  how often, and price moves only as traders react — weaker and indirect.
- **Not a manipulation scenario.** `--scenario` replaces the
  *participants*; a market condition touches no participant. Different
  axes, and they compose — a pump can run in a bear market.
- **Precedence:** saved scenario → market condition → explicitly typed
  event flags → other typed flags. So `--random-events` overrides a
  preset's news rate, and `--market-condition` typed on the command line
  overrides one stored in a scenario.
- **Deterministic.** A preset only rewrites settings before the run; it
  draws nothing. Omitting it changes nothing, and saved scenarios carry it
  inside their existing `params_json`.

### Saving a scenario (reusable configurations)

A **scenario** is a named set of simulation *inputs* — what to ask for —
saved so it can be asked for again:

```bash
# save the configuration this run used
python scripts/simulate_coin.py --ticks 40 --pricing-mode amm --no-whales \
    --scenario pump_and_dump --seed 48291 --save-scenario amm-pump

# run it again, without retyping any of it
python scripts/simulate_coin.py --load-scenario amm-pump

# same scenario, one field changed for this run only
python scripts/simulate_coin.py --load-scenario amm-pump --ticks 100
```

- **A scenario is not a run.** `coin_runs` (below) stores what a
  simulation *produced*; `coin_scenarios` stores what to *ask for*. And
  neither is a checkpoint: loading a scenario rebuilds the request and
  runs it again from tick one — it does not resume a paused simulator.
  Because the seed is part of what was saved, that rerun reproduces the
  original run exactly.
- **Careful with the word "scenario".** The `--scenario` flag selects a
  *manipulation preset* (`pump_and_dump`, `wash_trading`) and is **one
  field** of a configuration. `--save-scenario`/`--load-scenario` store
  and recall an **entire** configuration, which may or may not name such
  a preset.
- **Precedence is one rule:** the loaded scenario is the baseline, and
  any flag you type on that command line replaces that field. A flag you
  don't type keeps the scenario's value — including when the scenario's
  value happens to differ from the flag's own default. Typing a flag
  counts even if you type its default value.
- **What gets saved.** Every field of the request: ticks, pricing mode,
  traders/whales, manipulation preset, market condition, events, random
  events, psychology, whale observation, and the seed. `--pricing-mode`
  and `--seed` are optional on the command line, so a save records the
  values that *actually ran* rather than "whatever the config says" —
  otherwise an edit to `default.yaml` would silently change what a
  scenario means.
- **Where it lives.** The configured database (`database.path`, default
  `data/simulator.db`, or `CRYPTOSIM_DB_PATH`), created on first use and
  gitignored. A run with neither scenario flag never opens it.
- **Saving validates.** A configuration is checked before it is written,
  so a scenario that could not be run is never stored as though it could.
  `--ticks` itself is unbounded for a plain run, but a *saved* scenario is
  held to the request bound (2000), so that anything saved can also be
  run from the browser.

### Running a batch

The same configuration, many times, under independent deterministic
seeds:

```bash
python scripts/simulate_coin.py --ticks 50 --batch 100 --seed 48291
python scripts/simulate_coin.py --load-scenario amm-pump --batch 50
```

```text
Batch of 4 runs
  configuration  : 10 ticks, random_walk
  base seed      : 48291
  seed stride    : 10000

 run          seed  simulation id     ticks  result
------------------------------------------------------------
   0         48291  8872f93a721b7e98     10  ok
   1         58291  09e3832d1cb5bc5b     10  ok
   ...
  completed      : 4 of 4
```

- **Seeds.** Run *i* uses `base_seed + i * 10000`, through the same
  derivation every participant seed already comes from. The stride is
  deliberate: a run's base seed is *also* the origin its whales, traders
  and event generator are offset from, so spacing runs by one would hand
  one run's price engine a seed another run already gave a whale. The
  base is `--seed` if given, else the loaded scenario's seed, else the
  configured seed — a batch is **never** seeded from a drawn number, so
  the same command always produces the same batch.
- **Reproducible run by run.** Run *i* of a batch is exactly the single
  run at run *i*'s seed — the summary prints each seed, so any run can be
  re-run on its own with `--seed`.
- **Run count.** 1–1000 on the command line (200 in the dashboard). The
  upper bound is about memory (every run's analytics are kept), not about
  the simulator.
- **Failures are collected, not swallowed.** A run that raises is listed
  as `FAILED` with its error, the remaining runs still execute, and the
  command exits non-zero.
- **Serial, on purpose.** A run takes a few milliseconds — 1000 runs of
  20 ticks takes about 1.4 s — so parallelism would buy little while
  putting ordering and reproducibility at risk.
- **Nothing is stored.** A batch writes no database row.
- **Scenarios work as usual.** `--load-scenario` supplies the baseline
  and typed flags override it, exactly as for a single run. `--batch`
  itself is *not* part of a saved scenario — a scenario says what to
  simulate, not how many times. `--report` describes one run and is
  refused with `--batch`.
- **In Python:** `run_batch(params, runs, runner=run_simulation,
  base_seed=...)` returns a `BatchResult` holding one `BatchRun` per run
  (index, seed, payload, error). The runner is injected, so the batch
  layer orchestrates without owning a second simulation engine.

### Aggregate statistics across a batch

Every `--batch` run prints a distribution per metric after the per-run
list:

```text
Aggregate statistics
  runs           : 5 of 5 succeeded
  percentiles    : linear interpolation at rank p/100 x (n-1); p50 is the median
  std dev        : sample (n-1), blank below two observations

  metric                    n         mean       median        stdev ...
  close_price               5      1.00721     0.996345     0.106988 ...
  cumulative_return         5   0.00721314  -0.00365495     0.106988 ...
```

- **The reports' own numbers, never recomputed.** Each metric is a field
  `MarketSummary` already defines — the return is its `cumulative_return`
  (`close/open − 1`), the volatility its sample standard deviation of log
  returns, the drawdown its own. Nothing is re-derived from prices, so an
  aggregate can never drift from what a run's own report says. There is
  deliberately **no absolute price change**: the report defines none.
- **Metrics:** open/close/high/low/mean price, cumulative and log return,
  mean return, volatility, realized volatility, max and end drawdown,
  market cap (start and end), total volume, turnover, participant
  turnover, average trade size and trader VWAP.
- **Definitions.** Mean is `fsum(values)/n`. Median is
  `statistics.median`. Percentiles (P05, P25, P50, P75, P95) use the
  project's single convention — linear interpolation at rank
  `p/100 × (n−1)`, shared from `analytics/_series.percentile` — so **P50
  is exactly the median**. Standard deviation is the **sample** one (n−1),
  and is `n/a` below two observations. An undefined dispersion is never
  reported as zero.
- **Missing stays missing.** A per-run metric is `float | None`; runs that
  could not compute it contribute no observation, so a metric's `n` can be
  lower than the number of successful runs. Failed runs count as failed
  and contribute nothing.
- **Descriptive only.** No confidence intervals, no significance tests,
  no forecasts, and no claim that one configuration beats another.
- **In Python:** `aggregate_batch(batch_result) -> AggregateStatistics`,
  or `aggregate_values(name, values) -> MetricStatistics` for the pure
  statistics. Stored values keep full precision; rounding happens only in
  the CLI's formatting.

### Stress testing

Demanding configurations, run through the ordinary entry points and then
checked for having come out intact:

```bash
python scripts/stress_test.py            # the ordinary cases (~2s)
python scripts/stress_test.py --heavy    # plus the costly ones (~5s more)
python scripts/stress_test.py --list     # what would run, without running it
python scripts/stress_test.py --only amm # cases whose name contains "amm"
```

- **It tests the simulator; it does not extend it.** Every case is
  expressed in options the simulator already accepts, and every run goes
  through `run_simulation` / `run_batch`.
- **Boundaries tested are the simulator's own:** ticks 1 and 2000
  (`MAX_TICKS`), seeds 0 and 2³²−1, batches of 1 and 1000
  (`MAX_BATCH_RUNS`), both pricing modes, both manipulation presets, and
  the feature combinations — each also one step **outside** the bound,
  where validation must refuse it (a refusal is a pass for those cases).
- **The 200-trader case is the harness's ceiling, not the simulator's.**
  `coin.traders` has no validated maximum.
- **A case passes when** it completes the ticks it asked for, its report
  holds no non-finite value, its prices are valid, its volumes and counts
  are non-negative, its price series is in tick order — and its
  **accounting still balances**: exactly in AMM mode (`Decimal`), within
  1e-9 relative in random-walk mode (float wallets accumulate rounding; a
  real loss still fails). Selected cases are run twice and must match.
- **Failures are structured**, and **nothing is persisted**.
- **Cost.** The ordinary tier is part of `pytest`; the two costly cases
  are marked `slow` (`pytest -m slow` or `--heavy`).

> These tests exercise selected demanding configurations within the
> simulator's defined limits. They do not prove the simulator correct
> outside them, and say nothing about production-grade safety — this is a
> fictional simulator, not a trading system.

### Saving a coin run (persistence)

A coin simulation is ordinarily ephemeral. `CoinRunRepository` stores a
*finished* run in SQLite so it can be read back later. This is a Python
API only — neither the CLI nor the dashboard saves runs.

```python
from crypto_simulator.data import CoinRunRepository, connect, init_db
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation

payload = payload_to_dict(run_simulation(SimulationParams(ticks=50, random_seed=48291)))

conn = connect("data/simulator.db")   # ":memory:" works too
init_db(conn)                          # idempotent; never drops existing runs
repo = CoinRunRepository(conn)

run_id = repo.save(payload)            # one transaction: the run and all its ticks
repo.list_runs(limit=10)               # stored runs, newest first (metadata only)
restored = repo.load(run_id)           # == payload, exactly
conn.close()
```

- **Where it lives.** The same SQLite database and connection layer
  (`crypto_simulator/data/database.py`) the trading-platform track uses.
  The coin tables (`coin_runs`, `coin_run_ticks`, and `coin_scenarios` for
  saved scenarios) are additions to `crypto_simulator/data/schema.sql`;
  the two tracks share a file and never join against each other.
  `data/*.db` is gitignored, so runs stay local.
- **What is stored.** The run's metadata and its ordered per-tick series
  (tick, price, market cap, volume) as columns, and the request and the
  analytics report as JSON text. Nothing is pickled.
- **What is not stored.** Individual fills, event records, pool reserves,
  per-participant state and the dashboard's tick-level series.
- **Saving is not checkpointing.** Loading gives a finished result back;
  it does not resume a live `CoinSimulator`.
- **Persistence observes, it never influences.** A simulation is
  identical whether or not it is saved — a test asserts exactly that.

### Dashboard

```bash
streamlit run crypto_simulator/app.py
```

The app opens on the coin simulator, the **Simulate** page. (The dormant
multi-asset experiment is a separate page under **Legacy**.) Simulate has
three independent panels:

- **Single run.** Controls: ticks (1–2000), pricing mode, manipulation
  scenario, traders, whales, news events, random news events, psychology,
  whale observation, and an optional random seed ("Set the random seed",
  off by default, which uses the configured seed). **Run simulation**
  renders the run's report in seven sections — market summary (with the
  price chart), traders, whales, events, psychology, manipulation and
  market regimes — followed by **tick-level views**: synthetic OHLC
  candles over 5/10/20/50 recorded ticks (aggregated from simulation-tick
  prices; not exchange candles), per-tick volume by component, recorded
  AMM pool state, and recorded event state.
- **Batch runs.** Runs the configuration set above 1–200 times (default
  20) under derived seeds: a summary with any failures, each aggregated
  metric's range, price-path bands across runs, and per-run histograms.
- **Scenario comparison.** Choose pricing modes, manipulation scenarios
  and market conditions; every combination is one configuration, run
  under a shared base seed (at most 400 simulations in total; AMM with
  whales is refused before running). Shows each configuration's spread
  side by side, in the order selected — never ranked.

What the dashboard does **not** offer: a market-condition control for a
single run or a batch (only the comparison panel has one), scenario
save/load, or saving runs. A seeded dashboard run is the same run the CLI
performs with those options and that seed, and the tests require the two
to agree bit for bit.

The dashboard is a **read-only observer**: every figure on screen is a
value the report (or the recorded tick series) already holds, passed
through a format spec — nothing is recomputed in the frontend, an
unavailable figure says so rather than showing zero, and the wording is
descriptive, never causal. The full design record is in the Phase 10 and
Phase 20 sections of the roadmap.

### Configuration

Default settings live in `crypto_simulator/config/default.yaml`: the
`coin:` section (the active track), plus `simulation` (including
`random_seed`), `market` (the trading-platform track's assets), `database`,
`ui` and `logging`. A few values can be overridden with environment
variables, mapped in `crypto_simulator/config/settings.py`:

| Variable | Overrides |
|---|---|
| `CRYPTOSIM_DB_PATH` | `database.path` |
| `CRYPTOSIM_STARTING_BALANCE` | `simulation.starting_balance` |
| `CRYPTOSIM_LOG_LEVEL` | `logging.level` |
| `CRYPTOSIM_RANDOM_SEED` | `simulation.random_seed` |
| `CRYPTOSIM_PRICING_MODE` | `coin.pricing_mode` |

They are read from the **process environment** only — the simulator does
not load a `.env` file. `.env.example` lists them; to use a copy, export
it into your shell first (for example `set -a; source .env; set +a`), or
set a variable for one command:

```bash
CRYPTOSIM_PRICING_MODE=amm python scripts/simulate_coin.py --ticks 20 --no-whales
```

## Documentation

| Document | Covers |
|---|---|
| [`README.md`](README.md) | This overview: purpose, installation, quickstart, capabilities, testing, structure |
| [`CHANGELOG.md`](CHANGELOG.md) | What each release contains, its compatibility notes and known limitations |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The two tracks, layering, the run data flow and tick loop, state and persistence boundaries, invariants |
| [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) | Seeds and their precedence, determinism scope, batch seed derivation, compatibility fingerprints and levels, CI |
| [`docs/CLI.md`](docs/CLI.md) | Every `scripts/simulate_coin.py` option, scenarios, batches, stress testing, exit codes, environment variables |
| [`docs/DASHBOARD.md`](docs/DASHBOARD.md) | Launching the dashboard, every control and view, runtime state, limitations |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | The phase-by-phase design record: every phase's scope, decisions, models (AMM math, events, psychology, whales, analytics definitions, dashboard design) and verification |
| [`docs/PHASE_19_FINAL.md`](docs/PHASE_19_FINAL.md) | The Phase 19 realism/feedback report: what was established, what was not, and why |
| [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) | The steps to verify and publish a release |

## Testing and CI

```bash
pytest                                          # the full suite, minus slow tests
pytest -m slow                                  # only the costly stress cases
python scripts/compat/compare_checkpoints.py    # checkpoint compatibility comparison
pytest --cov --cov-report=term-missing          # coverage report
```

- **`pytest`** runs everything except tests marked `slow` (deselected by
  default in `pyproject.toml`), in about a minute.
- **`pytest -m slow`** runs the three heavy stress cases (maximum ticks ×
  traders, maximum batch).
- **`compare_checkpoints.py`** extracts each historical checkpoint
  commit with `git archive`, runs the compatibility digest grid
  (`tests/compat/grid.py`) against it in a fresh subprocess, and compares
  every result with the pinned digests in
  `tests/compat/pinned_digests.json`. Every checkpoint should report
  `IDENTICAL`. It needs the full git history (not a shallow clone), and
  its `--write-pins` option re-pins deliberately — it is never a fix for
  a failing comparison.

**CI.** GitHub Actions (`.github/workflows/ci.yml`) runs on every push and
pull request to `main`, on **macOS** runners:

| Job | Python | Runs |
|---|---|---|
| Test suite | 3.12 and 3.13 | `pytest` |
| Slow tests | 3.13 | `pytest -m slow` |
| Compatibility checkpoints | 3.13 (full history) | `compare_checkpoints.py` |
| Coverage | 3.13 | `pytest --cov`, reported in the job summary and uploaded as the `coverage-html` artifact (reported, not gated) |

CI is macOS-only because macOS is where the pinned digests and
fingerprints were produced; see [Reproducibility](#reproducibility).

## Project structure

```
crypto_simulator/       The package
├── core/               The simulation: CoinSimulator, the random-walk engine,
│   │                   volume model, whales and cohorts (plus the dormant
│   │                   MarketEngine/OrderEngine/portfolio)
│   ├── traders/        Trader strategies, manipulators, settlement, registry
│   ├── liquidity/      Constant-product AMM pool
│   ├── events/         News events, catalog, timeline and random generation
│   └── psychology/     Psychology state and market signals (opt-in)
├── models/             Data classes: Coin, Wallet (coin track); Asset, Order,
│                       Trade, Account (trading-platform track)
├── services/           Builds and runs simulations: build_coin_simulator,
│                       SimulationParams, scenarios, market conditions, batch
├── analytics/          Post-run analytics, the report, aggregate statistics,
│                       the tick-level series and cross-run price paths
├── stress/             The stress-test cases, checks and runner
├── data/               SQLite schema, connection, repositories (coin runs,
│                       coin scenarios, trading-platform tables)
├── dashboard/          The coin dashboard: runs a simulation, serializes the
│                       report, renders one section per module
├── visualization/      Plotly chart builders (pure functions) and the
│                       shared chart style (style.py)
├── config/             default.yaml and settings loading (env overrides)
├── utils/              Logging
└── app.py              Streamlit entry point: pages and navigation
scripts/
├── simulate_coin.py    The coin-simulation CLI
├── stress_test.py      The stress-test CLI
└── compat/             compare_checkpoints.py, the checkpoint comparison tool
tests/                  pytest suite, mirroring the package layout
└── compat/             The compatibility digest grid and its pinned digests
examples/               Runnable example scripts (seeded run, market conditions, batch)
docs/                   Architecture, reproducibility, CLI and dashboard guides;
                        roadmap, phase reports and release checklist
CHANGELOG.md            Release notes
data/                   Local SQLite database (gitignored, created on first use)
.github/                CI workflow, Dependabot, pull request template
```

**Layering rule.** The simulation (`core/`, built by `services/`)
produces the state and the recorded ticks. `analytics/` observes that
output; `dashboard/` observes the simulation's output and the analytics.
Observers never feed state back into the simulator: nothing in `core/`,
`services/`, `config/`, `models/` or `data/` imports `analytics/` or
`dashboard/`, and structural tests enforce this (for example
`tests/analytics/test_events_simulation.py` and
`tests/dashboard/test_data.py`).

## Reproducibility

- **Seeds.** Every run is deterministic given its inputs. Without
  `--seed` a run uses `simulation.random_seed` from the configuration;
  `--seed N` (0–4294967295) overrides it for one run and is printed in the
  run's header. The seed is the base every participant seed — whales,
  traders, manipulators, the random-event generator — is derived from, so
  it is selected, not added: there is no second random-number system. The
  dashboard's seed control takes the same seeds with the same meaning, so
  a run seeded on the command line reproduces in the browser and vice
  versa. Saved scenarios store the seed; batches derive theirs from one
  base seed (see [Running a batch](#running-a-batch)).
- **Scope of "identical".** Bit-for-bit reproduction is verified on
  **macOS** with **Python 3.12+**. On Linux, the random walk's
  floating-point maths (`random.gauss`, `math.exp`) can differ from
  Apple's libm in the last bit, and the simulation amplifies that into
  different results — so the same seed is not guaranteed to give the same
  run across platforms, and CI stays on macOS until a cross-platform
  fingerprint strategy is decided.
- **Why Python 3.12+.** Python 3.12 changed built-in `sum()` of floats to
  compensated summation. Under 3.11 the AMM fingerprint comes out
  different from the pinned one, so the support floor was raised rather
  than the pins or the numerics changed.
- **Compatibility checks.** Two builder fingerprints (random-walk and
  AMM) and a digest grid over historical checkpoints are pinned in
  `tests/compat/`; `pytest` checks the current code against them and
  `compare_checkpoints.py` checks every historical checkpoint (see
  [Testing and CI](#testing-and-ci)). A deliberate behavior change (such
  as Phase 18's psychology calibration) is recorded as a calibration
  boundary rather than by overwriting the old pins.
- **Dependencies** are version ranges, not a lock file, so an exact
  environment is not pinned.

## Disclaimer

This software is provided for educational and entertainment purposes only.
Nothing in this repository is financial advice, and nothing in this
repository can place a real trade, hold a real asset, or interact with a
real exchange. Any resemblance between simulated prices and real market
data is coincidental and unsuitable for real-world decision making.
