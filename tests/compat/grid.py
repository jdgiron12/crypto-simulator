"""Compatibility digest grid (Phase 9, Step 0). Developer/test tooling only.

Runs fixed, seeded simulations and reduces each to a short SHA-256 digest
of everything the run produced. The digests are pinned in
``pinned_digests.json``; ``tests/compat/test_compat_grid.py`` checks the
working tree against them, and ``scripts/compat/compare_checkpoints.py``
checks any git ref against them.

**Levels.** Each Phase 8 checkpoint added whale features. The grid for
level ``L`` uses only the features that existed at checkpoint ``L``, so
the same grid can run against that checkpoint and against every later
one. Every checkpoint at level ``L`` or later must reproduce the pinned
digests of every level up to ``L`` — the disabled-feature compatibility
Phase 8 promised at each step.

This module imports nothing but the standard library and the package
under test (resolved from ``sys.path``, which is how the comparison tool
points it at an archived checkpoint). Nothing in the package imports it.
Timestamps are excluded from every digest: they are wall-clock stamped.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import io
import os
import random
import runpy
import sys
from pathlib import Path

REFERENCE = "b5a5f87f6b383ebd0a28ddbd8d5851a5155f4716"

# level: (checkpoint, what that level adds)
LEVELS = {
    0: ("aa213a8", "pre-Phase 8: unfunded whales only"),
    1: ("187b901", "funding, behavior, min_trade_fraction, cooldown"),
    2: ("1dca548", "target allocation"),
    3: ("c47b913", "minimum trade interval"),
    4: ("b593fb3", "explicit behavior transitions"),
    5: ("7557aa0", "intent strength"),
    6: ("ca78e62", "behavior cycles"),
    7: ("649bdee", "whale observation"),
    8: ("b5a5f87", "whale cohorts"),
}

FINGERPRINTS = {"random_walk": "d1218e0e0739f776", "amm": "f853009b5818169e"}

# (flags, minimum level whose CLI prints the same output for them)
CLI_RUNS = (
    (("--ticks", "30"), 0),
    (("--ticks", "30", "--no-traders"), 0),
    (("--ticks", "30", "--no-whales"), 0),
    (("--ticks", "40", "--scenario", "pump_and_dump"), 0),
    (("--ticks", "40", "--scenario", "wash_trading"), 0),
    (("--ticks", "30", "--events"), 0),
    (("--ticks", "30", "--random-events"), 0),
    (("--ticks", "30", "--psychology"), 0),
    (("--ticks", "30", "--events", "--random-events", "--psychology", "--scenario", "pump_and_dump"), 0),
    (("--ticks", "25", "--pricing-mode", "amm", "--no-whales"), 0),
    (("--ticks", "40", "--pricing-mode", "amm", "--no-whales", "--scenario", "pump_and_dump", "--psychology"), 0),
    (("--ticks", "25", "--pricing-mode", "amm", "--no-whales", "--events", "--random-events"), 0),
    (("--ticks", "30", "--whale-observation"), 7),
    (("--ticks", "30", "--events", "--psychology", "--whale-observation"), 7),
)

QUICK_CASES, QUICK_TICKS = 12, 100
SUPPLY = 1_000_000.0
BEHAVIORS = ("neutral", "accumulate", "distribute")


def _package():
    import crypto_simulator

    return crypto_simulator


def _settings():
    """The default configuration, read straight from the YAML file so
    ``CRYPTOSIM_*`` environment overrides cannot leak into a digest."""
    import yaml
    from crypto_simulator.config.settings import DEFAULT_CONFIG_PATH, build_settings

    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as handle:
        return build_settings(yaml.safe_load(handle), DEFAULT_CONFIG_PATH)


def _norm(value, keep_cohort):
    """Dataclasses as (name, value) pairs, recursively. ``cohort_id`` is
    dropped below level 8, where ``WhaleObservation`` did not have it."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return (type(value).__name__,) + tuple(
            (f.name, _norm(getattr(value, f.name), keep_cohort))
            for f in dataclasses.fields(value) if keep_cohort or f.name != "cohort_id")
    if isinstance(value, (list, tuple)):
        return tuple(_norm(v, keep_cohort) for v in value)
    return repr(value)


def _digest(view) -> str:
    return hashlib.sha256(repr(view).encode()).hexdigest()[:16]


