"""``Whale``: a large coin holder capable of moving price with one trade.

Phase 1's ``CoinSimulator`` drives price purely through ``MarketEngine``'s
random walk — nothing represents an actor whose trade size, relative to
total supply, is large enough to move price on its own. This adds exactly
that: on ticks it decides to act, a whale buys or sells a random fraction
of total supply and the resulting trade size determines a multiplicative
price-impact factor.

Deliberately minimal: no order book, no liquidity-depth curve — a plain
linear impact model (``impact = 1 + impact_coefficient * fraction_of_supply``).

Two kinds of whale (Phase 8, Step 1):

- **Unfunded** (the default, and the original behavior): holds coins only
  and trades against assumed external liquidity. Its buys are uncapped
  and its sells are capped at its holdings; it is outside the simulator's
  conserved accounting.
- **Funded** (``starting_cash`` given): holds a ``Wallet`` of cash and coins
  and settles every trade against the market reserve with the same
  clamp-and-transfer code traders use (``settle_against_reserve``), so it
  never creates or destroys coins or cash.

A funded whale also has a persistent ``WhaleBehavior``:

- ``NEUTRAL``: buys or sells at random when active, as unfunded whales do.
- ``ACCUMULATE``: buys when active; ``DISTRIBUTE``: sells when active.

**Target allocation** (Phase 8, Step 2). With a ``target_coin_fraction``,
an accumulating or distributing whale manages toward that share of its
portfolio value. Marked at the tick's trade price:

    portfolio_value = cash + coins * price
    coin_fraction   = coins * price / portfolio_value
    allocation_gap  = target_coin_fraction - coin_fraction

A positive gap means underweight coins, a negative gap overweight.
``Whale.allocation(price)`` returns all three on a ``WhaleAllocation``.

Each active tick the whale closes part of that gap, never all of it by
rule and never more than it has:

- The **behavior fixes the direction** — an accumulator only ever buys, a
  distributor only ever sells. A target can stop a whale, never reverse
  it, so an accumulator sitting above its target simply holds rather than
  selling back down to it (and a distributor below its target holds).
- The trade is **bounded**: the drawn size (uniform in
  [``min_trade_fraction``, ``max_trade_fraction``] x supply), then capped
  at the coins that exactly reach the target, then clamped by
  ``settle_against_reserve`` to the whale's cash or coins and the
  reserve's. Each clamp only shrinks the fill, so the whale approaches the
  target from one side and **never crosses it**. The target cap can size a
  fill below ``min_trade_fraction`` on the last leg: crossing the target
  would be the worse failure, so the cap wins.
- A **dead zone** (``TARGET_DEAD_ZONE``) ends the approach: once the
  remaining gap is within it the whale holds instead of trading dust
  forever against float residue.

These are ordinary portfolio-management intents, not manipulation (that is
``core/traders/manipulation.py``), and whales read no news or psychology.

A behavior is a persistent *state*, not a one-off choice: a funded whale
can be moved between the three with ``set_behavior`` (Phase 8, Step 4).
Every transition among them is allowed, it is always explicit — nothing in
this module ever changes a whale's behavior on its own — and it changes
only the state. Balances, target, pacing counters and the RNG stream all
carry straight through, so a whale that goes accumulate → neutral →
accumulate resumes exactly where it left off. A target is dormant while
the whale is neutral (it belongs to the directional behaviors) rather than
discarded.

**Observation** (Phase 8, Step 7). ``observe`` and
``complete_observation`` produce a frozen ``WhaleObservation`` describing
one whale on one tick — the behavior, intent and cycle phase in force, the
price its settlement used, its allocation either side, whether pacing was
blocking it, and what it filled. Both are pure reads: they place no trade,
move no balance and draw no randomness. ``CoinSimulator`` calls them only
when built with ``whale_observation=True``.

**Accumulation / distribution cycles** (Phase 8, Step 6). An optional
``cycle`` turns a funded whale's behavior into a repeating timetable —
accumulate for a while, stand down, distribute, stand down, repeat. It is
a *clock*, not a judgement: phases and their durations are fixed up front,
and the whale never infers where it is in the cycle from price, returns,
volume, news, psychology or profit. Off by default; a whale without one is
exactly what it was at Step 5.

**Intent strength** (Phase 8, Step 5). ``intent_strength`` scales how
hard a *directional* whale pushes: it multiplies the size drawn for a
trade, so 0.5 is a whale leaning half as hard as usual, 2.0 twice as
hard, and 0.0 no directional pressure at all (it requests nothing and so
never fills). The default 1.0 multiplies by one and is exactly the
behavior of every earlier step.

It changes only the *requested* size. Everything downstream still binds:
the target cap, the whale's cash and coins, and the reserve all clamp the
fill afterwards, so strong intent cannot cross a target, overdraw a
wallet or drain a reserve — it only asks for more, sooner. ``NEUTRAL``
ignores it entirely (a whale trading both sides has no direction to
press), which also makes it inert for every unfunded whale, since those
are always neutral. It is kept across behavior transitions, dormant while
neutral and back in force when the whale is directional again.

Intent strength is a *setting*, not a reaction: nothing adjusts it
automatically, and it reads no price, news, psychology or market state.

**Trade scheduling / patience** (Phase 8, Step 3). Two independent,
opt-in pacing counters keep a whale out of the market after it trades:

- ``cooldown_ticks`` (Step 1): applies to *any* whale, funded or not, and
  starts after any trade that moved coins.
- ``min_trade_interval_ticks`` (Step 3): funded whales only — the minimum
  number of ticks to wait between successful trades. It models a large
  participant pacing its execution, spacing out meaningful portfolio
  adjustments instead of trading at every opportunity. It is *not*
  psychology: it reads no price, news, sentiment or market state at all,
  only its own tick counter.

Both count the same way. A trade at tick ``T`` with a setting of ``N``
blocks exactly the next ``N`` ticks, so the earliest next eligible tick is
``T + N + 1`` (``N = 0`` blocks nothing). They do not replace one another:
the whale is eligible only when *both* have expired, so the effective wait
is the longer of the two. Only a trade that actually moved coins starts
either counter — an inactive tick, a blocked tick, a target already
reached, a dead-zone hold, and a fill that clamps to nothing all leave
both untouched.

Randomness: one private ``random.Random(seed)`` stream per whale. Each
eligible tick draws the activity check, and on active ticks a side and a
size, in that order, whatever the behavior — the behavior decides the
direction, never the draws. After a trade that moved coins, a
``cooldown_ticks`` counter keeps the whale out for that many ticks, during
which it draws nothing, and a whale waiting out its minimum trade
interval draws nothing either — both counters are checked before the
activity draw. Target allocation adds no randomness at all: the
gap, the dead-zone test and the size cap are deterministic arithmetic on
the balances and the price, applied after the draws. With the defaults
(``cooldown_ticks`` 0, ``min_trade_interval_ticks`` 0,
``min_trade_fraction`` 0, unfunded) every draw and trade is exactly what
it was before.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum

from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import settle_against_reserve
from crypto_simulator.models.wallet import Wallet


class WhaleAttempt(str, Enum):
    """What the execution path did on one tick (Phase 8, Step 7).

    Recorded as a fact by the code that took each branch, rather than
    inferred afterwards from balances — the two are not the same, because
    a whale whose activity check passed can still fill nothing when the
    reserve is exhausted.

    - ``BLOCKED``: a cooldown or trade interval kept it out; no draw taken.
    - ``INACTIVE``: eligible, but the activity check said no this tick.
    - ``HELD``: eligible and active, but its target left nothing to do
      (inside the dead zone, or the target lay the other way).
    - ``NO_FILL``: eligible and active, reached settlement, and the fill
      clamped to nothing — no cash, no coins, or an exhausted reserve.
    - ``FILLED``: coins actually moved.

    Observation-only: nothing in the whale's own logic reads it, and
    setting it changes no balance, no return value and no randomness.
    """

    BLOCKED = "blocked"
    INACTIVE = "inactive"
    HELD = "held"
    NO_FILL = "no_fill"
    FILLED = "filled"


class WhaleBehavior(str, Enum):
    NEUTRAL = "neutral"
    ACCUMULATE = "accumulate"
    DISTRIBUTE = "distribute"


@dataclass(frozen=True)
class WhaleTrade:
    """One whale's trade for a single tick."""

    whale_id: str
    side: str
    quantity: float
    price_impact: float


