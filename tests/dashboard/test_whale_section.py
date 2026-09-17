"""The whale dashboard section (Phase 10, Step 4).

Every figure on screen must be one the whale analytics produced, so the
checks format the report's own ``WhaleActivityReport`` (and the
``WhaleSummary`` it embeds) and compare strings. The interesting cases are
the ones the analytics deliberately keep apart: observation coverage
versus no activity, a recorded outcome versus an assumed one, a whale
without a target versus one at its target, and cohort co-fill, which is
co-occurrence and must not be described as anything stronger.

The rich world is built through the Python API because funded whales with
targets, cycles and cohorts are not reachable from the dashboard's run
options — but it is a real simulation, not a hand-written report.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics import build_report
from crypto_simulator.analytics.whale_activity import (
    COVERAGE_COMPLETE,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    AllocationGapStats,
    TargetReaching,
    WhaleActivity,
)
from crypto_simulator.analytics.whales import TICK_OUTCOMES, AllocationPath, WhaleSummary
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.whale import Whale
from crypto_simulator.core.whale_cohort import WhaleCohort
from crypto_simulator.dashboard import whale_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.serialization import report_to_dict
from crypto_simulator.dashboard.whale_section import (
    ALL_WHALES,
    ALLOCATION_DETAIL,
    AMM_MESSAGE,
    ACTIVITY_DETAIL,
    DETAIL_COLUMNS,
    GAP_DETAIL,
    NOT_OBSERVED_MESSAGE,
    NO_ACTIVITY_MESSAGE,
    NO_COHORTS_MESSAGE,
    NO_WHALES_MESSAGE,
    SUMMARY_DETAIL,
    TARGET_DETAIL,
    WHALE_SELECT_KEY,
)
from tests.core.test_coin_simulator_traders import _all_five, _coin

PRICE = ",.4f"
VOLUME = ",.0f"
NOTIONAL = ",.2f"
SIGNED_VOLUME = "+,.0f"
SIGNED_NOTIONAL = "+,.2f"
RATIO = ".2%"


def _whale_app(whales=None, simulation=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.whale_section import render_whales

    render_whales(whales, symbol="FIC", simulation=simulation)


def _render(whales: dict, simulation: dict | None = None) -> AppTest:
    return AppTest.from_function(
        _whale_app, kwargs={"whales": whales, "simulation": simulation}, default_timeout=60
    ).run()


def _metrics(at: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _captions(at: AppTest) -> str:
    return " ".join(caption.value for caption in at.caption)


def _rows(at: AppTest, index: int) -> list[dict[str, str]]:
    return at.dataframe[index].value.to_dict("records")


def _visible_text(at: AppTest) -> str:
    """Everything the reader can see: captions, headings, messages, metric
    labels and every table header and cell."""
    parts = [element.value for element in at.caption]
    parts += [element.value for element in at.markdown]
    parts += [element.value for element in at.info]
    parts += [metric.label for metric in at.metric]
    for index in range(at.dataframe.len):
        frame = at.dataframe[index].value
        parts += list(frame.columns)
        parts += [str(cell) for row in frame.to_dict("records") for cell in row.values()]
    return " ".join(parts).lower()


def _rich_ticks(ticks: int = 40):
    """A real run with the whale features the dashboard's own options
    cannot reach: funded whales with a target, pacing, a cycle and a
    two-member cohort."""
    whales = [
        Whale("legacy", 30_000.0, activity_probability=0.5, cooldown_ticks=2, seed=7),
        Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
              activity_probability=0.6, max_trade_fraction=0.01, min_trade_interval_ticks=1, seed=8),
        Whale("member-a", 20_000.0, starting_cash=150_000.0, activity_probability=0.8,
              max_trade_fraction=0.004, seed=9),
        Whale("member-b", 20_000.0, starting_cash=150_000.0, activity_probability=0.8,
              max_trade_fraction=0.004, seed=10),
    ]
    cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 5},
                                 {"behavior": "distribute", "duration": 5}],
                           ("member-a", "member-b"))]
    sim = CoinSimulator(_coin(), seed=42, whales=whales, whale_cohorts=cohorts,
                        traders=_all_five(seed_base=42), reserve_cash=500_000.0,
                        whale_observation=True)
    recorded = sim.run(ticks)
    return sim, recorded


def _report_for(sim, recorded):
    report = build_report(recorded, initial_price=sim.coin.starting_price,
                          total_supply=sim.coin.initial_supply)
    return report.whale_activity, report_to_dict(report)["whale_activity"]


@pytest.fixture(scope="module")
def dashboard_run():
    """What the dashboard's own options produce: one unfunded whale."""
    payload = run_simulation(SimulationParams(ticks=25, whale_observation=True))
    serialized = payload_to_dict(payload)
    return payload.report.whale_activity, serialized["report"]["whale_activity"], serialized["simulation"]


