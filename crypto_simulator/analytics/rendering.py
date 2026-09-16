"""Plain-text rendering of a ``SimulationReport`` (Phase 9, Step 8b).

Presentation only. ``render_report`` formats values that already exist on
the report — it calls no analytics function, reads no simulator object,
and computes no figure (no sums, ratios or averages of its own), so every
number shown is exactly the one the report holds. The same report always
renders to the same string: no timestamps, identifiers or ordering that
could vary between runs.

Missing data is shown as missing. A ``None`` renders as ``n/a`` (or a
sentence saying why the section is unavailable), never as zero; a zero the
analytics define as zero renders as zero. Wording stays descriptive: values
are "observed", "recorded" or "during", and nothing here states or implies
that one thing moved another, or what happens next.
"""

from __future__ import annotations

from typing import Iterable

from crypto_simulator.analytics.events import MIN_VOLATILITY_RETURNS
from crypto_simulator.analytics.regimes import MIN_REFERENCE_WINDOWS
from crypto_simulator.analytics.report import SimulationReport

RULE = "=============================================================================="
_SUB = "------------------------------------------------------------------------------"


def render_report(report: SimulationReport) -> str:
    """The whole report as one string, sections in a fixed order."""
    lines: list[str] = []
    for section in (_header, _market, _traders, _whales, _events, _psychology, _manipulation, _regimes):
        lines.extend(section(report))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# --- formatting helpers -----------------------------------------------------------------------------------


def _num(value, spec: str = ",.4f") -> str:
    return "n/a" if value is None else format(value, spec)


def _pct(value, spec: str = "+.2%") -> str:
    return "n/a" if value is None else format(value, spec)


def _tick(value) -> str:
    return "n/a" if value is None else str(value)


def _span(first, last) -> str:
    if first is None:
        return "none"
    return f"{first}" if first == last else f"{first}-{last}"


def _title(name: str, note: str) -> list[str]:
    return [name, f"  ({note})", _SUB]


def _row(label: str, value: str) -> str:
    return f"  {label:<24} {value}"


def _join(values: Iterable[str]) -> str:
    joined = ", ".join(values)
    return joined or "none"


# --- sections --------------------------------------------------------------------------------------------


def _header(report: SimulationReport) -> list[str]:
    market = report.market
    requested = ""
    if report.start_tick is not None or report.end_tick is not None:
        requested = f" (requested ticks {_tick(report.start_tick)}-{_tick(report.end_tick)})"
    return [
        RULE,
        "SIMULATION REPORT",
        "Descriptive observations of a finished synthetic run. Not a prediction,",
        "a recommendation or a trading signal, and no figure states a cause.",
        RULE,
        _row("ticks analysed", f"{report.ticks}{requested}"),
        _row("tick range", _span(market.first_tick, market.last_tick)),
        _row("pricing mode", market.pricing_mode or "n/a"),
    ]


def _market(report: SimulationReport) -> list[str]:
    m = report.market
    lines = _title("MARKET", "recorded prices and volume")
    if m.ticks == 0:
        return lines + ["  no ticks were analysed"]
    v = m.volume_breakdown
    recovery = "not recovered" if m.recovery_tick is None else f"recovered tick {m.recovery_tick}"
    drawdown = _pct(m.max_drawdown, ".2%")
    if m.drawdown_peak_tick is not None:
        drawdown = f"{drawdown} (peak tick {m.drawdown_peak_tick}, trough tick {m.drawdown_trough_tick}, {recovery})"
    background = "n/a (AMM mode)" if v.background_volume is None else _num(v.background_volume, ",.0f")
    lines += [
        _row("open / close", f"{_num(m.open_price)} / {_num(m.close_price)}"),
        _row("return", f"{_pct(m.cumulative_return)} (log {_num(m.log_return, '+.4f')})"),
        _row("high", f"{_num(m.high_price)} at tick {_tick(m.high_tick)}"),
        _row("low", f"{_num(m.low_price)} at tick {_tick(m.low_tick)}"),
        _row("volatility", f"{_num(m.volatility)} per tick (realized {_num(m.realized_volatility)}, "
                           f"{m.return_count} returns)"),
        _row("max drawdown", drawdown),
        _row("drawdown at close", _pct(m.end_drawdown, ".2%")),
        _row("missing ticks", str(m.missing_tick_count)),
        _row("total volume", _num(v.total_volume, ",.0f")),
        _row("  background", background),
        _row("  whale", _num(v.whale_volume, ",.0f")),
        _row("  organic traders", _num(v.organic_volume, ",.0f")),
        _row("  manipulators", _num(v.manipulator_volume, ",.0f")),
        _row("  wash legs", _num(v.wash_volume, ",.0f")),
        _row("turnover", "n/a (no total supply given)" if m.turnover is None
             else f"{_pct(m.turnover, '.2%')} (participants {_pct(m.participant_turnover, '.2%')})"),
        _row("trader VWAP", _num(m.trader_vwap)),
    ]
    if m.pool_activity is not None:
        pool = m.pool_activity
        lines.append(_row("AMM swaps", f"{pool.swap_count}, fees {_num(pool.fees_cash, ',.4f')} cash + "
                                       f"{_num(pool.fees_coins, ',.4f')} coins"))
    return lines