@dataclass(frozen=True)
class WhaleState:
    """A snapshot of a whale's persistent state. ``cash`` is ``None`` for an
    unfunded whale; ``cooldown_remaining`` is the number of upcoming ticks
    it will sit out."""

    whale_id: str
    behavior: WhaleBehavior
    funded: bool
    cash: float | None
    coins: float
    target_coin_fraction: float | None
    cooldown_remaining: int


TARGET_DEAD_ZONE = 1e-9
"""How close to ``target_coin_fraction`` counts as reached (Phase 8, Step 2).

An allocation gap at or inside this many parts of portfolio value — one
part per billion — ends the approach: the whale holds instead of trading.
Without it a whale would keep filing dust trades forever, each one burning
a cooldown and nudging price, because float residue leaves the gap
minutely nonzero after the trade that "reaches" the target.

It is a gap threshold, not a size threshold, and deliberately *not*
``min_trade_fraction``: a whale whose smallest configured trade is larger
than its whole gap must still be able to close that gap (sized down — see
``_funded_trade``), not sit out forever. One part per billion of portfolio
value is economically nothing while still sitting ~7 orders of magnitude
above double-precision epsilon, so it absorbs accumulated float error
without ever masking a real allocation decision.
"""


@dataclass(frozen=True)
class WhaleAllocation:
    """A funded whale's portfolio marked at one price (Phase 8, Step 2).

    ``coin_fraction`` is the share of ``portfolio_value`` held in coins and
    ``allocation_gap`` is ``target_coin_fraction - coin_fraction``:
    positive means underweight coins, negative overweight, and
    ``at_target`` reports whether it is inside ``TARGET_DEAD_ZONE``.
    ``target_coin_fraction``, ``allocation_gap`` and ``target_coins`` are
    ``None`` for a whale with no target.

    A portfolio worth nothing (no cash, no coins) has no meaningful
    composition; ``coin_fraction`` is 0.0 there by convention.
    """

    price: float
    portfolio_value: float
    coin_value: float
    coin_fraction: float
    target_coin_fraction: float | None
    allocation_gap: float | None
    target_coins: float | None

    @property
    def at_target(self) -> bool:
        """Whether no target-driven trade is due: no target, or a gap
        inside the dead zone in either direction."""
        return self.allocation_gap is None or abs(self.allocation_gap) <= TARGET_DEAD_ZONE