def run_digest(sim, ticks: int, level: int, transitions=None) -> str:
    """Everything a run produced, as far as ``level`` can express it."""
    out = []
    for t in range(1, ticks + 1):
        for whale_index, behavior in (transitions or {}).get(t, ()):
            whale = sim.whales[whale_index]
            if whale.wallet is not None and getattr(whale, "cycle", None) is None:
                whale.set_behavior(behavior)
        out.append(sim.step())
    whales = []
    for w in sim.whales:
        row = [w.whale_id, w.holdings, w._rng.getstate()]
        if level >= 1:
            row += [w.state(), None if w.wallet is None else (w.wallet.cash, w.wallet.coins, w.wallet.average_cost)]
        if level >= 3:
            row.append(w.interval_remaining)
        if level >= 5:
            row.append(w.intent_strength)
        if level >= 6:
            row.append(w.cycle_state())
        whales.append(tuple(row))
    view = [[(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.pool_state,
              t.event_state, t.psychology) for t in out],
            whales,
            [(tr.trader_id, tr.wallet.cash, tr.wallet.coins, tr.wallet.average_cost) for tr in sim.traders],
            (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals(),
            sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate()]
    if level >= 7:
        view.append(_norm([t.whale_observations for t in out], keep_cohort=level >= 8))
    return _digest(view)


def builder_fingerprint(sim) -> str:
    """The Phase 7 builder fingerprint, computed exactly as
    ``tests/core/test_coin_simulator_psychology._builder_fingerprint``."""
    ticks = sim.run(200)
    view = [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades,
             [(f.trader_id, f.side.value, f.requested_quantity, f.quantity, f.price, f.notional, f.reason)
              for f in t.trader_trades],
             t.pool_state) for t in ticks]
    view.append([(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders])
    view.append((sim.reserve.cash, sim.reserve.coins, sim.accounting_totals()))
    return _digest(view)


# --- world generation -----------------------------------------------------------------------------


def _cycle(g):
    phases = [{"behavior": g.choice(BEHAVIORS), "duration": g.randint(1, 12)} for _ in range(g.randint(1, 4))]
    if all(p["behavior"] == "neutral" for p in phases):
        phases[0]["behavior"] = g.choice(("accumulate", "distribute"))
    return phases


def _whale(g, i, level):
    from crypto_simulator.core.whale import Whale

    kw = dict(activity_probability=round(g.uniform(0.05, 1.0), 3), max_trade_fraction=round(g.uniform(0.001, 0.03), 4),
              impact_coefficient=round(g.uniform(0.0, 3.0), 2), seed=g.randint(0, 10_000))
    coins = round(g.uniform(0.0, 60_000.0), 1)
    if level == 0 or g.random() < 0.25:
        return Whale(f"w{i}", coins, **kw), False
    kw["cooldown_ticks"] = g.choice((0, 0, 1, 3))
    if g.random() < 0.3:
        return Whale(f"w{i}", coins, **kw), False
    kw["starting_cash"] = round(g.uniform(0.0, 300_000.0), 1)
    kw["min_trade_fraction"] = round(kw["max_trade_fraction"] * g.choice((0.0, 0.0, 0.3, 1.0)), 6)
    behavior = g.choice(BEHAVIORS)
    kw["behavior"] = behavior
    cycle = _cycle(g) if level >= 6 and g.random() < 0.35 else None
    if cycle is not None:
        kw["cycle"] = cycle
    if level >= 2 and g.random() < 0.5 and (behavior != "neutral" or cycle is not None):
        kw["target_coin_fraction"] = round(g.uniform(0.0, 1.0), 3)
    if level >= 3:
        kw["min_trade_interval_ticks"] = g.choice((0, 0, 2, 5))
    if level >= 5:
        kw["intent_strength"] = g.choice((1.0, 1.0, 0.0, 0.5, 1.5, 2.0))
    cohort_eligible = level >= 8 and cycle is None and g.random() < 0.5
    return Whale(f"w{i}", coins, **kw), cohort_eligible


def _traders(g, kind):
    from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
    from crypto_simulator.core.traders.strategies import (
        DipBuyer, LongTermHolder, MomentumTrader, PanicSeller, RetailTrader)

    if kind == 0:
        return []
    base = g.randint(0, 10_000)

    def common(i, cash, coins, prob, size, risk):
        return dict(starting_cash=cash, starting_coins=coins, trade_probability=prob, max_trade_size=size,
                    risk_tolerance=risk, seed=base + i)

    out = [RetailTrader("retail", **common(0, 5_000.0, 5_000.0, 0.6, 2_000.0, 0.3)),
           MomentumTrader("momentum", **common(1, 5_000.0, 5_000.0, 0.7, 2_000.0, 0.5)),
           DipBuyer("dip", **common(2, 8_000.0, 2_000.0, 0.7, 2_000.0, 0.5)),
           PanicSeller("panic", **common(3, 3_000.0, 8_000.0, 0.8, 3_000.0, 0.2)),
           LongTermHolder("lth", **common(4, 5_000.0, 5_000.0, 0.3, 1_000.0, 0.5))]
    if kind == 2:
        out += [PumpAndDump("pump", **common(5, 50_000.0, 0.0, 1.0, 5_000.0, 0.5)),
                WashTrader("wash", **common(6, 20_000.0, 20_000.0, 1.0, 2_000.0, 0.5))]
    return out


def _market(g):
    from crypto_simulator.core.events import EventEngine, MarketEvent
    from crypto_simulator.core.events.generator import RandomEventGenerator

    mode, extras = g.randint(0, 3), {}
    if mode >= 1:
        extras["events"] = EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8,
                                                    sentiment=g.choice((-0.7, 0.6)), volatility_boost=1.0,
                                                    attention=1.0, start_tick=g.randint(1, 30), duration=20)])
    if mode >= 2:
        extras["psychology"] = True
    if mode >= 3:
        extras["event_generator"] = RandomEventGenerator(probability=0.1, seed=g.randint(0, 999))
    return extras


