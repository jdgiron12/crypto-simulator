# Development Roadmap

This roadmap tracks what's implemented vs. planned. The project is
strictly a **fictional, educational simulator** at every stage — no phase
introduces real exchange connectivity, real trading, or real money.

## Phase 0 — Scaffolding ✅

- [x] Modular project structure (`config`, `models`, `data`, `core`,
      `services`, `visualization`, `utils`, `app.py`)
- [x] YAML-based configuration system with env var overrides
- [x] SQLite schema + connection management + repositories
- [x] Domain models (`Asset`, `Order`, `Trade`, `Account`, `Holding`)
- [x] Plotly chart builders (candlestick, equity curve, allocation)
- [x] Streamlit shell with placeholder tabs
- [x] pytest suite covering config, models, data layer, visualization
- [ ] CI (lint + test) — TODO

## Phase 1 — Synthetic Market Data ✅ (current)

- [x] Implement `MarketEngine.step()` / `current_price()`: a per-asset
      random-walk or GBM price process, seeded via config for
      reproducibility
- [x] Persist generated ticks to `price_history`
- [x] Dashboard tab: candlestick chart per asset, manually advanced one
      tick at a time via a button (not yet auto-updating on a timer —
      see Phase 5 for a possible autorefresh pass)

## Phase 2 — Order Execution (Simulated)

- [ ] Implement `OrderEngine.submit()`:
  - Market orders fill immediately at current simulated price
  - Limit orders fill only when price crosses the limit
  - Configurable slippage/fee model
- [ ] Trade tab: order entry form wired to `TradingService`
- [ ] History tab: order + trade tables from persisted data

## Phase 3 — Portfolio & Analytics

- [ ] Realized P&L (in addition to existing unrealized P&L calc)
- [ ] Cost-basis method selection (average cost / FIFO)
- [ ] Portfolio tab: equity curve, allocation pie chart, P&L breakdown
- [ ] Account funding / reset flows (simulated deposits only)

## Phase 4 — Scenario & Strategy Tools

- [ ] Configurable market scenarios (bull/bear/crash/volatility spike)
- [ ] Scripted/rule-based trading bots running against the simulator
- [ ] Backtest-style replay of a saved price history
- [ ] Multi-account support for comparing strategies side by side

## Phase 5 — Polish

- [ ] Packaging (`pip install`-able), Dockerfile
- [ ] Expanded docs, example notebooks
- [ ] Performance pass on tick throughput / DB writes

---

## Coin Economy Simulation (standalone track)

A separate, minimal single-coin economic simulation
(`core.coin_simulator.CoinSimulator`) — distinct from the multi-asset
trading engine above (`core.market_engine.MarketEngine` + accounts/orders).
Built for a future line of participant/event-driven extensions; kept
deliberately bare until then.

- [x] `Coin` model: fixed symbol/name/initial supply/starting price
      (`models/coin.py`)
- [x] `CoinSimulator`: composes `SimulationClock` + `MarketEngine` (single
      symbol) + `VolumeModel` into a per-tick loop (`core/coin_simulator.py`)
- [x] Market cap calculation (`price * initial_supply` — Phase 1 has no
      minting/burning)
- [x] `VolumeModel`: synthetic per-tick volume, independent of real trades
      (`core/volume_model.py`)
- [x] Simulation loop: `CoinSimulator.run(ticks)`, demoed by
      `scripts/simulate_coin.py`
- [x] Whales / large holders influencing price via outsized simulated
      orders (`core/whale.py`: `Whale`/`WhaleTrade`, configurable under
      `coin.whales` in `default.yaml`) — linear price-impact model only,
      no order book or liquidity depth yet
