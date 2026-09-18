# Crypto Market Simulator

A **fictional, educational** cryptocurrency market simulator.

> ⚠️ **This project is a simulation only.** It does not connect to any real
> exchange, does not execute real trades, and does not move real money. All
> prices, order books, and balances are synthetically generated for learning
> and experimentation purposes.

## Why this exists

A sandbox for exploring market mechanics, portfolio behavior, and trading
strategy ideas without any financial risk — built entirely on synthetic data.

## Tech stack

| Concern            | Choice     |
|--------------------|------------|
| Language           | Python 3.11+ |
| Persistence        | SQLite     |
| Charts             | Plotly     |
| UI                 | Streamlit  |
| Testing            | pytest     |

## Architecture

```
crypto_simulator/
├── config/         Settings loading (YAML + env overrides)
├── models/         Plain data classes: Asset, Order, Trade, Account
├── data/           SQLite schema, connection handling, repositories (CRUD)
├── core/           Simulation engine: clock, synthetic market data, order
│                   matching, portfolio math — all storage-agnostic
│   ├── traders/    Rule-based trader agents (and manipulators) for the
│   │               coin economy sim
│   ├── liquidity/  Constant-product AMM pool (alternative pricing mode)
│   ├── events/     Fictional news events, their timeline and random generation
│   └── psychology/ Market psychology state and signals (opt-in)
├── services/       Orchestrates core + data for the UI layer
├── analytics/      Post-run market, event, psychology and whale analysis (reads results; never feeds back)
├── dashboard/      Coin-economy dashboard: runs one simulation, serializes its
│                   SimulationReport, renders it (read-only observer)
├── visualization/  Plotly chart builders (pure functions)
├── utils/          Logging and shared helpers
└── app.py          Streamlit entrypoint (presentation only)
```

**Data flow:** `app.py` → `services/` → `core/` + `data/` → SQLite.
`models/` are the shared vocabulary between layers. `config/` is loaded once
at startup and passed down — no module reaches for global state on its own.

The "no real exchange" guarantee is structural: `core/market_engine.py` is
the only source of prices (synthetically generated), and there is no network
client anywhere in this codebase.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for what's implemented vs. planned.

## Project status

🚧 **Phase 1 — Synthetic Market Data.** Module structure, configuration,
persistence schema, and Streamlit shell are in place, and the market engine
now generates and persists synthetic per-asset prices (GBM random walk,
seeded for reproducibility) with a candlestick dashboard tab. Order matching
and portfolio P&L are still stubbed — see the roadmap.

## Getting started

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for running tests
pip install -e .                      # so `streamlit run` can import the package

# 3. Run the test suite
pytest

