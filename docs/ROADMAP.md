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
  - [x] Psychology calibration — completed in Phase 18 (see "Coin
        economy: future roadmap" below)
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
- [x] Advanced market analytics (Phase 9, complete — see "Advanced
      market analytics" below)
  - [x] Step 0: analytics hygiene and compatibility harness
  - [x] Step 1: core market analytics
  - [x] Step 2: trader analytics
  - [x] Step 3: whale activity analytics
  - [x] Step 4: event-window market path analytics
  - [x] Step 5: psychology-market co-movement analytics
  - [x] Step 6: manipulation analytics
  - [x] Step 7: descriptive market regimes
  - [x] Step 8a: unified report data
  - [x] Step 8b: report rendering and `--report`
- [x] Web dashboard (Phase 10: Steps 1-7 complete — see "Web dashboard"
      below)
  - [x] Step 1: dashboard foundation and architecture
  - [x] Step 2: functional market dashboard
  - [x] Step 3: functional trader dashboard
  - [x] Step 4: functional whale dashboard
  - [x] Step 5: events and psychology dashboard
  - [x] Step 6: manipulation and regimes dashboard
  - [x] Step 7: simulation controls
- [x] CLI random-seed parity (Phase 11, complete — see "Coin economy:
      future roadmap" below)
- [x] Coin-track persistence (Phase 12, complete — see "Coin economy:
      future roadmap" below)
- [x] Scenario save/load (Phase 13, complete — see "Coin economy: future
      roadmap" below)
- [x] Mass/batch simulation (Phase 14, complete — see "Coin economy:
      future roadmap" below)
- [x] Aggregate statistics (Phase 15, complete — see "Coin economy:
      future roadmap" below)
- [x] Stress testing (Phase 16, complete — see "Coin economy: future
      roadmap" below)
- [x] Market-condition scenario system (Phase 17, complete — see "Coin
      economy: future roadmap" below)
- [x] Psychology calibration (Phase 18, complete — closes the roadmap
      gate below — see "Coin economy: future roadmap" below)
- [x] Realism / feedback pass (Phase 19, closed — individual responses
      to crowd information established, participant-to-participant
      propagation / herding not established; see "Coin economy: future
      roadmap" below and `docs/PHASE_19_FINAL.md`)
- [x] Advanced visualization (Phase 20, closed — tick-level, batch,
      scenario-comparison and cross-run price-path views; see "Coin
      economy: future roadmap" below)
- [x] CI / GitHub integration (Phase 21, closed — macOS GitHub Actions:
      Python 3.12/3.13 suite, slow tests, checkpoint comparison, coverage
      artifact; see "Coin economy: future roadmap" below)
- [x] Documentation & notebooks (Phase 22, closed — architecture,
      reproducibility, CLI and dashboard guides and executable example
      scripts; see "Coin economy: future roadmap" below)
- [x] Version 1.0 (Phase 23, closed — version 1.0.0 prepared and
      audited release-ready; see "Coin economy: future roadmap" below)

> **Roadmap gate:** Psychology calibration must be completed before
> implementing feedback-heavy features such as cascades, herding, or social
> influence.
>
> Phase 18 below closes this gate; Phase 19 is the feedback pass it
> unlocks.

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

Status: **complete** (Steps 0–8b). Every Phase 9 step is post-run
analytics only: nothing it computes feeds back into the simulation, and
the psychology calibration gate above still applies.

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

**Step 1 — core market analytics** (`analytics/market.py`, private
helpers in `analytics/_series.py`). `analyze_market(ticks, *,
initial_price=None, total_supply=None, start_tick=None, end_tick=None)
-> MarketSummary`, frozen throughout, post-run only. It reads recorded
ticks and nothing else: no simulation code changed, no randomness is
drawn, and nothing it computes reaches the simulation. Descriptive only —
no figure is a claim about why the market moved, and none is a signal.

- **Price path.** One price per tick (its close); no candles, no tick 0.
  `initial_price` (the pre-run price, normally `coin.starting_price`)
  joins the path as point `PRE_RUN_TICK` = 0 — the convention
  `analytics/events.py` already uses — only when tick 1 is analysed; a
  window starting later never gets it. Open is the first point, close the
  last; high and low are the path's extremes, earliest on ties.
  `start_tick`/`end_tick` select a window of tick numbers and every
  definition then applies to that window alone.
- **Returns** (simple, and log for volatility) exist only between
  consecutive tick numbers; a missing tick is never bridged, and
  `missing_tick_count` reports the gaps. `volatility` is the sample
  standard deviation of log returns with at least two of them — the same
  definition as `analytics/events.py`, checked to agree bit for bit.
  `realized_volatility` is sqrt(sum of squared log returns). Neither is
  annualized: a tick is simulated time, not calendar time.
- **Drawdown** is `1 - price / running peak`; `max_drawdown` is the
  deepest (earliest trough on ties) with its peak and trough ticks, and
  `recovery_tick` is the first later point back at or above that peak
  (`None` if it never gets there). A path that never falls has a maximum
  of 0.0 and no peak/trough ticks.
- **Market cap** is price × `total_supply` at open and close; `None`
  without `total_supply`.
- **Volume decomposition.** A random-walk tick's `volume` is its
  synthetic volume plus every whale trade plus every trader fill — *both*
  wash legs included (replaying that accumulation reproduces each tick's
  volume bit for bit). So each recorded quantity is classified once:
  `total = background + whale + organic + manipulator + wash`, where wash
  is every fill flagged `wash` (whoever made it), manipulator is any other
  fill by a manipulation strategy, and organic is the rest. Wash volume is
  never added on top of trader volume. Background is the synthetic
  volume, which is not recorded, so it is the per-tick residual
  `volume - fsum(participant quantities)` — exact up to a few units in the
  last place, never clamped. In AMM mode the volume is only trader fills
  (wash legs included), there are no whales, and `background_volume` is
  `None` (not applicable, rather than a measured zero).
- **Activity.** Fill counts by category (zero-quantity whale trades are
  counted apart and are not fills); `average_trade_size` over whale,
  organic and manipulator fills; `trader_vwap` over non-wash trader fills
  (AMM prices include fees).
- **Turnover** is `total_volume / total_supply`, the same scale the
  synthetic volume is drawn at; `participant_turnover` counts only whale,
  organic and manipulator volume (no synthetic background, no wash legs).
  Both need `total_supply`.
- **AMM pool activity**: swap count, fees (cash on buys, coins on sells,
  kept apart), and the largest absolute price impact of a single swap —
  exact `Decimal`s from the recorded swaps, which equal the pool's own
  fee counters. `None` in random-walk mode.

**Step 2 — trader analytics** (`analytics/traders.py`).
`analyze_traders(ticks, *, start_balances=None, end_balances=None,
initial_price=None, trader_ids=None) -> TraderReport`, with frozen
`TraderSummary` (per trader, ordered by id) and `StrategySummary` (per
recorded strategy label). Post-run and descriptive only: it reads the
`TraderTrade` records and the balances it is given, draws no randomness,
changes no simulation code, and makes no recommendation.

- **The simulator's accounting is the source of truth.** Quantities and
  notionals are taken as settlement recorded them — in random-walk mode
  `notional` is the exact cash moved; in AMM mode it is the float value of
  the exact `Decimal` amount, fee included. Nothing is re-priced and no
  balance is reconstructed in the analytics. The tests prove the records
  are exactly what settlement did: replaying each trader's fills with the
  same `Wallet` calls in `settle_against_reserve`'s order reproduces the
  actual wallets bit for bit (partial fills and wash round trips
  included), and in AMM mode the recorded swap amounts land exactly, in
  `Decimal`, on the actual wallets and on the pool.
- **Records, fills, legs.** A record with zero quantity is counted but is
  not a fill. Each fill is exactly one of a buy, a sell, or a wash leg
  (flagged `wash` by the simulator). Buy and sell figures exclude wash
  legs, which have their own counts, volume and notional; `total_volume`,
  `vwap` (Σ notional / Σ quantity) and the flows cover every fill, so wash
  volume is counted exactly once. Activity (`active_ticks`, first/last
  fill tick, average fill size) counts fills, never attempts.
- **Requested versus filled.** `requested_volume` sums the recorded
  `requested_quantity` of every record; `fill_ratio` = filled /
  requested, `None` when requested is 0 or unrecorded. Random-walk
  settlement can only clamp, so the ratio is at most 1; an AMM buy spends
  the budget its request is worth at the tick's opening price, so it can
  receive more when earlier swaps that tick lowered the pool price (every
  such case was verified to follow a price fall).
- **Net flows**: `net_coin_flow` = bought − sold; `net_cash_flow` = cash
  received on sells − cash paid on buys (a buy is negative, as in the
  wallet). In AMM mode `exact_cash_flow`/`exact_coin_flow` are the exact
  `Decimal` flows from the recorded swaps.
- **AMM fees** are the recorded `swap.fee` of each trader's own swaps —
  cash for buys, coins for sells, kept apart — and are informational: the
  fee is already inside the swap amounts and notional and is never charged
  again. Trader fees sum to the pool's own fee counters. `None` in
  random-walk mode.
- **Equity and P&L** use the demo CLI's definition exactly: equity = cash
  + coins × price (the expression `Wallet.equity` evaluates), valued at
  `initial_price` for the start balances and at the last analysed tick's
  price for the end balances; P&L = end − start; return = P&L / start
  equity when that is positive. The ticks record no wallets, so the
  balances are `{trader_id: (cash, coins)}` snapshots of the simulator's
  own wallets, supplied by the caller. The P&L equals the CLI's figure bit
  for bit (tested in both modes, with scenarios). No realized/unrealized
  split, cost basis or extra fee accounting.
- **Population and strategies.** The population is every trader seen in
  a record plus every trader in the balances (or exactly `trader_ids`);
  participation = active / population. A trader known only from balances
  has no recorded strategy and is grouped under `None`. The manipulator
  flag is the recorded strategy label, never inferred from behavior.
- **Missing data** gives `None`, never a stand-in: no balances → no
  equity or P&L; no `initial_price` → no start equity; no ticks → no final
  price; zero start equity → no return.

**Step 3 — whale activity analytics** (`analytics/whale_activity.py`).
`analyze_whale_activity(ticks) -> WhaleActivityReport`, frozen throughout,
post-run and descriptive only. It builds on Step 1 and Step 7 rather than
competing with them — a `WhaleActivity` *embeds* the existing
`WhaleSummary` (`analytics/whales.py`) instead of recomputing any of it,
and the market-wide volume figures are `analyze_market`'s own
`VolumeBreakdown.total_volume`/`.participant_volume` for the same ticks.
There is exactly one accounting engine for whale balances and volume;
this module never re-derives cash or coin movement itself.

- **Volume share.** `whale_volume` is the sum of every reported whale's
  `WhaleSummary.total_volume` (observation-based); `total_market_volume`
  and `participant_volume` are Step 1's own totals for the same ticks.
  `whale_volume_share_of_total`/`_of_participants` divide the two,
  `None` with a zero denominator — never a manufactured ratio.
- **Observation coverage.** A tick with an empty `whale_observations`
  tuple cannot be told apart from "no whale acted" and "observation was
  off" (the convention `analytics/whales.py` already accepts).
  `coverage` is `"none"` (no analysed tick carried an observation — every
  whale-level figure is unavailable, not zero, since whales may still
  have traded unobserved), `"complete"` (every tick did), or `"partial"`
  (some did; the observed subset is analysed and reported as real
  numbers, only the label says it was incomplete).
- **Per-whale additions**, in `WhaleActivity` alongside the embedded
  `WhaleSummary`: `first_fill_tick`/`last_fill_tick`, `average_fill_size`,
  and `volume_share_of_whale_volume` (this whale's total volume against
  the report's aggregate).
- **Allocation gap** (`AllocationGapStats`) — mean/max absolute gap and
  mean signed gap — uses every observation that carries a target-relative
  allocation, whatever the whale's current behavior: a dormant (neutral)
  tick still has a well-defined gap, it is just not being pursued.
  `None` with no applicable observation, never a zero-sample result.
- **Target reaching** (`TargetReaching`) is the opposite: it counts only
  observations taken while the whale was actively `ACCUMULATE` or
  `DISTRIBUTE`, so a target left dormant by a transition, a neutral cycle
  phase or a neutral cohort phase is never mistaken for an unreached (or
  reached) pursuit. `first_tick_at_target`/`ticks_to_target` use the
  existing dead-zone test (`WhaleAllocation.at_target`).
- **Behavior aggregation** (`BehaviorActivity`) groups every observation
  by the behavior *in force that tick* — already cohort/cycle-resolved —
  into fill counts, buy/sell/total volume and net coin flow. Always
  reports all three behaviors, zero-filled when unobserved: a real fact
  about the run, not a stand-in for missing data.
- **Cohort activity** (`CohortActivity`) aggregates a cohort's reported
  members (membership and counts read from the observations themselves,
  not from the cohort's own configuration, which this module does not
  receive): member/active-member counts, observation ticks, fills,
  volumes, net coin flow, and volume share of the report's aggregate
  whale volume.
- **Cohort co-fill** (`CoFillStats`) is a plain simultaneity count — the
  share of a cohort's member-observation-ticks belonging to a tick on
  which two or more members filled, plus how many of those simultaneous
  ticks were same-side versus mixed-side. It says nothing about
  coordination, herding, influence or causation: cohorts are already a
  fixed, non-reactive schedule (`core/whale_cohort.py`), and this module
  adds no new behavior. `None` (not a degenerate ratio) for a cohort with
  fewer than two members.
- **AMM.** Phase 8 whales are rejected in AMM mode, so an AMM run's ticks
  carry no whale trades or observations. Nothing here special-cases AMM —
  the ordinary "no observations" path already yields `coverage="none"`
  and an empty report — and `analyze_market` still raises if `ticks` mix
  AMM and random-walk records, reused for free.
- **Duplicate whale ids** within one tick's observations are rejected
  with `analyze_whales`'s own error, reused rather than re-implemented.

**Step 4 — event-window market path analytics**
(`analytics/event_windows.py`). `analyze_event_windows(ticks, events, *,
initial_price=None, total_supply=None, post_window=..., baseline_window=...,
trader_count=None, random_event_ids=None) -> EventWindowReport`, frozen
throughout, post-run and descriptive only. It adds nothing that
`analytics/events.py` (event observations) and `analytics/market.py`
(Step 1's price/return/volume/drawdown definitions) do not already
define — it only *partitions* a run's ticks into four windows per event
and hands each partition to `analyze_market` unchanged, so every return,
drawdown and volume figure is Step 1's exact formula, never a copy of it.

- **Four windows**, derived only from the event's own ground-truth
  lifecycle (`MarketEvent.start_tick`/`last_active_tick`/`expires_at`,
  never guessed from price behavior) and non-overlapping by construction:
  `pre_event` (`baseline_window` ticks before `start_tick` — the same
  parameter Step 1 already defines, reused verbatim), `active`
  (`start_tick..last_active_tick`, the `EventPhase.ACTIVE` span),
  `decay` (`last_active_tick+1..expires_at-1`, the `EventPhase.DECAYING`
  span — `None` when `decay_ticks == 0`, since there is then nothing to
  request, not an empty result), and `post_event` (`post_window` ticks
  starting at `expires_at`, the first tick with zero effect). A fifth,
  `effect`, is `active` and `decay` combined (`start_tick..expires_at-1`
  — "while the event had any effect at all"), a convenience window for
  peak/trough/expiration-price questions spanning both. This four-way
  split deliberately differs from `analytics/events.py`'s own coarser
  "post window" (`post_window` ticks after `last_active_tick`, which can
  overlap the decaying phase) — that is Step 1's view; Step 4's is more
  granular, and no tick is ever counted in more than one of
  pre/active/decay/post.
- **Named prices** are not duplicated as separate fields; they are exact
  nested reads off each window's embedded `MarketSummary`: pre-event
  price is `pre_event.market.close_price`, activation price
  `active.market.open_price`, peak/trough price `effect.market.high_price`
  /`.low_price`, expiration price `effect.market.close_price`, and
  post-event price `post_event.market.close_price`.
- **Incompleteness is preserved, never padded.** Each `EventWindow`
  carries both `ticks_requested` (the window's length by definition,
  already clamped to tick 1) and `market.ticks` (what was actually
  supplied); `complete` compares them. A window with literally nothing to
  request (`decay_ticks == 0`, or an event starting at tick 1 has no
  pre-event window) is `None` outright, distinct from a window that could
  exist but has fewer ticks than requested.
- **No bridging.** Every return, drawdown and volatility figure comes
  from `analyze_market`'s own log-return machinery, which never bridges
  across a missing tick number; a window with zero observed ticks reports
  `None` returns, never zero, and a single observed tick reports an exact
  zero return (a real fact — open equals close — not a missing one).
- **Volume** is exactly `analyze_market`'s `VolumeBreakdown` per window
  (background/whale/organic/manipulator/wash in random-walk mode, trader
  swap volume only in AMM mode). Whale volume reads
  `SimulationTick.whale_trades` directly — recorded whenever a whale
  trades whether or not `whale_observation` was turned on — so it is
  always directly observable in random-walk mode and naturally `0.0` in
  AMM (Phase 8 rejects whales there); this is not the richer per-whale
  detail `analytics/whale_activity.py` (Step 3) adds, which this module
  does not attempt.
- **Overlap** reuses `analyze_events`'s own detection
  (`overlapping_event_ids`/`overlap_count`) verbatim; overlapping events
  keep separate identities and separate windows, never merged into one
  synthetic event or attributed to one over another live at the same
  time. Adjacent events that merely touch (one's `expires_at` equals the
  next's `start_tick`) do not count as overlapping.
- **Provenance** reuses `analyze_events`'s own `randomly_generated`
  field (`True`/`False`/`None` for unknown) via `random_event_ids`; no
  new provenance model.
- **Category aggregation** (`CategoryActivity`) groups reported events by
  their ground-truth `category`: event count, observed ticks, mean
  severity/sentiment, mean active/post-window return and active-window
  volatility over whichever events have one, and total active-window
  volume. Categories are listed alphabetically, never ranked; there is no
  "best" or "worst" category and no claimed effect.
- **Event ids must be unique** across the supplied `events` — the same
  contract `core/events/engine.py`'s `EventEngine` already enforces at
  construction, checked again here since a hand-built `events` sequence
  can bypass it.
- **Performance.** A `{tick: SimulationTick}` index and `analyze_events`
  are each built once; each window then slices only its own relevant
  ticks before calling `analyze_market`, so cost is `O(events × relevant
  ticks)`, not `O(events × total ticks)`.

**Step 5 — psychology-market co-movement analytics**
(`analytics/psychology_market.py`). `analyze_psychology_market(ticks, *,
initial_price=None) -> PsychologyMarketReport`, frozen throughout,
post-run and descriptive only. It is not a second psychology or market
implementation: `analyze_psychology`'s own validation, per-component
distributions (mean, percentiles, threshold occupancy, persistence) and
event-period comparison are embedded verbatim, and every price/volume
figure is `analyze_market`'s own `VolumeBreakdown` for the tick in
question.

- **Never a causal claim.** Every relationship is a same-tick or lagged
  *co-movement* — values observed alongside each other, nothing more.
  Wording throughout is "observed alongside", "same-tick relationship",
  "lagged descriptive comparison"; the module and its tests are checked
  to never contain "caused", "led to", "drove", "resulted in", a forecast
  claim, or an "effectiveness" claim.
- **Alignment is by tick number, never by list position.** `ordered_ticks`
  sorts and validates first, so shuffled input never changes the result.
  A same-tick return needs the previous tick number present and adjacent
  (Step 1's rule, reused); a missing tick is never bridged, and its
  absence simply leaves that tick's return (and any lag-1 pair landing on
  it) unavailable rather than zero.
- **Per-tick observations** (`PsychologyMarketObservation`): price,
  simple/log return (`None` without a valid predecessor), total volume,
  `analyze_market`'s per-tick participant/whale volume, the four
  psychology components, the tick's dominant component (the same
  tie-break `analyze_psychology` documents — largest value, ties to the
  first in `COMPONENTS` order, `NEUTRAL` at all zero), and event context
  read straight off the tick's own `EventState` (`event_active`,
  `event_count`, `event_sentiment`, `event_attention` — all `None` only
  when the run had no event engine at all). No event *severity* figure:
  that is `MarketEvent` ground truth (`analytics/events.py`/
  `analytics/event_windows.py`), which this function's signature — taking
  only `ticks` — has no access to.
- **Correlation method**: Pearson's r (`statistics.correlation`, linear).
  Fewer than two paired observations, or either side constant across the
  pairs, reports `None` with `unavailable_reason` set
  (`INSUFFICIENT_PAIRS`/`ZERO_VARIANCE`) — never `NaN`/infinity, never a
  fabricated value. A fixed, short, declared list of same-tick pairs is
  reported (fear/fomo/conviction vs. log return, fear/fomo/uncertainty vs.
  volume, conviction vs. participant volume, uncertainty vs.
  `abs_log_return` — the log return's own magnitude, since this codebase
  has no per-tick volatility to pair against; Step 1's volatility is a
  window statistic, not a single tick's), never ranked and never labelled
  "strongest".
- **Lag** is limited to lag 1, deliberately (a smaller correct
  implementation over a broad, unreliable one): each psychology component
  at tick *t* against the log return realised at tick *t + 1*, labelled
  `PSYCHOLOGY_LEADS_MARKET` — a timing label, not a forecasting claim —
  with `pairs` reflecting whatever no-bridging exclusions apply.
- **Grouping** (`ComponentGroupComparison`) splits each component's ticks
  at one fixed, pre-declared threshold (`GROUP_THRESHOLD = 0.5`, the same
  "at or above" convention `analyze_psychology`'s occupancy already uses)
  into low/high, reporting each side's mean log return, volume and
  participant volume side by side — sample counts included, groups never
  ranked, an empty side reporting `None` averages rather than zeroes.
- **Coverage** (`"none"`/`"partial"`/`"complete"`) restates — rather than
  imports — the three-level vocabulary `analytics/whale_activity.py`
  (Step 3) established, since the two describe unrelated kinds of
  coverage.
- **AMM**: whale volume is `0.0` in every observation (Phase 8 rejects
  whales there); nothing here infers whale activity from a residual.
- **Performance.** One pass builds the price path and tick-indexed return
  map; per-tick volume is one `analyze_market` call over a single-tick
  list (`O(1)` each); correlations and groups are each one linear pass
  over the already-built observations — overall `O(ticks + valid paired
  observations)`.

**Step 6 — manipulation analytics** (`analytics/manipulation.py`).
`analyze_manipulation(ticks, *, initial_price=None) -> ManipulationReport`,
frozen throughout, post-run and descriptive only. It is not a second
settlement or volume engine: every top-level volume figure is
`analyze_market`'s own `VolumeBreakdown` for these ticks, and
`pump_and_dump_strategy`/`wash_strategy` are `analyze_traders`'s own
`StrategySummary` for those two strategy labels, embedded rather than
recomputed.

- **Identification is registry-based, never inferred from behavior.** A
  fill is manipulation exactly when the simulator recorded it that way:
  `TraderTrade.wash` (set on both legs by `execute_wash`/
  `execute_wash_via_pool`, whoever the trader is) or `TraderTrade.strategy`
  naming a class in `MANIPULATION_STRATEGIES`
  (`core/traders/registry.py`). A large trade, a fast return or unusual
  volume is never treated as manipulation on its own. This module's own
  per-fill classification mirrors `analytics/market.py`'s
  `_volume_breakdown` precedence exactly (wash first, then a registered
  strategy, then organic), so the two never disagree.
- **Volume, precisely.** `manipulation_volume` is
  `manipulator_volume + wash_volume` — two of `VolumeBreakdown`'s five
  *already-disjoint* categories, never wash added on top of a total that
  already contains it. `pump_and_dump_volume` is `manipulator_volume`
  under today's registry (the only non-wash manipulation strategy); a
  test proves `background + whale + organic + manipulator + wash` equals
  `total_volume` on both hand-built and real-run ticks. The two share
  fields use *different* numerators on purpose:
  `manipulation_share_of_total` divides the wash-inclusive
  `manipulation_volume` by `total_market_volume` (which also includes
  wash), while `manipulation_share_of_participants` divides only
  `pump_and_dump_volume` by `participant_volume` — Step 1 already
  excludes wash (a self-cancelling leg) from `participant_volume`, so
  pairing a wash-inclusive numerator with it would produce a ratio that
  isn't a share of anything and can exceed 1.
- **Pump-and-dump phases** come from `TraderTrade.reason` — the exact
  string `PumpAndDump._decide` already records on every fill it produces
  ("accumulate", "pump", "dump"; see `core/traders/manipulation.py`) —
  never reconstructed from a price threshold or the scheme's tick
  schedule (which this function has no access to: its signature takes
  only `ticks`). One `PumpAndDumpSummary` per manipulator id, since
  phases are inherently per-trader; each summary's price, return and
  drawdown figures are one `analyze_market` call over that trader's own
  observed span (`first_tick`..`last_tick`) — peak `market.high_price`,
  trough `market.low_price`, scenario return `market.cumulative_return`,
  drawdown-after-peak `market.max_drawdown`/`.drawdown_peak_tick`/
  `.drawdown_trough_tick`/`.recovery_tick`. None of this is a claim of
  profit or success, and no claim is made that the supplied ticks capture
  a scenario's whole run — a summary with no dump fills may mean the
  scheme never reached that phase, or that the phase lies outside the
  analysed range; the two cannot be told apart from ticks alone.
- **Wash trading** (`WashSummary`) aggregates every fill flagged `wash`
  into fill count, volume, a buy/sell split (which `analytics/traders.py`
  deliberately does not report, keeping wash apart from a trader's
  buy/sell figures), notional, active-tick timing and volume per active
  tick. Price observations around wash activity are exactly that —
  observations, never a "wash-trading price impact": random-walk wash
  legs settle at the going price with no impact of their own; AMM wash
  legs are real swaps that can move the pool's spot price through its own
  mechanics, never attributed to manipulation "working".
- **Manipulation vs. organic** (`ActivityComparison`) puts volume,
  buy/sell split, notional, active ticks and average fill size side by
  side — a comparison, never a ranking, and never a claim about how well
  either worked or whether one responded to the other.
- **Coverage** (`"none"`/`"partial"`/`"complete"`) describes something
  narrower than in Steps 3/5: `SimulationTick.trader_trades` has no
  opt-in recording flag to be missing, so this is which manipulation
  *kinds* were found (pump-and-dump, wash, both, neither) — not, and
  never, a claim about a scenario's temporal completeness (see above).
- **P&L/equity** are always `None` here (this function accepts no wallet
  balances); call `analyze_traders` directly with balances for an exact
  figure, per its own Step 2 convention.
- **Performance.** One linear pass over every recorded fill builds every
  aggregate in this module; per-scenario price/return figures are one
  `analyze_market` call over that scenario's own (typically short) tick
  span — overall `O(ticks + manipulation records)`.

**Step 7 — descriptive market regimes** (`analytics/regimes.py`).
`analyze_regimes(ticks, *, initial_price=None, window_size=20,
total_supply=None) -> RegimeReport`, frozen throughout, post-run and
descriptive only. **Regime labels describe observed historical market
conditions and are not predictions or trading signals.** Nothing reads
them back: no trader, whale, event or psychology state consumes a regime,
and no label is an input to the simulation.

- **Windows** are fixed by tick number, not by which ticks were supplied:
  window `k` covers ticks `k·window_size + 1` .. `(k + 1)·window_size`
  (1–20, 21–40, … by default). Only windows holding at least one tick are
  reported (`window_index` exposes a whole window skipped by a gap). A
  window with fewer ticks than it spans — a gap, or the run ending
  part-way through, as the final window usually does — is kept with
  `complete=False` and analysed on the ticks it has, never padded.
  `coverage` is `"complete"` only when every reported window is.
- **Every figure is `analyze_market`'s own**, over the window's ticks,
  embedded as `market`: price path, high/low, returns, volatility,
  realized volatility, drawdown, `VolumeBreakdown`, average trade size,
  turnover (with `total_supply`). That includes Step 1's windowing: a
  return exists only between consecutive tick numbers inside the window,
  so the return into a window's first tick belongs to no window, and the
  pre-run price joins window 0 only when tick 1 is present (without
  `initial_price`, window 0 simply has one return fewer).
  `market.cumulative_return`/`log_return` are Step 1's open-to-close
  figures and span any internal gap; `net_log_return` sums consecutive
  returns only, and is what direction uses — no label rests on a move
  across a missing tick.
- **Taxonomy** — four independent dimensions, each `None` when the data
  cannot support it (a window can exist with a dimension unavailable):
  - `direction` (`rising`/`falling`/`flat`): `net_log_return` against the
    window's own `market.realized_volatility` — rising when the net move
    is larger, falling when more negative, flat otherwise. Scale-free, no
    percentage cut-off; needs at least two returns (Step 1's volatility
    minimum). A missing tick is not a flat tick: gaps simply contribute no
    return.
  - `volatility` and `volume` (`low_`/`normal_`/`high_`): the window's
    `market.volatility` and its volume per observed tick against the lower
    and upper quartiles of the same figure over every **earlier complete**
    window (below the lower quartile low, above the upper high, between
    them inclusive normal; quartiles by the inclusive linear-interpolation
    percentile `analytics/psychology.py` documents). No class until four
    earlier complete windows exist — the fewest that can populate four
    quartile bins. The quartile bounds used are recorded on the window
    (`volatility_reference`/`volume_reference`) so every label can be
    checked by hand.
  - `market_state` (`at_high`/`drawdown`/`recovery`): against the highest
    price observed anywhere in the analysed history up to the window's
    last point — `at_high` when the window closes at that running high;
    otherwise `recovery` when the drawdown at the close is smaller than at
    the window's first point, and `drawdown` when it is not. "Recovery"
    means a narrowing already observed, not one still to come.
  `description` joins the four labels (`unavailable` for a missing one);
  there is no Cartesian enum of combined regimes.
- **No look-ahead.** A window's labels read only its own ticks, earlier
  windows and earlier prices: the grid is fixed by tick number, the
  quartile reference grows one completed window at a time (a window joins
  it only after its own labels are fixed, so it is never compared with
  itself), and the running high is a prefix maximum. Tests truncate real
  runs and rewrite every later tick's price and volume, and require every
  earlier window to come back identical. The trade-off is deliberate:
  early windows are classed against a thinner history than later ones,
  and a class is relative to the run *before* the window, never the whole
  run — a dataset-wide quantile would leak later windows into earlier
  labels.
- **Context, never a label input.** Each window records, alongside its
  labels: event state from each tick's own `EventState` (ticks with a
  live event, distinct event ids and categories, most live at once —
  `event_active` is `None` when no tick recorded an event state); mean
  fear/FOMO/conviction/uncertainty over ticks that recorded psychology
  only (`None` without any, never a neutral stand-in); ticks carrying
  whale observations; and manipulation volume and activity, read from the
  window's `VolumeBreakdown` (manipulator + wash, each counted once).
  Tests attach events, maximal fear and uncertainty, and whale
  observations to otherwise identical ticks and require identical labels.
  A high-volatility window with a live event is two observations side by
  side; a sharp rally is labelled `rising`, never a pump, and no window is
  labelled manipulated from its price path. Event severity is not
  recorded per tick and is not reported.
- **Validation** reuses the existing checks: duplicate tick numbers,
  invalid prices, mixed AMM/random-walk ticks, invalid `initial_price`/
  `total_supply` and malformed psychology states are rejected, as are an
  invalid `window_size` and a non-finite or negative volume.
- **Performance.** One pass buckets ticks and builds the running high;
  each window is one `analyze_market` call over its own ticks; each
  reference insert is a binary search plus one list insert — linear in
  ticks at ordinary window sizes (about 0.5 s for 80,000 ticks at the
  default), with a memory-move term that only grows noticeable when
  windows are tiny relative to the run (80,000 one-tick windows ≈ 3 s).

**Step 8a — unified report data** (`analytics/report.py`).
`build_report(ticks, *, events=None, random_event_ids=None,
initial_price=None, total_supply=None, start_balances=None,
end_balances=None, window_size=20, start_tick=None, end_tick=None)
-> SimulationReport`. Data only, and descriptive only: it composes the
independent analytics into one frozen object and changes no simulation
behavior. **Rendering the report is not part of Step 8a, and neither is a
`--report` CLI flag** — both are Step 8b.

- **Composition, not calculation.** Each section is one call to an
  existing function, held unchanged: `market` (`analyze_market`),
  `traders` (`analyze_traders`), `whale_activity`
  (`analyze_whale_activity`, which embeds `analyze_whales`),
  `event_windows` (`analyze_event_windows`, which embeds `analyze_events`'
  ground truth and overlap), `psychology_market`
  (`analyze_psychology_market`, which embeds `analyze_psychology`),
  `manipulation` (`analyze_manipulation`) and `regimes`
  (`analyze_regimes`). The builder has no arithmetic of its own — no
  second accounting, volume, P&L or regime calculation — which a test
  checks structurally, and tests require every section to equal the
  direct call. Every analytics function stays independently usable, and
  no analytics module imports the report layer.
- **Unavailable stays unavailable.** Sections keep their own function's
  meaning for missing data rather than being filled in: psychology off
  gives `psychology_market` coverage `"none"` with no observations; no
  whale observation gives `whale_activity` coverage `"none"` and
  `whale_volume=None`; no manipulators gives `manipulation` coverage
  `"none"`; no balances or `initial_price` leave P&L and equity `None`.
  `event_windows` alone can be absent: it is `None` when no event timeline
  is passed, since ticks do not record events' ground truth and the report
  never reconstructs or infers events — distinct from `events=()`, a
  timeline with no events and so an empty report.
- **One scope for every section.** `start_tick`/`end_tick` (inclusive)
  select the same ticks everywhere. Only `analyze_market` accepts a range
  itself, so the builder orders and validates the ticks once, lets
  `analyze_market` validate and apply the range, and passes the identical
  scoped ticks to every other function; tests check each section against
  the direct call on that scope. Each function then applies its own
  conventions within it (the pre-run price only when tick 1 is in scope,
  regime windows on the tick-number grid, events reported only if they
  start in scope), and the balances must be the wallets at the scope's
  start and end.
- **Pure and immutable.** No randomness, no mutation of ticks, events,
  balances or simulator state, identical output for identical input in
  any order; the report and every section are frozen.

**Step 8b — report rendering and `--report`** (`analytics/rendering.py`,
`scripts/simulate_coin.py`). `render_report(report) -> str` turns a
`SimulationReport` into a plain-text summary with one section each for
the market, traders, whale activity, event windows, psychology,
manipulation and regimes; the demo CLI prints it after the run when
`--report` is given:

    python scripts/simulate_coin.py --ticks 60 --events --psychology --report

- **Opt-in observer.** Without `--report` the CLI behaves exactly as
  before: its stdout is byte-identical for every pinned compatibility
  invocation in both pricing modes, and no extra wallet reads or analytics
  run. With it, the ordinary output is printed unchanged first and the
  report follows, built once by `build_report` from the finished run's
  ticks, the event timeline and the traders' wallets before and after the
  run. The report never touches the simulation.
- **Presentation only.** The renderer formats values already on the
  report — it calls no analytics function and has no arithmetic of its
  own, which a test checks structurally — so every number shown is the
  report's own, and the same report always renders to the same string.
- **Unavailable stays unavailable.** A `None` renders as `n/a` or a
  sentence saying why (no event timeline, no psychology recorded, no whale
  observations, no wallet balances, no total supply), never as zero; a
  zero the analytics define renders as zero.
- **Descriptive wording.** Values are "observed" or "recorded"; the text
  states no cause, no forecast and no trading advice, and the regime
  section describes past windows only.

Phase 9 is complete.

### Web dashboard (Phase 10)

Status: **Steps 1-7 complete**. The dashboard is an *observer* of a finished
run: it changes no simulation behavior, adds no persistence and runs no
batch of simulations. Persistence, scenario save/load and mass simulation
are Phases 12-14 of the future roadmap (see "Coin economy: future
roadmap" below), calibration is Phase 18, and the final visual design is
Phase 20 — Step 1 is deliberately plain.

**Where it lives.** The repository already had one frontend (Streamlit,
`app.py`) and one chart layer (Plotly, `visualization/charts.py`), so
Phase 10 extends them rather than introducing a second frontend, an HTTP
API or a JavaScript build. The dashboard is a new tab (🪙 Coin Simulation)
in the existing app; Streamlit's own session state is the state model, as
it already was for the market engine.

**Step 1 — dashboard foundation and architecture**
(`crypto_simulator/dashboard/`, `tests/dashboard/`). No simulation code
changed: the CLI's output is byte-identical for every pinned invocation
(`--report` included), the compatibility grid and both builder
fingerprints are unchanged, and nothing in `core/`, `services/` or
`analytics/` imports the package (a test checks this structurally).

- **One run, one report, one payload.** `data.run_simulation(params)`
  builds the simulator with `build_coin_simulator`, runs it, and calls
  `build_report` once — the same sequence, with the same seeds and the
  same report inputs, that `scripts/simulate_coin.py --report` uses. The
  tests require the payload's report to equal the CLI-built report and to
  render to the same string, and the price series to equal the recorded
  ticks. Every UI component then reads that one payload; no component
  runs analytics of its own.
- **`SimulationReport` is the analytical contract.** No figure is
  recomputed for the frontend — not a return, volatility, drawdown, VWAP,
  P&L, whale or psychology figure, event window, manipulation figure or
  regime label. `DashboardPayload` adds only the run's metadata and the
  simulator's own recorded per-tick price, market cap and volume (copied
  for charting, not derived).
- **Serialization boundary** (`dashboard/serialization.py`). Frozen
  dataclasses become objects of their *declared* fields in declaration
  order (properties are never evaluated), tuples become arrays, mappings
  become objects with sorted string keys, enums become their values,
  `Decimal` becomes `float` (the report stays the exact source of truth)
  and a non-finite float is an error. `None` stays `null` — never a
  stand-in zero — and an unsupported type raises instead of being
  stringified, so no `str(...)`/`repr(...)` of an internal object can
  reach the browser.
- **Deterministic.** The same parameters give the same payload:
  `simulation_id` is derived from the parameters and seed rather than
  drawn or timed, and the payload carries tick *numbers*, because
  `SimulationClock` anchors its timestamps to the wall clock the run
  started at.
- **Parameters are a closed set.** `SimulationParams` mirrors the CLI's
  flags and validates them against known values (`PricingMode`,
  `MANIPULATION_SCENARIOS`, an explicit tick bound). Nothing is evaluated,
  imported or executed by name from the frontend.
- **States.** Empty before the first run, `Running simulation...` while
  one is in flight (the request clears the previous result first, so no
  run's figures are ever shown under another run's request), the results
  after a successful run, and the error itself after a failure — with no
  stale and no invented figures. An unsupported combination (whales in AMM
  mode, say) surfaces as that error rather than a crash.
- **Sections.** Market summary and price chart hold data. Traders,
  whales, events, psychology, manipulation and regimes are named
  placeholders whose data is already in the payload, for later steps.

**Step 2 — functional market dashboard**
(`dashboard/market_section.py`, `dashboard/formatting.py`,
`visualization/charts.py`, `tests/dashboard/test_market_section.py`). The
market section is now functional in both pricing modes. Still no
simulation code changed: the CLI's output is byte-identical for the pinned
invocations, the compatibility grid and both fingerprints are unchanged,
and the dashboard remains read-only.

- **Everything comes from `SimulationReport.market`.** The section
  displays the price overview (open, close, return, log return, high, low
  with their ticks, mean price), the volume decomposition and fill counts,
  volatility and realized volatility with the return count, drawdown (the
  maximum with its peak, trough and recovery ticks, and the drawdown at
  close), market cap, turnover and participant turnover, average trade
  size, trader VWAP, AMM swap activity, and a statistics table of every
  figure shown. A structural test parses the module and asserts it calls
  no analytics function and contains no arithmetic operator at all, so a
  figure can only come from the report.
- **Analytics properties, by name.** `VolumeBreakdown` defines the
  participant total and the fill counts as properties, which the generic
  serializer does not emit. Rather than have the UI add the components up,
  `serialization.DERIVED_FIELDS` lists those three properties explicitly
  and the payload carries the analytics' own values, after the declared
  fields and in a fixed order.
- **The chart** (`price_path_chart`, extended) plots the recorded price
  path over tick numbers, in tick order, with hover showing the tick's
  price and volume and axis labels on both axes. Its only annotations are
  the report's high and low; a point whose tick is not a recorded one (the
  pre-run price at tick 0, which `analyze_market` includes in the path) is
  left off rather than moved onto a tick it did not happen at.
- **What is deliberately absent.** The report defines no absolute price
  change, so the headline shows the return it does define rather than
  subtracting two prices. The report defines drawdown as scalars and not
  as a series, so there is no drawdown chart: building one would mean
  reimplementing the analytics' drawdown formula in the frontend.
- **Missing keeps its meaning.** `None` renders as `n/a`, never zero:
  background volume is `n/a (AMM mode)`, the pool section says why there
  are no swaps in random-walk mode, and market cap and turnover stay `n/a`
  without a total supply. Tested on runs with no ticks, one tick, no
  supply, no traders and no whales, all of which render.
- **Reruns.** The Step 1 state machine is unchanged and there is no second
  state store: requesting a run clears the previous payload first, so the
  market figures disappear while a run is in flight, a new run replaces
  them, and a failed run leaves none of them on screen.

**Step 3 — functional trader dashboard**
(`dashboard/trader_section.py`, `tests/dashboard/test_trader_section.py`).
The trader section reads `report.traders` and nothing else. No simulation,
analytics or accounting code changed: the CLI's output is byte-identical
for the pinned invocations, the compatibility grid and both fingerprints
are unchanged.

- **Sections.** A population overview (the report's own totals: traders
  active, participation, fills, volume, notional, VWAP, net coin and cash
  flows, combined P&L, return, start and end equity, with buy/sell/wash
  volume, filled-versus-requested, fees, final price and ticks in
  captions); a strategy table, one row per `StrategySummary` as the report
  groups them; a per-trader activity table and a per-trader performance
  table, both one row per `TraderSummary` in the report's order; and a
  detail view listing every figure recorded for one selected trader.
- **Nothing is recomputed.** P&L is `analyze_traders`' P&L, not a
  subtraction of equities; VWAP is its VWAP, not notional over volume;
  strategy rows are the report's groups, not the UI re-summing traders.
  A structural test parses the module and asserts it calls no analytics
  function and contains no arithmetic operator at all. A test also
  requires the detail view to cover every declared `TraderSummary` field,
  so a new analytics field cannot be silently dropped.
- **The selector filters.** Choosing a trader re-renders the stored
  payload; a test drives the real UI and asserts the runner is called once
  across a run and a selection. A selection left over from a population
  that no longer exists falls back to the overview instead of failing.
- **Recorded classifications, not inferred ones.** Wash legs, wash share
  and the manipulation-strategy mark come from the simulator's own flags
  and registered labels. Traders the analytics know only from balances
  have no recorded strategy and appear as "(balances only)", as the
  analytics group them.
- **Missing keeps its meaning.** A trader with no fills has no VWAP, fill
  ratio, fill span or average fill; a report built without wallet
  snapshots has no equity or P&L anywhere and says why; random-walk runs
  have no swap fees. All render `n/a`, never zero. Tested on runs with no
  traders, no fills, no balances, one tick, and in both pricing modes.
- **`StrategySummary` has no return field**, so the strategy table shows
  none and says so rather than dividing P&L by an equity itself.
- **Serialization.** `TraderSummary.active` joins `DERIVED_FIELDS` — the
  analytics' own call on whether a trader filled anything, shown as a
  column instead of the UI deciding what a fill count means.

**Step 4 — functional whale dashboard**
(`dashboard/whale_section.py`, `tests/dashboard/test_whale_section.py`).
The whale section reads `report.whale_activity` (which embeds
`analyze_whales`' `WhaleSummary`) and nothing else. No simulation,
analytics or accounting code changed: the CLI's output is byte-identical
for the pinned invocations, the compatibility grid and both fingerprints
are unchanged, and AMM mode still rejects whales.

- **Sections.** Observation coverage and the observed tick count; the
  report's whale volume and its shares of market and participant volume;
  a per-whale activity table (funded, cohort, observed ticks, trades,
  volume, share of whale volume, VWAP, net flows, first/last fill, average
  fill); the recorded per-tick outcomes, one column per `TICK_OUTCOMES`
  entry, with each whale's behavior and cycle-phase ticks; the
  per-behavior activity table; allocation paths with targets, ticks at
  target, crossings, gap statistics and target-reaching ticks; cohort
  activity and co-fill statistics; and a detail view listing every figure
  recorded for one selected whale.
- **Recorded, never inferred.** Behavior is the behavior the simulator
  recorded for that tick, not a reading of a trade's size or side. Each
  observed tick carries exactly one recorded outcome, so a whale that did
  not fill is not reported as inactive and a blocked whale is not reported
  as idle. A structural test asserts the module calls no analytics
  function and contains no arithmetic operator.
- **Co-fill stays descriptive.** `CoFillStats` counts ticks on which
  cohort members filled together; a cohort follows a fixed schedule set
  before the run, so the section calls this co-occurrence. A test scans
  everything the reader can see for causal or herding wording.
- **Unavailable is not zero.** Three different runs give a report with no
  whales — no whales configured, whales not observed, or AMM mode, which
  does not support whales — and the section says which, from the run's own
  parameters. Partial observation coverage is labelled as such, with the
  note that an unobserved tick is not a tick without activity. A whale
  with no target has no allocation record, so those columns are `n/a`.
- **Cohorts are Python-API only**, so a dashboard run never has one and
  the section says so; the tests build a real two-member cohort world
  through `CoinSimulator` to cover cohort and co-fill rendering.
- **Serialization fix.** Mapping *keys* now carry their own value like any
  other value: `WhaleSummary.behavior_ticks` is keyed by `WhaleBehavior`,
  which previously serialized as `"WhaleBehavior.ACCUMULATE"` — an
  implementation representation the contract forbids — and now serializes
  as `"accumulate"`. A key type with no rule is an error instead of being
  `str()`-ed. No analytics changed; this is the dashboard's own boundary.

**Step 5 — events and psychology dashboard**
(`dashboard/event_section.py`, `dashboard/psychology_section.py`, their
tests). Two separate sections, reading `report.event_windows` and
`report.psychology_market`. No simulation, analytics or accounting code
changed: the CLI's output is byte-identical for the pinned invocations,
the compatibility grid and both fingerprints are unchanged.

- **Events.** One row per event with the recorded ground truth (category,
  severity, sentiment, volatility boost, attention, start, last active
  tick, duration, decay, expiry), its recorded provenance and its overlap;
  one row per window (`pre_event`, `active`, `decay`, `post_event`,
  `effect`) carrying that window's own `MarketSummary` figures, the ticks
  it requested and observed, and whether it was complete; the per-category
  activity; and a detail view for one selected event.
- **Psychology.** Coverage, the four component summaries, a chart of the
  recorded components over ticks (drawn from the report's own
  observations), threshold occupancy, persistence, the recorded
  associations with their lag and direction, the market averages for each
  component's low and high ticks, the event-period means, and the per-tick
  observations with the dominant label the analytics named.
- **Descriptive by construction.** Both sections describe what was
  observed *during* a window or alongside a component level: a correlation
  is an association, overlapping events are listed rather than blamed, and
  a run's components are never combined into a score the analytics do not
  define. Tests read back every caption, heading, message and table cell
  and fail on causal wording ("caused", "drove", "triggered",
  "influenced", "led to", ...). Structural tests assert both modules call
  no analytics function and contain no arithmetic operator.
- **Unavailable keeps its meaning.** No event timeline (`None`) is kept
  distinct from a timeline whose events all start outside the analysed
  ticks (an empty list); psychology that was never switched on says so
  rather than showing neutral values; a correlation the analytics could
  not compute keeps their reason instead of a zero; and the event-period
  comparison is absent unless the run recorded events.
- **`PsychologyMarketReport` has no dominant-component totals** (those
  live in `analyze_psychology`'s own report, which this section does not
  receive), so the dominant component is shown per tick and the absence of
  totals is stated rather than filled in.
- **The psychology containment rule still holds.** Only the simulator, the
  trader strategies and the psychology analytics may import that package.
  The dashboard reads the serialized report instead: it names the
  components from the report's own summaries and repeats the one coverage
  literal it compares against (a test pins it to the analytics constant).
  The guard in `tests/core/psychology/test_signals.py` now matches imports
  of the psychology *modules* rather than any module name containing the
  word, so `dashboard/psychology_section.py` does not trip it; its list of
  permitted importers is unchanged, and the refined predicate flags
  exactly the same modules as before.
- **Serialization.** `EventWindow.ticks_observed`/`complete`/
  `volume_per_tick` and `EventPathSummary.event_id`/`overlapping`/
  `overlap_count` join `DERIVED_FIELDS` — the analytics' own derived
  figures, which the UI would otherwise have to work out.

**Step 6 — manipulation and regimes dashboard**
(`dashboard/manipulation_section.py`, `dashboard/regime_section.py`, their
tests). Two separate sections, reading `report.manipulation` and
`report.regimes`, which fill the last two placeholders: every section of
the report is now rendered. No simulation, analytics or accounting code
changed — the compatibility grid, the pinned CLI digests and both builder
fingerprints are unchanged.

- **Manipulation.** The analytics' own coverage word for which
  manipulation *kinds* were observed (none / partial / complete) with the
  caveat they state — it is not a claim that a scenario's whole extent
  fell inside the analysed ticks; the manipulation volume with both of the
  report's shares (whose denominators differ on purpose) and its active
  ticks; one row per kind from that kind's own `StrategySummary`, so
  pump-and-dump and wash trading are never merged; one row per manipulator
  and recorded phase (`accumulate`, `pump`, `dump`); each manipulator's
  observed span beside the `MarketSummary` the analytics computed over it;
  the aggregate `WashSummary`; and the report's own `ActivityComparison`.
- **Identification stays registry-based.** A fill is manipulation because
  the simulator recorded it as a wash leg or under a registered
  manipulation strategy — never because a trade was large, a price moved
  fast, a trader was big or a volume was unusual. Phases are the recorded
  reasons on each fill, counted by the analytics; the section reconstructs
  no phase boundary and recomputes no scenario return or volume.
- **Regimes.** Window count, complete and incomplete windows and the
  window size; one row per window carrying the analytics' own labels and
  their own `description`; the figures each label is read from
  (`net_log_return` against realized volatility, the quartile reference of
  the earlier complete windows, the running peak and the drawdown at each
  end of the window); the window's `RegimeContext` (events, psychology
  means, whale-observed ticks) recorded beside the labels; the report's own
  `*_counts` tallies, including the unavailable tally; and a chart of each
  window's recorded volume per observed tick, a series the report already
  holds.
- **Unavailable keeps its meaning.** An early window has no volatility or
  volume class until four earlier complete windows exist, and no direction
  without enough returns: the section shows `n/a` and leaves it there —
  never a `normal_*` stand-in, never a neighbour's label, never a zero. A
  window shorter than its grid span is marked incomplete rather than
  padded, a phase with no recorded fills keeps `n/a` ticks, a kind the
  report has no strategy summary for is `n/a` throughout rather than zero,
  and a share with a zero denominator stays `n/a`. Zeros the analytics
  define as facts (no wash legs, with `trader_trades` always fully
  recorded) are shown as the zeros they are.
- **Descriptive by construction.** Manipulation figures describe what was
  recorded during a scenario's own ticks; a regime describes one past
  window and says nothing about what follows it (`recovery` is a drawdown
  that had already narrowed by the window's close). Tests read back every
  caption, heading, message and table cell and fail on causal wording, and
  structural tests assert both modules call no analytics function, contain
  no arithmetic operator, reach for no raw trade record, and — for the
  regime section — name no label constant of their own.
- **Serialization.** `PumpAndDumpSummary.total_volume`/`total_fills`,
  `RegimeContext.event_active`, `RegimeObservation.complete`/`description`
  and `RegimeReport.total_windows`/`complete_windows`/`incomplete_windows`
  join `DERIVED_FIELDS`: the analytics' own properties (the last three are
  the figures `analytics/rendering.py` prints), read as they stand rather
  than re-derived in the UI. `event_active` is tri-state on purpose —
  `None` when no tick in the window recorded an event state at all, which
  a count alone cannot express.
- **End to end.** The integration tests run real simulations with each
  manipulation preset in both pricing modes, press Run in the real UI, and
  compare what is on screen with an independently built `SimulationReport`
  — including a run with no scenario, a run that stops inside the scheme,
  early unlabelled regime windows, a second run replacing the first, and a
  failed run clearing every table.

**Step 7 — simulation controls** (`dashboard/data.py`, `dashboard/view.py`,
`tests/dashboard/`). The last Phase 10 step. Steps 2-6 made every report
section readable; this one makes the run *requestable*. No simulation,
analytics or accounting code changed: the CLI's output is byte-identical
for the pinned invocations, the compatibility grid and both builder
fingerprints are unchanged, and the dashboard remains read-only.

- **What was missing.** Step 1's controls already mirrored every CLI flag,
  so flag parity was not the gap. The gap was the other half of the run's
  identity: `simulation_id` is derived from the parameters *and the seed*,
  but the seed was not requestable — it was read from
  `simulation.random_seed` in the configuration (`42`). Every dashboard
  run with the same options was therefore byte-identical, so pressing
  **Run simulation** twice could not produce a different sample path, and
  a run on screen could not be deliberately reproduced or varied.
- **The seed joins the closed parameter set.** `SimulationParams` gains
  `random_seed: int | None = None`, validated like `ticks` against
  explicit bounds (`MIN_SEED`/`MAX_SEED`), rejecting a bool, a float, a
  string and anything out of range before the request reaches the builder.
  `None` means the configured seed — the pre-Step-7 behavior — so a
  defaulted request is unchanged.
- **The seed is selected, not invented.** `_with_seed_override` replaces
  `simulation.random_seed` in a copy of the settings, the same
  `dataclasses.replace` pattern `_with_event_overrides` already used for
  `--events`/`--random-events`. The builder is called with the arguments
  it always was — a test pins its keyword set — and every participant seed
  still follows from `build_coin_simulator`'s own `base_seed + offset`
  derivation. The dashboard seeds no participant, no RNG and no generator
  directly, adds no simulator input, and leaves the application settings
  object untouched. A seeded dashboard run is still exactly a CLI run: the
  integration tests' reference builder applies the seed the way the
  configuration does, and seeded random-walk, AMM and event/psychology
  cases are compared against it.
- **`None` passes the settings through by identity.** An unseeded request
  hands the builder the very settings object it was given rather than a
  rebuilt copy, so the defaulted path is not merely equivalent but
  unchanged — a test asserts the identity.
- **The control** (`view.py`) is a checkbox and a number, off by default.
  The number starts at the configured seed (read through
  `data.configured_seed`, so the view still reads no configuration of its
  own), which makes turning the control on and running reproduce the run
  already on screen instead of silently switching to another. The input is
  disabled while the override is off, and the number is read *only* when
  the override is on, so a seed left in the control from an earlier
  request cannot leak into a later unseeded run — a test drives exactly
  that sequence. The widget's bounds are the data layer's bounds, so the
  UI cannot offer a seed the request would reject, and the request
  validates anyway.
- **The status line already reported the seed**, so the seed a run used is
  on screen for a seeded and an unseeded run alike; it is the effective
  seed, never `n/a`, because a run always has one.
- **One observable change on the default path:** `simulation_id` is a hash
  over the serialized parameters, which now carry a `random_seed` key, so
  a defaulted request's id differs from its Step 6 value. Every analytical
  figure, the price series and every other metadata field are byte-
  identical (checked against a `24f022a` worktree across four parameter
  sets). The id's documented property — the same parameters and seed
  always give the same id, and nothing else feeds into it — is unchanged,
  no test pins an id literal, and nothing persists one, the dashboard
  having no persistence by design.
- **Deliberately not in this step**, because the roadmap assigns them
  elsewhere: saving or exporting runs (Phase 12 — coin-track persistence
  — and Phase 13 — scenario save/load), batch or multi-seed sweeps
  (Phase 14 — mass/batch simulation), calibration controls (Phase 18 —
  psychology calibration) and the final visual design (Phase 20 —
  advanced visualization). See "Coin economy: future roadmap" below.

---

## Coin economy: future roadmap (Phase 11–23)

Authoritative from checkpoint `80cacacba079a874a2fdc74c05f1d592e2784d6b`
(Phase 10 Step 7) onward. This supersedes the informal "Phase 12 owns
mass simulation, Phase 14 calibration" placeholders that appeared in the
Phase 10 sections above — those were shorthand notes written while
Phase 10 was in progress, not a specification, and both have been
corrected above to point here. None of Phase 1–10 is renamed, rebuilt or
reinterpreted by this section.

This numbering continues the coin-economy track's own Phase 6–10
sequence and is unrelated to the multi-asset trading platform's separate
Phase 0–5 numbering earlier in this document. It is also independent of
any other, external phase numbering (e.g. a project-setup or tooling
plan) — Phase 11 below means the eleventh coin-economy phase in *this*
file, nothing else.

No phase below is implemented yet. Every phase must reuse the existing
architecture — `CoinSimulator`, the random-walk and AMM engines, trader
strategies, the event engine, psychology, whale behavior, manipulation
scenarios, `analytics/`, the report generator, the dashboard and the
deterministic seed derivation — rather than introduce a parallel one, and
must leave Phase 1–10 behavior unchanged unless a phase explicitly says
otherwise. The trading-platform track's `OrderEngine` stays out of scope
for the coin economy: it intentionally settles trades directly through
wallets, not an order book, and only a future phase that says so
explicitly may change that.

### Phase 11 — CLI random-seed parity

**Complete.** `scripts/simulate_coin.py` takes `--seed`, so a
command-line run can reproduce a specific run without editing
`default.yaml` — the parity the dashboard has had since Phase 10 Step 7.
No simulation, analytics or accounting code changed: the CLI's output is
byte-identical for the pinned invocations, the compatibility grid is
IDENTICAL at all nine levels and both builder fingerprints are unchanged.

- **The seed is selected, not invented.** `--seed N` replaces
  `simulation.random_seed` in a copy of the settings —
  `replace(settings, simulation=replace(settings.simulation,
  random_seed=N))` — which is the shape `--events`/`--random-events`
  already used for their own config overrides, and the same one the
  dashboard's `_with_seed_override` uses. Every participant seed still
  follows from `build_coin_simulator`'s own `base_seed + offset`
  derivation (`_derive_seed`), so no participant, RNG or generator is
  seeded directly and no second random-number system exists.
- **Omitting it is the old behavior, by identity.** Without `--seed` the
  settings object is not rebuilt at all, so a defaulted run is the
  configured-seed run the CLI always did. Naming the configured seed
  explicitly gives that same run.
- **One bound, shared** (`services/coin_simulation.py`). `MIN_SEED`/
  `MAX_SEED` moved out of `dashboard/data.py` to sit beside the
  derivation they bound, in the module both front ends already import.
  Neither front end carries a copy, so the CLI and the dashboard accept
  exactly the same seeds and a run seeded in one reproduces in the other;
  a test asserts both the shared values and the absence of a local
  redefinition in either. The dashboard re-exports them, so every
  existing import site is unchanged. Nothing new depends on the dashboard
  package — the direction `core`/`services`/`analytics` must never import
  it is preserved.
- **Validation at the boundary.** A non-integer is argparse's own error;
  an out-of-range seed is `parser.error("--seed must be between …")`.
  Both exit 2 with a usage message rather than a traceback, and neither
  falls back to another seed.
- **Output.** The seed is printed in the run header *only* when `--seed`
  is given, the way `--scenario` already prints only when asked for, so
  a default run's output is unchanged to the byte.
- **Parity is tested, not assumed.** A test runs the CLI with a seed and
  compares its recorded prices against `run_simulation(SimulationParams(
  random_seed=…))` — the dashboard's own path — and they agree.

### Phase 12 — Coin-track persistence

**Complete** (`data/coin_runs.py`, `data/schema.sql`,
`tests/data/test_coin_runs.py`). A finished coin run can be stored and
read back; the coin track was ephemeral before this. No simulation,
analytics or accounting code changed: the CLI's output is byte-identical
for the pinned invocations, the compatibility grid is IDENTICAL at all
nine levels and both builder fingerprints are unchanged.

- **The existing connection layer was reusable; the schema was not.**
  `data/database.py` is track-neutral by construction — it "knows nothing
  about business rules", opens connections with `PRAGMA foreign_keys =
  ON` and a row factory, and runs an idempotent `CREATE TABLE IF NOT
  EXISTS` script. Only `schema.sql`'s tables and `repositories.py` were
  trading-platform-specific. So Phase 12 adds two tables to that schema
  and one repository beside the existing ones, rather than a second
  database system: same `connect`/`init_db`, same repository pattern,
  stdlib `sqlite3`, no ORM, no new dependency.
- **The boundary is a finished run**, not a live simulator. `coin_runs`
  holds the run's metadata (`simulation_id`, seed, pricing mode, coin,
  requested/completed ticks) with the request and the analytics report as
  JSON text; `coin_run_ticks` holds the per-tick series (price, market
  cap, volume) as columns, keyed `(run_id, tick)`. Columns for what
  Phase 15 will aggregate over, JSON for what is read whole and never
  queried field by field. Nothing is pickled: every stored value is an
  INTEGER, a REAL or TEXT.
- **Deliberately no tables** for individual fills, event records, pool
  reserves or per-participant state. The report's analytics already
  describe them and nothing yet reads the raw records; a table with no
  reader is a boundary widened for nothing.
- **Saving is not checkpointing.** A stored run is a finished result.
  Loading returns that result; it cannot resume a `CoinSimulator`, and
  this phase does not pretend otherwise.
- **It stores the payload the dashboard already reads** — the
  `{"simulation", "report", "price_series"}` mapping, which
  `to_jsonable` already guarantees is plain JSON-compatible data. The
  repository takes that *mapping* rather than a `DashboardPayload`, so
  `data` still imports nothing from `dashboard` (the structural rule
  holds) and the CLI, the dashboard and Phase 14's batch runner can all
  save through one call.
- **Atomic writes.** A run and all of its ticks go in under one `with
  conn:` block, so a save that fails part-way leaves no row at all —
  tested by making a tick unstorable mid-insert and asserting both tables
  are empty afterwards, and that earlier runs are untouched.
- **Non-destructive and idempotent.** Re-running `init_db` over a
  database that already holds runs keeps them, on a real file as well as
  in memory. A surrogate `run_id` is the key, so the same request may be
  saved twice and stays two rows — `simulation_id` is derived from the
  request and would collide.
- **Round trip is exact.** `load(save(payload)) == payload`, including
  every float: prices and volumes go through SQLite REAL and come back
  bit for bit. Verified on a real file across close/reopen, in both
  pricing modes, and for one-tick, no-trader, no-whale, no-participant,
  event and scenario runs.
- **Persistence observes; it never influences.** The repository is handed
  a completed run, draws no random number, and mutates neither the
  simulator nor its own argument — a test runs the same seeded request
  before and after a save and requires the two to be identical.
- **SQL safety.** Every value is a bound parameter; the only text
  formatted into a statement is the module's own column-name constant,
  which a test asserts by parsing the source and checking what the
  `execute`/`executemany` f-strings interpolate. A payload value that
  looks like SQL is stored as data.

### Phase 13 — Scenario save/load

**Complete** (`services/simulation_params.py`, `services/scenarios.py`,
`data/coin_scenarios.py`, `scripts/simulate_coin.py`). A run's
configuration can be saved under a name and run again. No simulation,
analytics or accounting code changed: the CLI's output is byte-identical
for the pinned invocations, the compatibility grid is IDENTICAL at all
nine levels and both builder fingerprints are unchanged.

- **"Scenario" now means two things, deliberately.** The older sense is a
  *manipulation preset* — `pump_and_dump`, `wash_trading` in
  `MANIPULATION_SCENARIOS`, selected by the `scenario` **field** of a
  request, and the sense Phase 17 will extend with market-condition
  presets. The new sense is a *saved scenario*: an entire
  `SimulationParams` under a user-chosen name. Nothing was renamed —
  renaming either would break a CLI flag or a stored field for no gain —
  so both modules and the README state the distinction instead. A saved
  scenario may name a manipulation preset; it is not one.
- **`SimulationParams` moved to `services/`.** It is the coin track's
  canonical request type, but it lived in `dashboard/data.py` and
  `services` may not import `dashboard`, so a scenario service could not
  validate into it where it was. It now sits beside
  `build_coin_simulator`, whose keyword arguments its fields mirror, and
  `dashboard.data` re-exports it (with `MAX_TICKS`, `PRICING_MODES`,
  `SCENARIOS`) so all sixteen existing import sites are untouched. No
  field, default, validation rule or declaration order changed, so a
  request still serializes identically and still derives the same
  `simulation_id` — checked against the Phase 12 value.
- **Inputs, not outputs, and not a checkpoint.** `coin_scenarios` stores
  the request; `coin_runs` (Phase 12) stores what a request produced.
  Loading a scenario rebuilds the request and runs it from tick one,
  reproducing the original run because the seed is part of what was
  saved. Nothing pauses or resumes a live `CoinSimulator`.
- **A name is the identity.** `coin_scenarios.name` is `UNIQUE`, so
  saving under an existing name *updates* that scenario (keeping its
  `created_at`, moving `updated_at`) rather than quietly creating a
  second one to collide with it. `simulation_id` is deliberately not
  reused: it identifies a run, and two saves of one configuration are one
  scenario.
- **Layering.** `data/coin_scenarios.py` is dicts-in/dicts-out like the
  Phase 12 repository, so `data` still imports no service and no front
  end; `services/scenarios.py` owns the conversion to and from
  `SimulationParams` and is what callers talk to — the same shape
  `MarketService` already has over its repositories.
- **Validation is the existing validation.** A loaded scenario is
  constructed as a `SimulationParams`, so a stored request is held to
  exactly the rules a typed-in one is. Missing, unknown and invalid
  fields are each named in the error; a corrupted or unreadable row is
  reported rather than turned into a default request. A scenario written
  by a version that knew a field this one does not says so.
- **CLI.** `--save-scenario NAME` and `--load-scenario NAME`. Precedence
  is one rule: the scenario is the baseline and a flag typed on that
  command line replaces that field. Explicitness is detected by
  pre-filling argparse's namespace with a sentinel — argparse only
  applies a default to a `dest` the namespace lacks — so typing
  `--ticks 20` counts as an override even though 20 is the parser's own
  default, which a comparison against defaults could not tell from
  silence. A run with neither flag never opens the database and its
  output is unchanged to the byte.
- **A save records what ran.** `--pricing-mode` and `--seed` are both
  optional, so a scenario pins the effective mode and seed rather than
  "whatever the config says" — otherwise an edit to `default.yaml` would
  silently change what a stored scenario means. Saving also validates
  first, so a configuration the request type rejects is never written
  down as though it worked; note this is where a plain run and a saved
  one differ, since `--ticks` itself remains unbounded.
- **No dashboard integration**, deliberately. The Phase 10 contract
  records the dashboard as adding no persistence, and a save/load control
  is user-facing surface no Phase 13 requirement asks for; the service is
  front-end-agnostic, so adding one later needs no rework here.
- **Equivalence is tested, not assumed.** Running a loaded scenario is
  compared against running the same configuration directly — the whole
  payload, report included — for random-walk, AMM, `pump_and_dump`,
  `wash_trading` and an events/psychology run, and the same comparison is
  made through the real CLI.

### Phase 14 — Mass/batch simulation

**Complete** (`services/batch.py`, `scripts/simulate_coin.py`,
`services/coin_simulation.py`). One configuration can be run many times
under independent deterministic seeds. No simulation, analytics or
accounting code changed: the single-run CLI output is byte-identical for
the pinned invocations, the compatibility grid is IDENTICAL at all nine
levels and both builder fingerprints are unchanged.

- **The runner is injected, so there is still one simulation engine.**
  `run_simulation` lives in the dashboard package, which `services` may
  not import, and rebuilding its body in `services` would have been a
  second engine. `run_batch(params, runs, *, runner, base_seed=None)`
  therefore takes the entry point as an argument — the same injection
  `run_simulation` itself already offers for `builder`, one layer out.
  The batch layer never looks inside what the runner returns, so it is
  tied to no particular shape of result.
- **The stride is the load-bearing detail.** A run's base seed is not
  only the `CoinSimulator`'s own seed but the origin its participants are
  offset from (`+100` whales, `+1000` traders, `+2000` manipulators,
  `+3000` random events, each plus an index). Spacing runs by one would
  hand run *i*'s price engine the seed run *i−100* already gave a whale —
  different consumers drawing on an identical stream. `BATCH_SEED_STRIDE
  = 10_000`, wider than any within-run offset, keeps each run's whole
  seed space to itself; a test asserts no run's base seed appears among
  any other run's subsystem seeds for fifty participants of each kind.
  Seeds still come from the existing `_derive_seed(base, offset)` — no
  new random architecture, and the batch draws no random number at all
  (verified by comparing `random.getstate()` across a batch).
- **Never seeded from chance.** The base is `--seed` if given, then the
  request's own seed, then the configured `simulation.random_seed`. A
  batch with no seed named is still reproducible.
- **Run *i* is the single run at run *i*'s seed** — batching is not a
  different way of simulating, and a test compares a batch member's whole
  payload against that run performed alone.
- **Failures are collected, not swallowed.** A run that raises is
  recorded with its index, seed, exception type and message; the rest of
  the batch still runs; the CLI lists each failure and exits non-zero.
  `BaseException` is not caught, so an interrupt still stops the batch.
- **Serial and in memory, on purpose.** A run is 1–3 ms and its payload a
  few tens of kilobytes; 1000 runs of 20 ticks takes about 1.4 s.
  Parallelism would buy little against the ordering, RNG and platform
  reproducibility it would put at risk. `MAX_BATCH_RUNS = 1000` is a
  memory bound, not a simulator one. Both are future work, not gaps:
  streaming results out as they are produced would be the way to raise
  the bound.
- **CLI.** `--batch RUNS` replaces the tick table with one line per run
  (index, seed, simulation id, ticks, result) plus the batch's identity.
  `--report` describes one run and is refused with `--batch`. Phase 13
  precedence is unchanged, and `--batch` is deliberately *not* part of a
  saved scenario: a scenario says what to simulate, not how many times.
- **Nothing is persisted.** A batch writes no database row — Phase 12's
  repository exists, but a batch quietly inserting hundreds of runs is
  not something to do by default. An opt-in flag to store a batch's runs
  is recorded as future work.
- **Nothing is aggregated.** `BatchResult` holds the individual runs and
  counts of them; no mean, distribution or comparison is computed
  anywhere, and a test asserts the result type has grown no such
  attribute. That is Phase 15's work, and `BatchResult.payloads` is what
  it will read.

### Phase 15 — Aggregate statistics

**Complete** (`analytics/aggregate.py`, `analytics/_series.py`,
`scripts/simulate_coin.py`). Phase 14 executes batches; this describes
them. No simulation, accounting or per-run analytics code changed: the
single-run CLI output is byte-identical for the pinned invocations, the
compatibility grid is IDENTICAL at all nine levels and both builder
fingerprints are unchanged.

- **It lives in `analytics`, not `services`.** The plan said
  `services/aggregate_statistics.py`; inspection of the layering proved
  that wrong. A structural test
  (`tests/analytics/test_events_simulation.py`) forbids `core`,
  `services`, `config`, `models` and `data` from importing `analytics` at
  all — analytics observes the simulator, never the reverse — so a
  services module could not have used this package's percentile and
  volatility conventions without copying them. Aggregation *is*
  descriptive analytics, so it belongs here. The batch result is read by
  attribute rather than imported, the same way the batch runner keeps its
  payloads opaque, so `analytics` gains no dependency on `services`
  either; a test asserts the module names none of `services`, `data` or
  the dashboard package.
- **One percentile in the project, not two.** The convention already
  existed, documented in `analytics/psychology.py` and referred to by
  `analytics/regimes.py`: linear interpolation at rank `p/100 × (n − 1)`,
  the "inclusive" definition. It was private to `psychology.py`, so it
  moved to `analytics/_series.py` beside the other shared numeric
  helpers and `psychology.py` now calls it — a behaviour-preserving
  refactor, with Phase 7's own tests unchanged and green.
  `statistics.quantiles` was deliberately **not** used: it computes a
  different method, and using it would have put two percentile
  definitions in the simulator. P50 is therefore exactly the median.
- **The reports' own numbers.** Every metric is a `MarketSummary` field
  the analytics already define, read as it stands. A test compares each
  statistic against the same statistic taken over the runs' own report
  values, which is the guard against the aggregate layer and the
  per-run analytics drifting apart. **No absolute price change** is
  reported: the report defines none on purpose (Step 2 of Phase 10
  records why), and adding one here would be the competing definition
  that rule exists to prevent.
- **Conventions match the simulator's, not a library's default.** Mean is
  `fsum(values)/n`, as `psychology.py` computes its means. Standard
  deviation is the **sample** one and is `None` below
  `MIN_VOLATILITY_RETURNS` observations — the same constant and the same
  rule the simulator's own volatility uses, so a single-run batch reports
  an undefined dispersion rather than a zero.
- **Missing stays missing.** A per-run metric is `float | None`, so a
  metric's `count` may be lower than the batch's successful runs — a
  batch of one-tick runs produces no volatility at all and says so. A
  failed run contributes no observation to anything and is never read as
  zero; `requested`, `successful` and `failed` stay distinct from each
  metric's own count.
- **CLI.** The aggregate section follows the per-run list under its own
  heading, one line per metric however many runs there were, and states
  which percentile and which standard deviation it is reporting. This is
  the one place Phase 14's output changed — by addition — so two of that
  phase's own CLI tests were rewritten rather than deleted: one now
  asserts the *per-run list* still carries no statistics, the other that
  output grows exactly one line per run.
- **Descriptive only, and cheap.** No confidence interval, significance
  test, forecast or comparison claim. Aggregating 1000 runs takes ~23 ms,
  about 1% of running them; the cost is one sort per metric.
- **Nothing is persisted.** No aggregate table, no repository wiring; the
  statistics live in memory like the batch they describe.

### Phase 16 — Stress testing

**Complete** (`crypto_simulator/stress/`, `scripts/stress_test.py`,
`tests/stress/`). 24 demanding configurations run through the ordinary
entry points and checked for having come out intact. No simulation,
analytics, services or CLI file changed: `scripts/simulate_coin.py` is
byte-identical for the pinned invocations, the compatibility grid is
IDENTICAL at all nine levels, both fingerprints are unchanged, and no
defect was found to patch.

- **A new application-level package.** The harness needs
  `run_simulation` (dashboard), `run_batch` (services) *and*
  `aggregate_batch` (analytics), and the two structural rules forbid
  `services` from importing `analytics` and both from importing the
  dashboard. `crypto_simulator/stress/` sits above all three, as
  `dashboard/` does, and contains no simulation: a test asserts the
  runner never drives a simulator itself.
- **Boundaries are the simulator's own**, not invented: ticks 1 and
  `MAX_TICKS`, seeds `MIN_SEED` and `MAX_SEED`, batches of 1 and
  `MAX_BATCH_RUNS`, both pricing modes, both manipulation presets, the
  optional features together, and whales-with-AMM. Each numeric bound is
  also tested one step outside, where the existing validation must refuse
  it — nine cases whose *expected* outcome is a clean rejection, checked
  to be refused for the stated reason rather than merely refused.
- **Participant count has no simulator maximum**, and Phase 16 adds
  none. `coin.traders` is a configuration list with no validated bound,
  so `HARNESS_MAX_TRADERS = 200` is documented as this harness's ceiling,
  chosen from measurement (cost is roughly ticks x traders; the costliest
  case is ~2.5 s and well under a hundred megabytes).
- **Accounting is checked without a second run loop.** Conservation comes
  from `CoinSimulator.accounting_totals()`, reached through the builder
  injection `run_simulation` already offers: the injected builder
  constructs the simulator exactly as the default one does, records it
  and its opening tally, and the same simulator is asked again
  afterwards. AMM mode must balance **exactly** — it settles in
  `Decimal`; random-walk mode settles float wallets and is allowed
  representation drift within 1e-9 relative, which is what the demo CLI
  has always reported. A test pins both halves: real drift passes, a
  thousand missing coins does not.
- **A case passes when** it completed the ticks it asked for, its report
  is free of non-finite values (checked by running it through the
  serialization boundary, which refuses one wherever it hides), its
  prices satisfy `is_valid_price`, its volumes and counts are
  non-negative, its series is in tick order, and its accounting balances.
  Selected cases are run twice and required to match.
- **Failures are structured.** An unexpected exception is recorded with
  type and message and the suite continues to the next, independent case;
  `BaseException` is not caught, so Ctrl-C still stops it. A case that
  survives a configuration that should have been refused fails.
- **Phase 14 and 15 are reused, not reimplemented.** Multi-run cases go
  through `run_batch` (which seeds them and collects their failures) and
  are described by `aggregate_batch`; the harness recomputes no statistic
  and keeps no payloads, only the small aggregate.
- **Two tiers.** The ordinary tier runs in ~2 s inside `pytest`; the two
  costly cases (maximum ticks x 200 traders, and the 1000-run batch) are
  marked `slow` and deselected by default via `addopts`, so the suite
  stays in seconds. `pytest -m slow` or `--heavy` runs them.
- **Nothing is persisted**, and no bound was raised: `MAX_BATCH_RUNS`,
  `MAX_TICKS` and the seed range are untouched.
- **What it does not claim.** These cases exercise selected demanding
  configurations *within* the simulator's defined limits. They do not
  prove it correct outside them and say nothing about production-grade
  safety.

### Phase 17 — Market-condition scenario system

**Complete** (`services/market_conditions.py`). Three named configuration
presets — `bull`, `bear`, `meme` — selected by
`--market-condition`/`SimulationParams.market_condition`. No simulation
mechanic was added: every field a preset writes already existed and is
already validated. The compatibility grid is IDENTICAL at all nine
levels, both fingerprints are unchanged, and `simulate_coin.py` is
byte-identical for seven pinned invocations.

- **A separate axis from manipulation presets, not an extension of
  them.** `MANIPULATION_SCENARIOS` replaces *participants* — it adds
  manipulators and a follower crowd trading to a scheme. A market
  condition touches no participant; it rewrites the news mix, its rate
  and severity, the drift the random walk takes from sentiment, and the
  coin's base volatility. The two compose, and a test runs a pump in a
  bear market. `pump_and_dump` and `wash_trading` are untouched.
  (The roadmap once listed eight presets including Whale Attack and
  Liquidity Crisis; three are implemented, and the rest are left
  unimplemented rather than faked — see the honesty note below.)
- **One new request field.** `market_condition: str | None = None`,
  validated against the registry exactly as `scenario` is validated
  against `MANIPULATION_SCENARIOS`. Because it rides in
  `SimulationParams`, Phase 13 saves it, Phase 14 batches it, Phase 15
  aggregates it and Phase 16 stresses it with **no change to any of
  them** — tests in each of those suites prove it.
- **Existing simulation IDs are preserved.** The id is a hash of the
  request, so adding a field would have changed the id of every request
  ever made. `_ID_OPTIONAL_FIELDS` leaves an unset optional field out of
  the canonical form, so a request that names no condition keeps its id —
  pinned by a test against `9d91fa3421344f96`, the value from Phase 12 —
  while two requests that differ in the field still differ.
- **The AMM caveat is a constraint, not a nuance.** `CoinSimulator`
  *raises* on a nonzero `drift_per_sentiment` in AMM mode ("events move
  price only through trader reactions"), so a preset that set drift
  unconditionally would abort every AMM run. `apply_market_condition`
  takes the effective pricing mode and applies drift only to a
  random-walk run; in AMM the preset still changes the news, and price
  moves only as traders react. No AMM mechanic was bent to make a
  direction appear, and a test runs every preset in AMM to prove it does
  not raise.
- **Honest semantics.** A preset tilts the odds. Tests compare medians
  across batches of thirty runs — `bull` above no-condition above `bear`
  — and one test deliberately asserts that *some* `bull` runs fall,
  because a preset that never fell would be claiming more than it does.
  `meme` is a volatility regime rather than a direction: its realized
  volatility is several times the baseline, and its median outcome falls
  only because a multiplicative walk drags the median when noise rises.
- **No persistence change.** The preset name rides inside the existing
  `params_json`; `schema.sql` is untouched and no market-condition table
  exists. The registry is immutable code (`MappingProxyType`, frozen
  dataclasses, read-only category maps).
- **Precedence** is one chain: saved scenario → market condition →
  explicitly typed event flags → other typed flags. The condition is
  applied before the event overrides, so `--random-events` overrules a
  preset's news rate, and a typed `--market-condition` overrules one
  stored in a scenario.
- **Deterministic.** A preset only rewrites settings before the builder
  runs and draws nothing; random events still come from the existing
  seed stream, so changing the weights changes which events are drawn,
  deterministically.

### Phase 18 — Psychology calibration

**Complete.** Exactly one constant changed, for a reason the Step 3.5
audit had already identified and this phase reproduced independently.
The roadmap gate above is closed.

- **The defect was dimensional, not aesthetic.** `recent_return` spans
  one interval; `momentum` spans the whole window, `SIGNAL_WINDOW - 1`
  = 4 intervals. Both were divided by `PRICE_MOVE_SCALE` (0.05), so a
  four-interval displacement was measured against a one-interval
  yardstick and ordinary drift read as an extreme trend. Reproduced
  before changing anything: momentum supplied **71%** of the price
  pressure (audit: 73%) and fear or FOMO sat above 0.9 on **49.2%** of
  ticks (audit: 35–52%).
- **The change.** `MOMENTUM_SCALE = PRICE_MOVE_SCALE * sqrt(SIGNAL_WINDOW
  - 1)` = 0.10, applied to the momentum term only. A random walk's
  displacement over k intervals grows with sqrt(k), so this is the
  horizon-consistent divisor: a 10% move over the window now counts for
  what a 5% move over one interval does. Candidates were measured before
  choosing — linear scaling (0.20) over-corrected to a 38% momentum
  share, sqrt scaling lands at 55%, near the parity the formula intends.
- **Nothing else was touched.** `PRICE_MOVE_SCALE`, `VOLATILITY_SCALE`,
  `TERM_CAP`, `SIGNAL_WINDOW`, every trader's `psychology_sensitivity`,
  `PSYCHOLOGY_MAX_SHIFT`, the analytics thresholds, the state's bounds
  and the absence of decay all stand. Where evidence did not justify a
  change, none was made.
- **Measured effect** (20 fixed seeds x 200 ticks, both pricing modes,
  no/scheduled/random events, psychology off and on, plus the three
  Phase 17 conditions). Share of ticks with a component at or above 0.90:
  random walk with no events **29.3% -> 21.4%**, with a schedule
  **28.6% -> 22.6%**, AMM with no events **26.5% -> 23.2%**. Event-heavy
  and market-condition cells barely move, which matches the audit's
  finding that events drive uncertainty rather than fear/FOMO. Psychology
  **off** cells are bit-identical. No further tuning followed from these
  numbers.
- **What did not change.** Both builder fingerprints (they are built
  without psychology), the historical 336, every psychology-free pinned
  digest, simulation IDs, seed derivation, and psychology-disabled runs —
  byte-identical across six pinned CLI invocations, including one under a
  Phase 17 market condition.
- **What did change, and why the harness now says so.** 66 pinned
  digests move — 51 across the nine levels, 11 common, 4 CLI — every one
  a psychology-enabled run. Undoing only `MOMENTUM_SCALE` reproduces all
  66 exactly, which is the evidence that the calibration is their sole
  cause. Four whale-cohort expectations move for the same reason; their
  provenance comment now records that, rather than continuing to claim
  values that came from a pre-calibration archive.
- **Calibration boundaries in the compatibility harness.** Pinning the
  new values over the old ones would have made every earlier checkpoint
  fail, because `compare_checkpoints.py` runs *archived* source against
  the pins. The pin file now records superseded digests under
  `calibrations`, and `grid.CALIBRATIONS` says how to detect a
  calibration **in the source under test** — for Phase 18, whether
  `MOMENTUM_SCALE` exists — so each checkpoint is compared against the
  digests its own code should produce. No case is skipped or excused:
  corrupting a superseded digest still fails the comparison, and 9/9
  levels report IDENTICAL again. A `--write-pins` now carries the
  boundary record forward instead of dropping it.
- **Deferred to Phase 19 (model shape, not calibration).** Roughly a
  third of ticks still sit above 0.90 once a real one-directional move is
  under way, because `tanh(B)` reaches 0.9 at B ~ 1.5 by construction.
  Changing that means changing the formula's shape — as would adding
  decay, memory, or any cross-trader effect — and none of it belongs in a
  calibration phase.

### Phase 19 — Realism / feedback pass

Unlocked by Phase 18. Expands the behavioral realism model with
participant-to-participant feedback.

- Scope: cascades, herding, social influence, other behavioral
  feedback, more realistic market reactions.
- Gated: no feedback loop in this phase's scope may be implemented
  before Phase 18 is complete.
- Builds on the existing psychology/trader architecture
  (`core/psychology/`, `core/traders/`) rather than a parallel
  behavioral system.

**CLOSED.** Implementation commit
`7f9353b0b96c2e1f18fefc6468774b85660a0d6d` (preceded by `b12ce1d`). Full
record: `docs/PHASE_19_FINAL.md`.

| | |
|---|---|
| Phase objective | Investigate behavioral feedback realism |
| Established | Individual behavioral responses to crowd information |
| Not established | Participant-to-participant propagation / herding |
| Disposition | Close the current architecture; defer a new multi-agent architecture to a future phase |

#### Completed

- Crowd-flow observation (lag-1 organic flow, `crowd_flow`)
- Participation response (`crowd_response`, momentum)
- Directional crowd-flow response (`crowd_direction`, retail)
- AMM architecture analysis (flow/price near-collinearity)
- Breadth identifiability experiment
- Leave-self-out breadth response (`breadth_observation` /
  `breadth_response`, retail)
- Others-only propagation experiment
- Architecture / disposition review

#### Final scientific result

Phase 19 demonstrated bounded participant-level behavioral responses to
aggregate crowd information, including a retail directional response to
leave-self-out breadth. However, the preregistered others-only
propagation experiment did not establish a response in non-retail trader
classes. Therefore genuine multi-participant herding, cascades, and
market-wide behavioral amplification were not established. Further
feedback realism requires new architecture rather than additional tuning
of the current mechanism.

The experiments narrowed the architecture and identified what is
missing. In the tested configuration no non-retail trader's direction
depends on any non-price information produced by another participant
group; momentum's crowd-flow reader affects participation only, and it
was off in the propagation test. Another group's behavior can therefore
reach non-retail direction only through price and market state. In
AMM mode executed organic flow sets pool reserves and therefore price
(measured `corr(flow, return) ≈ 0.997`). This makes crowd-flow responses
difficult to identify separately from price-mediated behavior. It does
not make every AMM experiment impossible.

**Not established:** participant-to-participant propagation; multi-agent
herding; cascades; contagion; market-wide behavioral amplification; a
validated independent-value AMM process.

**Not claimed:** that the retail breadth response is equivalent to
herding; that the Step 17 null proves propagation is impossible in all
architectures; that AMM realism is fundamentally impossible.

The subsections below record what each shipped primitive is and what
its measurement did and did not show. All flags default off. With them
off, the 480-run experiment grid reproduced `8bdc13e` bit-for-bit, and
compat pins and builder fingerprints are unchanged.

#### Shipped: the crowd-flow participation response

A bounded participation primitive, opt-in and
off by default, built in four steps: a read-only baseline measurement
(Step 1), the lag-1 organic crowd-flow observable (Step 2), a
measurement of what that observable already predicts before anything
reacts to it (Step 3), and one behavioural response to it (Step 4).

- **What it is.** Each tick carries `crowd_flow`: what the organic
  crowd did on the *previous completed* tick, as a signed fraction of
  total supply in [-1, 1], with wash legs, manipulator fills and whale
  trades excluded. A trader with a non-zero `crowd_sensitivity` gets a
  bounded, saturating, continuous participation increment when that
  crowd was loud — `tanh(|flow| / CROWD_FLOW_SCALE)`, scaled and capped
  at `CROWD_URGE_CAP`, applied as a second pass of the engagement
  operator psychology already uses. `momentum` is the only strategy
  with a non-zero default sensitivity (0.5, worth at most +15%
  participation relative). Two independent flags: `crowd_observation`
  delivers the signal, `crowd_response` lets traders act on it, and
  both default off.
- **What it touches.** Participation and nothing else — not sizing, not
  direction, not a threshold, not a price target, and never
  `compute_psychology`. No new RNG source and no change to draw
  ordering.
- **What the measurement established.** Step 4 compared A2 (response
  on) against A1 (the same observable present and ignored), paired
  seed-for-seed across 24 cells × 20 seeds in both pricing modes. The
  targeted effect is real: momentum participation rose in **23 of 24
  cells**, significant at the seed level in 12. Stabilising strategies
  were unaffected, volatility barely moved, and the Phase 18 psychology
  guards stayed within their framework.
- **What the measurement did NOT establish — read this before
  extending it.** No detectable **market-level herding signature**. The
  pre-registered aggregate metric M5b (the conditional association
  between lag-1 organic flow and subsequent trader direction, under the
  approved control set) moved by a median of +0.0035 against a
  structural baseline of about 0.09, and was:
  - **significant in 0 of 24 cells**, and
  - **above twice the null floor in 0 of 24 cells** — the null floor
    being the same estimator applied to the participation gate, a
    channel that provably cannot respond to crowd flow at all.

  So this primitive is a *crowd-flow participation response*. It is not
  herding and not social influence, and it must not be described as
  either without saying that the experiment did not establish them.
  Step 3 had already found that the A1 arm carries a non-zero M5b on
  its own, so any future mechanism must be differenced against A1
  seed-for-seed rather than against zero.
- **Kept as an opt-in primitive.** The A1 arm — observable present,
  response off — is the honest baseline for measuring whatever comes
  next, so the two flags stay separate even once another mechanism
  supplies market-level feedback.

#### Shipped: the directional crowd-flow response (Steps 7–8)

- **What it is.** `crowd_direction`: a bounded, antisymmetric tilt of
  retail's buy/sell choice toward the side of the previous tick's organic
  flow (`crowd_direction_tilt`, retail sensitivity 0.25). Committed in
  `7f9353b`.
- **What the measurement established.** RW: the frozen M5b bar was met
  (12/12 cells significant, 12/12 above twice the null floor).
- **What it did NOT establish.** AMM failed the frozen bar (0/12
  significant, 2/12 above the floor). Verdict **PARTIAL**; F1 FAIL, F2
  TRIGGERED (price-mediated / volatility), F3 FAIL (one cell breach).
  No claim of market-wide herding.
- **Why AMM failed (Steps 9–10).** AMM price is almost a deterministic
  function of cumulative organic flow (`corr(flow, return) ≈ 0.997`), so
  a lag-1 flow response cannot be credited separately from price
  response under the frozen controls.

#### Shipped: the leave-self-out breadth response (Steps 12–15, 17)

- **Identifiability (Step 12).** Leave-self-out signed participation
  breadth keeps substantial variation after the strict price/path
  controls: residual share median RW 0.478, AMM 0.442, 12/12 cells in
  both modes. Verdict: **supported**.
- **What it is (Steps 13–14).** `MarketContext.crowd_breadth`: the
  previous completed tick's leave-self-out signed breadth, delivered per
  trader under `breadth_observation`. Retail alone responds
  (`breadth_direction_tilt`, 0.25, outermost layer) under
  `breadth_response`. Preregistered, committed in `7f9353b`. No new RNG.
- **Retail response (Step 15).** Retail's directional response is
  demonstrated at decision level in all 24 cells. The frozen market-level
  bar was met in RW (C1 12/12, C2b 12/12) but not in AMM (C1 5/12,
  C2b 12/12). Verdict **PARTIAL**. F1 and F6 remain formal failures;
  F2–F5 and gates G1–G6 passed.
- **Propagation (Step 17).** Did retail's response change non-retail
  traders' direction? No: RW C1 0/12, C2 0/12; AMM C1 0/12, C2 1/12.
  Verdict **FAIL**. G1–G7 verification passed. Step 17 is a
  preregistered deterministic re-analysis of the Step 15 runs, not an
  independent replication.
- **Retained, scoped as retail-only.** It supports the claim "retail
  responds to observed breadth", not "the market exhibits herding".

#### Not accepted: the AMM external-market variant

An external GBM reference price arbitraged into the pool, meant to
decorrelate AMM flow from price. It failed its preregistered pre-check
(P1, P2, S1, S2, S3, S6 FAIL; S4, S5, S7 PASS), so the planned experiment
never ran and nothing was tuned. It is archived as a failed experimental
prototype on branch `experiment/phase19-amm-external-failed`. It is not
part of the supported simulator architecture.

#### Deferred future work (not Phase 19 tasks)

- A non-retail observer that reads an independent crowd signal (the
  missing second observer class)
- An independent / fundamental value process for AMM identification
  (a redesign under a new pre-registration, not a retune of the archived
  prototype)
- Possible dynamic-liquidity / LP architecture
- Future cascade experiments, which need a second observer class first
- Stabilizer criterion redesign: the frozen "no sign change in
  cell-mean net flow" rule tripped on two near-zero RW panic-seller
  means (F6 / F17.5). It stays a formal FAIL; a future pre-registration
  may redesign the criterion.
- The psychology saturation shape Phase 18 deferred here (`tanh`
  saturation during one-directional moves). Phase 19 did not address it.

### Phase 20 — Advanced visualization

Expands the coin-economy dashboard's chart layer beyond the
price/volume/component-line charts Phase 10 shipped.

- Candidate charts: candlestick-style price view, holder growth, supply
  distribution, whale activity, volume, sentiment, psychology, regime
  changes, scenario comparisons, batch/aggregate distributions (once
  Phase 14/15 exist).
- Existing dashboard charts (`price_path_chart`, `component_lines_chart`,
  and the tables/charts each section already renders) are not
  duplicated — this phase adds views the current sections don't have.

**Phase 20 is closed** (see the closeout after Step 9). Steps:

- **Step 1 — audit (read-only).** The dashboard keeps only the report and
  the per-tick price, market cap and volume; everything else a run records
  per tick was dropped after `run_simulation`.
- **Step 2 — tick model specification.** A frozen field contract with
  decisions D1–D6 (spec kept outside the repository, sha256 `5fc1c459…`).
- **Step 3 — tick-level visualization model (implemented).**
  `analytics/tick_series.py` builds a columnar `TickSeries` from a run's
  `SimulationTick` sequence and its explicit population: market fields and
  returns (no gap bridging), the `analytics/market.py` volume split,
  per-class organic fills, whale and pump-and-dump volumes, recorded event
  state, psychology, AMM pool state, and the descriptive organic crowd-flow
  and breadth observables. `dashboard/data.py` adds
  `run_dashboard_simulation`, which runs the simulation once and returns a
  `DashboardRun(payload, tick_series)`; `run_simulation` and its payload are
  unchanged (byte-identical against `cfeb886`), and `tick_series_to_dict`
  serializes by the payload's own rules.
  - **TickSeries is ephemeral dashboard analytical data and is not
    persisted.** `DashboardPayload`, `payload_to_dict`, `CoinRunRepository`
    and the saved-run schema are unchanged.
  - **Saved runs created without tick-level recording do not reconstruct
    TickSeries**; a view that needs it shows "Tick-level data was not
    recorded for this saved run."
  - Batch runs, aggregate statistics and stress testing do not build it.
  - Not in the model: decision-level data (holds, tilts), leave-self-out
    breadth, replayed holdings or P&L, slippage, timestamps.
  - Tests: `tests/analytics/test_tick_series.py`,
    `tests/dashboard/test_data_tick_series.py` (92). Full suite 3695;
    `tests/compat` 25; checkpoints 9/9 IDENTICAL; fingerprints RW
    `d1218e0e0739f776`, AMM `f853009b5818169e`; pins unchanged; CLI output
    byte-identical against `cfeb886`.
  - No chart or dashboard view uses it yet.
- **Step 4 — tick-level dashboard views (implemented).** A new
  **Tick-level views** section, rendered after the seven existing sections
  (so no existing section or chart moves; the price chart is still the
  first chart), draws only from the run's stored `TickSeries`:
  - **Synthetic OHLC** — candles over windows of 5/10/20/50 recorded ticks
    (default 10): open is the first recorded price, high the highest, low
    the lowest, close the last; a final shorter window is marked partial.
    Every chart and caption says: *Synthetic OHLC aggregated from recorded
    simulation-tick prices.* These are not exchange candles.
  - **Volume by component** — per-tick stacked bars of the recorded split
    (organic, manipulator, wash, plus whale and background where recorded),
    which add up to each tick's recorded volume.
  - **Recorded pool state** (AMM only) — reserves, invariant, cumulative
    fees and cumulative swap count; random-walk runs say no pool state is
    recorded.
  - **Recorded event state** — sentiment, volatility and attention
    multipliers and live-event count per tick, described as recorded state;
    runs without news events say so.
  - Plumbing: `render_dashboard` now defaults to `run_dashboard_simulation`
    and keeps the serialized tick series under its own session key beside
    the unchanged payload. Changing the OHLC window only re-renders; only
    the Run button runs a simulation.
  - TickSeries remains ephemeral and unpersisted. A run without one shows
    "Tick-level data was not recorded for this saved run." There is no
    saved-run loader in the dashboard yet, so today this state is reached
    only through a runner that returns a payload alone; a future saved-run
    loader will use the same state.
  - Not added: a second psychology chart or spot-price line (both already
    shown), Phase 19 observables, holders, supply, P&L, drawdown replay,
    slippage, batch and scenario-comparison views.
  - Tests: 47 new (`tests/visualization/test_tick_charts.py`,
    `tests/dashboard/test_tick_section.py`,
    `tests/dashboard/test_view_tick_series.py`). Full suite 3742;
    `tests/compat` 25; checkpoints 9/9 IDENTICAL; fingerprints RW
    `d1218e0e0739f776`, AMM `f853009b5818169e`; pins unchanged; payload
    and CLI output (including `--batch`) byte-identical against `6a2ba6a`.
- **Step 5 — batch/aggregate/scenario audit (read-only).** One batch is
  one `SimulationParams`; every completed run keeps its `DashboardPayload`;
  `aggregate_batch` describes the 19 `MarketSummary` metrics with count,
  mean, median, sample standard deviation, min, max and P5/P25/P50/P75/P95.
  A whole `BatchResult` is too large for session state at the service
  limits, so the dashboard must keep a reduction.
- **Step 6 — batch visualization (implemented).** A **Batch runs** panel
  after every single-run view, for one configuration at a time:
  - `dashboard/data.py` adds `run_dashboard_batch(params, runs)`: Phase
    14's `run_batch` with `run_simulation` as the runner (the CLI's
    `--batch` path, so batch runs still return plain payloads and build no
    `TickSeries`), then Phase 15's `aggregate_batch`, unchanged. The result
    is reduced at once to a `DashboardBatch`: the request and base seed,
    requested/successful/failed counts, each failure (index, seed, error),
    each successful run's index, seed, simulation id and 19 aggregated
    metric values (read through the aggregate's own accessor), and the
    `AggregateStatistics`. No payload, price series or tick series is
    kept — about 1 KB per run.
  - **Dashboard batch limit: `MAX_DASHBOARD_BATCH_RUNS = 200`**, because a
    dashboard batch runs synchronously; the service's `MAX_BATCH_RUNS`
    (1000, used by the CLI) is unchanged, and the panel states both.
  - **Views** (`dashboard/batch_section.py`, display only;
    `visualization/batch_charts.py`, pure Plotly): the batch summary and a
    failure table; one selected aggregated metric's mean, median (P50),
    sample standard deviation, min, P5, P25, P75, P95 and max with a range
    chart (min–max, P5–P95, P25–P75, median and mean markers); per-run
    histograms of close price, cumulative return, max drawdown and total
    volume with the aggregate's mean and median as reference lines. A
    metric no successful run computed says so; a batch with no successful
    run shows only its summary and failures; a one-run batch shows no
    standard deviation and no spread.
  - **Descriptive only.** Every figure is labelled as the spread of
    successful simulated runs of one configuration — *not a forecast or
    real-market probability*. P5–P95 is an observed spread, not a
    confidence or prediction interval.
  - **Separate state.** The batch has its own status, result and error
    keys and its own Run batch button; a batch leaves the single run's
    payload and tick series in place, and a single run leaves the batch.
  - Deferred to Step 7 or later: scenario comparison, a market-condition
    control, per-tick percentile price paths, psychology/manipulation and
    other non-market distributions, batch persistence, confidence
    intervals and significance testing.
  - Tests: 119 new (`tests/visualization/test_batch_charts.py`,
    `tests/dashboard/test_data_batch.py`,
    `tests/dashboard/test_batch_section.py`,
    `tests/dashboard/test_view_batch.py`). Full suite 3861; `tests/compat`
    25; checkpoints 9/9 IDENTICAL; fingerprints RW `d1218e0e0739f776`, AMM
    `f853009b5818169e`; pins unchanged; original 336 pass; CLI output
    (including `--batch`) byte-identical against `c5909a1`.
- **Step 7 — scenario comparison (implemented).** A **Scenario comparison**
  panel after the batch panel runs separate batches of explicitly selected
  configurations and shows them side by side:
  - **Configurations** are every combination of the pricing modes
    (`random_walk`, `amm`), manipulation presets (none, `pump_and_dump`,
    `wash_trading`) and Phase 17 market conditions (neutral/no preset,
    `bear`, `bull`, `meme`) selected, labelled with every dimension
    (`RW | Pump & dump | Bull`). Every other run option is held constant
    and shown as such, with the dimensions actually varied named.
  - **Checked before running.** `plan_comparison` shows configurations ×
    runs = total simulations and reports anything that stops the
    comparison; the button stays disabled until there is none. AMM with
    whales on is refused (the simulator's rule), never run with whales
    quietly removed. Limits: `MAX_DASHBOARD_BATCH_RUNS` (200) per
    configuration and **`MAX_COMPARISON_RUNS = 400`** in total; the
    service's `MAX_BATCH_RUNS` is unchanged.
  - **Shared seed.** One base seed for every configuration, passed to
    `run_batch(..., base_seed=...)`, so corresponding runs have the same
    derived seed; different configurations may still consume random
    streams differently, and the panel says so. No paired test is made.
  - **Execution.** `run_dashboard_comparison` runs one `run_batch` per
    configuration with `run_simulation` and reduces each with Step 6's
    `reduce_batch` (so `aggregate_batch`, unchanged). Session state keeps
    only the held-constant request, base seed, run counts, compared
    dimensions and one reduced batch per configuration, under keys of its
    own; the single run and the batch panel are untouched by it and it by
    them.
  - **Views** (`dashboard/comparison_section.py`,
    `visualization/comparison_charts.py`): per-configuration run counts
    and failures; one selected aggregated metric's min–max, P5–P95,
    P25–P75, median and mean per configuration as a range chart and a
    table; the median of every aggregated metric per configuration as a
    plain matrix (no colour scale). Configurations stay in canonical
    order — never sorted by value, ranked or scored. A configuration with
    no successful run keeps its summary and failures and is left out of
    the chart.
  - **Descriptive only.** The panel states that the charts compare
    descriptive statistics from separate batches of synthetic simulations
    and establish no causal effect, forecast or real-market probability;
    that market-condition presets are simulator configurations; that RW
    and AMM are different pricing architectures; and that a preset's drift
    does not apply in AMM.
  - Still deferred: per-tick percentile price paths, psychology,
    manipulation and other expanded aggregation, batch persistence,
    confidence intervals, significance tests, causal estimation,
    forecasting and ranking.
  - Tests: 115 new (`tests/visualization/test_comparison_charts.py`,
    `tests/dashboard/test_data_comparison.py`,
    `tests/dashboard/test_comparison_section.py`,
    `tests/dashboard/test_view_comparison.py`). Full suite 3976;
    `tests/compat` 25; checkpoints 9/9 IDENTICAL; fingerprints RW
    `d1218e0e0739f776`, AMM `f853009b5818169e`; pins unchanged; original
    336 pass; CLI output (including `--batch` and `--market-condition`)
    byte-identical against `fa6ade8`.
- **Step 8 — cross-run price paths (implemented).** Inside the **Batch
  runs** panel, between the aggregate range chart and the histograms, a
  **Price paths across runs** chart shows the recorded price at each tick
  across the successful runs of the batch's one configuration:
  - `analytics/price_paths.py` — `aggregate_price_paths(result)` reads each
    successful run's `payload.price_series` by shape, requires the first
    run's ticks to be consecutive and every other run's to match them
    exactly, requires every price to be positive and finite, and hands
    each tick's prices to Phase 15's `aggregate_values`. The result is a
    columnar `PricePathBands` (runs, ticks, minimum, P5, P25, median, P75,
    P95, maximum, mean); no successful run gives `None`. Nothing is
    truncated, padded or interpolated — a mismatch is a `ValueError` naming
    the run — and there is no tick 0.
  - **Reduced data only.** `reduce_batch(result, *, price_paths=False)`
    computes the bands, when asked, while the runs are still in memory;
    `run_dashboard_batch` asks. `DashboardBatch.price_paths` holds only the
    bands (ticks × 9 numbers): no `BatchResult`, run, per-run price series
    or TickSeries enters session state.
  - **View:** P5–P95 and P25–P75 filled bands and the median line; minimum
    and maximum as dotted lines behind a "Show minimum and maximum across
    runs" checkbox (off; it only redraws). The mean is stored, not drawn.
    Individual run paths are not drawn, sampled or kept. The disclosure
    says the chart is the per-tick spread of recorded prices across
    successful simulated runs of one configuration, not a forecast or
    real-market probability, and the caption that the median line and band
    edges are not the path of any single run. Failures are counted ("n of
    m requested runs"); one successful run says the bands coincide with
    its path; an all-failed batch shows no chart.
  - **Step 7 unchanged.** Scenario comparison still reduces without price
    paths (`price_paths` is `None` in every group); cross-configuration
    bands remain deferred, with individual paths, confidence intervals,
    significance tests, forecasting and ranking.
  - Tests: 89 new (`tests/analytics/test_price_paths.py` plus the batch
    data, section, chart and view tests; four Step 6 chart-position and
    key-list expectations updated for the new chart). Full suite 4065;
    `tests/compat` 25; checkpoints 9/9 IDENTICAL; fingerprints RW
    `d1218e0e0739f776`, AMM `f853009b5818169e`; pins unchanged; original
    336 pass; CLI output byte-identical against `d264556`.
- **Step 9 — remaining-scope audit (read-only).** Inventoried every
  dashboard view, reconciled the original candidates against the code and
  the recorded data, and found nothing left to build. Conclusion: ready to
  close. No source, test or roadmap change was made in the step.

#### Phase 20 — Advanced Visualization — CLOSED

Closed at the Step 8 implementation commit `e903ebe` (`feat: add cross-run
price path visualization`); this closeout is documentation only. Phase 20
expanded the dashboard beyond the Phase 10 price/volume/component-line
layer through:

- synthetic tick-window OHLC (Step 4);
- tick-level volume composition (Step 4);
- AMM pool state — reserves, invariant, cumulative fees and swaps (Step 4);
- recorded event state (Step 4);
- batch summary and failures, and the aggregate range view (Step 6);
- batch distributions of close price, cumulative return, max drawdown and
  total volume (Step 6);
- scenario comparison — plan, per-configuration run/failure summary,
  selected-metric range comparison and median matrix (Step 7);
- cross-run percentile price paths — P5–P95 and P25–P75 bands, the median
  and an optional minimum/maximum, kept as reduced bands only, with no
  individual run path retained (Step 8).

The Step 9 audit found that every original candidate is reconciled, that
no justified visualization remains, and that no instrumentation gap blocks
a roadmap candidate. No Step 10 is warranted. Further charts that the
existing data would allow (per-tick whale buy/sell volume, per-class
organic net flow, per-tick AMM price impact) were deliberately rejected:
they answer no Phase 20 requirement and would add to an already dense
page.

**Original candidates — final disposition.**

| Candidate | Final disposition |
|---|---|
| Candlestick-style price view | COMPLETE — implemented as synthetic OHLC |
| Holder growth | NOT JUSTIFIED — the population is fixed |
| Supply distribution | DEFERRED — requires holdings/fill replay |
| Whale activity | COMPLETE |
| Volume | COMPLETE |
| Sentiment | COMPLETE |
| Psychology | COMPLETE |
| Regime changes | COMPLETE |
| Scenario comparisons | COMPLETE |
| Batch/aggregate distributions | COMPLETE |
| Percentile paths | COMPLETE for one configuration; cross-configuration deferred |

Synthetic OHLC is not exchange-style candle data: the simulator records
one price per tick, so each candle only summarizes a window of recorded
tick prices.

**Not modelled / not justified.** These would describe something the
simulator does not have; nothing here implies the mechanism exists.

- Holder-growth visualization — the population is fixed at construction
  and no agent enters, so there is no holder growth to draw.
- Phase 19 herding, propagation or cascade visualization, and any
  participant-to-participant propagation claim — not established by
  Phase 19 (`docs/PHASE_19_FINAL.md`).
- Probability claims, forecasting, causal inference and real-market
  interpretation — every view is a description of synthetic runs.

**Deliberately deferred for future work.** The data or definition does not
exist yet; each would need its own design.

- Per-tick supply distribution — ticks do not record wallets; it needs a
  holdings/fill replay the Step 2 model excludes.
- Per-tick P&L and batch P&L distributions — P&L exists only from start
  and end balance snapshots.
- Aggregate slippage visualization — slippage is defined per AMM swap
  only; no per-tick or per-run aggregate is defined.
- Cross-configuration percentile paths and individual path overlays.
- Psychology and manipulation batch distributions — batch aggregation
  covers only the 19 market metrics.
- Batch and comparison persistence.
- Confidence intervals and significance testing.

**Phase 19 boundary.** The tick-level model records the descriptive organic
crowd-flow and breadth observables, but Phase 20 does not draw them as
behavioral mechanisms: dashboard runs cannot enable the Phase 19 response
flags (`SimulationParams` has none), participant-to-participant
propagation was not established, herding/cascade/contagion claims were not
established, and a chart of organic fill imbalance would not establish
them. Phase 20 makes no causal or behavioral claim from those observables.

**Performance finding.** After Step 8 the full suite once appeared to take
about 175s, against about 97s at Step 7. The difference did not reproduce.
Controlled back-to-back measurements were about 58.73s at Step 7
(`d264556`) and 59.22s at Step 8 (59.94s with `--durations`); the 462
Phase 20 tests alone took about 10.59s. Step 8 itself added roughly 0.5s.
The 175s run is not attributable to any demonstrated code regression;
machine load at the time is a plausible contributor, but its cause is not
established.

**Final verified state (Step 8).** Full suite `4065 passed, 3 deselected`
(89 new in Step 8); `tests/compat` 25 passed; checkpoints 9/9 IDENTICAL;
fingerprints RW `d1218e0e0739f776`, AMM `f853009b5818169e`; historical pins
unchanged; original 336 pass; CLI 15/15 byte-identical against Step 7. The
working tree was clean before this closeout.

**Handoff.** Next is Phase 21 (CI / GitHub integration), then Phase 22
(documentation & notebooks) and Phase 23 (Version 1.0), below.

### Phase 21 — CI / GitHub integration

Adds automated CI, closing the item open since Phase 0.

- GitHub Actions running the existing test suite (`pytest`) on push/PR.
- Lint/type checks where they earn their place, without demanding a
  source rewrite to pass them.
- Clean failure reporting; a red run should be legible without digging
  through raw logs.
- No production code changes to satisfy CI — CI conforms to the code,
  not the reverse, at this phase.

#### Phase 21 — CI / GitHub Integration — CLOSED

The repository is connected to GitHub (`jdgiron12/crypto-simulator`) and
GitHub Actions runs on every push and pull request to `main`. No
production code changed in this phase. Commits: `8117b97` (Actions
foundation), `9fdd8ea` (macOS runner), `a00e1cc` (Python matrix and slow
tests), `6c65108` (Python support aligned with reproducibility), `d00c3d9`
(coverage reporting), `0108ab7` (Dependabot and PR template).

**CI jobs** (`.github/workflows/ci.yml`, all on `macos-latest`):

| Job | Python | Command |
|---|---|---|
| `test` | 3.12, 3.13 | `pytest` |
| `slow` | 3.13 | `pytest -m slow` |
| `compat` | 3.13, full history | `python scripts/compat/compare_checkpoints.py` |
| `coverage` | 3.13 | `pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html` |

- **macOS is authoritative.** The pinned compatibility digests and the
  RW/AMM fingerprints were produced on macOS. On Linux the random-walk
  path (`random.gauss`, `math.exp`) gives last-ulp differences between
  glibc and Apple's libm, which the simulation amplifies into different
  digests, so CI stays macOS-only until a cross-platform fingerprint
  strategy is decided.
- **Supported Python is `>=3.12`.** Python 3.12 changed built-in `sum()`
  of floats to compensated summation; under 3.11 the AMM fingerprint is
  `b072d4c066478e1c` instead of the pinned `f853009b5818169e`, reproduced
  exactly under 3.13 by substituting a left-to-right `sum`. The support
  floor was raised rather than the pins or the numerics changed.
- **Slow tests** (the three heavy stress cases) and the **checkpoint
  comparison** (9/9 IDENTICAL) run on every push.
- **Coverage** is reported, not gated: terminal `term-missing` output, a
  job summary built from the `coverage.xml` pytest-cov writes, and the
  `htmlcov/` report uploaded as the `coverage-html` artifact. Measured
  baseline 99.18% (29,409 statements, 242 missed). No threshold.
- **Dependabot** checks GitHub Actions monthly; Python dependencies are
  deliberately excluded. A **pull request template** asks for summary,
  validation and compatibility/reproducibility impact.

**Deferred.**

- Issue templates — single-maintainer project; add if outside
  contributions begin.
- Cross-platform (Linux) CI — needs a fingerprint strategy first.
- Dependency locking — Python dependencies remain unpinned.
- Lint/type-check tooling — not introduced; a future phase may add it
  where it earns its place.
- Open Dependabot PRs #1 (`actions/checkout` 4→7), #2
  (`actions/upload-artifact` 4→6) and #3 (`actions/setup-python` 5→7) —
  left unmerged; each changes the workflow and should pass CI on its own.
- Branch protection and other GitHub settings — an administrative
  recommendation (e.g. require the CI jobs on `main`), not repository code.

**Final verified state.** Local macOS Python 3.13: `4065 passed, 3
deselected`; `pytest -m slow` 3 passed; checkpoints 9/9 IDENTICAL;
fingerprints RW `d1218e0e0739f776`, AMM `f853009b5818169e`; pins unchanged.

**Handoff.** Next is Phase 22 (documentation & notebooks), then Phase 23
(Version 1.0).

### Phase 22 — Documentation & notebooks

Completes the documentation item open since the trading-platform
track's Phase 5.

- Architecture, simulation mechanics, trader behavior, AMM, psychology,
  whale behavior, events, manipulation scenarios, persistence, batch
  experiments, analytics, the scenario system, the dashboard,
  reproducibility and testing — each documented as it actually behaves,
  not as planned.
- Example notebooks where they add something a document can't (an
  interactive walkthrough of a run, say).

#### Phase 22 — Documentation & Notebooks — CLOSED

Documentation only: no simulation behavior, numerical logic, random-number
behavior, fingerprint, compatibility pin, CI workflow, dependency or
dashboard behavior changed in this phase. Every document was written
against the current source and every command it presents as runnable was
executed. Commits: `72305f2` (README and `.env.example` reconciled, Step 2),
`f4aee22` (`docs/ARCHITECTURE.md`, Step 3), `dce3390`
(`docs/REPRODUCIBILITY.md` and `docs/CLI.md`, Step 4), `fe24880`
(`docs/DASHBOARD.md`, Step 5), `5812921` (executable examples, Step 6),
and this closeout (Step 7: final audit, README documentation table and
structure, stale forward references in `docs/ARCHITECTURE.md`).

**Steps.**

- [x] Step 1 — documentation audit and plan (no commit).
- [x] Step 2 — README reconciled against the repository; `.env.example`
  corrected to the real process-environment behavior.
- [x] Step 3 — `docs/ARCHITECTURE.md`: the two tracks, layering, the run
  data flow and tick loop, state and persistence boundaries, invariants.
- [x] Step 4 — `docs/REPRODUCIBILITY.md` (seed entry points and precedence,
  determinism scope, batch derivation, compatibility levels and
  calibration boundaries, CI) and `docs/CLI.md` (every option, scenarios,
  batches, stress testing, exit codes, environment variables).
- [x] Step 5 — `docs/DASHBOARD.md`: launch, every control and view,
  runtime state, persistence, limitations, troubleshooting.
- [x] Step 6 — `examples/basic_simulation.py`,
  `examples/scenario_comparison.py` and `examples/batch_statistics.py`,
  run by `tests/examples/test_examples.py` in subprocesses.
- [x] Step 7 — final audit and closeout.

**Notebooks.** The "example notebooks" item is met by executable
`examples/*.py` scripts instead: they run in CI through the test suite,
need no Jupyter dependency, and cannot drift silently from the API. No
notebook was added.

**Deferred to Phase 23.**

- Packaging: `pyproject.toml` lists only the top-level `crypto_simulator`
  package; subpackage inclusion and a non-editable install are unverified.
- Versioning, CHANGELOG / release notes and the final 1.0 checklist.
- Dependency pinning decision (`requirements*.txt` remain ranges), and
  the unused `python-dotenv` dependency.
- `run_simulation`, the shared single-run entry point used by the CLI's
  batch mode, the stress harness and the examples, lives in
  `crypto_simulator/dashboard/data.py`; moving it is an architecture
  decision, not documentation.
- Source-level CLI wording and validation issues recorded in
  `docs/CLI.md` §16 (`--psychology` "uncalibrated" / "calibration
  deferred" text, reflowed `--help` description, `--ticks <= 0`
  traceback, unchecked `CRYPTOSIM_RANDOM_SEED` range).
- Possible restructuring of this roadmap.

**Final verified state.** Local macOS, Python 3.13: `4068 passed, 3
deselected` (the three new example tests included); `pytest -m slow` 3
passed; checkpoints 9/9 IDENTICAL; fingerprints RW `d1218e0e0739f776`,
AMM `f853009b5818169e`; pins unchanged; all internal Markdown links
resolve.

**Handoff.** Next is Phase 23 (Version 1.0).

### Phase 23 — Version 1.0

The final milestone. Before it is declared:

- Phases 11–22 (or whichever subset is judged required) are complete.
- Full test suite, regression checks (compat harness, historical-336
  baseline, both builder fingerprints) and the Phase 16 stress suite all
  pass.
- Reproducibility is verified end to end (seeded CLI and dashboard runs,
  saved/loaded scenarios, batch runs).
- Documentation is complete; the dashboard, scenario system,
  persistence, batch simulation and reporting all work as documented.
- No known critical accounting defect remains.
- The exact release checklist is finalized at the time of release, not
  fixed here in advance.

#### Phase 23 — Version 1.0 — CLOSED

The final release phase. No simulation behavior, random-number behavior,
fingerprint or compatibility pin changed in it: across the whole phase
the only change inside `crypto_simulator/` is `__version__`.

- [x] Step 1 — release-readiness audit (no changes). Found one blocker: a
  built wheel contained only the top-level package.
- [x] Step 2 — packaging: `[build-system]`, package discovery for every
  `crypto_simulator` subpackage, `default.yaml` and `schema.sql` as package
  data, runtime dependencies declared; verified by a fresh non-editable
  install (`051ffb4`).
- [x] Step 3 — dependency and project metadata: unused `python-dotenv`
  removed; keywords, classifiers and project URLs added. No license and no
  authors, by decision (`81d398a`).
- [x] Step 4 — CLI: `--ticks` below 1 is a clean argument error; stale
  `--psychology` help wording removed; usage examples keep their layout.
  The "calibration deferred" run output is kept because it is part of the
  pinned CLI digests (`3f3e8b3`).
- [x] Step 5 — public Python API documented in the README and covered by
  `tests/test_public_api.py`; no code moved (`7ca87f0`).
- [x] Step 6 — version 1.0.0 prepared: version set in `pyproject.toml`
  and `crypto_simulator/__init__.py`, `CHANGELOG.md`,
  `docs/RELEASE_CHECKLIST.md`, README status and installation.
- [x] Step 7 — final release audit against `docs/RELEASE_CHECKLIST.md`:
  every release-critical area passed, and this closeout is its only change.

**Final verified state (Step 7, at `a2bb497`).** Local macOS, Python
3.13: `4101 passed, 3 deselected`; `pytest -m slow` 3 passed;
`tests/compat` 25 passed; checkpoints 9/9 IDENTICAL; fingerprints RW
`d1218e0e0739f776`, AMM `f853009b5818169e`; pins unchanged since Phase 18
(`8bdc13e`), with its calibration boundary still implemented; original 336
pass against current source. The wheel and sdist both build as `1.0.0`;
a fresh non-editable install (from the wheel, and from the sdist) passes
`pip check`, needs no `python-dotenv`, resolves every documented import
path from `site-packages`, loads `default.yaml` and `schema.sql`, and
reproduces run `7e806a4d73f2889e` (close `1.2854888267695834`). The
installed CLI's output is byte-identical to the repository's; the
examples and the stress suite pass against the installed package. CI is
green on `main`. No LICENSE, license metadata or authors, by decision. No
tag, GitHub release or package publication has been made.

**Left for after 1.0 (none blocks the release).**

- `docs/ARCHITECTURE.md`'s repository tree does not list `CHANGELOG.md` or
  `docs/RELEASE_CHECKLIST.md`, and `docs/CLI.md` §16's introduction still
  reads "left unchanged in this documentation step".
- CI does not build and install the wheel; packaging is covered by
  `tests/test_packaging.py` and the release checklist.
- Dependabot PRs #1–#3 (GitHub Actions version bumps) remain open.
- Known, documented limits stay as they are: bit-for-bit reproduction is
  verified on macOS only, and the CLI's "calibration deferred" wording is
  kept for compatibility.

**Handoff.** The planned development roadmap is complete. Tagging `v1.0.0`,
a GitHub release and any publication are a separate decision, made by
following `docs/RELEASE_CHECKLIST.md`.

### Phase 24 — Front-end redesign (in progress)

Goal: turn the dashboard into a calm, coherent dark product using the
existing Streamlit and Plotly stack, without changing simulation
behavior, compatibility pins, public APIs or the analytics boundary.
Trading practice (orders, portfolio, history) is not part of this phase;
it needs backend work and will be planned separately.

- [x] Step 1 — read-only UI/UX audit and design proposal (no changes).
- [x] Step 2 — design foundation: `.streamlit/config.toml` (dark theme,
  only options Streamlit has had since the declared minimum; minimal
  toolbar), `visualization/style.py` (tokens, `CHART_TEMPLATE`,
  `CHART_LAYOUT`), the template applied in all 11 chart builders, and
  `theme=None` on every `st.plotly_chart` call. Streamlit's front end
  fills in the page font and backgrounds unless a figure sets them on its
  own layout, so `CHART_LAYOUT` sets them beside the template. Chart data
  was verified identical (every rendered trace, colors aside, across RW,
  AMM, batch and comparison runs), and the change was reviewed in a
  browser.
- [x] Step 3 — app shell and navigation: `st.navigation` (top bar;
  `app.PAGES`) with **Simulate** as the landing page and **Legacy →
  Multi-asset sandbox** for the dormant experiment; the Trade, Portfolio
  and History placeholders removed from the app (their code untouched).
  Streamlit drops a widget's value once a run goes by without drawing it,
  so `view.retain_control_state()` keeps `RUN_CONTROL_KEYS` across page
  visits, and the controls' defaults moved from widget arguments into
  session state (same keys, same values) so keeping them never collides
  with a widget default. Batch and comparison stay on Simulate: on their
  own pages they would read controls that are not drawn there. Moving
  them is planned with the shared control sidebar (Step 4).
- [x] Step 4 — simulation workspace: the run setup in the sidebar,
  grouped, with plain-language labels (`format_func` only; keys, defaults
  and stored values unchanged); three workflow tabs (Single run, Batch
  analysis, Scenario comparison) reading that one setup; a run shows its
  status, `market_section.render_market_overview` (headline figures and
  price chart) and then detail tabs (`render_market_details` and every
  other section, in their old order); an empty-state guide, a
  "setup changed since this run" note (`RUN_PARAMS_KEY`) and an AMM +
  whales warning before running; a compact header line instead of the
  large title; `style.TOP_LEGEND` for the three one-line-title chart
  builders. Rendered chart data is identical to Step 2's baseline. Batch
  and comparison stayed on Simulate, as tabs, by request.
- [x] Step 5 — layout polish: the headline figures sit in a wrapping row
  (`st.container(horizontal=True)`, available since the 1.53 floor) and
  no longer truncate at ~860px; the close price's delta, which repeated
  the Return figure, is gone; sections drawn in a detail tab leave out
  their own heading (`heading=False`), and the batch and comparison tabs
  draw none; follow-on caption notes moved word for word into a collapsed
  "Notes on these figures" expander (`dashboard/notes.py`); batch and
  comparison charts get short titles, with their disclosures as wrapping
  captions (`disclosure_in_title=False`; the builders' default output is
  unchanged). Chart trace data is identical to Step 4's. The ~70px under
  the navigation bar is left as is: no supported setting changes it.
- [x] Step 6 — responsive detail figures and mobile comparison: every
  fixed `st.columns` figure row in the detail and batch tabs now goes
  through `dashboard/metric_row.render_metric_row`, the same wrapping
  `st.container(horizontal=True)` row as the headline (which now uses
  it too). No label is cut short at ~860px with the sidebar open, and
  a 390px screen fits two or three figures per line. The comparison chart
  gets `compact=True` (`comparison_range_chart`'s default output is
  unchanged): a bottom, left-anchored legend (`BOTTOM_LEGEND`) with
  `LEGEND_ALLOWANCE` added height, and y-axis tick text with one compared
  dimension per line (`stacked_label`). Trace data, hover text and
  category order are unchanged. Every metric's label, value and order,
  every table, caption and chart trace are identical to Step 5's. The
  only rendered change is the comparison chart's height, legend and tick
  text. Checked in a browser at 390px (iframe), 860px with the sidebar
  open, and 1440px. The navigation gap is unchanged.
- [x] Step 7 — consistency pass: seven messages that told the reader to
  change a control still used the names from before Step 4 ("News
  events", "Psychology", "whale observation", "the run options"). They now
  name the sidebar's Run setup controls by their drawn labels: the events,
  tick-data, psychology, manipulation and whale messages, and the
  comparison plan's AMM + whales problem. The plan's "Held constant" line
  uses the same names, in sidebar order. All three run buttons share
  `RUN_ICON`. `tests/dashboard/test_dashboard_consistency.py` checks
  every quoted control name against the rendered sidebar's labels. Text
  and icons only: metrics, tables and chart traces are identical to
  Step 6's.

**Streamlit version floor (found in Steps 2–3, corrected after Step 3).**
The declared `streamlit>=1.38` was not accurate. Measured by running
`tests/dashboard`, `tests/visualization` and `tests/test_visualization.py`
against each Streamlit release in a disposable environment:

| Streamlit | Result |
|---|---|
| 1.38–1.48 | The app does not work: `width="stretch"` is rejected (175–176 failures) |
| 1.49–1.52 | The app works, but a stale trader/whale/event selection is not reset after a new run (3 `test_a_stale_selection_falls_back_to_the_overview` failures) |
| 1.53–1.62 | Every test passes except `tests/dashboard/test_view_comparison.py`, which imports `streamlit.testing.v1.errors` (added in 1.63) |
| 1.63 | Everything passes |

So the application needs **1.53** and the test suite **1.63**. Corrected
in a separate dependency-maintenance commit: `pyproject.toml` and
`requirements.txt` declare `streamlit>=1.53,<2.0`, and
`requirements-dev.txt` adds `streamlit>=1.63,<2.0` for test environments
(CI installs it). The test's import is unchanged.

---

**Out of scope, permanently:** live exchange APIs, real order routing,
real wallets/custody, real payment rails. If a future contributor
proposes any of these, it does not belong in this repository.