@pytest.fixture(scope="module")
def rich():
    sim, recorded = _rich_ticks()
    return _report_for(sim, recorded)


@pytest.fixture(scope="module")
def partial():
    """The same real ticks with the observations stripped from half of
    them — the analytics' 'partial coverage' case."""
    sim, recorded = _rich_ticks(20)
    mixed = [
        tick if tick.tick % 2 else dataclasses.replace(tick, whale_observations=())
        for tick in recorded
    ]
    return _report_for(sim, mixed)


# --- overview and coverage -------------------------------------------------------------------------------


def test_overview_totals_are_the_reports_own(rich):
    report, payload = rich
    shown = _metrics(_render(payload))
    assert shown["Whales listed"] == format(len(report.whales), ",d")
    assert shown["Whale volume"] == format(report.whale_volume, VOLUME)
    assert shown["Share of market volume"] == format(report.whale_volume_share_of_total, RATIO)
    assert shown["Share of participant volume"] == format(
        report.whale_volume_share_of_participants, RATIO
    )


def test_overview_captions_carry_the_market_context(rich):
    report, payload = rich
    captions = _captions(_render(payload))
    assert f"market volume {format(report.total_market_volume, VOLUME)}" in captions
    assert f"participant volume {format(report.participant_volume, VOLUME)}" in captions
    assert f"cohorts {format(len(report.cohorts), ',d')}" in captions


def test_complete_coverage_is_reported(rich):
    report, payload = rich
    assert report.coverage == COVERAGE_COMPLETE
    captions = _captions(_render(payload))
    assert f"observation coverage {COVERAGE_COMPLETE}" in captions
    assert f"observed ticks {report.observed_ticks:,d} of {report.ticks:,d}" in captions


def test_partial_coverage_is_reported_and_explained(partial):
    report, payload = partial
    assert report.coverage == COVERAGE_PARTIAL
    at = _render(payload)
    captions = _captions(at)
    assert f"observation coverage {COVERAGE_PARTIAL}" in captions
    assert f"observed ticks {report.observed_ticks:,d} of {report.ticks:,d}" in captions
    assert "an unobserved tick is not a tick without activity" in captions
    assert at.dataframe.len > 0  # the observed subset is still described


# --- per-whale activity ----------------------------------------------------------------------------------


def test_the_activity_table_has_one_row_per_whale_in_report_order(rich):
    report, payload = rich
    rows = _rows(_render(payload), 0)
    assert [row["Whale"] for row in rows] == [w.summary.whale_id for w in report.whales]


def test_activity_figures_are_the_reports_own(rich):
    report, payload = rich
    for row, activity in zip(_rows(_render(payload), 0), report.whales):
        summary = activity.summary
        assert row["Funded"] == ("yes" if summary.funded else "no")
        assert row["Cohort"] == (summary.cohort_id or "n/a")
        assert row["Observed ticks"] == format(summary.observed_ticks, ",d")
        assert row["Trades"] == format(summary.trade_count, ",d")
        assert row["Volume"] == format(summary.total_volume, VOLUME)
        assert row["VWAP"] == format(summary.vwap, PRICE)
        assert row["Net coins"] == format(summary.net_coin_flow, SIGNED_VOLUME)
        assert row["Net cash"] == format(summary.net_cash_flow, SIGNED_NOTIONAL)
        assert row["Share of whale volume"] == format(activity.volume_share_of_whale_volume, RATIO)
        assert row["First fill"] == str(activity.first_fill_tick)
        assert row["Last fill"] == str(activity.last_fill_tick)
        assert row["Average fill"] == format(activity.average_fill_size, VOLUME)