def _traders(report: SimulationReport) -> list[str]:
    t = report.traders
    lines = _title("TRADERS", "recorded fills; wash legs reported apart")
    if t.population == 0:
        return lines + ["  no trader activity recorded"]
    if t.pricing_mode == "amm":
        fees = f"{_num(t.fees_paid_cash)} cash + {_num(t.fees_paid_coins)} coins"
    else:
        fees = "n/a (random-walk mode has no swap fees)"
    if t.pnl is None:
        pnl = "n/a (no wallet balances supplied)"
    else:
        pnl = (f"{_num(t.pnl, '+,.2f')} (equity {_num(t.start_equity, ',.2f')} -> {_num(t.end_equity, ',.2f')}, "
               f"return {_pct(t.equity_return)})")
    lines += [
        _row("traders active", f"{t.active_traders} of {t.population} ({_pct(t.participation_rate, '.0%')})"),
        _row("fills", str(t.fill_count)),
        _row("buy / sell / wash volume",
             f"{_num(t.buy_volume, ',.0f')} / {_num(t.sell_volume, ',.0f')} / {_num(t.wash_volume, ',.0f')}"),
        _row("total volume", f"{_num(t.total_volume, ',.0f')} (notional {_num(t.total_notional, ',.2f')})"),
        _row("VWAP", _num(t.vwap)),
        _row("fees paid", fees),
        _row("combined P&L", pnl),
        "",
        f"  {'strategy':<18} {'traders':>9} {'fills':>7} {'volume':>12} {'net coins':>12} {'P&L':>13}",
    ]
    for s in t.strategies:
        label = s.strategy or "(balances only)"
        if s.is_manipulation_strategy:
            label = f"{label} *"
        lines.append(f"  {label:<18} {s.active_trader_count:>4} of {s.trader_count:<2} {s.fill_count:>7} "
                     f"{_num(s.total_volume, ',.0f'):>12} {_num(s.net_coin_flow, '+,.0f'):>12} "
                     f"{_num(s.pnl, '+,.2f'):>13}")
    if any(s.is_manipulation_strategy for s in t.strategies):
        lines.append("  * registered manipulation strategy")
    return lines


