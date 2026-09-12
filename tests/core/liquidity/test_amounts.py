import math
from decimal import Decimal

import pytest

from crypto_simulator.core.liquidity.amounts import EXACT, float_at_most, to_amount, to_rate


def test_to_amount_converts_floats_exactly():
    assert to_amount(0.1) == Decimal(0.1)
    assert to_amount(0.1) != Decimal("0.1")
    assert to_amount("2.5") == Decimal("2.5")
    assert to_amount(3) == Decimal(3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "NaN"])
def test_to_amount_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        to_amount(bad)


def test_to_amount_rejects_bool():
    with pytest.raises(TypeError):
        to_amount(True)


def test_to_rate_uses_the_human_decimal_for_floats():
    assert to_rate(0.003) == Decimal("0.003")


def test_float_at_most_never_exceeds_value():
    for text in ["0.1", "1e-30", "123456789.123456789123456789", "2", "1e300"]:
        value = Decimal(text)
        result = float_at_most(value)
        assert Decimal(result) <= value
        assert Decimal(math.nextafter(result, math.inf)) > value


def test_exact_context_does_not_round():
    a, b = Decimal(0.1), Decimal(1e6)
    assert EXACT.subtract(EXACT.add(a, b), b) == a