# --- recorded outcomes -----------------------------------------------------------------------------------


def test_the_outcome_columns_are_the_analytics_outcomes(rich):
    _, payload = rich
    headers = list(_rows(_render(payload), 1)[0])
    assert headers[1:1 + len(TICK_OUTCOMES)] == list(TICK_OUTCOMES)


def test_outcome_counts_are_the_recorded_ones(rich):
    report, payload = rich
    for row, activity in zip(_rows(_render(payload), 1), report.whales):
        for outcome in TICK_OUTCOMES:
            assert row[outcome] == format(activity.summary.outcome_ticks[outcome], ",d")


def test_pacing_blocks_are_shown_as_recorded(rich):
    """A whale the pacing rules stopped is recorded as blocked, not as
    inactive or as a whale that chose not to trade."""
    report, payload = rich
    rows = {row["Whale"]: row for row in _rows(_render(payload), 1)}
    blocked = [w for w in report.whales
               if w.summary.blocked_by_cooldown_ticks or w.summary.blocked_by_interval_ticks]
    assert blocked, "the rich world should exercise cooldown and interval pacing"
    for activity in blocked:
        row = rows[activity.summary.whale_id]
        assert row["blocked_by_cooldown"] == format(activity.summary.blocked_by_cooldown_ticks, ",d")
        assert row["blocked_by_interval"] == format(activity.summary.blocked_by_interval_ticks, ",d")
        assert row["inactive"] == format(activity.summary.inactive_ticks, ",d")


def test_behavior_and_cycle_ticks_are_the_recorded_mappings(rich):
    report, payload = rich
    for row, activity in zip(_rows(_render(payload), 1), report.whales):
        behaviors = activity.summary.behavior_ticks
        expected = ", ".join(
            f"{behavior.value} {ticks:,d}"
            for behavior, ticks in sorted(behaviors.items(), key=lambda item: item[0].value)
        )
        assert row["Behavior ticks"] == expected
        phases = activity.summary.phase_ticks
        if phases:
            assert row["Cycle phase ticks"] == ", ".join(
                f"{phase} {ticks:,d}" for phase, ticks in sorted(phases.items())
            )
        else:
            assert row["Cycle phase ticks"] == "none"


def test_a_cycling_whale_shows_its_phase_ticks(rich):
    report, payload = rich
    cycling = [w for w in report.whales if w.summary.phase_ticks]
    assert cycling, "the cohort members follow a cycle"
    rows = {row["Whale"]: row for row in _rows(_render(payload), 1)}
    assert rows[cycling[0].summary.whale_id]["Cycle phase ticks"] != "none"


# --- behavior --------------------------------------------------------------------------------------------


def test_the_behavior_table_is_the_reports_own(rich):
    report, payload = rich
    rows = _rows(_render(payload), 2)
    assert len(rows) == len(report.behaviors)
    for row, behavior in zip(rows, report.behaviors):
        assert row["Behavior"] == behavior.behavior.value
        assert row["Observation ticks"] == format(behavior.observation_ticks, ",d")
        assert row["Fills"] == format(behavior.fill_count, ",d")
        assert row["Buy volume"] == format(behavior.buy_volume, VOLUME)
        assert row["Sell volume"] == format(behavior.sell_volume, VOLUME)
        assert row["Total volume"] == format(behavior.total_volume, VOLUME)
        assert row["Net coins"] == format(behavior.net_coin_flow, SIGNED_VOLUME)


# --- allocation and targets ------------------------------------------------------------------------------


def test_allocation_figures_are_the_reports_own(rich):
    report, payload = rich
    targeted = [w for w in report.whales if w.summary.allocation
                and w.summary.allocation.target_coin_fraction is not None]
    assert targeted, "the rich world should include a whale managing a target"
    rows = {row["Whale"]: row for row in _rows(_render(payload), 3)}
    for activity in targeted:
        path, row = activity.summary.allocation, rows[activity.summary.whale_id]
        assert row["Target"] == format(path.target_coin_fraction, RATIO)
        assert row["First allocation"] == format(path.first_coin_fraction, RATIO)
        assert row["Last allocation"] == format(path.last_coin_fraction, RATIO)
        assert row["Mean allocation"] == format(path.mean_coin_fraction, RATIO)
        assert row["Ticks at target"] == format(path.ticks_at_target, ",d")
        assert row["Crossed target"] == ("yes" if path.crossed_target else "no")
        assert row["Dormant crossings"] == format(path.dormant_crossings, ",d")


