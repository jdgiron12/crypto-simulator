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
from crypto_simulator.dashboard.serialization import DERIVED_FIELDS, report_to_dict, to_jsonable


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


# --- allowlisted analytics properties (Phase 10, Step 2) -------------------------------------------------


def test_the_allowlist_only_names_analytics_properties():
    for owner, names in DERIVED_FIELDS.items():
        declared = {field.name for field in dataclasses.fields(owner)}
        for name in names:
            assert name not in declared, f"{name} is a declared field of {owner.__name__}"
            assert isinstance(getattr(owner, name), property)


def test_volume_breakdown_carries_its_analytics_totals(payload):
    """The dashboard would otherwise have to add the components up
    itself, which is the analytics' job."""
    volume = payload.report.market.volume_breakdown
    result = report_to_dict(payload.report)["market"]["volume_breakdown"]
    assert result["participant_volume"] == volume.participant_volume
    assert result["trader_fills"] == volume.trader_fills
    assert result["fills"] == volume.fills


def test_allowlisted_properties_follow_the_declared_fields(payload):
    volume = payload.report.market.volume_breakdown
    result = report_to_dict(payload.report)["market"]["volume_breakdown"]
    declared = [field.name for field in dataclasses.fields(volume)]
    assert list(result) == declared + list(DERIVED_FIELDS[type(volume)])


def test_event_properties_are_carried(payload):
    """Phase 10, Step 5: an event window's own completeness and volume per
    tick, and an event path's id and overlap."""
    from crypto_simulator.dashboard.data import SimulationParams, run_simulation

    report = run_simulation(
        SimulationParams(ticks=25, events=True, psychology=True)
    ).report
    result = report_to_dict(report)
    event, path = result["event_windows"]["events"][0], report.event_windows.events[0]
    assert event["event_id"] == path.event_id
    assert event["overlapping"] == path.overlapping
    assert event["overlap_count"] == path.overlap_count
    window = event["active"]
    assert window["ticks_observed"] == path.active.ticks_observed
    assert window["complete"] == path.active.complete
    assert window["volume_per_tick"] == path.active.volume_per_tick


def test_manipulation_and_regime_properties_are_carried():
    """Phase 10, Step 6: a pump-and-dump summary's own totals, a regime
    window's completeness and description, a regime context's event flag,
    and the report's own window counts."""
    from crypto_simulator.dashboard.data import SimulationParams, run_simulation

    report = run_simulation(
        SimulationParams(ticks=110, scenario="pump_and_dump", events=True, psychology=True)
    ).report
    result = report_to_dict(report)

    summary = report.manipulation.pump_and_dump[0]
    serialized = result["manipulation"]["pump_and_dump"][0]
    assert serialized["total_volume"] == summary.total_volume
    assert serialized["total_fills"] == summary.total_fills

    regimes = result["regimes"]
    assert regimes["total_windows"] == report.regimes.total_windows
    assert regimes["complete_windows"] == report.regimes.complete_windows
    assert regimes["incomplete_windows"] == report.regimes.incomplete_windows
    for shown, observation in zip(regimes["observations"], report.regimes.observations):
        assert shown["complete"] == observation.complete
        assert shown["description"] == observation.description
        assert shown["context"]["event_active"] == observation.context.event_active


def test_the_new_properties_follow_their_declared_fields():
    """The allowlisted properties come after the declared fields, in the
    order the allowlist names them."""
    from crypto_simulator.analytics.manipulation import PumpAndDumpSummary
    from crypto_simulator.analytics.regimes import RegimeObservation, RegimeReport
    from crypto_simulator.dashboard.data import SimulationParams, run_simulation

    report = run_simulation(SimulationParams(ticks=30, scenario="pump_and_dump")).report
    result = report_to_dict(report)
    for owner, shown in (
        (PumpAndDumpSummary, result["manipulation"]["pump_and_dump"][0]),
        (RegimeObservation, result["regimes"]["observations"][0]),
        (RegimeReport, result["regimes"]),
    ):
        declared = [field.name for field in dataclasses.fields(owner)]
        assert list(shown) == declared + list(DERIVED_FIELDS[owner])


