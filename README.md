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
```

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

### Coin economy dashboard

The same run, in the browser. Launch the app as above
(`streamlit run crypto_simulator/app.py`) and open the **🪙 Coin
Simulation** tab: pick the options (the CLI's flags), press **Run
simulation**, and the finished run's analytics report is displayed.

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
  remains the exact source), enums become their values, and an
  unsupported type is an error rather than a stringified Python object.
  Properties are not evaluated either, except for a short allowlist
  (`DERIVED_FIELDS`) of figures the analytics themselves define — the
  `VolumeBreakdown` totals — so the dashboard reads them instead of adding
  the components up itself. The same request always produces the same
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
- **Phase 10, Step 2 scope:** the market section. The trader, whale,
  event, psychology, manipulation and regime sections are still named
  placeholders; their data is already in the payload and later Phase 10
  steps render it.

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