def _whales(report: SimulationReport) -> list[str]:
    w = report.whale_activity
    lines = _title("WHALE ACTIVITY", "recorded whale observations; descriptive only")
    if w.coverage == "none":
        return lines + ["  no whale observations recorded (whale volume is still counted under MARKET)"]
    lines += [
        _row("observation coverage", f"{w.coverage} ({w.observed_ticks} of {w.ticks} ticks)"),
        _row("whale volume", f"{_num(w.whale_volume, ',.0f')} ({_pct(w.whale_volume_share_of_total, '.1%')} of total, "
                             f"{_pct(w.whale_volume_share_of_participants, '.1%')} of participant volume)"),
        "",
        f"  {'whale':<14} {'cohort':<8} {'fills':>6} {'buy':>10} {'sell':>10} {'net coins':>11}  "
        f"{'fill ticks':<10} target",
    ]
    for activity in w.whales:
        s = activity.summary
        path = activity.summary.allocation
        if path is None:
            target = "unfunded" if not s.funded else "n/a"
        elif path.target_coin_fraction is None:
            target = f"none (coin share {_num(path.last_coin_fraction, '.3f')})"
        else:
            reached = activity.target_reaching
            first = "not reached" if reached is None or reached.first_tick_at_target is None \
                else f"first at tick {reached.first_tick_at_target}"
            target = (f"{_num(path.target_coin_fraction, '.3f')} (share {_num(path.last_coin_fraction, '.3f')}, "
                      f"{first})")
        lines.append(f"  {s.whale_id:<14} {activity.cohort_id or '-':<8} {s.trade_count:>6} "
                     f"{_num(s.buy_volume, ',.0f'):>10} {_num(s.sell_volume, ',.0f'):>10} "
                     f"{_num(s.net_coin_flow, '+,.0f'):>11}  {_span(activity.first_fill_tick, activity.last_fill_tick):<10} "
                     f"{target}")
    lines.append("  behavior in force:")
    for b in w.behaviors:
        lines.append(f"    {b.behavior.value:<11} {b.observation_ticks:>5} whale-ticks, {b.fill_count:>4} fills, "
                     f"volume {_num(b.total_volume, ',.0f')}, net {_num(b.net_coin_flow, '+,.0f')}")
    for c in w.cohorts:
        co_fill = "n/a (one member)" if c.co_fill is None else _pct(c.co_fill.co_fill_ratio, ".0%")
        lines.append(f"  cohort {c.cohort_id}: {c.active_member_count} of {c.member_count} members filled, "
                     f"{c.fill_count} fills, volume {_num(c.total_volume, ',.0f')}, same-tick fills {co_fill}")
    return lines


def _events(report: SimulationReport) -> list[str]:
    lines = _title("EVENT WINDOWS", "market observed around each event's ground-truth lifecycle; not attributed")
    e = report.event_windows
    if e is None:
        return lines + ["  unavailable: no event timeline was supplied"]
    if not e.events:
        return lines + ["  no events started within the analysed ticks"]
    for path in e.events:
        g = path.ground_truth
        source = {True: "random", False: "scheduled", None: "provenance unknown"}[g.randomly_generated]
        decay = "no decay" if path.decay is None else f"decay ticks {path.decay.requested_start}-{path.decay.requested_end}"
        lines.append(f"  {g.event_id} ({g.category}, {source}): severity {g.severity:.2f}, "
                     f"sentiment {g.sentiment:+.2f}, active ticks {g.start_tick}-{g.last_active_tick}, {decay}")
        returns = []
        for label, window in (("before", path.pre_event), ("during", path.active), ("decay", path.decay),
                              ("after", path.post_event)):
            if window is None:
                continue
            note = "" if window.complete else f" [{window.ticks_observed}/{window.ticks_requested} ticks]"
            returns.append(f"{label} {_pct(window.market.cumulative_return)}{note}")
        lines.append(f"    return observed: {'; '.join(returns)}")
        lines.append(f"    volatility during {_num(path.active.market.volatility)}, "
                     f"overlapping events: {_join(path.overlapping_event_ids)}")
    return lines


def _psychology(report: SimulationReport) -> list[str]:
    p = report.psychology_market
    lines = _title("PSYCHOLOGY", "recorded market-wide state alongside the market; co-movement, not cause")
    if p.coverage == "none":
        return lines + ["  unavailable: no psychology was recorded"]
    lines += [
        _row("coverage", f"{p.coverage} ({p.ticks_with_psychology} of {p.ticks} ticks, "
                         f"ticks {_span(p.first_psychology_tick, p.last_psychology_tick)})"),
        f"  {'component':<12} {'mean':>6} {'median':>7} {'p90':>6} {'max':>6}   share of ticks at or above",
    ]
    for c in p.components:
        shares = "  ".join(f">={o.threshold:.2f} {o.share:.0%}" for o in c.occupancy)
        lines.append(f"  {c.component:<12} {c.mean:>6.3f} {c.median:>7.3f} {c.p90:>6.3f} {c.maximum:>6.3f}   {shares}")
    lines.append("  Pearson correlations with the market (paired ticks; lag 1 = market one tick later):")
    for r in p.correlations:
        value = f"{r.value:+.3f}" if r.value is not None else f"n/a ({r.unavailable_reason.replace('_', ' ')})"
        lines.append(f"    {r.x:<12} vs {r.y:<20} lag {r.lag}  {value:<28} pairs {r.pairs}")
    return lines


