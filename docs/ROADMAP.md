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
- [x] News/event shocks, event generation, event observation/analytics
      (Phase 6; checkpoint commit
      `11c7166083524c46113a2d778a4541c46e07cd4f` — see "News/event shocks"
      below)
- [ ] Participant psychology (Phase 7: Steps 1–4 complete, calibration
      deferred — see "Participant psychology" below)
  - [x] Step 1: `PsychologyState` core
  - [x] Step 2: market psychology signals
  - [x] Step 3: trader psychology integration
  - [x] Step 3.5: calibration audit
  - [x] Step 4: psychology observation and analytics
  - [ ] Psychology calibration — **deferred** to a future calibration
        phase
- [x] Advanced whale behavior (Phase 8, complete; checkpoint commit
      `b5a5f87f6b383ebd0a28ddbd8d5851a5155f4716` — see "Advanced whale
      behavior" below)
  - [x] Step 1: whale state and accumulation/distribution foundation
  - [x] Step 2: whale target allocation behavior
  - [x] Step 3: whale trade scheduling / patience
  - [x] Step 4: explicit whale behavior state machine
  - [x] Step 5: whale intent strength
  - [x] Step 6: whale accumulation / distribution cycles
  - [x] Step 7: whale observation and analytics
  - [x] Step 8: non-reactive whale cohort coordination
- [ ] Advanced market analytics (Phase 9, in progress — see "Advanced
      market analytics" below)
  - [x] Step 0: analytics hygiene and compatibility harness
  - [ ] Steps 1–8: planned, not implemented

> **Roadmap gate:** Psychology calibration must be completed before
> implementing feedback-heavy features such as cascades, herding, or social
> influence.

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
| Whales | supported (unfunded: external liquidity; funded: market reserve) | rejected with an error |
| Fees | none | `fee_rate` on every swap |
| Accounting | conserved to float precision | conserved exactly |

**Planned whale integration (needs sign-off — changes whale semantics).**
Give `Whale` a `Wallet` with starting cash, split `maybe_trade` into a
decision (side, size) and execution through `settlement` like traders.
Whale buys would then be limited by cash and move price along the pool
curve instead of the linear formula; random-walk mode could keep today's
behavior. (Phase 8 Step 1 added opt-in *funded* whales with a `Wallet`
that settle against the market reserve in random-walk mode; routing
whales through the pool is still unplanned — see "Advanced whale
behavior".)

Known simplifications to revisit:

- Unfunded whales (the default) still trade against assumed external
  liquidity in random-walk mode (their buys are uncapped and don't touch
  the market reserve), so their activity is outside the conserved-accounting
  system; funded whales settle against the reserve. AMM mode doesn't
  support either kind yet (see above).
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

### News/event shocks (Phase 6)

Checkpoint commit: `11c7166083524c46113a2d778a4541c46e07cd4f`.

**Architecture.** `core/events/` is pure data and arithmetic and depends on
nothing else in the simulator:

- `event.py` — `MarketEvent`: `severity` in (0, 1], `sentiment` in
  [-1, 1], `volatility_boost` ≥ 0, `attention` ≥ 0, `start_tick`,
  `duration`, `decay_ticks`. Lifecycle: scheduled → active (intensity 1)
  → decaying (linear, strictly between 1 and 0) → expired.
- `catalog.py` — `EVENT_CATEGORIES`: generic fictional categories
  (positive, negative, mixed), each a profile of effects at severity 1;
  `create_event` scales a profile by severity.
- `engine.py` — `EventEngine`: the event timeline. `state(tick)` returns an
  `EventState` combining every live event: sentiment
  `clamp(Σ sentiment × intensity, -1, 1)`, volatility multiplier
  `1 + Σ volatility_boost × intensity`, attention multiplier
  `1 + Σ attention × intensity`. The result doesn't depend on the order
  events were supplied.

**How events reach the market.** Events never set a price.

- Traders (both modes): `MarketContext` carries only the aggregate
  `sentiment` and `attention_multiplier`, never which events are live.
  Attention raises each trader's chance of acting (capped at 1); sentiment
  bends each strategy's own thresholds by its `sentiment_sensitivity`
  (defaults: retail 1.0, momentum 0.8, dip buyer 0, panic seller 1.0,
  long-term holder 0.2). Manipulators ignore news.
- Random-walk mode only: the random walk's volatility is scaled by the
  volatility multiplier. `coin.events.drift_per_sentiment` defaults to 0.0,
  so events add no directional drift; a nonzero value is rejected in AMM
  mode.
- AMM mode: events move the pool only through traders' swaps.

**Event generation.** Scheduled events come from `coin.events.scheduled`
(built through the catalog). Random events come from
`RandomEventGenerator` (`core/events/generator.py`, configured under
`coin.events.random`: per-tick `probability`, category weights, and
severity/duration/decay ranges). It has its own RNG, seeded at
`random_seed + 3000`, whose draws never depend on market activity. It is
asked at the start of each tick, so a random event is live from the tick
it starts.

**Observation/analytics.** `crypto_simulator/analytics/` (`analyze_events`)
is post-processing only: nothing in `core/` or `services/` imports it, and
it never feeds back into a run. Each `EventObservation` keeps ground truth
(`EventGroundTruth`: category, severity, sentiment, timing) apart from
what is computed from market output alone (`ObservedMarket`,
`ObservedTrading`, `ObservedPool`) over windows anchored on the event's
timing: the tick before, the event window, a post window and a baseline.
Results are descriptive, not causal; overlapping events are listed, not
disentangled.

**Scheduled vs random provenance.** `RandomEventGenerator.generated_events`
records every event the generator started. Passed to
`analyze_events(random_event_ids=...)`, it sets
`EventGroundTruth.randomly_generated` to `True` for those events and
`False` for the rest; without it, provenance is `None` (unknown).
`MarketEvent` and `EventEngine` carry no provenance themselves.

Demo: `python scripts/simulate_coin.py --events` (the demo schedule) and/or
`--random-events`; runs with events print an "Event analysis" table.

### Participant psychology (Phase 7)

Status: Steps 1, 2, 3, 3.5 and 4 complete. Calibration is **deferred** to
the later realism/calibration phase.

> **Roadmap gate:** Psychology calibration must be completed before
> implementing feedback-heavy features such as cascades, herding, or social
> influence.

**Step 1 — `PsychologyState` core** (`core/psychology/state.py`). A frozen
record of `fear`, `fomo`, `conviction` and `uncertainty`, each in [0, 1];
out-of-range or non-finite values are rejected rather than clamped.
`PsychologyState.neutral()` is all zeros.

**Step 2 — market psychology signals** (`core/psychology/signals.py`).
`compute_psychology(MarketSignals)` is pure and deterministic. Recent
return, momentum and news sentiment (× attention) form bullish and
bearish pressures (price terms in units of `PRICE_MOVE_SCALE` = 5%).
Fear and FOMO are `tanh` of their own pressure, damped by the opposite
one. Uncertainty grows with volatility (in units of `VOLATILITY_SCALE` =
0.10), event severity (× attention) and conflicting signals. Conviction is
net bullish confidence, eroded by uncertainty. Helpers:
`signals_from_closes` (returns, momentum and volatility from completed
closes) and `aggregate_event_severity` (the largest live
`severity × intensity`).

**Step 3 — trader psychology integration.** Off by default:
`CoinSimulator(psychology=True)` or
`build_coin_simulator(..., psychology=True)` turns it on (it isn't in the
config; the demo's `--psychology` flag, added in Step 4, turns it on
there). With it off, traders get the plain `MarketContext` and
every run is bit-identical to before (the 200-tick builder fingerprints
are pinned in `tests/core/test_coin_simulator_psychology.py`). With it on:

- Each tick, before traders decide, one market-wide `PsychologyState` is
  computed from the closes of the last `SIGNAL_WINDOW` (5) completed ticks
  and that tick's `EventState`, and recorded as `SimulationTick.psychology`.
- Aggregate severity (`live_event_severity` in `core/coin_simulator.py`) is
  the strongest live event's severity × its current intensity. Severity is
  looked up by event id; `EventState` and `EventEngine` are unchanged.
- Traders receive a `PsychologyContext` (a `MarketContext` subclass). Each
  strategy applies its own bounded modifiers after the Phase 6 news
  adjustments, scaled by its `psychology_sensitivity`:

  | Strategy | Sensitivity | More likely to act from | Rule adjustment |
  |---|---|---|---|
  | retail | 0.8 | FOMO or fear | FOMO − fear tilts buy vs sell |
  | momentum | 0.8 | — | conviction eases entry; fear eases exit |
  | dip buyer | 0.5 | — | fear eases the dip threshold; FOMO has no effect |
  | panic seller | 1.0 | fear | fear eases the panic threshold; conviction raises it |
  | long-term holder | 0.2 | — | FOMO − fear nudges its buy premium (±10%) |

- Participation p becomes `p × (1 + urge × (1 − p))`: 0 stays 0, and
  psychology never makes acting certain. A threshold is never lowered by
  more than half. No random draws are added, and manipulators ignore
  psychology.
- Psychology never sets a price: in both modes it acts only through
  traders' ordinary fills and swaps, and AMM accounting stays exact.

**Step 3.5 — calibration audit** (20 fixed seeds × 200 ticks; both pricing
modes; psychology off and on; no, scheduled and random events):

- The psychology state is very strong: fear or FOMO is above 0.9 on
  roughly 35–52% of ticks, including ordinary ticks with no events.
- The cause is the Step 2 formula, chiefly the fixed 5% scale applied to
  5-tick momentum (73% of the price pressure), not trader feedback: the
  same formula on psychology-off price paths gives about the same
  distribution in random-walk mode.
- Events mainly raise uncertainty and lower conviction; they don't
  materially change the fear/FOMO distribution.
- Trader amplification is moderate in random-walk mode (+16% fills; final
  price effect within seed noise) and stronger but bounded in AMM mode
  (+32% fills, final price ≈ 12.5% higher on average, 17 of 20 seeds
  higher, per-tick volatility +15%).
- No RNG, accounting, determinism or regression problems were found.

Calibration of these formulas is deferred to the later realism/calibration
phase, and the roadmap gate above applies.

**Step 4 — psychology observation and analytics**
(`crypto_simulator/analytics/psychology.py`). Read-only post-processing
alongside the Phase 6 event analytics: nothing in `core/` or `services/`
imports it, and it never feeds back into a run.
`analyze_psychology(ticks, *, event_ticks=None, persistence_threshold=0.75,
trader_count=None)` reads the `PsychologyState` recorded on each tick and
returns a frozen `PsychologyReport`:

- per component (fear, FOMO, conviction, uncertainty): count, mean,
  median, min, max, p90 and p95 (linear interpolation between closest
  ranks), the share of ticks at or above 0.25 / 0.50 / 0.75 / 0.90, and
  runs of consecutive ticks at or above the persistence threshold (longest
  run, where it starts, number of runs);
- the dominant component per tick (ties go to fear, then FOMO, conviction,
  uncertainty; an all-zero state is `neutral`), with counts and shares;
- trader fills, distinct traders with fills and (given `trader_count`)
  participation, on all ticks and on the ticks of each dominant component;
- an event-period comparison: each component's mean on ticks with a live
  event vs. the other ticks (from the ticks' recorded `EventState`, or from
  explicit `event_ticks`).

Ticks without psychology are counted and left out, never filled in with a
neutral state; a malformed state is rejected. Ticks are ordered by tick
number, so input order doesn't matter. All comparisons are descriptive:
they put numbers side by side over the same ticks and make no claim about
cause. Demo: `python scripts/simulate_coin.py --psychology` (add
`--events` for the event-period comparison) prints a "Psychology
observations" section; without the flag the output is unchanged.

### Advanced whale behavior (Phase 8)

Status: Steps 1-8 complete (checkpoint commit `b5a5f87`). Step 8 adds
non-reactive, schedule-driven cohort coordination only. Not implemented:
whale psychology, reactive whale-to-whale coordination (and herding,
front-running or insider behavior). Whale
manipulation remains handled by the Phase 5 manipulation system
(`core/traders/manipulation.py`); whale behaviors are ordinary
portfolio-management intents. AMM support remains subject to the existing
architecture: AMM mode still rejects every whale. Nothing here is
calibrated against real market data, and no claim is made that these
whales are realistic.

**Step 1 — whale state and accumulation/distribution foundation**
(`core/whale.py`). Every field below is optional; a whale configured
without them is the original *unfunded* whale, with the same trades,
draws and fingerprints as before.

- **Funded whales** (`starting_cash`): hold a `Wallet` (the authoritative
  balance) and settle every trade against the market reserve through
  `settle_against_reserve`, the clamp-and-transfer code traders use. Fills
  are limited by the whale's cash or coins and by the reserve, so coins
  and cash are conserved; funded whales count in
  `CoinSimulator.accounting_totals()`. Unfunded whales still trade against
  external liquidity, outside those totals.
- **Behavior** (`behavior`): `neutral` (random side when active, as
  before), `accumulate` (buys when active) or `distribute` (sells when
  active). Accumulate and distribute require `starting_cash`.
- **Target** (`target_coin_fraction`, accumulate/distribute only): the
  share of portfolio value, marked at the trade price, to hold in coins.
  The whale trades only toward it, only when it is active, and sizes the
  trade so it doesn't cross it; there is no rebalancing in the other
  direction. Step 2 below makes this a managed allocation target.
- **Sizing and cadence**: `activity_probability`; trade size uniform in
  [`min_trade_fraction`, `max_trade_fraction`] × supply; `cooldown_ticks`
  after any trade that moved coins, during which the whale sits out and
  draws nothing.
- **Price**: unchanged mechanism. The filled quantity sets the existing
  linear impact factor, applied through `MarketEngine.set_price`.
- **Randomness**: each whale keeps its own stream (seeded at
  `random_seed + 100 + i`). Active ticks draw activity, side and size in
  that order whatever the behavior, so the behavior decides direction,
  never the draws.
- **State**: `Whale.state()` returns a frozen `WhaleState` (behavior,
  funded, cash, coins, target, remaining cooldown). Whales read no events
  or psychology.

**Step 2 — whale target allocation behavior** (`core/whale.py`).
`target_coin_fraction` becomes a portfolio-management target a funded
whale works toward in bounded steps, rather than only a stopping
condition. A whale configured without a target is byte-for-byte what it
was at Step 1 — same trades, draws, prices and fingerprints.

- **The gap.** Marked at the tick's trade price,
  `portfolio_value = cash + coins x price`,
  `coin_fraction = coins x price / portfolio_value`, and
  `allocation_gap = target_coin_fraction - coin_fraction`: positive means
  underweight coins, negative overweight.
- **Direction is the behavior's, never the target's.** An accumulator only
  buys and a distributor only sells. A target can stop a whale, never turn
  it around: an accumulator above its target holds rather than selling back
  down to it, and a distributor below its target holds.
- **Bounded steps.** The drawn size (uniform in [`min_trade_fraction`,
  `max_trade_fraction`] x supply) is capped at the coins that land exactly
  on the target, then clamped by `settle_against_reserve` to the whale's
  cash or coins and the reserve's. Every clamp only shrinks the fill, so
  the whale approaches from one side and never crosses. A whale does not
  fully rebalance in one trade unless its drawn size and balances happen to
  allow it. The target cap can size the last leg below `min_trade_fraction`
  — crossing the target is the worse failure, so the cap wins.
- **Dead zone.** `TARGET_DEAD_ZONE` (1e-9, one part per billion of
  portfolio value) ends the approach: inside it the whale holds. Without
  it float residue leaves the gap minutely nonzero after the trade that
  reaches the target, and the whale would file dust trades forever, each
  burning a cooldown and nudging price. It is deliberately a *gap*
  threshold rather than `min_trade_fraction`: a whale whose smallest
  configured trade is larger than its whole gap must still be able to close
  that gap, not sit out forever.
- **Price basis.** The target is computed at the same price the trade
  settles at — the running price the whale is offered that tick, after any
  earlier whale's impact. No second price source, and no new slippage or
  impact formula.
- **Randomness: none added.** The gap, the dead-zone test and the size cap
  are deterministic arithmetic applied *after* the existing activity, side
  and size draws. A targeted whale takes exactly the draws an untargeted
  one takes, in the same order, and a whale on cooldown still draws
  nothing.
- **Observation.** `Whale.allocation(price)` returns a frozen
  `WhaleAllocation` (price, portfolio value, coin value, coin fraction,
  target, allocation gap, target coins, and `at_target`). It is `None` for
  an unfunded whale, and it is the same arithmetic the whale itself sizes
  from. `WhaleState` is unchanged; no analytics module was added.
- **Still out of scope here**: whale psychology (whales read no
  `PsychologyState`, fear, FOMO, conviction, uncertainty or social
  influence), whale coordination, and any manipulation behavior. AMM mode
  still rejects every whale, targeted or not.

**Step 3 — whale trade scheduling / patience** (`core/whale.py`).
`min_trade_interval_ticks`: the minimum number of ticks a *funded* whale
waits between successful trades. It models execution pacing — a large
participant spacing out meaningful portfolio adjustments instead of
trading at every opportunity.

**This is not psychology.** It reads no price, return, volatility,
momentum, news, sentiment, event state, `PsychologyState`, other whale or
manipulation signal. Its only input is its own tick counter. Whale
psychology remains unimplemented, and psychology calibration remains the
gate before feedback-heavy features (herding, social influence, cascades).

- **Exact tick semantics.** A successful trade at tick `T` with the
  setting at `N` blocks exactly the next `N` ticks, so the earliest next
  eligible tick is `T + N + 1`. `N = 0` (the default) blocks nothing and
  is exactly the Step 2 behavior. `N = 1` → next eligible `T + 2`;
  `N = 5` → `T + 6`.
- **Only a successful trade starts it.** The counter is set when, and only
  when, a fill actually moved coins. An inactive tick, a blocked tick, a
  target already reached, a `TARGET_DEAD_ZONE` hold, insufficient cash or
  coins, an exhausted reserve and any fill that clamps to nothing all
  leave it untouched. A partial fill *is* a successful trade — coins moved.
- **Composes with `cooldown_ticks`, does not replace it.** The two are
  separate countdowns with identical counting; `cooldown_ticks` still
  applies to every whale and still starts after any trade that moved
  coins. Both run down together on a blocked tick, and the whale is
  eligible only when both have expired — so the effective wait is the
  longer of the two (cooldown 2 + interval 5 blocks 5 ticks, not 7).
- **Sits above target allocation, never inside it.** Scheduling only
  decides *whether* the whale may act this tick. Once eligible, Step 2 is
  unchanged and still authoritative: behavior fixes direction, the dead
  zone still holds, the target still caps the size, and cash, coins,
  `min_trade_fraction` and the reserve still bound the fill. Pacing can
  never produce a trade in the wrong direction or across the target — it
  only spreads the same approach over more ticks.
- **Randomness: none added.** No new RNG stream and no new draws. Both
  counters are checked *before* the activity draw, so a blocked tick
  consumes nothing at all; enabling the setting removes draws (blocked
  ticks take none) and never adds any. With the setting at 0 the RNG
  sequence is exactly the Step 2 sequence.
- **Funded whales only.** Legacy unfunded whales are unchanged, and a
  nonzero `min_trade_interval_ticks` on one is rejected at construction
  rather than silently ignored (their pacing is `cooldown_ticks`). An
  unfunded whale trades against assumed external liquidity, so "successful
  trade" has no settlement to key off.
- **State.** One private integer countdown on the `Whale`, beside the
  cooldown counter, readable as `Whale.interval_remaining`. Nothing was
  added to `WhaleState`, `SimulationTick` or any analytics module.
- **AMM.** Unchanged and still unsupported: AMM mode rejects every whale,
  paced or not. No AMM-specific scheduling exists.

**Step 4 — explicit whale behavior state machine** (`core/whale.py`).
A behavior is a persistent *state* a funded whale can be moved between,
not just a construction-time choice. `Whale.set_behavior(behavior)` is the
transition; it returns the behavior the whale left.

- **States.** The three existing ones, unchanged: `WhaleBehavior.NEUTRAL`,
  `ACCUMULATE`, `DISTRIBUTE`. The enum is still a `str` enum, so the
  configuration strings `"neutral"`, `"accumulate"` and `"distribute"`
  remain the external names and `set_behavior` takes either form. No new
  state was added and `WhaleState` keeps its seven fields.
- **Transitions.** All nine pairs are permitted for a funded whale —
  including setting the current behavior again, which validates and is
  otherwise a no-op — so there is no transition table. The one restriction
  is the constructor's: an unfunded whale may only be `neutral`, and
  asking it to become directional raises rather than quietly funding it.
  A transition never changes whether a whale is funded.
- **A transition is a state change and nothing else.** It places no trade,
  moves no balance, and leaves `target_coin_fraction`, the trade-size band,
  `cooldown_ticks`, `min_trade_interval_ticks` and both remaining
  countdowns exactly as they were: a whale with 3 cooldown ticks left still
  has 3 afterwards, and transitioning repeatedly while blocked cannot
  shorten the wait. What changes is which direction the *next* eligible
  tick trades in, under the unchanged Step 2 and Step 3 rules — so
  becoming an accumulator far below its target does not buy; the next
  eligible tick does.
- **No automatic transitions.** Nothing in the module calls
  `set_behavior`, and no price, return, news, event, psychology, profit,
  loss, trader action or random draw can trigger one. Every transition is
  made explicitly by the caller. Automatic or adaptive whale behavior is
  **not** implemented and remains for a later phase, behind the psychology
  calibration gate.
- **Randomness: none.** A transition consumes no draws and adds no stream.
  A same-seed run with no transition is byte-identical to Step 3, and a
  given transition schedule replays exactly.
- **Targets across `neutral`.** The constructor still refuses
  `target_coin_fraction` together with `neutral`, so that pairing is now
  reachable only by transition. There the target is **dormant, not
  discarded**: a target steers one direction, which means nothing to a
  whale trading both, so a neutral whale ignores it and uses the ordinary
  neutral logic — and it is authoritative again the moment the whale is
  directional. This is the one behavioral coupling Step 4 changed, and it
  is unreachable in any Step 1-3 configuration.
- **AMM.** Unchanged and still unsupported: AMM mode rejects every whale
  in every behavior, and no sequence of transitions changes that.

**Step 5 — whale intent strength** (`core/whale.py`). `intent_strength`
is how hard a *directional* whale leans into its behavior: a weakly,
normally or strongly directional whale, set explicitly.

- **Range and default.** A number in `[0.0, 2.0]`, default `1.0`.
  `0.0` is no directional pressure, `1.0` the ordinary pressure every
  earlier step had, `2.0` the strongest a whale may be configured to lean.
  The ceiling is a guard rail, not an economic claim: without one the
  drawn size would stop mattering, since the fill would be decided
  entirely by the target cap and the reserve. Out-of-range values —
  negative, above the maximum, NaN, either infinity, booleans and
  non-numbers — are **rejected, never clamped**.
- **What it does.** One multiplication, on the size the whale *requests*:
  `requested = drawn_fraction × supply × intent_strength`, applied after
  the direction is chosen and before the target cap. Nothing else changed.
- **The default path is untouched.** Multiplying by `1.0` is exact in
  IEEE-754, so a whale at the default requests precisely what it did at
  Step 4 — same fills, prices, balances, RNG draws and fingerprints.
- **It bypasses nothing.** Intent changes only what is asked for; every
  existing bound still clamps the fill afterwards — the target cap and
  dead zone, `min_trade_fraction`/`max_trade_fraction` (which bound the
  *draw*), the whale's cash and coins, and the reserve. Strong intent
  cannot cross a target, overdraw a wallet or drain a reserve; it only
  asks for more, sooner, so a target is reached in fewer trades.
- **Neutral ignores it.** A whale trading both sides has no direction to
  press, so `NEUTRAL` reads the ordinary drawn size. That also makes
  intent inert for every unfunded whale, since those are always neutral —
  it is stored but never read, and gives them no funded semantics.
- **Scheduling and targets are untouched.** Setting intent resets no
  cooldown or trade interval, creates and changes no target, and places
  no trade. A fill that intent scaled to nothing starts no scheduling (it
  never filled); a partial fill still does, exactly as before.
- **Transitions preserve it.** `set_behavior` never changes intent and
  `set_intent_strength` never changes behavior. Intent is kept across a
  transition — dormant while neutral, back in force when the whale is
  directional again — so accumulate@2.0 → neutral → accumulate resumes
  at 2.0.
- **Randomness: none added.** No new stream and no new draws. The size
  already drawn is scaled deterministically; the draw order is unchanged;
  setting intent consumes nothing.
- **Configuration.** `intent_strength` under a whale entry, default
  `1.0`. Omitting it is exactly the Step 4 behavior.
- **No automatic adjustment.** Nothing changes intent on its own. Whales
  do **not** react to psychology, news, price, profit, volatility or any
  other market regime; every intent change is made explicitly by the
  caller. "Regime" here means only the configured strength of an
  explicitly chosen behavior.
- **AMM.** Unchanged and still unsupported: AMM mode rejects every whale
  at every intent strength.

**Step 6 — accumulation / distribution cycles** (`core/whale.py`). An
optional `cycle` gives a funded whale a repeating behavior timetable:
accumulate for a while, stand down, distribute, stand down, repeat.

- **A clock, not a judgement.** Phases and durations are fixed up front.
  The whale never infers where it is in its cycle from price, returns,
  volume, news, events, psychology, trader behavior or profitability, and
  the module imports none of those. The phase at any tick is a function of
  the tick count alone — predictable without running the market at all.
  This is **not** market-aware whale intelligence; adaptive behavior
  remains a later phase, behind the psychology calibration gate.
- **Off by default.** A whale with no cycle is byte-for-byte what it was
  at Step 5 — same fills, prices, balances, RNG draws and fingerprints —
  and carries no hidden phase counter.
- **Shape.** A list of phases, each `{"behavior": ..., "duration": ...}`
  (or a `WhalePhase`). Behavior is `neutral`/`accumulate`/`distribute`;
  duration is an integer of at least 1 tick. Validated strictly at
  construction — empty cycles, unknown behaviors, zero/negative/non-integer
  (including boolean) durations, missing or unknown keys, and malformed
  phases are **rejected, never repaired**, with the offending phase index
  named.
- **Timing.** A phase of N ticks is in force for exactly N ticks; the next
  phase opens on the tick after. The phase applies for the whole tick and
  the clock advances at the end of it, so behavior never changes
  mid-tick. Phase 0 is in force from construction, which means the cycle
  overrides the `behavior` field if they disagree. The cycle restarts
  after its last phase. Blocked and inactive ticks still advance the
  clock: a phase is a number of *ticks*, not of trades.
- **Transitions.** The cycle is only an automated caller of the Step 4
  `set_behavior`, with the same semantics: it resets no cooldown, no trade
  interval, no target and no intent, moves no balance, places no trade of
  its own, and draws no randomness. A cycling whale is indistinguishable
  from one told to transition by hand on the same ticks.
- **Target and intent carry across phases.** Both are kept untouched for
  the life of the cycle; a target is dormant through neutral phases (Step
  4) and authoritative through directional ones, and intent applies again
  the moment a directional phase resumes. Inside a phase every earlier
  rule still binds: target cap and dead zone, intent, the size band,
  cash, coins, the reserve, and both pacing counters.
- **Target validation is now cycle-aware.** Without a cycle the Step 2
  rule is unchanged (a target needs a directional behavior). With a cycle
  it is the *phases* that decide: a target is valid as long as at least
  one phase is directional, so a cycle need not repeat its opening
  behavior in the `behavior` field just to satisfy validation.
- **Randomness: none added.** No new stream, no new draws, no change to
  the draw order. A cycling whale takes exactly the draws an uncycled one
  with the same seed takes.
- **Funded whales only.** A cycle on an unfunded whale is rejected — its
  directional phases need a wallet to settle against, and a cycle never
  creates one or changes the accounting model.
- **Observability.** `Whale.cycle` is the immutable definition and
  `Whale.cycle_state()` returns a frozen `WhaleCycleState` (configured,
  phase index, phase behavior, ticks elapsed in the phase, phase duration,
  and the cycle itself). `WhaleState` is unchanged at seven fields.
- **Performance.** O(1) per whale per tick: one index lookup and one
  counter increment. The cycle is never rescanned from the start.
- **AMM.** Unchanged and still unsupported: AMM mode rejects every whale,
  cycling or not.

**Step 7 — whale observation and analytics** (`core/whale.py`,
`core/coin_simulator.py`, `analytics/whales.py`). An opt-in recording of
what each whale did, and descriptive post-processing over it.

**Observation is a recording, not whale intelligence.** It gives whales
no new information and no new behavior: nothing in the simulation reads
it, and a run with it on is identical to the same run with it off.

- **Opt-in.** `CoinSimulator(whale_observation=True)` (also on
  `build_coin_simulator`, and `--whale-observation` in the demo script);
  off by default, and not part of the config — it describes a *run*, not
  the market. With it off, behavior is byte-identical to Step 6 and
  `SimulationTick.whale_observations` is empty.
- **What is recorded.** One frozen `WhaleObservation` per whale per tick,
  in whale-list order: the whale id and whether it is funded; the
  behavior, intent strength and cycle phase/elapsed **in force for that
  tick**; the price its settlement actually used; its allocation before
  and after; the cooldown and interval counters as they stood *before* the
  tick (which is what says whether it was blocked); the trade it produced,
  if any; and its cash and coins afterwards. An unfunded whale has no
  wallet, so its allocations and cash are `None` — never a stand-in zero.
- **The price is the whale's own.** Each whale records the running price
  it settled at, before any later whale's impact moved it, so a fill is
  always described at the price it happened at rather than at a tick price
  the whale never saw.
- **No RNG, no accounting effect.** `Whale.observe` and
  `complete_observation` are pure reads: no draws, no balance changes, no
  trades. Observation on versus off gives identical prices, fills,
  holdings, reserves, trader results, event and psychology state, RNG
  sequence and final RNG state.
- **Analytics** (`analytics/whales.py`): `analyze_whales(ticks, *,
  whale_ids=None) -> WhaleReport`, frozen throughout and post-run only.
  Per whale: trade/buy/sell counts, volumes, notional, VWAP, net coin and
  cash flow, the realised allocation path (first/last/mean/min/max, ticks
  at target, widest gap, and whether any directional fill crossed the
  target — neutral-phase crossings, where the target is dormant, are
  counted separately as `dormant_crossings` since Phase 9 Step 0), time in
  each behavior, cycle phase occupancy, and a tick breakdown.
- **Tick outcomes.** Each observed whale-tick is exactly one of `traded`,
  `blocked_by_cooldown`, `blocked_by_interval`, `held_at_target`,
  `no_fill` or `inactive`, in that precedence (cooldown wins when both
  counters were running). `no_fill` — it tried and could not fill — is
  kept apart from `inactive` — it did not try. That distinction comes
  from `WhaleObservation.attempt`, which the execution path records as it
  takes each branch: the balances alone cannot tell an exhausted reserve
  from an idle tick, since a whale can be flush with cash and still fill
  nothing. Recording it writes one private marker per tick and changes no
  return value, balance or draw.
- **Descriptive only.** Every number says what was recorded, never why:
  other participants, events and noise act on the same ticks. Ticks with
  no observations are counted and excluded rather than replaced by neutral
  values, so a run made without the flag yields an empty report, not a
  report of zeros. Unfunded whales get no allocation path rather than a
  fabricated one.
- **Memory tradeoff.** With the flag on the run holds one small immutable
  record per whale per tick, so memory grows with ticks × whales. That is
  the cost of being able to describe pacing and dead-zone behavior (which
  needs the ticks a whale did *not* trade); long many-whale runs that do
  not need the detail should leave it off.
- **AMM.** Unchanged and still unsupported: AMM mode rejects every whale,
  so it records no observations.

**Step 8 — non-reactive whale cohort coordination**
(`core/whale_cohort.py`, `core/coin_simulator.py`, `core/whale.py`,
`analytics/whales.py`). A cohort puts several funded whales on one shared
behavior timetable, so they accumulate, stand down and distribute on the
same ticks.

Step 8 implements non-reactive cohort coordination. Reactive whale-to-whale behavior remains blocked by the psychology calibration gate.

- **Shape.** `WhaleCohort(cohort_id, cycle, member_ids)`: an immutable,
  non-empty id, an immutable `WhaleCycle` (the same phase shapes and the
  same validation a personal cycle has — empty cycles, unknown behaviors
  and bad durations are rejected with the phase index named), and a
  non-empty tuple of distinct member ids. Passed to
  `CoinSimulator(whale_cohorts=[...])`; none by default.
- **A clock shared, not a reaction.** The phase in force on simulator
  tick `t` (1 is the first tick) is a pure function of `t` and the cycle:
  `offset = (t - 1) mod cycle.total_ticks`. Nothing reads price, returns,
  volume, news, events, psychology, manipulation, traders, previous whale
  trades, or any whale's balances or behavior; members never observe each
  other. There is no `WhaleMarketView` and no aggregate whale context.
- **A cohort overrides a personal cycle — so both together are
  rejected.** Membership is checked when the simulator is built: only
  funded whales may join (an unfunded member is rejected; no wallet is
  ever created); a whale belongs to at most one cohort; a whale with its
  own `cycle` may not also be in a cohort (no silent precedence); cohort
  ids must be unique; member ids must name exactly one whale; and, as for
  a personal cycle, a member with a `target_coin_fraction` needs a
  directional phase in the cohort's cycle. Nothing is repaired or
  skipped.
- **Behavior only.** Each tick, before any whale acts, the simulator
  places every cohort and moves its members there with the Step 4
  `set_behavior`. Target, intent, cooldown, trade interval, balances and
  RNG state are untouched; a transition places no trade of its own, so a
  member flipping phase while blocked stays blocked and an idle member
  never trades. Members open in the first tick's phase at construction,
  as a whale with a personal cycle opens in phase 0.
- **Equivalent to a personal cycle.** A one-member cohort produces the
  same run — prices, fills, balances, RNG — as that whale carrying the
  cycle itself, and the same as the same transitions made by hand.
- **Randomness: none added.** The cohort module imports no randomness;
  members take exactly the draws a non-member with the same seed takes,
  and the price and volume streams are unaffected.
- **Order-independent.** Reordering the whale list or the cohort list
  changes no whale's schedule (fills may differ, as they always have,
  because whales settle in list order at the running price).
- **Observability.** `WhaleObservation` gains `cohort_id` (default
  `None`); for a member the cycle phase fields report the cohort's phase,
  the one in force. `WhaleSummary.cohort_id`, `WhaleReport.cohort_ids`
  and `WhaleReport.cohort(id)` group the analytics by cohort.
  `WhaleState`, `WhaleTrade` and `maybe_trade` are unchanged.
- **Performance.** O(whales + cohorts) per tick: one O(log phases)
  placement per cohort and one `set_behavior` per member; without cohorts
  the step is skipped entirely.
- **Compatibility.** Without cohorts every run is byte-identical to
  `649bdee` (pinned in `tests/core/test_coin_simulator_whale_cohorts.py`);
  builder fingerprints are unchanged.
- **Not configurable yet.** Cohorts are a Python API only; there is no
  `coin.whale_cohorts` config key, builder argument or demo flag.
- **AMM.** Unchanged: AMM mode still rejects every whale with the same
  message, and rejects cohorts too.
- **Module split.** Cohorts live in their own module, which reads from
  `core/whale.py` (including its cycle validator); `core/whale.py` does
  not import it, so the whale module's import-isolation guard is
  unchanged.

**Still not implemented for whales** (later phases, after the psychology
calibration gate): whale psychology or sentiment, behavior or intent
that adapts to market conditions (Step 6's cycles and Step 8's cohorts
are fixed timetables, not reactions), reactive whale-to-whale
coordination, herding, social influence, and cascades. Whale manipulation
remains the Phase 5 system's job.

**Note for a future AMM whale step.** Routing whales through the pool is
still unplanned, and target allocation does not change that: a pool fill's
price moves along the curve as the trade executes, so the coins that land
exactly on a target are no longer `target_coins - coins` at a single mark
price — sizing would need to solve against the constant-product curve (and
its fee), or iterate. That is a redesign of the sizing step, not a
parameter change, and is deliberately not attempted here.

### Advanced market analytics (Phase 9)

Status: Step 0 complete. Steps 1–8 (market, trader, whale-activity,
event-window, psychology co-movement, manipulation and regime analytics,
and a unified report) are planned and **not implemented**. Every Phase 9
step is post-run analytics only: nothing it computes may feed back into
the simulation, and the psychology calibration gate above still applies.

**Step 0 — analytics hygiene and compatibility harness**
(`analytics/whales.py`, `tests/compat/`, `scripts/compat/`). No
simulation code changed.

- **`crossed_target` correction.** A target binds a whale only while it
  is accumulating or distributing. `AllocationPath.crossed_target` now
  counts crossings by directional fills only; a neutral fill that crosses
  the target (after a transition, or in a neutral cycle or cohort phase)
  is counted in the new `dormant_crossings` field instead. Both keep the
  dead-zone rule, and both are `None` without a single target.
- **Linear duplicate-tick check.** `analyze_whales` validates tick
  numbers in one pass (previously quadratic) with the same error message.
- **Compatibility harness** (developer/test tooling; the package never
  imports it). `tests/compat/grid.py` runs a fixed digest grid in nine
  levels, one per Phase 8 checkpoint from `aa213a8` (pre-Phase 8) to
  `b5a5f87`, each using only the features that existed at that
  checkpoint, plus builder runs in both pricing modes, AMM worlds, both
  builder fingerprints and the demo CLI's output. The digests are pinned
  in `tests/compat/pinned_digests.json`; the test suite checks the working
  tree against them, and `python scripts/compat/compare_checkpoints.py`
  checks every checkpoint (or any `--ref`) against them — every
  checkpoint reproduces every level up to its own.

---

**Out of scope, permanently:** live exchange APIs, real order routing,
real wallets/custody, real payment rails. If a future contributor
proposes any of these, it does not belong in this repository.