def level_group(level: int, cases: int = QUICK_CASES, ticks: int = QUICK_TICKS) -> dict[str, str]:
    """Random worlds using exactly the features available at ``level``."""
    from crypto_simulator.core.coin_simulator import CoinSimulator
    from crypto_simulator.models.coin import Coin

    g = random.Random(20260915 + level)
    digests = {}
    for case in range(cases):
        drawn = [_whale(g, i, level) for i in range(g.randint(0, 6))]
        whales = [w for w, _ in drawn]
        kind = g.choice((0, 1, 1, 2))
        traders = _traders(g, kind)
        extras = _market(g)
        if level >= 7 and g.random() < 0.5:
            extras["whale_observation"] = True
        if level >= 8:
            from crypto_simulator.core.whale_cohort import WhaleCohort

            members = [w.whale_id for w, eligible in drawn if eligible]
            if members:
                n = min(len(members), g.randint(1, 2))
                extras["whale_cohorts"] = [WhaleCohort(f"c{j}", _cycle(g), tuple(members[j::n])) for j in range(n)]
        transitions = {}
        if level >= 4 and whales:
            for _ in range(g.randint(0, 5)):
                transitions.setdefault(g.randint(1, ticks), []).append((g.randrange(len(whales)), g.choice(BEHAVIORS)))
        seed = g.randint(0, 10_000)
        reserve_cash = g.choice((None, 500_000.0))
        name = f"L{level}-{case:02d}-w{len(whales)}-t{kind}"
        try:
            sim = CoinSimulator(Coin("FIC", "FictiCoin (Simulated)", SUPPLY, 2.0), seed=seed, whales=whales,
                                traders=traders, reserve_cash=reserve_cash, **extras)
            digests[name] = run_digest(sim, ticks, level, transitions)
        except Exception as exc:  # recorded, so a changed error shows as a changed digest
            digests[name] = f"ERR {type(exc).__name__}: {exc}"
    return digests


