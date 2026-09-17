"""The dashboard's serialization boundary (Phase 10, Step 1).

The contract is translation, not computation: types are converted by the
documented rules, values are carried across untouched, missing data stays
missing, and nothing is stringified as a fallback. Determinism matters as
much as correctness — the dashboard must show the same payload for the
same run.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import pytest

from crypto_simulator.analytics import analyze_market
from crypto_simulator.dashboard.serialization import report_to_dict, to_jsonable


class Colour(str, Enum):
    RED = "red"


class Level(Enum):
    ONE = 1


@dataclass(frozen=True)
class Inner:
    value: float | None


@dataclass(frozen=True)
class Outer:
    name: str
    count: int
    inner: Inner
    items: tuple[int, ...]

    @property
    def doubled(self) -> int:
        return self.count * 2


# --- scalars ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, True, False, 0, -7, 3.5, -0.0, "", "text"])
def test_scalars_pass_through_unchanged(value):
    result = to_jsonable(value)
    assert result == value and type(result) is type(value)


def test_none_stays_null_through_json():
    assert json.loads(json.dumps(to_jsonable({"missing": None}))) == {"missing": None}


def test_numbers_stay_numbers_through_json():
    payload = json.loads(json.dumps(to_jsonable({"i": 5, "f": 2.25})))
    assert payload == {"i": 5, "f": 2.25}
    assert isinstance(payload["i"], int) and isinstance(payload["f"], float)


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_non_finite_floats_are_rejected_with_their_path(value):
    with pytest.raises(ValueError, match=r"\$\.here"):
        to_jsonable({"here": value})


def test_non_finite_decimals_are_rejected():
    with pytest.raises(ValueError):
        to_jsonable(Decimal("NaN"))


# --- structured values -----------------------------------------------------------------------------------


def test_decimal_becomes_a_float():
    result = to_jsonable(Decimal("0.003"))
    assert isinstance(result, float) and result == 0.003


def test_enum_becomes_its_value():
    assert to_jsonable(Colour.RED) == "red"
    assert to_jsonable(Level.ONE) == 1


def test_dataclass_becomes_an_object_of_declared_fields_in_order():
    result = to_jsonable(Outer("a", 2, Inner(1.5), (3, 4)))
    assert list(result) == ["name", "count", "inner", "items"]
    assert result == {"name": "a", "count": 2, "inner": {"value": 1.5}, "items": [3, 4]}


def test_properties_are_not_serialized():
    assert "doubled" not in to_jsonable(Outer("a", 2, Inner(None), ()))


def test_tuples_and_lists_become_arrays_preserving_order():
    assert to_jsonable((3, 1, 2)) == [3, 1, 2]
    assert to_jsonable([(1,), [2]]) == [[1], [2]]


def test_mapping_keys_are_stringified_and_sorted():
    assert list(to_jsonable({2: "b", 1: "a", 10: "c"})) == ["1", "10", "2"]


def test_colliding_mapping_keys_are_an_error():
    with pytest.raises(TypeError, match="collide"):
        to_jsonable({1: "a", "1": "b"})


def test_unsupported_types_raise_instead_of_being_stringified():
    with pytest.raises(TypeError, match=r"\$\.when: no serialization rule for datetime"):
        to_jsonable({"when": datetime.datetime(2024, 1, 1)})


def test_unsupported_type_error_names_the_path_inside_a_structure():
    with pytest.raises(TypeError, match=r"\$\.outer\[1\]\.inner"):
        to_jsonable({"outer": [1, {"inner": object()}]})


# --- a real report ---------------------------------------------------------------------------------------


def test_report_to_dict_holds_every_section(payload):
    result = report_to_dict(payload.report)
    assert set(result) == {f.name for f in dataclasses.fields(payload.report)}


def test_report_to_dict_carries_values_across_untouched(payload):
    result = report_to_dict(payload.report)
    market = payload.report.market
    assert result["market"]["close_price"] == market.close_price
    assert result["market"]["cumulative_return"] == market.cumulative_return
    assert result["market"]["volume_breakdown"]["total_volume"] == market.volume_breakdown.total_volume
    assert result["ticks"] == payload.report.ticks


def test_report_to_dict_keeps_unavailable_figures_as_null(payload):
    """A run with no AMM pool has no pool activity — null, not an empty
    object and not zero."""
    result = report_to_dict(payload.report)
    assert payload.report.market.pool_activity is None
    assert result["market"]["pool_activity"] is None


def test_report_to_dict_is_json_serializable_without_nan(payload):
    json.dumps(report_to_dict(payload.report), allow_nan=False)


def test_report_to_dict_is_deterministic(payload):
    assert report_to_dict(payload.report) == report_to_dict(payload.report)


def test_report_to_dict_holds_no_python_representations(payload):
    text = json.dumps(report_to_dict(payload.report))
    for marker in ("Decimal(", "object at 0x", "<crypto_simulator", "PricingMode.", "TradeAction."):
        assert marker not in text


def test_report_to_dict_rejects_anything_else():
    with pytest.raises(TypeError, match="SimulationReport"):
        report_to_dict(analyze_market(()))