def _require_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")


def _require_fraction(name: str, value: object) -> None:
    _require_number(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1] (got {value!r})")


@dataclass(frozen=True)
class WhalePhase:
    """One leg of a ``WhaleCycle``: a behavior held for ``duration`` ticks."""

    behavior: WhaleBehavior
    duration: int


@dataclass(frozen=True)
class WhaleCycle:
    """A whale's repeating behavior timetable (Phase 8, Step 6).

    Immutable, and validated once at construction: at least one phase,
    each with a known behavior and a duration of at least one tick. The
    phases run in order and the cycle restarts when the last one expires.
    """

    phases: tuple[WhalePhase, ...]

    @property
    def total_ticks(self) -> int:
        """Ticks in one full pass through the cycle."""
        return sum(phase.duration for phase in self.phases)


@dataclass(frozen=True)
class WhaleObservation:
    """What one whale did on one tick (Phase 8, Step 7).

    A read-only record, produced only when a simulation runs with
    ``whale_observation=True``. It describes; it never feeds back.

    ``price`` is the price this whale's settlement actually used — the
    running price it was offered, before any later whale moved it — so a
    fill is always described at the price it happened at. ``behavior``,
    ``intent_strength`` and the cycle fields are what was in force for the
    tick. ``cooldown_remaining`` and ``interval_remaining`` are the counts
    *before* the tick, which is what says whether the whale was blocked.
    ``trade`` is ``None`` on a tick the whale did not fill, and
    ``attempt`` says *why* — whether it was blocked, never tried, was held
    by its target, or tried and filled nothing. That is recorded by the
    execution path itself, not reconstructed from the balances.

    An unfunded whale has no wallet, so ``allocation_before``,
    ``allocation_after`` and ``cash`` are ``None`` for it — never a
    stand-in zero.

    ``cohort_id`` (Phase 8, Step 8) names the cohort the whale follows, or
    is ``None`` for a whale outside every cohort. A member has no personal
    cycle, so for it the cycle fields report the cohort's phase — the one
    in force. The label is added by the simulation (see
    ``core/whale_cohort.py``); nothing in the simulation reads it back.
    """

    whale_id: str
    funded: bool
    behavior: WhaleBehavior
    intent_strength: float
    cycle_phase_index: int | None
    cycle_phase_elapsed: int | None
    price: float
    allocation_before: WhaleAllocation | None
    allocation_after: WhaleAllocation | None
    cooldown_remaining: int
    interval_remaining: int
    trade: WhaleTrade | None
    attempt: WhaleAttempt
    cash: float | None
    coins: float
    cohort_id: str | None = None


@dataclass(frozen=True)
class _WhaleSnapshot:
    """The half of a ``WhaleObservation`` that must be read *before* the
    whale trades. Internal to the observation path."""

    whale_id: str
    funded: bool
    behavior: WhaleBehavior
    intent_strength: float
    cycle_phase_index: int | None
    cycle_phase_elapsed: int | None
    price: float
    allocation_before: WhaleAllocation | None
    cooldown_remaining: int
    interval_remaining: int


@dataclass(frozen=True)
class WhaleCycleState:
    """Where a whale is in its cycle (Phase 8, Step 6).

    ``configured`` is False for a whale without one, and then every other
    field is ``None``/0. ``cycle`` is the immutable definition itself, so
    a caller can read the timetable without reaching into the whale.
    """

    configured: bool
    phase_index: int
    behavior: WhaleBehavior | None
    phase_elapsed: int
    phase_duration: int | None
    cycle: WhaleCycle | None


