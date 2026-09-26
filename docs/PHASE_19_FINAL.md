# Phase 19 — Realism / Feedback: Final Report

**Status: CLOSED.** Implementation commit
`7f9353b0b96c2e1f18fefc6468774b85660a0d6d`.

| | |
|---|---|
| Phase objective | Investigate behavioral feedback realism |
| Established | Individual behavioral responses to crowd information |
| Not established | Participant-to-participant propagation / herding |
| Disposition | Close the current architecture; defer a new multi-agent architecture to a future phase |

Phase 19 is neither a failure nor a success in establishing herding. Its
experiments narrowed the architecture and identified what is missing.

## 1. Objective

Determine whether the coin simulator can support genuine
participant-to-participant behavioral feedback: social influence,
herding, propagation, cascades, contagion, and market-wide amplification
caused by one participant group changing another's behavior. The phase
was not to claim any of these unless preregistered evidence established
it.

## 2. Experiments performed

The experiments used the 24-cell grid (the external-market pre-check used
its 12 AMM cells): {random walk, AMM} ×
psychology {off, on} × {events none, scheduled, random; conditions bull,
bear, meme}. Each cell ran 20 seeds (0, 10000, …, 190000), comparisons
were paired by seed, and pass/fail criteria were frozen before results.
The measurement harness and raw artifacts live outside the repository.

| Step | Question | Verdict |
|---|---|---|
| 1–3 | Baseline measurement; the lag-1 organic crowd-flow observable; what that observable predicts before anything reacts to it | Baseline: association exists, mostly price-mediated, and A1 already carries non-zero M5b |
| 4 | Momentum participation response to crowd flow | Participation up in 23/24 cells; herding metric M5b significant in 0/24, above 2× null floor in 0/24 |
| 7–8 | Retail directional crowd-flow tilt | **PARTIAL** (RW meets bar, AMM does not) |
| 9–10 | AMM architecture analysis | `corr(flow, return) ≈ 0.997` |
| — | AMM external-market variant pre-check (between Steps 10 and 12) | **Gate FAIL**; the planned experiment was not run |
| 12 | Breadth identifiability | **SUPPORTED** |
| 13–14 | Breadth-response pre-registration and implementation | Frozen and implemented (`7f9353b`) |
| 15 | Retail response to breadth | **PARTIAL** |
| 16 | Architecture review | Propagation unresolved |
| 17 | Others-only propagation | **FAIL** |
| 18 | Architecture and disposition review | Recommend CLOSE |

Pre-registration hashes (sha256):

- breadth identifiability: `b66a5d0e…abc728e`
- breadth response: `0062d69f…f25f35b89` (amendment 1 changed G1(ii)/G4 wording only)
- others-only propagation: `3ca00b6b…0700f458`
- external-market variant: `a568fa49…97394be`

## 3. Major mechanisms

All are opt-in, default off, and add no new RNG.

- **Crowd-flow observation** (`crowd_observation`). `MarketContext.crowd_flow`
  is the previous completed tick's organic flow as a signed fraction of
  supply. Wash legs, manipulator fills and whale trades are excluded.
- **Participation response** (`crowd_response`, `b12ce1d`). The engagement
  operator becomes
  `engage(p, u) = min(p·(1 + u·(1 − p)), nextafter(1, 0))`, where
  `u = min(CROWD_URGE_CAP, sensitivity · tanh(|flow| / CROWD_FLOW_SCALE))`.
  Only momentum is sensitive (0.5).
- **Directional crowd-flow response** (`crowd_direction`, `7f9353b`).
  Retail gets a bounded tilt
  `clamp(sensitivity · tanh(flow / CROWD_FLOW_SCALE), ±MAX_SHIFT)` at
  sensitivity 0.25.
- **Leave-self-out breadth** (`breadth_observation`, `7f9353b`).
  `b^-i = (n_buy^-i − n_sell^-i) / (n_buy^-i + n_sell^-i)` from the
  previous completed tick. It is delivered per trader to every
  news-responding trader.
- **Breadth response** (`breadth_response`, `7f9353b`). Retail only:
  `breadth_direction_tilt` at 0.25, applied as the outermost layer of
  news → psychology → crowd flow → breadth, all on the same draw.

## 4. Results

**Participation (Step 4).** The participation response is demonstrated.
Momentum participation rose in 23/24 cells, significant at seed level in
12. M5b moved by a median of +0.0035 against a baseline of about 0.09.
It was significant in 0/24 cells and above twice the null floor in 0/24.
This is not sufficient to establish herding.

**Directional crowd flow (Step 8).** RW M5b median +0.050: 12/12 cells
p < .01 and 12/12 above twice the null floor, which meets the bar. AMM
median +0.0049: 0/12 and 2/12, which does not meet the bar. Verdict
PARTIAL. No claim of market-wide herding.

**Breadth identifiability (Step 12).** Primary residual variance share
of `b_{t-1}` after the strict controls (C2): RW median 0.478
[0.241, 0.655], AMM median 0.442 [0.273, 0.646], 12/12 cells in each
mode. F1–F5 pass. Verdict SUPPORTED.