def test_gap_and_target_reaching_figures_are_the_reports_own(rich):
    report, payload = rich
    rows = {row["Whale"]: row for row in _rows(_render(payload), 3)}
    for activity in report.whales:
        row = rows[activity.summary.whale_id]
        gap, reaching = activity.allocation_gap, activity.target_reaching
        if gap is None:
            assert row["Mean absolute gap"] == "n/a"
        else:
            assert row["Mean absolute gap"] == format(gap.mean_absolute_gap, RATIO)
            assert row["Max absolute gap"] == format(gap.max_absolute_gap, RATIO)
            assert row["Mean signed gap"] == format(gap.mean_signed_gap, RATIO)
        if reaching is None:
            assert row["Ticks observed at target"] == "n/a"
        else:
            assert row["Ticks observed at target"] == format(reaching.target_observation_count, ",d")
            assert row["First tick at target"] == (
                "n/a" if reaching.first_tick_at_target is None else str(reaching.first_tick_at_target)
            )


def test_a_whale_without_a_target_keeps_its_gaps(rich):
    report, payload = rich
    untargeted = [w for w in report.whales
                  if w.summary.allocation is None or w.summary.allocation.target_coin_fraction is None]
    assert untargeted
    rows = {row["Whale"]: row for row in _rows(_render(payload), 3)}
    for activity in untargeted:
        row = rows[activity.summary.whale_id]
        assert row["Target"] == "n/a"
        assert row["Ticks at target"] == "n/a"
        assert row["Crossed target"] == "n/a"


def test_an_unfunded_whale_has_no_allocation_record(dashboard_run):
    report, payload, _ = dashboard_run
    assert all(w.summary.allocation is None for w in report.whales)
    row = _rows(_render(payload), 3)[0]
    assert {row["Target"], row["First allocation"], row["Mean allocation"]} == {"n/a"}


# --- cohorts ---------------------------------------------------------------------------------------------


def test_cohort_activity_is_the_reports_own(rich):
    report, payload = rich
    assert report.cohorts
    rows = _rows(_render(payload), 4)
    assert [row["Cohort"] for row in rows] == [c.cohort_id for c in report.cohorts]
    for row, cohort in zip(rows, report.cohorts):
        assert row["Members"] == format(cohort.member_count, ",d")
        assert row["Active members"] == format(cohort.active_member_count, ",d")
        assert row["Observation ticks"] == format(cohort.observation_ticks, ",d")
        assert row["Fills"] == format(cohort.fill_count, ",d")
        assert row["Total volume"] == format(cohort.total_volume, VOLUME)
        assert row["Net coins"] == format(cohort.net_coin_flow, SIGNED_VOLUME)
        assert row["Share of whale volume"] == format(cohort.volume_share_of_whale_volume, RATIO)


def test_co_fill_statistics_are_the_reports_own(rich):
    report, payload = rich
    cohorts = [c for c in report.cohorts if c.co_fill is not None]
    assert cohorts, "a two-member cohort should have co-fill statistics"
    rows = {row["Cohort"]: row for row in _rows(_render(payload), 5)}
    for cohort in cohorts:
        row, stats = rows[cohort.cohort_id], cohort.co_fill
        assert row["Co-fill ratio"] == (
            "n/a" if stats.co_fill_ratio is None else format(stats.co_fill_ratio, RATIO)
        )
        assert row["Eligible member ticks"] == format(stats.eligible_member_ticks, ",d")
        assert row["Co-fill member ticks"] == format(stats.co_fill_member_ticks, ",d")
        assert row["Simultaneous fill ticks"] == format(stats.simultaneous_fill_ticks, ",d")
        assert row["Same-side simultaneous"] == format(stats.same_side_simultaneous_ticks, ",d")
        assert row["Mixed-side simultaneous"] == format(stats.mixed_side_simultaneous_ticks, ",d")


