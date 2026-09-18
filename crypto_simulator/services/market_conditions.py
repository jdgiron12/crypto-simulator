"""Named market-condition presets (Phase 17).

A market condition is a *configuration preset*: a named, immutable set of
settings changes that puts the simulator into a particular kind of
market. It adds no mechanism. Every field a preset writes already exists
and is already validated — the news mix and its frequency, the drift the
random walk takes from event sentiment, the coin's base volatility — so a
condition only chooses values a user could have written in
``default.yaml`` themselves.

**Not a manipulation scenario.** ``MANIPULATION_SCENARIOS``
(``pump_and_dump``, ``wash_trading``) replace the *participants*: they
add manipulators, and a follower crowd, who trade to a scheme. A market
condition touches no participant. The two are different axes and compose
freely: a pump can run in a bear market.

**Not a saved scenario either.** Phase 13's scenarios are whole
``SimulationParams`` a user saved under a name, in the database. These
are fixed presets defined in code, and a request refers to one *by name*
— so a saved scenario records which condition it used, and needs no new
storage for it.

**What they honestly are.** A preset tilts the odds; it does not decree
an outcome. ``bull`` weights the news toward the catalog's positive
categories and gives the random walk a drift coefficient to read
sentiment through, so runs *tend* upward across a batch. Any single
seeded run may still fall, and nothing here should be read as a claim
that it will not. ``meme`` is not a direction at all: it raises
volatility, and because the walk is multiplicative that alone lowers the
median outcome even with a balanced news mix — the spread widens far more
than the middle moves.

**The AMM caveat is a hard constraint, not a footnote.**
``CoinSimulator`` *rejects* a nonzero ``drift_per_sentiment`` in AMM
mode — "in amm mode events move price only through trader reactions" —
so a preset applies its drift only to a random-walk run. In AMM the same
preset still changes which news arrives and how often, and price moves
only as traders react to it. That is weaker and indirect, and it is left
that way: no AMM mechanic is bent to make a direction show up.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from crypto_simulator.config.settings import Settings

__all__ = [
    "MARKET_CONDITIONS",
    "MARKET_CONDITION_NAMES",
    "MarketCondition",
    "apply_market_condition",
]

#: The pricing mode whose price process reads event sentiment as drift.
_DRIFT_MODE = "random_walk"


@dataclass(frozen=True)
class MarketCondition:
    """One named preset.

    Every field is optional: a preset changes what it means to change and
    leaves the rest of the configuration alone. ``drift_per_sentiment``
    is the exception that carries a condition — it is applied only to a
    random-walk run, because the simulator refuses it in AMM mode.
    """

    name: str
    description: str
    #: Per-tick chance of a random news event, replacing ``events.random.probability``.
    event_probability: float | None = None
    #: Catalog category -> weight for the random generator to draw from.
    event_categories: Mapping[str, float] = field(default_factory=dict)
    #: Inclusive severity range for generated events.
    event_severity: tuple[float, float] | None = None
    #: Random-walk log-drift per tick at sentiment +/-1. Ignored in AMM mode.
    drift_per_sentiment: float | None = None
    #: Replacement for ``coin.volatility``, the walk's base noise.
    volatility: float | None = None

    def __post_init__(self) -> None:
        if self.drift_per_sentiment is not None and self.drift_per_sentiment < 0:
            # The simulator's own rule: sentiment is signed, the coefficient is not.
            raise ValueError(
                f"{self.name}: drift_per_sentiment must be >= 0 (got {self.drift_per_sentiment})"
            )
        if self.volatility is not None and self.volatility < 0:
            raise ValueError(f"{self.name}: volatility must be >= 0 (got {self.volatility})")
        object.__setattr__(self, "event_categories", MappingProxyType(dict(self.event_categories)))

    def apply(self, settings: Settings, *, pricing_mode: str) -> Settings:
        """This preset's settings, built from ``settings``.

        Only the fields the preset names are replaced, and only through
        ``dataclasses.replace`` — the original settings object is never
        mutated, and the application's own settings are untouched.
        """
        events = settings.coin.events
        random_events = events.random
        if self.event_probability is not None:
            random_events = replace(random_events, probability=self.event_probability)
        if self.event_categories:
            random_events = replace(random_events, categories=dict(self.event_categories))
        if self.event_severity is not None:
            random_events = replace(random_events, severity=self.event_severity)
        if random_events is not events.random:
            events = replace(events, random=random_events)
        if self.drift_per_sentiment is not None and pricing_mode == _DRIFT_MODE:
            # Only random-walk mode reads sentiment as drift; AMM mode
            # rejects a nonzero coefficient outright.
            events = replace(events, drift_per_sentiment=self.drift_per_sentiment)

        coin = settings.coin
        if events is not coin.events:
            coin = replace(coin, events=events)
        if self.volatility is not None:
            coin = replace(coin, volatility=self.volatility)
        if coin is settings.coin:
            return settings
        return replace(settings, coin=coin)


#: Every preset, by the name a request refers to it with.
MARKET_CONDITIONS: Mapping[str, MarketCondition] = MappingProxyType(
    {
        "bull": MarketCondition(
            name="bull",
            description=(
                "news weighted to the catalog's positive categories, arriving often, with the "
                "random walk reading sentiment as upward drift"
            ),
            event_probability=0.15,
            event_categories={
                "exchange_listing": 3.0,
                "partnership_announcement": 2.0,
                "product_launch": 2.0,
                "adoption_growth": 2.0,
                "positive_regulation": 1.0,
            },
            drift_per_sentiment=0.004,
        ),
        "bear": MarketCondition(
            name="bear",
            description=(
                "news weighted to the catalog's negative categories; the same positive drift "
                "coefficient turns their negative sentiment into downward drift"
            ),
            event_probability=0.15,
            event_categories={
                "security_incident": 2.0,
                "regulatory_restriction": 2.0,
                "product_failure": 2.0,
                "supply_concern": 2.0,
                "competitor_announcement": 1.0,
            },
            drift_per_sentiment=0.004,
        ),
        "meme": MarketCondition(
            name="meme",
            description=(
                "constant, severe, high-attention news of both tones over a much noisier walk; "
                "a volatility regime, not a direction — though under a multiplicative walk that "
                "much noise drags the median outcome down on its own"
            ),
            event_probability=0.30,
            event_categories={
                "exchange_listing": 3.0,
                "security_incident": 3.0,
                "market_uncertainty": 2.0,
                "ambiguous_announcement": 2.0,
                "product_launch": 2.0,
                "supply_concern": 2.0,
            },
            event_severity=(0.6, 1.0),
            drift_per_sentiment=0.002,
            volatility=0.09,
        ),
    }
)

#: The accepted names, sorted, for validation messages and CLI choices.
MARKET_CONDITION_NAMES: tuple[str, ...] = tuple(sorted(MARKET_CONDITIONS))


def apply_market_condition(
    settings: Settings, name: str | None, *, pricing_mode: str
) -> Settings:
    """Put ``settings`` into the named market condition.

    ``None`` returns the settings unchanged, by identity, so a request
    that names no condition is configured exactly as it was before
    Phase 17. ``pricing_mode`` is the mode the run will actually use, so
    that a preset's drift reaches a random-walk run and is left off an
    AMM one, which the simulator would refuse.
    """
    if name is None:
        return settings
    condition = MARKET_CONDITIONS.get(name)
    if condition is None:
        raise ValueError(
            f"unknown market condition {name!r}; expected one of {list(MARKET_CONDITION_NAMES)}"
        )
    return condition.apply(settings, pricing_mode=pricing_mode)