INTENT_STRENGTH_MIN = 0.0
INTENT_STRENGTH_MAX = 2.0
INTENT_STRENGTH_DEFAULT = 1.0
"""Bounds on ``intent_strength`` (Phase 8, Step 5).

0.0 is no directional pressure, 1.0 the ordinary pressure every earlier
step had, and 2.0 the strongest a whale may be configured to lean. The
ceiling is a guard rail rather than an economic claim: without one, an
arbitrarily large multiplier would make the drawn size meaningless, since
the fill would then be decided entirely by the target cap and the
reserve. Values outside the range are rejected, never clamped.
"""


def _require_intent_strength(value: object) -> None:
    _require_number("intent_strength", value)
    if not INTENT_STRENGTH_MIN <= value <= INTENT_STRENGTH_MAX:
        raise ValueError(
            f"intent_strength must be within [{INTENT_STRENGTH_MIN}, {INTENT_STRENGTH_MAX}] (got {value!r})"
        )


def _coerce_phase(index: int, phase: object) -> WhalePhase:
    """One validated ``WhalePhase`` from a ``WhalePhase`` or a mapping with
    ``behavior`` and ``duration`` keys (the configuration shape)."""
    if isinstance(phase, WhalePhase):
        behavior, duration = phase.behavior, phase.duration
    elif isinstance(phase, dict):
        unknown = set(phase) - {"behavior", "duration"}
        if unknown:
            raise ValueError(
                f"cycle phase {index} has unknown key(s) {sorted(unknown)}; expected behavior and duration"
            )
        if "behavior" not in phase or "duration" not in phase:
            raise ValueError(f"cycle phase {index} needs both a behavior and a duration (got {phase!r})")
        behavior, duration = phase["behavior"], phase["duration"]
    else:
        raise ValueError(
            f"cycle phase {index} must be a dict with behavior and duration, or a WhalePhase "
            f"(got {phase!r})"
        )
    try:
        behavior = _coerce_behavior(behavior)
    except ValueError as error:
        raise ValueError(f"cycle phase {index}: {error}") from None
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
        raise ValueError(
            f"cycle phase {index} duration must be an integer >= 1 (got {duration!r})"
        )
    return WhalePhase(behavior, duration)


def _coerce_cycle(cycle: object) -> WhaleCycle | None:
    """A validated ``WhaleCycle``, or ``None`` when no cycle is configured.

    Accepts a ``WhaleCycle``, or a list/tuple of phases — each a
    ``WhalePhase`` or a ``{"behavior": ..., "duration": ...}`` dict, which
    is the shape the configuration loader produces. Malformed cycles
    raise; nothing is repaired or skipped.
    """
    if cycle is None:
        return None
    if isinstance(cycle, WhaleCycle):
        phases = cycle.phases
    elif isinstance(cycle, (list, tuple)):
        phases = tuple(cycle)
    else:
        raise ValueError(f"cycle must be a list of phases or a WhaleCycle (got {cycle!r})")
    if not phases:
        raise ValueError("cycle must have at least one phase; omit it entirely to run without one")
    return WhaleCycle(tuple(_coerce_phase(i, phase) for i, phase in enumerate(phases)))


def _coerce_behavior(behavior: WhaleBehavior | str) -> WhaleBehavior:
    """``behavior`` as a ``WhaleBehavior``, accepting the enum or the
    configuration string. Used by the constructor and ``set_behavior`` so
    both reject the same values with the same message."""
    try:
        return WhaleBehavior(behavior)
    except ValueError:
        raise ValueError(
            f"Unknown whale behavior {behavior!r}; expected one of {[b.value for b in WhaleBehavior]}"
        ) from None


def _require_price(price: float) -> None:
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a positive finite number (got {price!r})")