def _manipulation(report: SimulationReport) -> list[str]:
    m = report.manipulation
    lines = _title("MANIPULATION", "fills recorded by registered manipulation strategies; descriptive only")
    if m.coverage == "none":
        return lines + ["  no manipulation fills recorded"]
    lines += [
        _row("kinds observed", f"{m.coverage} (pump-and-dump: {'yes' if m.pump_and_dump else 'no'}, "
                               f"wash: {'yes' if m.wash.fill_count else 'no'})"),
        _row("manipulation volume", f"{_num(m.manipulation_volume, ',.0f')} "
                                    f"({_pct(m.manipulation_share_of_total, '.1%')} of total volume)"),
        _row("pump-and-dump volume", f"{_num(m.pump_and_dump_volume, ',.0f')} "
                                     f"({_pct(m.manipulation_share_of_participants, '.1%')} of participant volume)"),
        _row("active ticks", f"{m.active_ticks} (ticks {_span(m.first_tick, m.last_tick)})"),
    ]
    for p in m.pump_and_dump:
        lines.append(f"  {p.trader_id}: recorded phases")
        for label, fills, volume, first, last in (
                ("accumulate", p.accumulation_fills, p.accumulation_volume, p.first_accumulation_tick,
                 p.last_accumulation_tick),
                ("pump", p.pump_fills, p.pump_volume, p.pump_start_tick, p.pump_end_tick),
                ("dump", p.dump_fills, p.dump_volume, p.dump_start_tick, p.dump_end_tick)):
            lines.append(f"    {label:<10} {fills:>4} fills, volume {_num(volume, ',.0f'):>10}, ticks {_span(first, last)}")
        pm = p.market
        lines.append(f"    price over ticks {p.first_tick}-{p.last_tick}: {_num(pm.open_price)} -> {_num(pm.close_price)} "
                     f"({_pct(pm.cumulative_return)}), high {_num(pm.high_price)} at tick {_tick(pm.high_tick)}, "
                     f"max drawdown {_pct(pm.max_drawdown, '.2%')}")
    if m.wash.fill_count:
        w = m.wash
        lines.append(_row("wash legs", f"{w.fill_count} (buy {_num(w.buy_volume, ',.0f')} / "
                                       f"sell {_num(w.sell_volume, ',.0f')}), {w.active_ticks} ticks "
                                       f"({_span(w.first_tick, w.last_tick)})"))
    return lines


def _regimes(report: SimulationReport) -> list[str]:
    r = report.regimes
    lines = _title("REGIMES", f"observed conditions per {r.window_size}-tick window; describes the past only")
    if not r.observations:
        return lines + ["  no windows: no ticks were analysed"]
    lines += [
        _row("windows", f"{r.total_windows} ({r.complete_windows} complete, {r.incomplete_windows} incomplete)"),
        f"  {'ticks':<11} {'n':>3}  {'direction':<10} {'volatility':<18} {'volume':<14} state",
    ]
    for o in r.observations:
        ticks = f"{o.start_tick}-{o.end_tick}"
        n = f"{o.tick_count}" if o.complete else f"{o.tick_count}*"
        lines.append(f"  {ticks:<11} {n:>3}  {o.direction or 'n/a':<10} {o.volatility or 'n/a':<18} "
                     f"{o.volume or 'n/a':<14} {o.market_state or 'n/a'}")
    if r.incomplete_windows:
        lines.append("  * incomplete window")
    lines.append(f"  n/a: direction needs {MIN_VOLATILITY_RETURNS} returns in the window; volatility and volume "
                 f"need {MIN_REFERENCE_WINDOWS} earlier complete windows")
    for label, counts in (("direction", r.direction_counts), ("volatility", r.volatility_counts),
                          ("volume", r.volume_counts), ("state", r.market_state_counts)):
        tallies = ", ".join(f"{name or 'n/a'} {count}" for name, count in counts)
        lines.append(f"  {f'{label}:':<11} {tallies}")
    return lines