- [x] Algorithmic/rule-based trader agents (`core/traders/`):
  - `TraderAgent` base class (trade probability gate, sizing by
    `risk_tolerance` × balance capped at `max_trade_size`, seeded RNG);
    strategies implement only `_decide(MarketContext) -> TradeDecision`
    (BUY / SELL / HOLD)
  - Five strategies: `retail`, `momentum`, `dip_buyer`, `panic_seller`,
    `long_term_holder`, looked up by name in `TRADER_STRATEGIES`
  - `Wallet` balances (`models/wallet.py`) settled against a market
    reserve wallet by `execute_decision`: fills clamped to cash/holdings/
    reserve, coins and cash conserved
  - Net trader flow moves price via `MarketEngine.set_price()` (same linear
    impact shape as whales); fills recorded in `SimulationTick.trader_trades`
    and added to tick volume
  - Configured under `coin.traders` / `coin.market_reserve_cash` /
    `coin.trader_impact_coefficient`; built by
    `services.coin_simulation.build_coin_simulator`
- [x] Liquidity pools / AMM-style pricing as an alternative to the GBM walk
      (`core/liquidity/`, selected with `coin.pricing_mode: amm` — see
      "AMM pricing mode" below)
- [x] Manipulation scenarios (pump-and-dump, wash trading)
      (`core/traders/manipulation.py`, configured under `coin.manipulators`
      or run as presets with `--scenario` — see "Manipulation scenarios"
      below)
- [ ] News/event shocks (scheduled or random price-impacting events)
- [ ] Participant psychology (sentiment-driven demand shifts)

Each of the above should plug into `CoinSimulator.step()` (e.g. a
participant registry consulted before/after the price update) rather than
being special-cased into today's loop. New trader strategies need only a
`TraderAgent` subclass plus a `TRADER_STRATEGIES` entry (or a
`MANIPULATION_STRATEGIES` entry for manipulators).

### AMM pricing mode

**Architecture.** `core/liquidity/`:

- `pool.py` — `AMMPool` (`spot_price`, `quote_buy`/`quote_sell`,
  `buy`/`sell`, `optimal_deposit`, `add_liquidity`/`remove_liquidity`,
  `state`), plus `SwapResult`, `LiquidityChange`, `PoolState` and the
  `AMMError` family. Pure pool math; never touches wallets.
- `amounts.py` — `Decimal` rules: `EXACT` (unlimited precision, used for
  every balance update) and 60-digit `FLOOR`/`CEILING`/`NEAREST` contexts
  for the divisions the curve needs.
- `settlement.py` — executes trader decisions as pool swaps and seeds the
  pool from a wallet, handling the float-wallet ↔ `Decimal`-pool boundary.

`CoinSimulator.step()` dispatches on `PricingMode`: `_step_random_walk()`
(the pre-existing logic, unchanged) or `_step_amm()`.

**Pricing equation.** x = coin reserve, y = cash reserve, x · y = k, spot
price P = y / x. Swaps are exact-input with fee rate f on the input asset:

| | input | output | reserves after | spot after (f = 0) |
|---|---|---|---|---|
| buy  | Δy cash  | x − ⌈k / (y + Δy(1−f))⌉ coins | (x − out, y + Δy) | P · (1 + Δy/y)² |
| sell | Δx coins | y − ⌈k / (x + Δx(1−f))⌉ cash  | (x + Δx, y − out) | P / (1 + Δx/x)² |

Every `SwapResult` records amount in, fee, amount in after fee, amount out,
spot price before/after, execution price (incl. fee), price impact
(relative spot change) and slippage.

**Fee model.** `coin.amm.fee_rate` (default 0.003 = 0.3%, must be in
[0, 1)), charged on the input asset: cash on buys, coins on sells. The
output is priced on the net input; the fee stays in the reserves (Uniswap
v2 model), so it deepens the pool, grows k, and accrues to LP shares.
It is reported on every swap and in cumulative `fees_collected_cash` /
`fees_collected_coins` counters. (Holding fees *outside* the reserves was
considered and rejected: a later LP would mint shares against reserves
alone yet claim earlier fees.)

**Slippage model.** Slippage is the fee-free execution price's shortfall
versus the pre-trade spot price; for the constant-product curve it is
exactly net/y for buys and net/(x + net) for sells, so it grows with trade
size relative to pool depth. `buy(..., min_coins_out=)` /
`sell(..., min_cash_out=)` refuse swaps that would deliver less.

