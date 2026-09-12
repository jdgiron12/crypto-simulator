"""From market and news conditions to a ``PsychologyState``.

``compute_psychology(signals)`` is a pure, deterministic function of an
explicit ``MarketSignals`` record: no randomness, no global state, nothing
read from the simulator. It is deliberately simple and explainable, not a
model of real human psychology, and its scales are uncalibrated.

The inputs become two directional pressures and one magnitude, each a sum
of dimensionless terms (every term capped at ``TERM_CAP`` so extreme but
finite inputs can't overflow):

    bullish B = max(return, 0)/PRICE_MOVE_SCALE + max(momentum, 0)/PRICE_MOVE_SCALE
                + max(sentiment, 0) * attention
    bearish D = max(-return, 0)/PRICE_MOVE_SCALE + max(-momentum, 0)/PRICE_MOVE_SCALE
                + max(-sentiment, 0) * attention

Attention multiplies only the news terms (including severity below): it
amplifies whatever the news says, and does nothing without news.

    fomo        = tanh(B) * (1 - tanh(D))
    fear        = tanh(D) * (1 - tanh(B))
    uncertainty = tanh(volatility/VOLATILITY_SCALE + severity * attention + min(B, D))
    conviction  = tanh(max(B - D, 0)) * (1 - uncertainty)

So each pressure raises its own emotion and damps the opposite one
(good news lowers fear, bad news lowers FOMO and conviction); conflicting
signals (min(B, D)) add to uncertainty; conviction is net bullish
confidence, eroded by uncertainty. Neutral inputs give the neutral state
(all zeros), and ``tanh`` keeps every output within [0, 1].

Two helpers turn simulator data into ``MarketSignals``:
``signals_from_closes`` (returns, momentum and volatility from a short
window of completed closing prices) and ``aggregate_event_severity`` (the
severity of the strongest live event).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from crypto_simulator.core.psychology.state import PsychologyState

# A recent move or trend of 5% counts as one unit of pressure (tanh(1) ~ 0.76).
PRICE_MOVE_SCALE = 0.05
# Per-tick volatility (std of log returns) that counts as one unit of uncertainty.
VOLATILITY_SCALE = 0.10
# tanh(20) is 1.0 in floating point, so capping terms loses nothing.
TERM_CAP = 20.0
# Completed ticks of price history behind momentum and volatility.
SIGNAL_WINDOW = 5


def _require_finite(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")


@dataclass(frozen=True)
class MarketSignals:
    """Conditions the psychology is computed from. Defaults are neutral.

    recent_return: fractional price change over a short recent window
        (0.05 = +5%); >= -1.
    momentum: fractional price change over a longer window; >= -1.
    volatility: per-tick volatility, e.g. the standard deviation of recent
        log returns; >= 0.
    event_sentiment: aggregate news sentiment in [-1, 1].
    event_severity: how big the news is, whatever its direction, in [0, 1].
    attention: news attention multiplier, >= 1 (1 = no extra attention).
    """

    recent_return: float = 0.0
    momentum: float = 0.0
    volatility: float = 0.0
    event_sentiment: float = 0.0
    event_severity: float = 0.0
    attention: float = 1.0

    def __post_init__(self) -> None:
        for name in ("recent_return", "momentum", "volatility", "event_sentiment", "event_severity", "attention"):
            _require_finite(name, getattr(self, name))
        if self.recent_return < -1 or self.momentum < -1:
            raise ValueError("recent_return and momentum can't be below -1 (a price can't fall more than 100%)")
        if self.volatility < 0:
            raise ValueError(f"volatility must not be negative (got {self.volatility!r})")
        if not -1.0 <= self.event_sentiment <= 1.0:
            raise ValueError(f"event_sentiment must be within [-1, 1] (got {self.event_sentiment!r})")
        if not 0.0 <= self.event_severity <= 1.0:
            raise ValueError(f"event_severity must be within [0, 1] (got {self.event_severity!r})")
        if self.attention < 1.0:
            raise ValueError(f"attention must be >= 1 (got {self.attention!r})")


def _term(value: float) -> float:
    return min(value, TERM_CAP)


def compute_psychology(signals: MarketSignals) -> PsychologyState:
    """The ``PsychologyState`` implied by ``signals`` (see module docstring)."""
    # max(0.0, x), never max(x, 0.0): max keeps the first of equal values, so
    # the latter turns x = -0.0 into a -0.0 "zero" that prints differently.
    r, m, s, a = signals.recent_return, signals.momentum, signals.event_sentiment, signals.attention
    bullish = (
        _term(max(0.0, r) / PRICE_MOVE_SCALE)
        + _term(max(0.0, m) / PRICE_MOVE_SCALE)
        + _term(max(0.0, s) * a)
    )
    bearish = (
        _term(max(0.0, -r) / PRICE_MOVE_SCALE)
        + _term(max(0.0, -m) / PRICE_MOVE_SCALE)
        + _term(max(0.0, -s) * a)
    )
    uncertainty = math.tanh(
        _term(signals.volatility / VOLATILITY_SCALE)
        + _term(signals.event_severity * a)
        + min(bullish, bearish)
    )
    return PsychologyState(
        fear=math.tanh(bearish) * (1.0 - math.tanh(bullish)),
        fomo=math.tanh(bullish) * (1.0 - math.tanh(bearish)),
        conviction=math.tanh(max(0.0, bullish - bearish)) * (1.0 - uncertainty),
        uncertainty=uncertainty,
    )


def aggregate_event_severity(live_events: Iterable[tuple[float, float]]) -> float:
    """How severe the strongest live event is right now.

    ``live_events`` holds one ``(severity, intensity)`` pair per live event,
    both in [0, 1]; intensity is the event's current strength (1 while
    active, fading while it decays). The result is the largest
    ``severity * intensity`` — 0.0 with no live events — so overlapping
    events never add up past 1, and their order doesn't matter.
    """
    strongest = 0.0
    for severity, intensity in live_events:
        for name, value in (("severity", severity), ("intensity", intensity)):
            _require_finite(name, value)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1] (got {value!r})")
        strongest = max(strongest, severity * intensity)
    return strongest


def signals_from_closes(
    closes: Sequence[float],
    *,
    event_sentiment: float = 0.0,
    event_severity: float = 0.0,
    attention: float = 1.0,
) -> MarketSignals:
    """``MarketSignals`` from completed closing prices, oldest first.

    recent_return = last close / the close before it - 1
    momentum      = last close / first close - 1 (over the whole window)
    volatility    = sample std of the log returns between consecutive closes

    With a single close, returns and momentum are 0.0; with fewer than two
    log returns, volatility is 0.0. Pass only closes of ticks that have
    already finished — nothing here can tell a future price from a past one.
    """
    prices = list(closes)
    if not prices:
        raise ValueError("closes must not be empty")
    for price in prices:
        _require_finite("close", price)
        if price <= 0:
            raise ValueError(f"closes must be positive (got {price!r})")
    if len(prices) < 2:
        recent_return = momentum = 0.0
    else:
        recent_return = prices[-1] / prices[-2] - 1.0
        momentum = prices[-1] / prices[0] - 1.0
    log_returns = [math.log(after / before) for before, after in zip(prices, prices[1:])]
    return MarketSignals(
        recent_return=recent_return,
        momentum=momentum,
        volatility=_sample_std(log_returns) if len(log_returns) >= 2 else 0.0,
        event_sentiment=event_sentiment,
        event_severity=event_severity,
        attention=attention,
    )


def _sample_std(values: list[float]) -> float:
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((v - mean) ** 2 for v in values) / (len(values) - 1))