def test_co_fill_is_described_as_co_occurrence(rich):
    _, payload = rich
    captions = _captions(_render(payload))
    assert "describes co-occurrence" in captions
    assert "not one whale moving another" in captions


def test_the_visible_wording_stays_descriptive(rich):
    """What a reader sees must describe what was recorded, never claim one
    whale moved another or that co-fill is herding."""
    _, payload = rich
    shown = _visible_text(_render(payload))
    for word in ("herding", "social influence", "influenced", "caused", "contagion",
                 "drove", "predicts", "recommend"):
        assert word not in shown


def test_a_run_without_cohorts_says_so(dashboard_run):
    report, payload, _ = dashboard_run
    assert report.cohorts == ()
    at = _render(payload)
    assert NO_COHORTS_MESSAGE in _captions(at)
    assert at.dataframe.len == 4  # activity, outcomes, behavior, allocation


# --- detail and selection --------------------------------------------------------------------------------


def test_the_selector_lists_every_whale(rich):
    report, payload = rich
    at = _render(payload)
    assert list(at.selectbox[0].options) == [
        ALL_WHALES, *[w.summary.whale_id for w in report.whales]
    ]
    assert at.table.len == 0


def test_selecting_a_whale_shows_its_recorded_figures(rich):
    report, payload = rich
    activity = next(w for w in report.whales if w.summary.allocation is not None)
    at = _render(payload)
    at.selectbox(key=WHALE_SELECT_KEY).set_value(activity.summary.whale_id).run()

    frame = at.table[0].value
    detail = dict(zip(frame.index, frame[DETAIL_COLUMNS[1]]))
    summary = activity.summary
    assert detail["Whale"] == summary.whale_id
    assert detail["Funded"] == ("yes" if summary.funded else "no")
    assert detail["Trades"] == format(summary.trade_count, ",d")
    assert detail["Notional"] == format(summary.notional, NOTIONAL)
    assert detail["VWAP"] == format(summary.vwap, PRICE)
    assert detail["Share of whale volume"] == format(activity.volume_share_of_whale_volume, RATIO)
    assert detail["Target coin fraction"] == format(summary.allocation.target_coin_fraction, RATIO)
    assert detail["Maximum absolute gap"] == format(summary.allocation.max_abs_gap, RATIO)
    for outcome in TICK_OUTCOMES:
        assert detail[f"Ticks {outcome}"] == format(summary.outcome_ticks[outcome], ",d")


def test_the_detail_view_covers_every_recorded_field():
    """A new analytics field must surface rather than be dropped."""
    nested = {"summary", "allocation_gap", "target_reaching"}
    activity_fields = {f.name for f in dataclasses.fields(WhaleActivity)} - nested
    assert {field for _, field, _ in ACTIVITY_DETAIL} == activity_fields

    expanded = {"allocation", "behavior_ticks", "phase_ticks", "outcome_ticks"}
    summary_fields = {f.name for f in dataclasses.fields(WhaleSummary)} - expanded
    assert {field for _, field, _ in SUMMARY_DETAIL} == summary_fields

    assert {field for _, field, _ in ALLOCATION_DETAIL} == {
        f.name for f in dataclasses.fields(AllocationPath)
    }
    assert {field for _, field, _ in GAP_DETAIL} == {
        f.name for f in dataclasses.fields(AllocationGapStats)
    }
    assert {field for _, field, _ in TARGET_DETAIL} == {
        f.name for f in dataclasses.fields(TargetReaching)
    }


def test_an_unfunded_whales_detail_keeps_its_gaps(dashboard_run):
    _, payload, _ = dashboard_run
    at = _render(payload)
    at.selectbox(key=WHALE_SELECT_KEY).set_value("whale-1").run()
    frame = at.table[0].value
    detail = dict(zip(frame.index, frame[DETAIL_COLUMNS[1]]))
    assert detail["Funded"] == "no"
    assert detail["Target coin fraction"] == "n/a"
    assert detail["Gap samples"] == "n/a"
    assert detail["Cohort"] == "n/a"


