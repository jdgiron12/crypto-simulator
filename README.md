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
│   └── liquidity/  Constant-product AMM pool (alternative pricing mode)
├── services/       Orchestrates core + data for the UI layer
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
```

Everything comes from the `coin:` section of
`crypto_simulator/config/default.yaml`:

- **Coin economics** — symbol, supply, starting price, volatility.
- **Whales** — large holders that can move price with one outsized trade.
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

The demo prints each tick, a per-trader wallet/P&L table, and an
accounting check showing total coins and cash are unchanged (exactly, in
AMM mode, where the pool keeps `Decimal` accounting). To add a strategy,
subclass `TraderAgent` in `crypto_simulator/core/traders/` and register it
in `TRADER_STRATEGIES` (manipulation strategies go in
`MANIPULATION_STRATEGIES`). See [`docs/ROADMAP.md`](docs/ROADMAP.md) for
the AMM math, fee/slippage/liquidity model, how each manipulation scheme
plays out in each pricing mode, and what's planned next (news events,
participant psychology).

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