**Breadth response (Step 15)**, measured as
Δ partial_corr(a_t, b^-retail_{t-1} | CB), A2b − A1:

| Mode | C1 (Δ > 0, p < .01) | C2b (Δ > 2× null floor) | Median cell Δ | Bar |
|---|---|---|---|---|
| RW | 12/12 | 12/12 | +0.0673 | meets |
| AMM | 5/12 | 12/12 | +0.0699 | does not meet |

Verdict **PARTIAL**. The decision-level retail response is demonstrated
in both modes. The paired change in P(retail buys | b > 0) − P(retail
buys | b < 0) was positive in all 24 cells (+0.080 to +0.264).

**Others-only propagation (Step 17)**, measured as
Δ M17 = Δ partial_corr(a^-retail_t, b^-retail_{t-1} | CB), A2o − A1:

| Mode | C1 | C2 | Median cell Δ | Range |
|---|---|---|---|---|
| RW | 0/12 | 0/12 | +0.0017 | [−0.0062, +0.0062] |
| AMM | 0/12 | 1/12 | +0.0071 | [−0.0260, +0.0378] |

Verdict **FAIL** (F17.1). The per-class secondaries (momentum, dip
buyer, panic seller, long-term holder) and the execution-level
secondary show no cell with Δ > 0 at p < .01. Next-tick aggregate-flow
correlations are not evidence of propagation, because next-tick flow
includes retail itself responding to breadth.

**Provenance of Step 17.** Step 17 reused the deterministic Step 15
snapshot, seeds, ticks and configuration. Its runs reproduced Step 15
bit-for-bit (G7, 480/480 per arm). It is a preregistered endpoint
re-analysis of an existing deterministic experiment, not an independent
replication, and its p-values do not independently confirm Step 15. An
uncontrolled fill-level others-only contrast was inspected during
Step 16. The controlled decision-level endpoint and its per-cell and
per-class breakdowns were preregistered before they were computed.

## 5. Architecture findings

**Price loop.** Market state → price and price history → psychology
(derived from the price path), with news sentiment and attention
alongside → trader decisions → executed trades → price. In RW this last
step is GBM plus linear impact; in AMM it goes through the pool reserves.

**Breadth path.** Previous-tick fills → leave-self-out breadth → retail
tilt → retail fills → market state.

**Where propagation stops.** Momentum, dip-buyer, panic-seller and
long-term-holder traders read only price, price history, news and
psychology. Their breadth sensitivity is 0, and no non-retail strategy
reads `crowd_breadth` (verified as Step 17 gate G1). Retail's behavior
can therefore reach other classes only through price and market state.
That is ordinary price following, which the preregistered controls
largely remove. In the Step 15/17 configuration, no non-retail trader
consumes non-price information produced by another participant group.
The only other non-retail crowd reader, momentum's Step 4 participation
response to `crowd_flow`, was off in those arms and affects participation
only.

**AMM.** The pipeline is executed organic flow → AMM reserves → price,
with measured `corr(flow, return) ≈ 0.997`. The current AMM architecture
makes crowd-flow responses difficult to identify separately from
price-mediated behavior, because executed organic flow directly
determines pool price. This does not make every AMM experiment
impossible: leave-self-out breadth, a participation count rather than a
flow, stayed identifiable in AMM in Step 12.

The three phenomena are distinct:

- **Price following** (A acts → price moves → B reacts) is present.
- **Aggregate crowd response** (crowd breadth → D reacts) is
  demonstrated for retail only.
- **Genuine propagation / herding** (A changes B, B changes C, the
  aggregate amplifies) is not established.

## 6. Failed criteria

These stand as recorded and are not reinterpreted:

- Step 8: AMM primary bar, F1 FAIL, F2 TRIGGERED (price-mediated /
  volatility), F3 FAIL (one cell breach).
- Step 15: AMM primary bar (C1 5/12), F1 FAIL (the bar was not met in
  both modes), F6 FAIL.
- Step 17: F17.1 FAIL (primary) and F17.5 FAIL (the stabilizer rule,
  which is F6 reproduced).
- External-market pre-check: P1, P2, S1, S2, S3, S6 FAIL.

## 7. Safety / integrity findings

- **Steps 15 and 17:** 0 price, accounting or pool violations in 1440
  runs each. 0 containment breaches (1176 cell checks, 0 run-level). AMM
  A2/A1 realized-volatility ratio within [0.982, 1.057]. Phase 18
  psychology guards passed. A0 = A1 = `8bdc13e` in 480/480. Gates G1–G6
  (Step 15) and G1–G7 (Step 17) passed: no new RNG, no same-tick leakage,
  retail exclusion verified, and the external market absent.