def test_an_unavailable_regime_label_stays_null():
    """An early window has no volatility or volume class; the payload
    keeps ``null`` rather than a stand-in label or a zero."""
    from crypto_simulator.dashboard.data import SimulationParams, run_simulation

    report = run_simulation(SimulationParams(ticks=30)).report
    window = report_to_dict(report)["regimes"]["observations"][0]
    assert report.regimes.observations[0].volatility is None
    assert window["volatility"] is None and window["volume"] is None
    assert window["volatility_reference"] is None


def test_a_strategy_the_report_has_no_summary_for_stays_null():
    from crypto_simulator.dashboard.data import SimulationParams, run_simulation

    report = run_simulation(SimulationParams(ticks=25, scenario="wash_trading")).report
    manipulation = report_to_dict(report)["manipulation"]
    assert report.manipulation.pump_and_dump_strategy is None
    assert manipulation["pump_and_dump_strategy"] is None
    assert manipulation["wash_strategy"]["strategy"] == report.manipulation.wash_strategy.strategy


def test_the_psychology_report_keeps_its_properties_out(payload):
    """Nothing in the dashboard imports the psychology analytics, so the
    allowlist does not reach into that package: the serialized psychology
    report carries its declared fields only."""
    from crypto_simulator.analytics.psychology_market import PsychologyMarketReport

    result = report_to_dict(payload.report)["psychology_market"]
    assert set(result) == {f.name for f in dataclasses.fields(PsychologyMarketReport)}
    assert "ticks_without_psychology" not in result


def test_a_class_outside_the_allowlist_keeps_its_properties_out(payload):
    market = report_to_dict(payload.report)["market"]
    assert set(market) == {field.name for field in dataclasses.fields(payload.report.market)}


def test_tuples_and_lists_become_arrays_preserving_order():
    assert to_jsonable((3, 1, 2)) == [3, 1, 2]
    assert to_jsonable([(1,), [2]]) == [[1], [2]]


def test_mapping_keys_are_stringified_and_sorted():
    assert list(to_jsonable({2: "b", 1: "a", 10: "c"})) == ["1", "10", "2"]


def test_an_enum_key_contributes_its_value_not_its_repr():
    """A JSON name is a value like any other: ``Colour.RED`` is ``red``,
    never ``"Colour.RED"`` (Phase 10, Step 4)."""
    assert to_jsonable({Colour.RED: 3}) == {"red": 3}
    assert to_jsonable({Level.ONE: 3}) == {"1": 3}


def test_a_key_type_with_no_rule_is_an_error():
    with pytest.raises(TypeError, match="no serialization rule for a float key"):
        to_jsonable({1.5: "a"})
    with pytest.raises(TypeError, match="no serialization rule for a tuple key"):
        to_jsonable({(1, 2): "a"})


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
    for marker in ("Decimal(", "object at 0x", "<crypto_simulator", "PricingMode.", "TradeAction.",
                   "WhaleBehavior."):
        assert marker not in text


def test_enum_keyed_analytics_mappings_carry_their_values():
    """``WhaleSummary.behavior_ticks`` is keyed by ``WhaleBehavior``."""
    from crypto_simulator.core.whale import WhaleBehavior
    from crypto_simulator.dashboard.data import SimulationParams, run_simulation

    report = run_simulation(SimulationParams(ticks=8, whale_observation=True)).report
    whale = report.whale_activity.whales[0].summary
    serialized = report_to_dict(report)["whale_activity"]["whales"][0]["summary"]
    assert set(serialized["behavior_ticks"]) == {b.value for b in WhaleBehavior}
    for behavior, ticks in whale.behavior_ticks.items():
        assert serialized["behavior_ticks"][behavior.value] == ticks


def test_report_to_dict_rejects_anything_else():
    with pytest.raises(TypeError, match="SimulationReport"):
        report_to_dict(analyze_market(()))
