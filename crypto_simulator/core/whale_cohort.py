"""Whale cohorts: funded whales sharing one behavior timetable (Phase 8, Step 8).

A ``WhaleCohort`` is a named ``WhaleCycle`` plus the ids of the whales that
follow it. Every member runs the same phase on the same tick, so a group of
large holders can accumulate together, stand down together and distribute
together.

It is **non-reactive coordination**: a predetermined, synchronized
schedule and nothing more. The phase in force on a tick is a pure function
of the simulator's tick number and the cycle —

    offset = (tick - 1) mod cycle.total_ticks

— with tick 1, the first simulated tick, opening phase 0. That is exactly
where a personal ``cycle`` stands on a whale's first tick, so a one-member
cohort behaves identically to the same whale carrying that cycle itself.
Nothing here reads price, returns, volume, news, psychology, manipulation,
traders, previous trades, or any whale's balances or behavior: members do
not observe each other, and adding, removing or reordering whales never
changes where a cohort is.

A cohort changes a member's behavior and nothing else. It works through the
Step 4 ``Whale.set_behavior``, so a transition resets no cooldown, trade
interval, target or intent, moves no balance, places no trade of its own
and draws no randomness. Whether the whale then trades on the tick is
decided, as ever, by its pacing, activity draw, target and settlement.

Membership rules, checked when a simulation binds its cohorts
(``WhaleCohortSchedule``):

- only funded whales (those given ``starting_cash``) may join — a cohort's
  directional phases need a wallet, and a cohort never creates one;
- a whale belongs to at most one cohort;
- a whale in a cohort may not also carry a personal ``cycle``: the cohort
  would override it, and silently discarding a configured cycle is worse
  than refusing the combination;
- as with a personal cycle, a member carrying a ``target_coin_fraction``
  needs at least one directional phase in the cohort's cycle.

Cycle validation is ``core/whale.py``'s own, so a cohort accepts exactly
the phase shapes a personal cycle does and rejects the same mistakes with
the same messages. This module only reads from ``core/whale.py``; the whale
module does not import it, so the whale's import isolation is unchanged.
"""

from __future__ import annotations

import bisect
import dataclasses
from dataclasses import dataclass, field
from typing import Sequence

from crypto_simulator.core.whale import (
    Whale,
    WhaleBehavior,
    WhaleCycle,
    WhaleObservation,
    _coerce_cycle,
)


@dataclass(frozen=True)
class WhaleCohortPosition:
    """Where a cohort's timetable stands on one tick: which phase is in
    force, how many ticks of it have already run, and its behavior."""

    cohort_id: str
    tick: int
    phase_index: int
    phase_elapsed: int
    behavior: WhaleBehavior


@dataclass(frozen=True)
class WhaleCohort:
    """A named, shared behavior timetable and the whales that follow it.

    Immutable, and validated once at construction. ``cycle`` accepts a
    ``WhaleCycle`` or the list-of-phases shape a whale's own ``cycle``
    takes; ``member_ids`` is a non-empty list or tuple of distinct whale
    ids. Which whales those ids name is resolved, and the membership rules
    checked, only when a simulation binds the cohort.
    """

    cohort_id: str
    cycle: WhaleCycle
    member_ids: tuple[str, ...]
    # Cumulative phase ends, so a tick is placed with one binary search
    # instead of a walk from the start of the cycle.
    _phase_ends: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cohort_id, str) or not self.cohort_id:
            raise ValueError(f"cohort_id must be a non-empty string (got {self.cohort_id!r})")
        try:
            cycle = _coerce_cycle(self.cycle)
        except ValueError as error:
            raise ValueError(f"cohort {self.cohort_id!r}: {error}") from None
        if cycle is None:
            raise ValueError(f"cohort {self.cohort_id!r} needs a cycle; a cohort without one has no schedule")
        members = self.member_ids
        if not isinstance(members, (list, tuple)):
            raise ValueError(
                f"cohort {self.cohort_id!r} member_ids must be a list or tuple of whale ids (got {members!r})"
            )
        if not members:
            raise ValueError(f"cohort {self.cohort_id!r} must have at least one member")
        seen: set[str] = set()
        for member in members:
            if not isinstance(member, str) or not member:
                raise ValueError(
                    f"cohort {self.cohort_id!r} member ids must be non-empty strings (got {member!r})"
                )
            if member in seen:
                raise ValueError(f"cohort {self.cohort_id!r} lists whale {member!r} more than once")
            seen.add(member)
        ends, total = [], 0
        for phase in cycle.phases:
            total += phase.duration
            ends.append(total)
        object.__setattr__(self, "cycle", cycle)
        object.__setattr__(self, "member_ids", tuple(members))
        object.__setattr__(self, "_phase_ends", tuple(ends))

    def position_at(self, tick: int) -> WhaleCohortPosition:
        """The phase in force on simulator tick ``tick`` (1 is the first
        simulated tick). Pure arithmetic on the tick and the cycle: no
        state, no randomness, O(log phases)."""
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 1:
            raise ValueError(f"tick must be an integer >= 1 (got {tick!r})")
        offset = (tick - 1) % self._phase_ends[-1]
        index = bisect.bisect_right(self._phase_ends, offset)
        start = self._phase_ends[index - 1] if index else 0
        return WhaleCohortPosition(
            self.cohort_id, tick, index, offset - start, self.cycle.phases[index].behavior
        )

    def behavior_at(self, tick: int) -> WhaleBehavior:
        """The behavior every member runs on simulator tick ``tick``."""
        return self.position_at(tick).behavior