def test_a_stale_selection_falls_back_to_the_overview(rich):
    _, payload = rich
    at = AppTest.from_function(
        _whale_app, kwargs={"whales": payload, "simulation": None}, default_timeout=60
    )
    at.session_state[WHALE_SELECT_KEY] = "whoever"
    at.run()
    assert not at.exception
    assert at.table.len == 0
    assert at.selectbox[0].value == ALL_WHALES


def test_selecting_a_whale_runs_no_simulation():
    def dashboard(runner=None):
        from crypto_simulator.dashboard.view import render_dashboard

        render_dashboard(runner=runner)

    runs = []

    def counting_runner(params):
        runs.append(params)
        return run_simulation(params)

    at = AppTest.from_function(dashboard, kwargs={"runner": counting_runner}, default_timeout=90).run()
    at.number_input(key="coin_dashboard_ticks").set_value(8)
    at.checkbox(key="coin_dashboard_whale_observation").set_value(True)
    at.button(key="coin_dashboard_run").click().run()
    assert len(runs) == 1
    before = at.session_state["coin_dashboard_payload"]

    at.selectbox(key=WHALE_SELECT_KEY).set_value("whale-1").run()
    assert len(runs) == 1
    assert at.session_state["coin_dashboard_payload"] == before
    assert at.table.len > 0


# --- unavailable states ----------------------------------------------------------------------------------


def _section_for(params: SimulationParams):
    serialized = payload_to_dict(run_simulation(params))
    return serialized["report"]["whale_activity"], serialized["simulation"]


def test_a_run_without_whales_says_so():
    whales, simulation = _section_for(SimulationParams(ticks=6, include_whales=False))
    at = _render(whales, simulation)
    assert NO_WHALES_MESSAGE in [info.value for info in at.info]
    assert at.metric.len == 0 and at.dataframe.len == 0


def test_an_amm_run_says_whales_are_unsupported():
    whales, simulation = _section_for(
        SimulationParams(ticks=6, pricing_mode="amm", include_whales=False)
    )
    at = _render(whales, simulation)
    assert AMM_MESSAGE in [info.value for info in at.info]
    assert at.dataframe.len == 0


def test_an_unobserved_run_is_not_reported_as_no_activity():
    """Whales traded; the run just did not record observations."""
    whales, simulation = _section_for(SimulationParams(ticks=6, whale_observation=False))
    at = _render(whales, simulation)
    assert NOT_OBSERVED_MESSAGE in [info.value for info in at.info]
    assert f"observation coverage {COVERAGE_NONE}" in _captions(at)


def test_without_run_metadata_the_message_stays_neutral():
    whales, _ = _section_for(SimulationParams(ticks=6, include_whales=False))
    at = _render(whales, None)
    assert NO_ACTIVITY_MESSAGE in [info.value for info in at.info]


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=1, whale_observation=True),
        SimulationParams(ticks=3, whale_observation=True, events=True),
        SimulationParams(ticks=3, whale_observation=True, include_traders=False),
        SimulationParams(ticks=5, whale_observation=True, psychology=True),
    ],
    ids=["one-tick", "events", "no-traders", "psychology"],
)
def test_the_section_renders_for_sparse_runs(params):
    whales, simulation = _section_for(params)
    at = _render(whales, simulation)
    assert not at.exception


# --- determinism and structure ---------------------------------------------------------------------------


def test_the_same_payload_renders_the_same_tables(rich):
    _, payload = rich
    first, second = _render(payload), _render(payload)
    assert [_rows(first, i) for i in range(first.dataframe.len)] == [
        _rows(second, i) for i in range(second.dataframe.len)
    ]
    assert _metrics(first) == _metrics(second)


BANNED_CALLS = {"analyze_whales", "analyze_whale_activity", "analyze_market", "build_report",
                "fsum", "sum", "round", "abs", "min", "max", "sorted"}


def _calls(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


def _arithmetic(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text())
    return [
        type(node.op).__name__
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod))
    ]


def test_the_whale_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(whale_section)


def test_the_whale_section_does_no_arithmetic():
    """Only `len` of the rows it is about to draw; every whale figure
    arrives computed."""
    assert _arithmetic(whale_section) == []
