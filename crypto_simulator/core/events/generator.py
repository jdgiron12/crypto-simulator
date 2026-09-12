"""``RandomEventGenerator``: fictional events that occur by chance during a run.

Each tick, at most one probability check: with ``probability`` p (0.05 =
5% per tick) a new event starts that tick. Its category is drawn by
weight, its severity, duration and decay from inclusive ranges, and it is
built through the catalog (``create_event``), so ``MarketEvent`` still
validates every event and the catalog stays the only source of category
effects. The generator only creates events and hands them to an
``EventEngine``; it never touches prices, pools, wallets or traders.

Randomness: one private ``random.Random(seed)`` stream, used for nothing
else. Draws per tick: none when p is 0; otherwise one for the probability
check, plus — only when an event occurs — one for the category, one for
the severity and one each for the duration and decay. The stream depends
only on its seed, the tick count and the configuration, never on market
activity.
"""

from __future__ import annotations

import math
import random
from typing import Mapping, Sequence

from crypto_simulator.core.events.catalog import EVENT_CATEGORIES, create_event
from crypto_simulator.core.events.engine import EventEngine
from crypto_simulator.core.events.event import MarketEvent

EVENT_ID_PREFIX = "random-"


def _is_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _check_range(
    name: str,
    value: object,
    *,
    integer: bool,
    minimum: float,
    exclusive_minimum: bool = False,
    maximum: float | None = None,
) -> tuple:
    kind = "integers" if integer else "numbers"
    bound = f"> {minimum}" if exclusive_minimum else f">= {minimum}"
    if maximum is not None:
        bound += f" and <= {maximum}"
    valid = (
        isinstance(value, (tuple, list))
        and len(value) == 2
        and all(_is_number(v) and (not integer or isinstance(v, int)) for v in value)
    )
    if valid:
        low, high = value
        valid = (low > minimum if exclusive_minimum else low >= minimum) and low <= high
        valid = valid and (maximum is None or high <= maximum)
    if not valid:
        raise ValueError(f"{name} must be a [low, high] pair of {kind} {bound}, low <= high (got {value!r})")
    return tuple(value)


def validate_random_event_parameters(
    probability: float,
    categories: Mapping[str, float],
    severity: Sequence[float],
    duration: Sequence[int],
    decay_ticks: Sequence[int],
) -> None:
    """Raise ``ValueError`` unless these are usable generator parameters.

    ``categories`` maps catalog categories to weights >= 0 (at least one
    positive); empty means every catalog category, equally likely.
    Severity must fit ``MarketEvent``'s (0, 1]; durations are >= 1 and
    decays >= 0 ticks.
    """
    if not _is_number(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability must be a number within [0, 1] (got {probability!r})")
    if not isinstance(categories, Mapping):
        raise ValueError(f"categories must map category names to weights (got {categories!r})")
    for name, weight in categories.items():
        if name not in EVENT_CATEGORIES:
            raise ValueError(f"unknown event category {name!r}; expected one of {sorted(EVENT_CATEGORIES)}")
        if not _is_number(weight) or weight < 0:
            raise ValueError(f"categories[{name!r}] must be a finite weight >= 0 (got {weight!r})")
    if categories and not any(weight > 0 for weight in categories.values()):
        raise ValueError("categories needs at least one positive weight")
    _check_range("severity", severity, integer=False, minimum=0.0, exclusive_minimum=True, maximum=1.0)
    _check_range("duration", duration, integer=True, minimum=1)
    _check_range("decay_ticks", decay_ticks, integer=True, minimum=0)


class RandomEventGenerator:
    """Starts at most one random, catalog-built event per tick."""

    def __init__(
        self,
        *,
        probability: float,
        categories: Mapping[str, float] | None = None,
        severity: Sequence[float] = (0.3, 1.0),
        duration: Sequence[int] = (2, 8),
        decay_ticks: Sequence[int] = (5, 20),
        seed: int | None = None,
    ) -> None:
        categories = {} if categories is None else categories
        validate_random_event_parameters(probability, categories, severity, duration, decay_ticks)
        self.probability = probability
        self.severity = tuple(severity)
        self.duration = tuple(duration)
        self.decay_ticks = tuple(decay_ticks)
        # Sorted by name so the draws don't depend on how the mapping was
        # ordered; zero weights are dropped, so they can never be chosen.
        weights = categories or dict.fromkeys(EVENT_CATEGORIES, 1.0)
        self.categories: tuple[str, ...] = tuple(sorted(name for name, w in weights.items() if w > 0))
        cumulative, total = [], 0.0
        for name in self.categories:
            total += weights[name]
            cumulative.append(total)
        # random.choices scales by the total, so weights needn't sum to 1.
        self._cum_weights: tuple[float, ...] = tuple(cumulative)
        self._rng = random.Random(seed)
        self._generated = 0
        self._events: list[MarketEvent] = []

    @property
    def enabled(self) -> bool:
        return self.probability > 0

    @property
    def generated_events(self) -> tuple[MarketEvent, ...]:
        """Every event this generator started, in order — the explicit record
        of which events were random (anything else in the engine was
        scheduled or injected by hand)."""
        return tuple(self._events)

    def maybe_inject(self, engine: EventEngine, tick: int) -> MarketEvent | None:
        """Maybe start an event at ``tick`` and inject it into ``engine``.

        ``tick`` is the tick about to be simulated, so the event is live
        for it; ``tick - 1`` is the last tick already simulated, which the
        engine uses to refuse backdating. Returns the event, if any.
        """
        if not self.enabled or self._rng.random() >= self.probability:
            return None
        category = self._rng.choices(self.categories, cum_weights=self._cum_weights)[0]
        low, high = self.severity
        # uniform() can round up past `high` by an ulp; stay inside the range.
        severity = min(high, max(low, self._rng.uniform(low, high)))
        duration = self._rng.randint(*self.duration)
        decay_ticks = self._rng.randint(*self.decay_ticks)
        event = create_event(
            category,
            event_id=self._next_id(engine),
            severity=severity,
            start_tick=tick,
            duration=duration,
            decay_ticks=decay_ticks,
        )
        engine.inject(event, current_tick=tick - 1)
        self._events.append(event)
        return event

    def _next_id(self, engine: EventEngine) -> str:
        """``random-000001``, ``random-000002``, ... skipping any id already
        in the engine (e.g. a scheduled event that happens to use one)."""
        taken = {event.event_id for event in engine.events}
        while True:
            self._generated += 1
            event_id = f"{EVENT_ID_PREFIX}{self._generated:06d}"
            if event_id not in taken:
                return event_id