def with_cohort(observation: WhaleObservation, position: WhaleCohortPosition) -> WhaleObservation:
    """``observation`` labelled with its whale's cohort.

    For a member the cohort's cycle is the one in force (a member has no
    personal cycle), so the cycle phase fields report the cohort's phase —
    the same values a personal cycle would record on that tick. Read-only:
    it returns a new record and touches no whale.
    """
    return dataclasses.replace(
        observation,
        cohort_id=position.cohort_id,
        cycle_phase_index=position.phase_index,
        cycle_phase_elapsed=position.phase_elapsed,
    )


class WhaleCohortSchedule:
    """A simulation's cohorts bound to its whales.

    Built once, from the cohorts and the simulation's whale list; every
    membership rule is checked here, and anything that breaks one raises
    — nothing is repaired or skipped. Afterwards ``apply(tick)`` places
    each cohort on the tick and moves its members to that phase's behavior:
    O(cohorts + members) per tick, and the tick number is its only input.
    """

    def __init__(self, cohorts: Sequence[WhaleCohort], whales: Sequence[Whale]):
        if not isinstance(cohorts, (list, tuple)):
            raise ValueError(f"whale_cohorts must be a list or tuple of WhaleCohort (got {cohorts!r})")
        by_id: dict[str, list[Whale]] = {}
        for whale in whales:
            by_id.setdefault(whale.whale_id, []).append(whale)
        cohort_ids: set[str] = set()
        assigned: dict[str, str] = {}
        bindings = []
        for cohort in cohorts:
            if not isinstance(cohort, WhaleCohort):
                raise ValueError(f"whale_cohorts entries must be WhaleCohort (got {cohort!r})")
            if cohort.cohort_id in cohort_ids:
                raise ValueError(f"cohort id {cohort.cohort_id!r} is used more than once")
            cohort_ids.add(cohort.cohort_id)
            directional = any(p.behavior is not WhaleBehavior.NEUTRAL for p in cohort.cycle.phases)
            members = []
            for member_id in cohort.member_ids:
                if member_id in assigned:
                    raise ValueError(
                        f"whale {member_id!r} is in cohorts {assigned[member_id]!r} and "
                        f"{cohort.cohort_id!r}; a whale may belong to at most one cohort"
                    )
                matches = by_id.get(member_id, [])
                if not matches:
                    raise ValueError(
                        f"cohort {cohort.cohort_id!r} names whale {member_id!r}, but the simulation "
                        "has no whale with that id"
                    )
                if len(matches) > 1:
                    raise ValueError(
                        f"cohort {cohort.cohort_id!r} names whale {member_id!r}, but {len(matches)} "
                        "whales share that id; cohort members need unique ids"
                    )
                whale = matches[0]
                if not whale.funded:
                    raise ValueError(
                        f"cohort {cohort.cohort_id!r} applies only to funded whales (those given "
                        f"starting_cash); whale {member_id!r} is unfunded, and joining a cohort "
                        "never creates a wallet"
                    )
                if whale.cycle is not None:
                    raise ValueError(
                        f"whale {member_id!r} has its own cycle and is also in cohort "
                        f"{cohort.cohort_id!r}; a cohort replaces a whale's personal cycle, so "
                        "configure one or the other"
                    )
                if whale.target_coin_fraction is not None and not directional:
                    raise ValueError(
                        f"whale {member_id!r} has a target_coin_fraction, which needs at least one "
                        f"accumulate or distribute phase in cohort {cohort.cohort_id!r}'s cycle"
                    )
                assigned[member_id] = cohort.cohort_id
                members.append(whale)
            bindings.append((cohort, tuple(members)))
        self._bindings: tuple[tuple[WhaleCohort, tuple[Whale, ...]], ...] = tuple(bindings)

    @property
    def cohorts(self) -> tuple[WhaleCohort, ...]:
        return tuple(cohort for cohort, _ in self._bindings)

    def apply(self, tick: int) -> dict[Whale, WhaleCohortPosition]:
        """Move every member to its cohort's behavior for ``tick`` and
        return each member's position.

        Reads nothing but ``tick``: no member's balances, behavior or
        trades, and no other whale at all. ``set_behavior`` is the Step 4
        transition — behavior only, no trade, no draw — and setting the
        behavior a whale already has is a no-op.
        """
        positions: dict[Whale, WhaleCohortPosition] = {}
        for cohort, members in self._bindings:
            position = cohort.position_at(tick)
            for whale in members:
                whale.set_behavior(position.behavior)
                positions[whale] = position
        return positions
