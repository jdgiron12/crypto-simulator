"""Decimal arithmetic rules for liquidity-pool accounting.

Two kinds of arithmetic, deliberately kept apart:

- ``EXACT``: +, -, * at unlimited precision. Every balance update (reserves,
  fees, shares, conservation totals) uses only these, so accounting never
  rounds. Never divide with it — a non-terminating quotient has no finite
  exact form.
- ``FLOOR`` / ``CEILING`` / ``NEAREST``: 60-significant-digit contexts for
  the divisions the curve needs. Each call site picks the direction that
  favors the pool (outputs down, retained reserves up), so rounding can
  only make ``k`` grow, never shrink.
"""

from __future__ import annotations

import decimal
import math
from decimal import Decimal

QUOTE_PRECISION = 60

EXACT = decimal.Context(
    prec=decimal.MAX_PREC,
    Emax=decimal.MAX_EMAX,
    Emin=decimal.MIN_EMIN,
    traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow],
)
FLOOR = decimal.Context(prec=QUOTE_PRECISION, rounding=decimal.ROUND_FLOOR)
CEILING = decimal.Context(prec=QUOTE_PRECISION, rounding=decimal.ROUND_CEILING)
NEAREST = decimal.Context(prec=QUOTE_PRECISION, rounding=decimal.ROUND_HALF_EVEN)

ZERO = Decimal(0)
ONE = Decimal(1)


def to_amount(value: Decimal | float | int | str) -> Decimal:
    """Convert an amount to ``Decimal`` without losing information.

    Floats convert exactly (their full binary value), because they come
    from float wallets and the pool must credit exactly what left them.
    """
    if isinstance(value, bool):
        raise TypeError("amounts must be numeric, not bool")
    amount = value if isinstance(value, Decimal) else Decimal(value)
    if not amount.is_finite():
        raise ValueError(f"amount must be finite (got {value!r})")
    return amount


def to_rate(value: Decimal | float | int | str) -> Decimal:
    """Convert a configured rate (e.g. a fee) to ``Decimal``.

    Floats go through ``repr`` so ``0.003`` means exactly 3/1000, not the
    nearest binary double to it.
    """
    if isinstance(value, float):
        value = repr(value)
    return to_amount(value)


def float_at_most(value: Decimal) -> float:
    """Largest float that is <= ``value``."""
    result = float(value)
    if Decimal(result) > value:
        result = math.nextafter(result, -math.inf)
    return result