- **F6 / F17.5 (future robustness task).** The frozen rule "no
  stabilizer's cell-mean net coin flow changes sign" failed for
  panic_seller in two RW cells:
  - RW psychology-off / random events: +1629.9 → −352.8
  - RW psychology-off / bull: −402.3 → +644.9

  Both A1 means sit close to zero relative to seed-to-seed variation:
  0.06 and 0.02 of the A1 standard deviation (≈ 26,200 and ≈ 23,900).
  One seed in 20 changed sign in each cell. There were no accounting,
  pool or containment violations, and the activity and fill-share
  clauses passed in every cell. The failure remains formally recorded.
  These magnitudes are a post-hoc description from saved Step 15 data,
  made during the Step 18 review. A future pre-registration may redesign
  the criterion, for example by requiring the A1 mean to be clearly
  away from zero before a sign change counts. The frozen rule was not
  changed.

## 8. External-market disposition

**Archived as a failed experimental prototype on branch
`experiment/phase19-amm-external-failed`.** The branch has the full note
at `docs/experiments/PHASE_19_AMM_EXTERNAL_MARKET.md`. The prototype is
not part of the supported simulator architecture.

- **Mechanism.** An external GBM reference price (coin volatility, event
  multiplier, no drift), arbitraged into the pool by a reserve-funded
  arbitrageur before traders act. AMM only; flag off by default.
- **Gate.** P1 required `corr(flow, return) ≤ 0.92` in every cell, and P2
  required residual flow variance after C_strict. S1–S7 covered realism,
  integrity and identity.
- **Result.**
  - P1 FAIL in 8/12 cells (corr 0.936–0.961).
  - P2 FAIL in 8/12 (residual share 0.06–0.12).
  - S1 and S3 FAIL in the meme cells: external flow 3.3× organic, 231
    reserve-capped trades, final price median 0.17.
  - S2 FAIL in 8/12.
  - S6 FAIL in 4/12.
  - S4, S5 and S7 PASS.
- **Why the experiment was not run and nothing was tuned.** The
  experiment was conditional on the gate. The mechanism had no free
  parameter by design, and any change would need a new pre-registration.
  The recorded structural analysis also shows that at the current pool
  depth (200k of 1M supply), P1 and S2 are jointly infeasible in the
  none and scheduled cells.
- **Why it was kept.** It is a documented negative result and the only
  implemented prototype of an independent value process. This does not
  show that every external or fundamental-value architecture would fail.

## 9. Final scientific conclusion

> Phase 19 established a bounded crowd-flow participation response and a
> bounded, decision-level retail directional response to leave-self-out
> participation breadth. Breadth retained identifiable variation after the
> preregistered price/path controls. However, the breadth response did not
> propagate to non-retail trader types under the preregistered Step 17
> others-only test. Therefore participant-to-participant propagation,
> herding, cascades, and market-wide behavioral amplification were not
> established.

**NOT ESTABLISHED:**

- participant-to-participant propagation
- multi-agent herding
- cascades
- contagion
- market-wide behavioral amplification
- a validated independent-value AMM process

**NOT CLAIMED:**

- that the retail breadth response is equivalent to herding
- that Step 17's null proves propagation is impossible in all architectures
- that AMM realism is fundamentally impossible

## 10. Deferred future architecture

These are open questions for a future phase. None is an active task, and
each needs its own pre-registration.

- **Non-retail independent observer signal.** A second observer class
  that reads a non-price, leave-self-out (or leave-class-out), anonymous
  crowd signal. Without one, propagation cannot be identified.
- **Independent / fundamental value process for AMM identification.**
  This is a redesign, likely involving pool depth. It is not a retune of
  the archived prototype.
- **Possible dynamic-liquidity / LP architecture,** where market depth
  responds to behavior.
- **Future cascade experiments** (A → B → C). These need the observer
  class first.
- **Other candidates reviewed in Step 18:** participant-composition
  signals, magnitude (size) responses, and pre-execution intent signals.
  An intent signal would break the no-same-tick-leakage invariant.
- **Stabilizer criterion redesign** (section 7).
- **The psychology saturation shape** Phase 18 deferred to Phase 19.
  Phase 19 did not address it.

## 11. Limitations

- Step 17 is a deterministic re-analysis of Step 15, not an independent
  replication.
- AMM flow/price near-collinearity limits every AMM result.
- Step 15 AMM missed its frozen bar, and Step 15 F1 and F6 failed.
- Step 17 F17.1 and F17.5 failed.
- Long-term-holder data are sparse. Its per-class partial correlation
  was defined in only 100/240 RW runs (≈ 25 decision rows per run) and
  5/240 AMM runs, so class-level long-term-holder conclusions are
  uninformative.
- Endpoints use decisions and fills; unmeasured intent cannot be
  inferred.
- A retail-only response cannot support a herding claim.
- The architectural explanation of the Step 17 null is analytical. It
  holds to the extent that the control set spans non-retail traders'
  inputs, and that was not separately measured.
- The measurement harness, pre-registrations and raw artifacts are kept
  outside this repository.

## 12. Final commit

- Implementation: `7f9353b0b96c2e1f18fefc6468774b85660a0d6d`, which
  builds on `b12ce1d` (participation response).
- Closeout: the documentation-only commit that adds this file.
- Archived failed prototype: branch `experiment/phase19-amm-external-failed`.
