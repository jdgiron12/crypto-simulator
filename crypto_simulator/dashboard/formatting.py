"""Display formatting for dashboard values (Phase 10).

Formatting only: each helper takes a value the payload already holds and
returns a string. Nothing here adds, scales, rounds or combines values —
a percentage is a format spec (``.2%``), not a multiplication — so the
number on screen is always the report's own.

``None`` means "not computable from the run", and every helper renders it
as ``UNAVAILABLE`` (``n/a``), never as zero or a blank. A zero the
analytics define as zero renders as zero. The specs match
``analytics.rendering`` so the dashboard and the CLI report show the same
figure the same way.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "UNAVAILABLE",
    "count",
    "flag",
    "number",
    "percent",
    "text",
    "tick",
    "tick_range",
]

UNAVAILABLE = "n/a"

#: The specs ``analytics.rendering`` uses, so both views agree.
PRICE_SPEC = ",.4f"
VOLUME_SPEC = ",.0f"
RETURN_SPEC = "+.2%"
RATIO_SPEC = ".2%"
#: Cash amounts carry cents; flows and P&L carry their sign, as the CLI
#: report shows them.
NOTIONAL_SPEC = ",.2f"
SIGNED_NOTIONAL_SPEC = "+,.2f"
SIGNED_VOLUME_SPEC = "+,.0f"


def number(value: Any, spec: str = PRICE_SPEC) -> str:
    """A numeric report value, or ``n/a`` when it is ``None``."""
    return UNAVAILABLE if value is None else format(value, spec)


def percent(value: Any, spec: str = RETURN_SPEC) -> str:
    """A ratio the analytics computed, shown as a percentage by format
    spec alone."""
    return UNAVAILABLE if value is None else format(value, spec)


def count(value: Any) -> str:
    """A count (fills, ticks, swaps), or ``n/a``."""
    return UNAVAILABLE if value is None else format(value, ",d")


def text(value: Any) -> str:
    return UNAVAILABLE if value is None else str(value)


def flag(value: Any) -> str:
    """A boolean the analytics recorded (a trader being active, a
    strategy being a manipulation strategy), or ``n/a`` when they report
    none — never guessed from other figures."""
    if value is None:
        return UNAVAILABLE
    return "yes" if value else "no"


def tick(value: Any) -> str:
    """A tick number, or ``n/a`` when the analytics report none."""
    return UNAVAILABLE if value is None else str(value)


def tick_range(first: Any, last: Any) -> str:
    """The analysed range as ``first-last``; ``n/a`` when either end is
    missing (no ticks were analysed)."""
    if first is None or last is None:
        return UNAVAILABLE
    return f"{first}-{last}"