def common_group(level: int, ticks: int = QUICK_TICKS) -> dict[str, str]:
    """Builder runs in both pricing modes, plus directly built AMM worlds
    with traders, manipulators, news and psychology. Observation variants
    need level 7.

    The digest view is fixed per case — level 0 for plain runs (the
    default builder whale is unfunded, so nothing later is needed) and
    level 7 for observed ones — so a case's digest is the same whichever
    checkpoint computes it."""
    from crypto_simulator.core.coin_simulator import CoinSimulator
    from crypto_simulator.models.coin import Coin
    from crypto_simulator.services.coin_simulation import build_coin_simulator

    settings = _settings()
    digests = {}
    for mode in ("random_walk", "amm"):
        for scenario in (None, "pump_and_dump", "wash_trading"):
            for psychology in (False, True):
                for observed in ((False, True) if level >= 7 and mode == "random_walk" else (False,)):
                    kw = dict(pricing_mode=mode, scenario=scenario, psychology=psychology)
                    if mode == "amm":
                        kw["include_whales"] = False
                    if observed:
                        kw["whale_observation"] = True
                    name = f"builder-{mode}-{scenario}-p{int(psychology)}" + ("-observed" if observed else "")
                    digests[name] = run_digest(build_coin_simulator(settings, **kw), ticks, 7 if observed else 0)
    g = random.Random(4242)
    for case in range(6):
        traders, extras = _traders(g, g.choice((1, 2))), _market(g)
        sim = CoinSimulator(Coin("FIC", "FictiCoin (Simulated)", SUPPLY, 2.0), seed=g.randint(0, 10_000),
                            traders=traders, reserve_cash=2_000_000.0, pricing_mode="amm", **extras)
        digests[f"amm-{case:02d}"] = run_digest(sim, ticks, 0)
    return digests


def fingerprints() -> dict[str, str]:
    from crypto_simulator.services.coin_simulation import build_coin_simulator

    settings = _settings()
    return {mode: builder_fingerprint(build_coin_simulator(settings, pricing_mode=mode,
                                                           include_whales=mode == "random_walk"))
            for mode in ("random_walk", "amm")}


def cli_digests(script: Path, level: int) -> dict[str, str]:
    """Run the demo CLI in-process for every flag set ``level`` supports
    and digest its output. ``CRYPTOSIM_*`` overrides are removed first."""
    from crypto_simulator.config.settings import clear_settings_cache

    saved_env = {k: v for k, v in os.environ.items() if k.startswith("CRYPTOSIM_")}
    saved_argv = sys.argv
    digests = {}
    try:
        for key in saved_env:
            del os.environ[key]
        for flags, min_level in CLI_RUNS:
            if level < min_level:
                continue
            clear_settings_cache()
            buffer = io.StringIO()
            sys.argv = [str(script), *flags]
            with contextlib.redirect_stdout(buffer):
                runpy.run_path(str(script), run_name="__main__")
            digests[" ".join(flags)] = hashlib.sha256(buffer.getvalue().encode()).hexdigest()[:16]
    finally:
        sys.argv = saved_argv
        os.environ.update(saved_env)
        clear_settings_cache()
    return digests


#: Deliberate behaviour changes that moved pinned digests, newest last.
#:
#: A checkpoint's source is compared against the digests *its own code*
#: should produce, so an intentional change has to be recorded rather
#: than pinned over. Each entry names a calibration and says how to tell,
#: from the source alone, whether it is present — no commit hashes, so a
#: ref can be checked without knowing where it sits in history.
#:
#: ``pinned_digests.json`` carries the *superseded* digests for each of
#: these under ``calibrations``; source without the calibration is
#: compared against those, source with it against the main pins.
CALIBRATIONS = {
    # Phase 18: momentum is divided by its own horizon's scale
    # (PRICE_MOVE_SCALE * sqrt(SIGNAL_WINDOW - 1)) instead of by the
    # one-interval PRICE_MOVE_SCALE. Only psychology-enabled runs move.
    "psychology-momentum-horizon": lambda: hasattr(
        _package_module("core.psychology.signals"), "MOMENTUM_SCALE"
    ),
}


def _package_module(dotted: str):
    import importlib

    return importlib.import_module(f"{_package().__name__}.{dotted}")


def calibrations() -> list[str]:
    """The calibrations the source under test implements, in order.

    Read from the source itself, so an archived checkpoint reports what
    it actually has rather than what its date implies.
    """
    present = []
    for name, is_present in CALIBRATIONS.items():
        try:
            if is_present():
                present.append(name)
        except (ImportError, AttributeError):
            pass  # a checkpoint predating the module simply lacks it
    return present


def compute(level: int, script: Path | None = None) -> dict:
    """Every group a checkpoint at ``level`` can run, as one JSON-ready dict."""
    return {
        "package": str(Path(_package().__file__).parent),
        "calibrations": calibrations(),
        "levels": {str(lv): level_group(lv) for lv in range(level + 1)},
        "common": common_group(level),
        "fingerprints": fingerprints(),
        "cli": cli_digests(script, level) if script is not None else {},
    }