class Whale:
    """A large holder that occasionally trades a chunk of total supply."""

    def __init__(
        self,
        whale_id: str,
        holdings: float,
        *,
        activity_probability: float = 0.1,
        max_trade_fraction: float = 0.05,
        impact_coefficient: float = 2.0,
        seed: int | None = None,
        starting_cash: float | None = None,
        behavior: WhaleBehavior | str = WhaleBehavior.NEUTRAL,
        target_coin_fraction: float | None = None,
        min_trade_fraction: float = 0.0,
        cooldown_ticks: int = 0,
        min_trade_interval_ticks: int = 0,
        intent_strength: float = INTENT_STRENGTH_DEFAULT,
        cycle: WhaleCycle | list | tuple | None = None,
    ):
        if not whale_id:
            raise ValueError("whale_id must not be empty")
        _require_number("holdings", holdings)
        if holdings < 0:
            raise ValueError("holdings must not be negative")
        _require_fraction("activity_probability", activity_probability)
        _require_number("max_trade_fraction", max_trade_fraction)
        if not 0.0 < max_trade_fraction <= 1.0:
            raise ValueError("max_trade_fraction must be within (0, 1]")
        _require_number("impact_coefficient", impact_coefficient)
        if impact_coefficient < 0:
            raise ValueError(f"impact_coefficient must not be negative (got {impact_coefficient!r})")
        _require_fraction("min_trade_fraction", min_trade_fraction)
        if min_trade_fraction > max_trade_fraction:
            raise ValueError(
                f"min_trade_fraction ({min_trade_fraction}) must not exceed max_trade_fraction ({max_trade_fraction})"
            )
        if isinstance(cooldown_ticks, bool) or not isinstance(cooldown_ticks, int) or cooldown_ticks < 0:
            raise ValueError(f"cooldown_ticks must be an integer >= 0 (got {cooldown_ticks!r})")
        if (
            isinstance(min_trade_interval_ticks, bool)
            or not isinstance(min_trade_interval_ticks, int)
            or min_trade_interval_ticks < 0
        ):
            raise ValueError(
                f"min_trade_interval_ticks must be an integer >= 0 (got {min_trade_interval_ticks!r})"
            )
        _require_intent_strength(intent_strength)
        cycle = _coerce_cycle(cycle)
        if cycle is not None and starting_cash is None:
            raise ValueError(
                "A cycle applies only to funded whales (those given starting_cash): its directional "
                "phases need a wallet to settle against, and a cycle never creates one"
            )
        behavior = _coerce_behavior(behavior)
        if starting_cash is not None:
            _require_number("starting_cash", starting_cash)
            if starting_cash < 0:
                raise ValueError(f"starting_cash must not be negative (got {starting_cash!r})")
        elif behavior is not WhaleBehavior.NEUTRAL:
            raise ValueError(
                f"A {behavior.value} whale needs starting_cash: an unfunded whale trades against "
                "unlimited external liquidity, so it could accumulate coins that don't exist"
            )
        elif min_trade_interval_ticks:
            raise ValueError(
                "min_trade_interval_ticks applies only to funded whales (those given starting_cash); "
                "an unfunded whale's pacing is cooldown_ticks"
            )
        if target_coin_fraction is not None:
            _require_fraction("target_coin_fraction", target_coin_fraction)
            # A target steers one direction, so a whale that will never be
            # directional has no use for one. With a cycle it is the phases
            # that decide, not the opening behavior: the target is dormant
            # through neutral phases and in force through the rest.
            if cycle is not None:
                if all(phase.behavior is WhaleBehavior.NEUTRAL for phase in cycle.phases):
                    raise ValueError(
                        "target_coin_fraction needs at least one accumulate or distribute phase in the cycle"
                    )
            elif behavior is WhaleBehavior.NEUTRAL:
                raise ValueError("target_coin_fraction applies only to accumulate or distribute whales")

        self.whale_id = whale_id
        self.activity_probability = activity_probability
        self.max_trade_fraction = max_trade_fraction
        self.min_trade_fraction = min_trade_fraction
        self.impact_coefficient = impact_coefficient
        self.behavior = behavior
        # How hard a directional whale leans. Stored whatever the behavior
        # is, so a transition through neutral and back doesn't lose it.
        self.intent_strength = intent_strength
        self.target_coin_fraction = target_coin_fraction
        self.cooldown_ticks = cooldown_ticks
        self.min_trade_interval_ticks = min_trade_interval_ticks
        # Two independent countdowns of upcoming ticks to sit out. Both live
        # on the whale because both are purely private pacing: nothing
        # outside it reads or writes them, and they depend on nothing but
        # this whale's own trades.
        self._cooldown_remaining = 0
        self._interval_remaining = 0
        # What the last tick's execution path did. Written by that path and
        # read only by observation; it steers nothing.
        self._last_attempt = WhaleAttempt.INACTIVE
        # The wallet is the authoritative balance of a funded whale; an
        # unfunded whale keeps only a coin count.
        self.wallet: Wallet | None = None if starting_cash is None else Wallet(cash=starting_cash, coins=holdings)
        self._holdings = holdings
        self._rng = random.Random(seed)
        # The cycle is a clock, not a memory: one index and one counter,
        # both advanced in O(1) at the end of every tick.
        self._cycle = cycle
        self._phase_index = 0
        self._phase_elapsed = 0
        if cycle is not None:
            # The cycle is authoritative from the start, so phase 0 sets the
            # behavior the whale opens in, overriding `behavior` if they
            # disagree. (Reaching a neutral phase while carrying a target is
            # the Step 4 dormant-target state, not a new one.)
            self.behavior = cycle.phases[0].behavior

    @property
    def funded(self) -> bool:
        return self.wallet is not None

    @property
    def holdings(self) -> float:
        """Coins currently held."""
        return self.wallet.coins if self.wallet is not None else self._holdings

    @property
    def interval_remaining(self) -> int:
        """Upcoming ticks this whale will sit out to honour
        ``min_trade_interval_ticks``. Always 0 when the setting is 0, and
        for unfunded whales, which the setting does not apply to.

        Kept off ``WhaleState`` on purpose: that snapshot's shape is part
        of the Step 2 contract, and this is a second, independent counter
        rather than a change to the cooldown it reports.
        """
        return self._interval_remaining

    def state(self) -> WhaleState:
        return WhaleState(
            whale_id=self.whale_id,
            behavior=self.behavior,
            funded=self.funded,
            cash=self.wallet.cash if self.wallet is not None else None,
            coins=self.holdings,
            target_coin_fraction=self.target_coin_fraction,
            cooldown_remaining=self._cooldown_remaining,
        )

    def set_behavior(self, behavior: WhaleBehavior | str) -> WhaleBehavior:
        """Move this whale to ``behavior`` and return the behavior it left
        (Phase 8, Step 4).

        Every transition among the three behaviors is allowed — there are
        no forbidden pairs, so there is no transition table — and setting
        the current behavior again is a no-op that still validates. The
        one restriction is the constructor's: only a funded whale may be
        ``accumulate`` or ``distribute``, because an unfunded whale trades
        against unlimited external liquidity and could accumulate coins
        that don't exist. Asking an unfunded whale for a directional
        behavior raises rather than quietly funding it.

        A transition is a state change and nothing else. It changes no
        balance, places no trade, draws no randomness, and leaves the
        target, the trade-size band and both pacing counters exactly as
        they were — a whale with 3 cooldown ticks left still has 3
        afterwards. What it changes is which direction the *next* eligible
        tick trades in, under the ordinary Step 2 and Step 3 rules.

        Transitions are only ever explicit: nothing in this module calls
        this method, and no price, news, psychology, profit or random draw
        can trigger one.
        """
        behavior = _coerce_behavior(behavior)
        if behavior is not WhaleBehavior.NEUTRAL and self.wallet is None:
            raise ValueError(
                f"An unfunded whale cannot become {behavior.value}: it needs starting_cash, and a "
                "behavior transition never changes a whale between funded and unfunded"
            )
        previous, self.behavior = self.behavior, behavior
        return previous

    @property
    def cycle(self) -> WhaleCycle | None:
        """This whale's behavior timetable, or ``None``. Immutable."""
        return self._cycle

    def cycle_state(self) -> WhaleCycleState:
        """Where this whale is in its cycle (Phase 8, Step 6). Always
        returns a snapshot; ``configured`` is False for a whale without
        one."""
        if self._cycle is None:
            return WhaleCycleState(False, 0, None, 0, None, None)
        phase = self._cycle.phases[self._phase_index]
        return WhaleCycleState(
            True, self._phase_index, phase.behavior, self._phase_elapsed, phase.duration, self._cycle
        )

    def observe(self, price: float) -> _WhaleSnapshot:
        """A read-only snapshot of this whale as it stands, marked at
        ``price`` (Phase 8, Step 7).

        Taken *before* the whale trades, so the behavior, intent, cycle
        position and pacing counters it records are the ones in force for
        the tick about to run. Pure: it mutates nothing, places no trade
        and draws no randomness. ``complete_observation`` pairs it with
        what the tick then did.
        """
        _require_price(price)
        cycle = self.cycle_state()
        # A cycling whale's phase is applied inside `maybe_trade`, so
        # `self.behavior` still holds the previous tick's phase on a
        # boundary. The behavior in force for the tick about to run is the
        # one the cycle is pointing at.
        behavior = cycle.behavior if cycle.configured else self.behavior
        return _WhaleSnapshot(
            whale_id=self.whale_id,
            funded=self.funded,
            behavior=behavior,
            intent_strength=self.intent_strength,
            cycle_phase_index=self._phase_index if cycle.configured else None,
            cycle_phase_elapsed=self._phase_elapsed if cycle.configured else None,
            price=price,
            allocation_before=self.allocation(price),
            cooldown_remaining=self._cooldown_remaining,
            interval_remaining=self._interval_remaining,
        )

    def complete_observation(
        self, snapshot: _WhaleSnapshot, trade: WhaleTrade | None
    ) -> WhaleObservation:
        """Pair a pre-trade ``snapshot`` with the tick's outcome.

        Read-only, like ``observe``: the balances and allocation it adds
        are this whale's as they stand now, at the snapshot's price.
        """
        if snapshot.whale_id != self.whale_id:
            raise ValueError(
                f"snapshot belongs to whale {snapshot.whale_id!r}, not {self.whale_id!r}"
            )
        return WhaleObservation(
            whale_id=snapshot.whale_id,
            funded=snapshot.funded,
            behavior=snapshot.behavior,
            intent_strength=snapshot.intent_strength,
            cycle_phase_index=snapshot.cycle_phase_index,
            cycle_phase_elapsed=snapshot.cycle_phase_elapsed,
            price=snapshot.price,
            allocation_before=snapshot.allocation_before,
            allocation_after=self.allocation(snapshot.price),
            cooldown_remaining=snapshot.cooldown_remaining,
            interval_remaining=snapshot.interval_remaining,
            trade=trade,
            attempt=self._last_attempt,
            cash=self.wallet.cash if self.wallet is not None else None,
            coins=self.holdings,
        )

    def set_intent_strength(self, intent_strength: float) -> float:
        """Set how hard this whale leans into its behavior and return the
        strength it had before (Phase 8, Step 5).

        Validated against ``[INTENT_STRENGTH_MIN, INTENT_STRENGTH_MAX]``
        and rejected, never clamped, outside it. Like ``set_behavior``
        this is a setting change and nothing else: it places no trade,
        moves no balance, draws no randomness, and leaves the behavior,
        the target, the trade-size band and both pacing counters exactly
        as they were. It takes effect on the next eligible tick.

        Stored for every whale, but only ``ACCUMULATE`` and ``DISTRIBUTE``
        read it — a neutral whale has no direction to press — so on a
        neutral or unfunded whale it is inert until (and unless) the whale
        becomes directional.
        """
        _require_intent_strength(intent_strength)
        previous, self.intent_strength = self.intent_strength, intent_strength
        return previous

    def allocation(self, price: float) -> WhaleAllocation | None:
        """This whale's portfolio composition marked at ``price``, against
        its target if it has one (Phase 8, Step 2).

        ``None`` for an unfunded whale, which holds no cash and so has no
        portfolio to allocate. This is the single source of the target
        arithmetic: ``_funded_trade`` sizes from the same numbers, at the
        same price it settles at, so what an observer reads is exactly what
        the whale acted on.
        """
        if self.wallet is None:
            return None
        _require_price(price)
        cash, coins = self.wallet.cash, self.wallet.coins
        portfolio_value = cash + coins * price
        coin_value = coins * price
        # A portfolio worth nothing has no composition to speak of.
        coin_fraction = coin_value / portfolio_value if portfolio_value > 0 else 0.0
        target = self.target_coin_fraction
        if target is None:
            return WhaleAllocation(price, portfolio_value, coin_value, coin_fraction, None, None, None)
        return WhaleAllocation(
            price,
            portfolio_value,
            coin_value,
            coin_fraction,
            target,
            target - coin_fraction,
            target * portfolio_value / price,
        )

    def maybe_trade(
        self, total_supply: float, *, price: float | None = None, reserve: Wallet | None = None
    ) -> WhaleTrade | None:
        """With probability ``activity_probability``, execute one trade.

        Returns ``None`` on ticks the whale sits out (cooling down, inactive,
        or — for a funded whale — nothing to do or nothing fillable). An
        unfunded whale's sells are capped at its holdings and its buys are
        not (external liquidity is assumed). A funded whale needs the tick's
        ``price`` and the market ``reserve`` to settle against. A sell's
        price impact divides price by the impact factor; a buy's
        multiplies by it.

        With a cycle configured, the tick's phase behavior is applied
        first and the cycle clock advances afterwards; neither step draws
        randomness or moves a balance.
        """
        if self._cycle is None:
            return self._trade_tick(total_supply, price, reserve)
        # The phase applies for the whole tick and the clock advances after
        # it, so a phase of N ticks covers exactly N of them and the next
        # phase opens on the tick after that. The cycle decides only which
        # behavior is in force; whether this tick trades at all is still
        # the ordinary pacing, activity, target and settlement logic.
        phase = self._cycle.phases[self._phase_index]
        if self.behavior is not phase.behavior:
            self.set_behavior(phase.behavior)
        trade = self._trade_tick(total_supply, price, reserve)
        self._advance_cycle()
        return trade

    def _advance_cycle(self) -> None:
        """One tick of the cycle clock: O(1), no randomness, and it never
        touches balances, pacing counters, the target or the intent."""
        self._phase_elapsed += 1
        if self._phase_elapsed >= self._cycle.phases[self._phase_index].duration:
            self._phase_elapsed = 0
            self._phase_index = (self._phase_index + 1) % len(self._cycle.phases)

    def _trade_tick(
        self, total_supply: float, price: float | None, reserve: Wallet | None
    ) -> WhaleTrade | None:
        # Both pacing counters are checked before the activity draw, so a
        # whale sitting one out consumes no randomness. They are separate
        # countdowns rather than one combined figure: each was started by
        # its own setting, and the whale waits for whichever runs longer.
        if self._cooldown_remaining > 0 or self._interval_remaining > 0:
            self._last_attempt = WhaleAttempt.BLOCKED
            if self._cooldown_remaining > 0:
                self._cooldown_remaining -= 1
            if self._interval_remaining > 0:
                self._interval_remaining -= 1
            return None
        if self._rng.random() > self.activity_probability:
            self._last_attempt = WhaleAttempt.INACTIVE
            return None

        side = self._rng.choice(("buy", "sell"))
        trade_fraction = self._rng.uniform(self.min_trade_fraction, self.max_trade_fraction)
        requested_quantity = trade_fraction * total_supply

        if self.wallet is None:
            if side == "sell":
                quantity = min(self._holdings, requested_quantity)
                self._holdings -= quantity
            else:
                quantity = requested_quantity
                self._holdings += quantity
        else:
            if price is None or reserve is None:
                raise ValueError("a funded whale needs the tick's price and the market reserve to trade")
            _require_price(price)
            fill = self._funded_trade(side, requested_quantity, price, reserve)
            if fill is None:
                return None
            side, quantity = fill

        # Coins moved, or the attempt settled to nothing (an unfunded sell
        # with nothing to sell still prints a zero-quantity trade).
        self._last_attempt = WhaleAttempt.FILLED if quantity > 0 else WhaleAttempt.NO_FILL
        fraction_of_supply = quantity / total_supply if total_supply else 0.0
        impact = 1.0 + self.impact_coefficient * fraction_of_supply
        price_impact = impact if side == "buy" else 1.0 / impact
        # Only a fill that actually moved coins paces the whale. Everything
        # that returned earlier — inactive, blocked, nothing to do, nothing
        # fillable — never reaches here, and a zero-quantity unfunded sell
        # is excluded by the same test the cooldown has always used.
        if quantity > 0:
            self._cooldown_remaining = self.cooldown_ticks
            if self.wallet is not None:
                self._interval_remaining = self.min_trade_interval_ticks

        return WhaleTrade(
            whale_id=self.whale_id,
            side=side,
            quantity=quantity,
            price_impact=price_impact,
        )

    def _funded_trade(
        self, drawn_side: str, requested: float, price: float, reserve: Wallet
    ) -> tuple[str, float] | None:
        """Direction from the behavior (the drawn side only for NEUTRAL),
        size capped so a target isn't crossed, then settled against the
        reserve. ``None`` when there is nothing to do or nothing fills.

        Deterministic throughout: the draws already happened in
        ``maybe_trade``, and everything here is arithmetic on the balances,
        the price and the configured target.
        """
        if self.behavior is WhaleBehavior.NEUTRAL:
            # Drawn side, and any target is dormant: a target steers one
            # direction, so it means nothing to a whale trading both. Only
            # a Step 4 transition can put a whale carrying a target in this
            # state — the constructor still refuses the combination — and
            # the target is kept, not cleared, for when it transitions back.
            side = drawn_side
            return self._settle(side, requested, price, reserve)
        side = "buy" if self.behavior is WhaleBehavior.ACCUMULATE else "sell"
        # Directional pressure: scale what the whale asks for, then let the
        # target and settlement clamp it as they always have. Multiplying
        # by the default 1.0 is exact in IEEE-754, so this line is a no-op
        # for every whale that doesn't set it.
        requested *= self.intent_strength
        if self.target_coin_fraction is not None:
            allocation = self.allocation(price)
            # How far the target is in the one direction this whale trades.
            # Negative means the target lies the other way: a behavior is
            # never reversed to chase it, so the whale just holds.
            distance = allocation.allocation_gap if side == "buy" else -allocation.allocation_gap
            if distance <= TARGET_DEAD_ZONE:
                self._last_attempt = WhaleAttempt.HELD
                return None
            # Coins that land exactly on the target. Trading at the mark
            # price leaves portfolio value unchanged, so this is the whole
            # gap, and capping the draw to it is what keeps the whale from
            # crossing. Settlement only ever clamps further down.
            room = (
                allocation.target_coins - self.wallet.coins
                if side == "buy"
                else self.wallet.coins - allocation.target_coins
            )
            requested = min(requested, room)
        return self._settle(side, requested, price, reserve)

    def _settle(self, side: str, requested: float, price: float, reserve: Wallet) -> tuple[str, float] | None:
        action = TradeAction.BUY if side == "buy" else TradeAction.SELL
        fill = settle_against_reserve(self.wallet, action, requested, price, reserve)
        if fill is None:
            self._last_attempt = WhaleAttempt.NO_FILL
            return None
        return side, fill[0]