**Difference from the linear model.** Random-walk mode's impact
`1 + c·q/supply` is linear, measured against total supply regardless of
available liquidity, and applied once after all fills (every trader in a
tick fills at the same price). AMM impact is convex, measured against the
pool's own reserves, borne by each swap individually, and diverges as a
buy approaches the whole coin reserve (for small trades it is ≈ 2·Δ/depth,
which is where random-walk mode's default coefficient of 2 comes from).

**Liquidity model.** LP shares: the initial provider (the market reserve,
id `market-reserve`) gets √k shares; deposits mint
`total · min(Δx/x, Δy/y)` (rounded down; excess over the pool ratio stays
in the pool — use `optimal_deposit`); withdrawals return the pro-rata
share of reserves, fees included (rounded down). The last share cannot be
withdrawn, so reserves always stay positive.

**Accounting.** The pool is exact `Decimal`; wallets stay `float`. Debits
credit the pool with the exact change in the wallet's float balance;
credits give the wallet the largest float whose exact increase is ≤ the
pool's output, the sub-ulp remainder staying in the pool. Rounding always
favors the pool, so k never decreases and outputs never exceed the curve.
`CoinSimulator.accounting_totals()` (traders + market reserve + pool
reserves) is conserved *exactly*, and the tests assert it with `==`.

**Configuration** (`coin:` in `default.yaml`, or `CRYPTOSIM_PRICING_MODE`):

```yaml
pricing_mode: "random_walk"   # or "amm"
amm:
  pool_coin_reserve: 200000.0  # cash side = coins × starting_price
  fee_rate: 0.003
```

Demo: `python scripts/simulate_coin.py --pricing-mode amm --no-whales`.

**Random-walk vs. AMM mode.**

| | random_walk (default) | amm |
|---|---|---|
| Price source | GBM random walk + linear impact | pool spot price; moves only on swaps |
| Trader counterparty | market reserve, one price per tick | the pool, sequential swaps with slippage |
| Volume | synthetic background + whale + trader | coins actually swapped |
| Whales | supported (external liquidity) | rejected with an error |
| Fees | none | `fee_rate` on every swap |
| Accounting | conserved to float precision | conserved exactly |

**Planned whale integration (needs sign-off — changes whale semantics).**
Give `Whale` a `Wallet` with starting cash, split `maybe_trade` into a
decision (side, size) and execution through `settlement` like traders.
Whale buys would then be limited by cash and move price along the pool
curve instead of the linear formula; random-walk mode could keep today's
behavior.

Known simplifications to revisit:

- Whales still trade against assumed external liquidity in random-walk
  mode (their buys are uncapped and don't touch the market reserve), so
  whale activity is outside the conserved-accounting system; AMM mode
  doesn't support them yet (see above).
- Random-walk mode: all traders in a tick fill at the same price and in
  list order; price impact is applied once from their net flow afterwards.
  The market reserve fills any trade at the current price until it runs
  out of coins or cash.
- AMM mode: traders swap in fixed list order, so earlier traders get
  better prices each tick. There is no exogenous price movement — without
  trade flow the price is flat, and in a deep pool the threshold
  strategies (momentum, dip buyer, panic seller) rarely trigger. The
  market reserve is the only LP and never adds or removes liquidity; no
  LP agents yet. Buys are exact-input only (no "buy exactly N coins").
- Wallets are floats: a trader receives at most the pool's output rounded
  down to what its float balance can represent (≤ 1 ulp of its balance
  per swap), with the remainder kept by the pool.

### Manipulation scenarios

**Architecture.** Manipulators are `TraderAgent` subclasses in
`core/traders/manipulation.py`. They hold wallets and settle through the
same reserve / pool code as everyone else, so accounting stays conserved
(exactly, in AMM mode). They live in their own registry
(`MANIPULATION_STRATEGIES`) and config list (`coin.manipulators`, empty by
default), are seeded at `random_seed + 2000 + i`, and trade after the
organic traders each tick. Putting one in the wrong list is an error.
`CoinSimulator` has exactly one special case: a WASH decision.

- **`pump_and_dump`**, phased by tick: *accumulate* (buy a fixed
  `accumulate_share` of the budget spread over `accumulate_ticks`), *pump*
  (spend the rest of the budget evenly over `pump_ticks`), then *dump*
  (sell holdings evenly over `dump_ticks`, then everything left). The
  budget is `risk_tolerance` × starting cash. `SchemePhase` / `phase(tick)`
  report where it is.
- **`wash_trader`** returns `TradeAction.WASH`, sized like a buy. It is
  settled as a buy leg plus a sell leg returning exactly the coins bought
  (`execute_wash` / `execute_wash_via_pool`). Both legs are recorded as
  `TraderTrade(wash=True)` and count toward `volume`;
  `SimulationTick.wash_volume` shows how much of it was fake.
  `execute_decision*` reject WASH decisions so a round trip can't be
  half-settled by mistake.

**Presets** (`MANIPULATION_SCENARIOS` in `services/coin_simulation.py`,
sized for the default config). A `ManipulationScenario` replaces
`coin.manipulators` and may add organic *followers* after `coin.traders`
(seeded as if they were further entries there, so nobody else is reseeded):

- `pump_and_dump` — a 30k budget: accumulate ticks 5–14, pump 15–16, dump
  17–19, plus four "marks" (momentum traders: enter on +15% over 3 ticks,
  exit only at −30%).
- `wash_trading` — one wash trader with 50k cash, active 90% of ticks.

**How each scheme plays out, by pricing mode** (default config, 30 ticks):

| | random_walk | amm |
|---|---|---|
| Wash trade cost | free: both legs fill at the tick price | pays `fee_rate` on both legs (≈ 2 × fee × notional), kept by LPs |
| Wash trade price effect | none — the price path is bit-identical to the run without it | retained fees lift spot slightly; the coin reserve returns exactly if the wash trader starts with no coins, otherwise to within the float-wallet rounding remainder (≤ 1 ulp of its coin balance; accounting stays exact) |
| Wash share of reported volume (preset) | ≈ 79% | ≈ 95% (no synthetic background volume) |
| Pump-and-dump with nobody to sell to | — | always loses exactly its fees (the curve is path independent) |
| Pump-and-dump preset | profits in 16/20 seeds, weakly (+3.5k at seed 42, peak ≈ 1.3×; the marks never trigger) | profits in 18/20 seeds (+5.7k at seed 42, peak ≈ 3×); the marks lose ≈ 22k |

Tests pin the seed-42 AMM outcome and require the AMM preset to profit in
at least 16 of seeds 1–20, so the scenario can't quietly stop
demonstrating the scheme.

Known simplifications to revisit:

- No hype or promotion: in this model, only the price move itself draws
  followers in, so a pump-and-dump needs momentum-chasing traders. The
  default population (whose long-term holder takes profit into the pump)
  isn't enough, which is why the preset brings its own marks. Participant
  psychology (below) is the place for hype.
- Nobody reads volume yet, so wash volume misleads only a human reading
  the tape. A sentiment model that reacts to volume would make it bite.
- Random-walk mode flatters the manipulator: every fill in a tick executes
  at the pre-impact price and impact is linear against total supply, so
  the manipulator's own impact costs it nothing, and a 30k pump barely
  registers against 3% volatility. Run the scenarios in AMM mode for
  realistic economics.
- The pump-and-dump runs on a fixed schedule; it doesn't adapt to price
  (e.g. dump early on a target gain).
- A wash trade is always one account; there's no multi-account collusion
  or detection yet.

---

**Out of scope, permanently:** live exchange APIs, real order routing,
real wallets/custody, real payment rails. If a future contributor
proposes any of these, it does not belong in this repository.