# 4. Launch the app
streamlit run crypto_simulator/app.py
```

## Coin economy simulation

A standalone, minimum-viable single-coin simulation (separate from the
multi-asset trading engine above) lives in `core.coin_simulator`. Run it
directly:

```bash
python scripts/simulate_coin.py --ticks 20
python scripts/simulate_coin.py --ticks 20 --no-traders   # whales only
python scripts/simulate_coin.py --ticks 20 --pricing-mode amm --no-whales
python scripts/simulate_coin.py --ticks 30 --pricing-mode amm --no-whales --scenario pump_and_dump
python scripts/simulate_coin.py --ticks 30 --scenario wash_trading
python scripts/simulate_coin.py --ticks 40 --events                # demo news schedule
python scripts/simulate_coin.py --ticks 40 --random-events         # random news events
python scripts/simulate_coin.py --ticks 40 --events --psychology   # psychology observations
python scripts/simulate_coin.py --ticks 40 --whale-observation     # whale observations
python scripts/simulate_coin.py --ticks 60 --events --psychology --report  # + analytics report
python scripts/simulate_coin.py --ticks 20 --seed 48291            # reproduce an exact run
```

**Reproducibility (`--seed`).** Every run is deterministic: the same seed
and the same flags always produce the same run. Without `--seed` a run
uses `simulation.random_seed` from the configuration, exactly as it
always has; `--seed N` overrides that for one run without editing
`default.yaml`, and the seed it used is printed in the run's header.
Naming the configured seed explicitly gives the configured run, so
turning the flag on changes nothing by itself. The seed is the base the
simulator already derives every participant's seed from — whales,
traders, manipulators and the random-event generator all follow from it —
so it is selected, not added: `--seed` introduces no second random-number
system. The dashboard's seed control (below) takes the same seeds and
means the same thing, so a run seeded on the command line reproduces in
the browser and vice versa.

Everything comes from the `coin:` section of
`crypto_simulator/config/default.yaml`:

- **Coin economics** — symbol, supply, starting price, volatility.
- **Whales** — large holders that can move price with one outsized trade.
  Optionally funded (`starting_cash`, random-walk mode): the whale then
  settles against the market reserve and can `accumulate` or `distribute`
  toward a `target_coin_fraction`. Funded whales can also be paced
  (`cooldown_ticks`, `min_trade_interval_ticks`), lean harder or softer
  (`intent_strength`), follow a fixed behavior timetable (`cycle`), and
  be moved between behaviors explicitly (`Whale.set_behavior`). Several
  funded whales can share one timetable as a **cohort** — Python API only
  for now (`CoinSimulator(whale_cohorts=[WhaleCohort(...)])`) — which is a
  fixed schedule, not whales reacting to the market or to each other.
  The demo's `--whale-observation` flag records what each whale did each
  tick and prints a descriptive summary (`analytics.analyze_whales`).
  Whales read no news or psychology.
- **Trader agents** — rule-based participants (`retail`, `momentum`,
  `dip_buyer`, `panic_seller`, `long_term_holder`), each with starting
  cash/coins, a per-tick trade probability, a max trade size, a risk
  tolerance (fraction of balance committed per trade) and
  strategy-specific `params`. Their trades settle against a market
  reserve (`market_reserve_cash` plus all unallocated coins), so no coins
  or cash are ever created, and their net flow moves price.

- **Pricing mode** — `pricing_mode: random_walk` (default: GBM random walk
  plus linear whale/trader price impact) or `amm` (a constant-product
  `x · y = k` liquidity pool seeded by the market reserve; traders swap
  through it with fees and slippage, and price moves only on trades).
  Configure the pool under `amm:` (`pool_coin_reserve`, `fee_rate`), or
  set `CRYPTOSIM_PRICING_MODE`. Whales aren't supported in AMM mode yet.

- **Manipulators** (educational) — `coin.manipulators` (empty by default)
  takes the same fields as `traders`, with manipulation strategies:
  `pump_and_dump` (accumulate → pump → dump on a tick schedule) and
  `wash_trader` (trades with itself to inflate reported volume). They're
  ordinary wallet-holding traders, so conservation still holds.
  `--scenario pump_and_dump|wash_trading` swaps in a ready-made setup; the
  pump-and-dump preset also adds the momentum-chasing "marks" it sells to.
  The demo then prints the manipulators' P&L, the organic traders'
  combined P&L, the peak price, and the wash share of reported volume.

- **News events** — `coin.events` (no events by default): scheduled
  events and/or random ones (`random.probability` per tick). Events never
  set a price; they shift traders' sentiment and participation (both
  modes) and random-walk volatility. Runs with events print a descriptive
  "Event analysis" table.

- **Participant psychology** — off by default and not part of the config:
  `build_coin_simulator(..., psychology=True)` gives traders a per-tick
  fear/FOMO/conviction/uncertainty state that bends each strategy's own
  rules. Its calibration is deferred (see the roadmap). The demo's
  `--psychology` flag turns it on and prints descriptive "Psychology
  observations" (`analytics.analyze_psychology`).

- **Market analytics** (Python API, post-run) —
  `analytics.analyze_market(sim.history, initial_price=..., total_supply=...)`
  describes a finished run or a window of one: returns, volatility,
  drawdown, market cap, a volume breakdown (synthetic background, whale,
  organic, manipulator and wash volume, each counted once), turnover and
  AMM pool activity. It only reads the recorded ticks; the demo CLI
  prints it as part of `--report`.
- **Trader analytics** (Python API, post-run) —
  `analytics.analyze_traders(sim.history, start_balances=..., end_balances=..., initial_price=...)`
  summarises each trader and each strategy: fills, buy/sell/wash volume,
  VWAP, net flows, requested versus filled, AMM fees, and — given
  `{trader_id: (cash, coins)}` wallet snapshots taken before and after the
  run — equity and P&L exactly as the demo prints them.
- **Whale activity analytics** (Python API, post-run) —
  `analytics.analyze_whale_activity(sim.history)` (needs
  `whale_observation=True`) builds on `analyze_whales` and
  `analyze_market` rather than duplicating them: each whale's volume
  share of the market, first/last fill ticks, allocation-gap statistics,
  when a target was first reached, per-behavior volume aggregation, and
  per-cohort volume with a descriptive fill-simultaneity ("co-fill")
  measure. Purely descriptive — no coordination, herding or causal claim.
  `None` (never a manufactured zero) wherever the underlying observations
  don't cover it; empty for AMM runs, which reject whales.
- **Event-window market path analytics** (Python API, post-run) —
  `analytics.analyze_event_windows(sim.history, events, initial_price=...)`
  builds on `analyze_events` and `analyze_market` rather than duplicating
  them: it splits each event's own lifecycle into four non-overlapping
  windows (pre-event, active, decay, post-event, plus a combined
  active+decay "effect" window) and hands each to `analyze_market`
  unchanged, so every price, return, drawdown and volume figure is Step
  1's exact definition. Descriptive only — "observed during/before/after",
  never an effect or a trading cue. `None` for a window with nothing to
  request by construction (no decay ticks, or an event starting on tick
  1), and an honest `complete=False` (never padded or bridged) for one
  that could exist but has fewer recorded ticks than requested.
- **Psychology-market co-movement analytics** (Python API, post-run) —
  `analytics.analyze_psychology_market(sim.history, initial_price=...)`
  (needs `psychology=True`) builds on `analyze_psychology` and
  `analyze_market` rather than duplicating them: per-tick psychology
  alongside price, return, volume and event context; a fixed, declared
  set of same-tick and lag-1 Pearson correlations (`None` with a reason —
  insufficient pairs or zero variance — never `NaN`); and low/high
  grouped market averages per component. Descriptive only — "observed
  alongside", never a cause, a forecast, or a measure of effectiveness.
  Aligned strictly by tick number (never bridged across a missing tick).
- **Manipulation analytics** (Python API, post-run) —
  `analytics.analyze_manipulation(sim.history, initial_price=...)` builds
  on `analyze_market` and `analyze_traders` rather than duplicating them:
  identification is registry-based only (`TraderTrade.wash` /
  `MANIPULATION_STRATEGIES`), never inferred from size or price movement.
  Pump-and-dump phases (`accumulate`/`pump`/`dump`) come straight from
  each fill's own recorded `reason`, one summary per manipulator id with
  its price/return/drawdown from `analyze_market` over its observed span;
  wash-trading gets a buy/sell-split volume, notional and active-tick
  aggregate; manipulation and organic activity are compared side by side.
  `manipulation_volume` is proven never to double-count wash against
  `analyze_market`'s volume decomposition. Descriptive only — no claim of
  profit, success, coordination, or that a scenario's full run was
  captured by the supplied ticks.
- **Descriptive market regimes** (Python API, post-run) —
  `analytics.analyze_regimes(sim.history, initial_price=..., window_size=20)`
  labels each fixed tick-number window (1–20, 21–40, …) along four
  independent dimensions: direction (`rising`/`falling`/`flat`: the net
  consecutive log return against the window's own realized volatility),
  volatility and volume (`low`/`normal`/`high` against the quartiles of
  *earlier* complete windows only), and market state
  (`at_high`/`drawdown`/`recovery` against the running high so far). Every
  figure is `analyze_market`'s own; a label never depends on anything after
  its window, never bridges a missing tick, and is `None` where the data
  can't support it. An incomplete final window is kept with
  `complete=False`. Events, psychology, whale observations and
  manipulation volume are recorded alongside as context and never feed a
  label. **Regime labels describe observed historical market conditions
  and are not predictions or trading signals.**
- **Unified report data** (Python API, post-run) —
  `analytics.build_report(sim.history, events=..., initial_price=..., start_tick=..., end_tick=...)`
  returns one frozen `SimulationReport` holding the market, trader, whale
  activity, event-window, psychology-market, manipulation and regime
  analytics, each exactly what its own function returns over one shared
  tick scope. It calculates nothing itself, so unavailable data stays as
  its function reports it (`event_windows` is `None` without an event
  timeline).
- **Analytics report** (CLI, opt-in) — add `--report` to any
  `simulate_coin.py` run to print a plain-text summary of that report
  after the usual output (`analytics.render_report(report)` in Python).
  Without the flag the CLI output is unchanged. Unavailable sections say
  so rather than showing zeros, and the report is descriptive only: no
  causes, forecasts or trading advice.

The demo prints each tick, a per-trader wallet/P&L table, and an
accounting check showing total coins and cash are unchanged (exactly, in
AMM mode, where the pool keeps `Decimal` accounting). To add a strategy,
subclass `TraderAgent` in `crypto_simulator/core/traders/` and register it
in `TRADER_STRATEGIES` (manipulation strategies go in
`MANIPULATION_STRATEGIES`). See [`docs/ROADMAP.md`](docs/ROADMAP.md) for
the AMM math, fee/slippage/liquidity model, how each manipulation scheme
plays out in each pricing mode, the news-event and psychology models, and
what's planned next.

### Saving a coin run (persistence)

A coin simulation is ordinarily ephemeral — it exists for as long as the
process that ran it. `CoinRunRepository` stores a *finished* run in
SQLite so it can be read back later:

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

- **Where it lives.** The same SQLite database and the same connection
  layer (`crypto_simulator/data/database.py`) the trading-platform track
  uses — one `connect`/`init_db`, no second database system. The coin
  tables (`coin_runs`, `coin_run_ticks`) are additions to
  `data/schema.sql`; the two tracks share a file and never join against
  each other. `data/*.db` is gitignored, so runs stay local.
- **What is stored.** The run's metadata and its ordered per-tick series
  (tick, price, market cap, volume) as columns, and the request and the
  analytics report as JSON text. Columns for what later phases will
  aggregate over; JSON for what is read whole. Nothing is pickled.
- **What is not stored.** Individual fills, event records, pool reserves
  and per-participant state get no tables of their own — the report's
  analytics already describe them, and nothing yet reads the raw records.
- **Saving is not checkpointing.** A stored run is a *finished result*.
  Loading gives that result back; it does not resume a live
  `CoinSimulator`, and Phase 12 does not claim to.
- **Persistence observes, it never influences.** The repository is handed
  a completed run. It draws no random number and touches no wallet, tick
  or pool, so a simulation is identical whether or not it is saved — a
  test asserts exactly that.

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
  No AMM mechanic was bent to make a direction appear.
- **Not a manipulation scenario.** `--scenario`
  (`pump_and_dump`, `wash_trading`) replaces the *participants*: it adds
  manipulators and a follower crowd. A market condition touches no
  participant. Different axes, and they compose — a pump can run in a
  bear market.
- **Precedence:** saved scenario → market condition → explicitly typed
  event flags → other typed flags. So `--random-events` overrides a
  preset's news rate, and `--market-condition` typed on the command line
  overrides one stored in a scenario.
- **Deterministic.** A preset only rewrites settings before the run; it
  draws nothing. Same request and seed, same run.
- **Saved scenarios carry it** with no schema change — the name rides
  inside the existing `params_json`.
- **Omitting it changes nothing**: the settings object is passed through
  untouched, and a request that names no condition keeps the simulation
  ID it has always had.

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

- **A scenario is not a run.** `coin_runs` (above) stores what a
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
  traders/whales, manipulation preset, events, random events, psychology,
  whale observation, and the seed. `--pricing-mode` and `--seed` are
  optional on the command line, so a save records the values that
  *actually ran* rather than "whatever the config says" — otherwise an
  edit to `default.yaml` would silently change what a scenario means.
- **Where it lives.** The configured database (`database.path`, or
  `CRYPTOSIM_DB_PATH`), the same one runs are stored in. A run with
  neither scenario flag never opens it.
- **Saving validates.** A configuration is checked before it is written,
  so a scenario that could not be run is never stored as though it could.
  Note that `--ticks` itself is unbounded for a plain run but a *saved*
  scenario is held to the request bound (2000), so that anything saved
  can also be run from the browser.

### Running a batch

The same configuration, many times, under independent deterministic
seeds:

```bash
python scripts/simulate_coin.py --ticks 50 --batch 100 --seed 48291
python scripts/simulate_coin.py --load-scenario amm-nightly --batch 50
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
- **Run count.** 1–1000. The upper bound is about memory (every run's
  analytics are kept), not about the simulator.
- **Failures are collected, not swallowed.** A run that raises is listed
  as `FAILED` with its error, the remaining runs still execute, and the
  command exits non-zero.
- **Serial, on purpose.** A run takes a few milliseconds — 1000 runs of
  20 ticks takes about 1.4 s — so parallelism would buy little while
  putting ordering and reproducibility at risk. It is noted as a possible
  future optimisation, not a gap.
- **Nothing is stored and nothing is averaged.** A batch writes no
  database row, and the summary reports identities and counts only. Means,
  distributions and comparisons across runs are Phase 15 (aggregate
  statistics); batch mode's job is to produce the runs they will read.
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

**Phase 14 executes batches; Phase 15 describes them.** Every `--batch`
run now prints a distribution per metric after the per-run list:

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
  deliberately **no absolute price change**: the report defines none, and
  adding one here would create a second definition of the same idea.
- **Metrics:** open/close/high/low/mean price, cumulative and log return,
  mean return, volatility, realized volatility, max and end drawdown,
  market cap (start and end), total volume, turnover, participant
  turnover, average trade size and trader VWAP.
- **Definitions.** Mean is `fsum(values)/n`. Median is
  `statistics.median`. Percentiles (P05, P25, P50, P75, P95) use the
  project's single convention — linear interpolation at rank
  `p/100 × (n−1)`, shared from `analytics/_series.percentile`, the same
  one the psychology analytics use — so **P50 is exactly the median**.
  Standard deviation is the **sample** one (n−1), and is `n/a` below two
  observations, matching the rule the simulator's own volatility uses.
  An undefined dispersion is never reported as zero.
- **Missing stays missing.** A per-run metric is `float | None`, where
  `None` means the run could not compute it. Those runs contribute no
  observation, so a metric's `n` can be lower than the number of
  successful runs — a batch of one-tick runs has no volatility at all,
  and says so rather than showing zeros.
- **Failed runs** count as failed and contribute nothing; they are never
  read as zero. `requested`, `successful` and `failed` stay distinct from
  each metric's own observation count.
- **Descriptive only.** No confidence intervals, no significance tests,
  no forecasts, and no claim that one configuration beats another.
- **Deterministic**, and cheap: aggregating 1000 runs takes ~23 ms,
  about 1% of running them.
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

- **It tests the simulator; it does not extend it.** No market mechanic,
  participant type or limit is added. Every case is expressed in options
  the simulator already accepts, and every run goes through
  `run_simulation` / `run_batch` — the harness contains no simulation of
  its own.
- **Boundaries tested are the simulator's own:** ticks 1 and 2000
  (`MAX_TICKS`), seeds 0 and 2³²−1, batches of 1 and 1000
  (`MAX_BATCH_RUNS`), both pricing modes, both manipulation presets, and
  the feature combinations. Each is also tested one step **outside** the
  bound, where the existing validation must refuse it — a refusal is a
  pass for those cases.
- **The 200-trader case is the harness's ceiling, not the simulator's.**
  `coin.traders` is a configuration list with no validated maximum;
  Phase 16 does not add one. 200 was chosen to keep the costliest case
  (paired with 2000 ticks) within a few seconds and tens of megabytes.
- **A case passes when** it completes the ticks it asked for, its report
  holds no non-finite value, its prices are valid prices, its volumes and
  counts are non-negative, its price series is in tick order — and its
  **accounting still balances**. Conservation is read from the
  simulator's own `accounting_totals()`, captured through the builder
  injection `run_simulation` already offers, so no run loop is
  duplicated. AMM mode must balance *exactly* (it settles in `Decimal`);
  random-walk mode is allowed representation drift within 1e-9 relative,
  because float wallets accumulate rounding — a real loss still fails.
- **Selected cases are run twice** and required to produce identical
  results.
- **Failures are structured.** An unexpected exception is recorded with
  its type and message and the suite continues to the next case; nothing
  is swallowed, and Ctrl-C still interrupts.
- **Nothing is persisted** — results live in memory, and no database is
  touched.
- **Cost.** The ordinary tier runs in ~2s and is part of `pytest`. The
  two costly cases are marked `slow` and left out of an ordinary run;
  use `pytest -m slow` or `--heavy`.

> These tests exercise selected demanding configurations within the
> simulator's defined limits. They do not prove the simulator correct
> outside them, and say nothing about production-grade safety — this is a
> fictional simulator, not a trading system.

### Coin economy dashboard

The same run, in the browser. Launch the app as above
(`streamlit run crypto_simulator/app.py`) and open the **🪙 Coin
Simulation** tab: pick the options (the CLI's flags, plus the seed),
press **Run simulation**, and the finished run's analytics report is
displayed.

```text
build_coin_simulator -> CoinSimulator.run -> build_report
                     -> DashboardPayload  -> payload_to_dict -> Streamlit
```

- **The report is the source of truth.** `crypto_simulator/dashboard/`
  runs one simulation, builds one `SimulationReport` from it, and renders
  that. It recomputes no figure: every number on screen is a value the
  report (or the recorded tick) already holds, passed through a format
  spec. A dashboard run is a CLI run — same builder, same seeds, same
  report inputs — and the tests require the two to agree bit for bit.
- **Read-only.** The dashboard observes a completed simulation; it never
  writes back to ticks, wallets, traders, whales, psychology, events, the
  pool or the RNG, and nothing in `core/`, `services/` or `analytics/`
  imports it.
- **The data contract** is `payload_to_dict(payload)`:
  `{"simulation": ..., "report": ..., "price_series": ...}`, plain
  JSON-compatible Python. `None` stays `null` (never a stand-in zero),
  numbers stay numbers, `Decimal` becomes `float` (the report itself
  remains the exact source), enums become their values — as mapping keys
  too — and an unsupported type (or key type) is an error rather than a
  stringified Python object.
  Properties are not evaluated either, except for a short allowlist
  (`DERIVED_FIELDS`) of figures the analytics themselves define — the
  `VolumeBreakdown` totals, whether a trader was active, an event window's
  completeness, a pump-and-dump summary's own totals, a regime window's
  completeness and description, whether a regime window recorded a live
  event, and the report's own window counts — so the
  dashboard reads them instead of working them out itself. The same request always produces the same
  payload, so the payload carries tick numbers rather than the clock's
  wall-clock timestamps.
- **States:** an empty state before the first run, `Running simulation...`
  during one, the results after it, and a plain error (with no stale or
  invented figures) when a run fails — for instance asking for AMM mode
  with whales, which the simulator rejects.
- **The market section** (Step 2, `dashboard/market_section.py`) is the
  functional part today, in both pricing modes: the price overview (open,
  close, return, high, low, mean) with the price chart; the analytics'
  own volume decomposition and fill counts; volatility and drawdown with
  their peak, trough and recovery ticks; market cap, turnover, average
  trade size and trader VWAP; AMM swap activity and fees when the run has
  a pool; and a statistics table of every figure shown, with the analysed
  and requested tick ranges. The chart plots the recorded price path over
  tick numbers, hover gives a tick's price and volume, and its two
  markers are the report's own high and low.
- **Nothing is derived in the frontend.** The report defines no absolute
  price change, so the headline shows the return it does define rather
  than subtracting two prices; it defines drawdown as scalars rather than
  a series, so there is no drawdown chart (building one would mean
  reimplementing the analytics' formula).
- **The trader section** (Step 3, `dashboard/trader_section.py`) shows
  `report.traders` — `analyze_traders`' own figures: the population
  overview (traders active, participation, fills, volume, notional, VWAP,
  net coin and cash flows, combined P&L, return and equities), a strategy
  table grouped as the report groups it, a per-trader activity table
  (fills, buy/sell/wash quantities, requested volume, fill ratio, active
  ticks, fill span, average fill), a per-trader performance table
  (notional, VWAP, wash share, swap fees, flows, closing balances, equity,
  P&L, return) and a detail view listing every figure the report records
  for one selected trader. The selector filters the payload already on
  screen: it runs no simulation and no analytics.
- **P&L, equity and VWAP are never recomputed.** They are
  `analyze_traders`' values, shown unchanged — the dashboard does not
  subtract equities, value wallets or divide notional by volume. A wash
  leg counts as one because the simulator flagged it, and a strategy is a
  manipulation strategy because that is its registered label.
- **The whale section** (Step 4, `dashboard/whale_section.py`) shows
  `report.whale_activity`: observation coverage and the observed tick
  count, the whale volume totals and shares, a per-whale activity table,
  the recorded per-tick outcomes (`traded`, `blocked_by_cooldown`,
  `blocked_by_interval`, `held_at_target`, `no_fill`, `inactive`), the
  per-behavior activity table, allocation paths with their targets and gap
  statistics, cohort activity with its co-fill statistics, and a detail
  view for one selected whale. Behavior is the behavior the simulator
  recorded, never inferred from a trade's size or side; co-fill is
  described as co-occurrence, since a cohort follows a fixed schedule.
- **Unavailable is not zero.** A run without whales, a run whose whales
  were not observed (whale observation is off by default), and an AMM run
  (whose pricing mode does not support whales) each produce a report with
  no whales — the section says which of those happened rather than showing
  zeros.
- **The events section** (Step 5, `dashboard/event_section.py`) shows
  `report.event_windows`: one row per event with the ground truth the
  simulator recorded (category, severity, sentiment, volatility boost,
  attention, timing, recorded provenance and overlap), one row per window
  around each event (before, active, decay, after, effect) with that
  window's own market summary and whether it observed every tick it asked
  for, the per-category activity, and a detail view for one event.
- **The psychology section** (Step 5, `dashboard/psychology_section.py`)
  shows `report.psychology_market`: coverage, the four components with
  their means, medians, ranges and percentiles, a chart of the recorded
  components over ticks, threshold occupancy, persistence runs, the
  recorded associations (same-tick and lagged, with the analytics' own
  reason when one could not be computed), market averages for the low and
  high ticks of each component, the means during event windows versus
  outside them, and the per-tick record with its dominant label.
- **Descriptive, never causal.** Both sections describe what was observed
  *during* a window or alongside a component level. A correlation is
  labelled an association; overlapping events are listed rather than
  blamed; the four components stay on their own 0-1 scale and are never
  combined into a score. Tests read back everything on screen and fail on
  causal wording.
- **The manipulation section** (Step 6,
  `dashboard/manipulation_section.py`) shows `report.manipulation`: the
  analytics' own coverage word for which manipulation kinds were
  observed, the manipulation volume with both of the report's shares and
  its active ticks, one row per kind (pump-and-dump, wash trading) from
  that kind's own strategy summary, one row per manipulator and recorded
  phase (`accumulate`, `pump`, `dump`), each manipulator's observed span
  with the market summary the analytics computed over it, the aggregate
  wash record, and the report's side-by-side comparison of manipulation
  and organic activity.
- **Manipulation is a recorded label, never an inference.** A fill counts
  as manipulation because the simulator flagged it as a wash leg or ran it
  under a registered manipulation strategy — never because a trade was
  large, a price moved fast or a trader was big. Phases come from each
  fill's own recorded reason; a phase with no fills keeps `n/a` ticks,
  since the analytics cannot tell a phase that never ran from one outside
  the analysed range, and the section does not decide for them.
- **The regime section** (Step 6, `dashboard/regime_section.py`) shows
  `report.regimes`: the window count, completeness and window size, one
  row per window with the analytics' own labels (`rising`/`falling`/`flat`,
  `low_volatility`/`normal_volatility`/`high_volatility`,
  `low_volume`/`normal_volume`/`high_volume`,
  `at_high`/`drawdown`/`recovery`) and their own description of it, the
  figures each label is read from with the quartile reference behind it,
  what else was recorded in each window, the report's own label tallies,
  and a chart of each window's recorded volume per observed tick.
- **Early windows stay unlabelled.** A volatility or volume class needs
  four earlier complete windows for its reference and a direction needs
  enough returns, so the first windows of a run carry no such label — `n/a`
  on screen, never filled in from the window's own figures or carried over
  from a neighbour. A window shorter than its grid span is marked
  incomplete rather than padded, and there is no combined regime label,
  because the analytics define none.
- **Both sections are descriptive.** A regime describes one past window
  and says nothing about the ticks after it; manipulation figures describe
  what was recorded during a scenario's own ticks. Tests read back every
  caption, heading, message and cell and fail on causal wording, and
  structural tests assert both modules call no analytics function, perform
  no arithmetic and never reach for a tick's raw fills.
- **The seed control** (Step 7) decides which run you get. It is off by
  default, and a run then uses `simulation.random_seed` from the
  configuration exactly as it always did. Turn it on and the same options
  run against the seed you choose: the same seed always reproduces the
  same run, and a different seed gives another sample path from the same
  settings. The number starts at the configured seed, so switching the
  control on without changing it reproduces the run you were already
  looking at. The seed a run used is shown in the status line under the
  results.
- **The seed is selected, not invented.** A requested seed replaces
  `simulation.random_seed` in a copy of the settings and reaches the run
  only through `build_coin_simulator`'s own derivation, which is where
  every participant seed already came from. The dashboard seeds nothing
  itself, adds no simulator input and leaves the application settings
  untouched; a seeded dashboard run is still exactly the run the CLI
  performs with those flags and that seed configured, which the tests
  check for random-walk, AMM and event/psychology runs.
- **Phase 10, Step 7 scope:** every section of the report is rendered —
  market, traders, whales, events, psychology, manipulation and regimes —
  and the run request is now fully specified from the browser. The
  dashboard still runs one simulation at a time and stores nothing: batch
  and multi-seed runs belong to Phase 12, calibration to Phase 14, and the
  final visual design comes after the simulator is complete.

## Configuration

Default settings live in `crypto_simulator/config/default.yaml` (starting
balance, simulated assets, database path, UI options, logging level). Copy
`.env.example` to `.env` to override individual values via environment
variables (see `crypto_simulator/config/settings.py` for the mapping) without
editing the YAML file.

## Testing

```bash
pytest                 # run the full suite
pytest --cov           # with coverage (requires pytest-cov)
```

## Disclaimer

This software is provided for educational and entertainment purposes only.
Nothing in this repository is financial advice, and nothing in this
repository can place a real trade, hold a real asset, or interact with a
real exchange. Any resemblance between simulated prices and real market
data is coincidental and unsuitable for real-world decision making.
