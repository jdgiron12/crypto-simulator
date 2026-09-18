"""What "the run came out intact" means (Phase 16).

Every check here is expressed in the simulator's own semantics rather
than in assumptions about what a market ought to look like: a price is
valid if ``analytics._series.is_valid_price`` says so, a figure is
missing if the analytics recorded ``None``, and conservation is the
equality the demo CLI already prints. None of these checks recompute a
metric — they read what the run produced and say whether it is possible.

Each function returns findings: an empty tuple means nothing wrong was
found, and each string names one thing that was.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from crypto_simulator.analytics._series import is_valid_price
from crypto_simulator.dashboard.data import payload_to_dict

__all__ = [
    "RANDOM_WALK_CONSERVATION_TOLERANCE",
    "check_accounting",
    "check_payload",
]

#: How far the float-wallet bookkeeping may drift over a run and still be
#: rounding rather than loss.
#:
#: AMM mode settles every fill in ``Decimal`` and conserves *exactly*, so
#: it is held to equality. Random-walk mode settles float wallets against
#: a float reserve, where a long run accumulates representation error —
#: the README says as much. This bound is relative and far tighter than
#: any real leak: a hundred thousand fills drift around 1e-17 of the
#: total, so 1e-9 catches a bug while never tripping on arithmetic.
RANDOM_WALK_CONSERVATION_TOLERANCE = Decimal("1e-9")

#: Report fields that are prices, and must look like prices when present.
_PRICE_FIELDS = ("open_price", "close_price", "high_price", "low_price", "mean_price")

#: Report fields that count or measure something and cannot be negative.
_NON_NEGATIVE_FIELDS = (
    "ticks",
    "missing_tick_count",
    "return_count",
    "volatility",
    "realized_volatility",
    "market_cap_start",
    "market_cap_end",
    "average_trade_size",
    "turnover",
    "participant_turnover",
)


def check_payload(payload: Any, *, requested_ticks: int) -> tuple[str, ...]:
    """Everything that must hold of one finished run.

    The first check is the strongest and the cheapest: serializing the
    payload runs it through the dashboard's serialization boundary, which
    refuses a non-finite float anywhere in the report. A run carrying a
    NaN or an infinity therefore cannot pass, wherever it hid.
    """
    findings: list[str] = []
    try:
        data = payload_to_dict(payload)
    except (ValueError, TypeError) as exc:
        return (f"the run's own report is not representable, so a value is not finite: {exc}",)

    simulation, report = data["simulation"], data["report"]
    market = report["market"]

    if simulation["completed_ticks"] != requested_ticks:
        findings.append(
            f"completed {simulation['completed_ticks']} of {requested_ticks} requested ticks"
        )
    if simulation["requested_ticks"] != requested_ticks:
        findings.append(
            f"the run recorded {simulation['requested_ticks']} requested ticks, not {requested_ticks}"
        )
    if report["ticks"] != requested_ticks:
        findings.append(f"the report analysed {report['ticks']} ticks, not {requested_ticks}")
    if len(data["price_series"]) != requested_ticks:
        findings.append(
            f"the price series has {len(data['price_series'])} points, not {requested_ticks}"
        )

    findings.extend(_price_findings(market))
    findings.extend(_non_negative_findings(market))
    findings.extend(_series_findings(data["price_series"]))
    findings.extend(_volume_findings(market["volume_breakdown"]))
    return tuple(findings)


def _price_findings(market: dict[str, Any]) -> Iterable[str]:
    for name in _PRICE_FIELDS:
        value = market.get(name)
        if value is not None and not is_valid_price(value):
            yield f"{name} is not a valid price ({value!r})"
    high, low = market.get("high_price"), market.get("low_price")
    if high is not None and low is not None and high < low:
        yield f"high_price {high} is below low_price {low}"


def _non_negative_findings(market: dict[str, Any]) -> Iterable[str]:
    for name in _NON_NEGATIVE_FIELDS:
        value = market.get(name)
        if value is not None and value < 0:
            yield f"{name} is negative ({value!r})"
    drawdown = market.get("max_drawdown")
    if drawdown is not None and not 0.0 <= drawdown <= 1.0:
        # A drawdown is a fraction of a peak; outside [0, 1] it is not one.
        yield f"max_drawdown is outside [0, 1] ({drawdown!r})"


def _series_findings(series: list[dict[str, Any]]) -> Iterable[str]:
    ticks = [point["tick"] for point in series]
    if ticks != sorted(ticks):
        yield "the recorded price series is not in tick order"
    if len(set(ticks)) != len(ticks):
        yield "the recorded price series repeats a tick"
    for point in series:
        if not is_valid_price(point["price"]):
            yield f"tick {point['tick']} recorded an impossible price ({point['price']!r})"
        if point["volume"] < 0:
            yield f"tick {point['tick']} recorded negative volume ({point['volume']!r})"
        if point["market_cap"] < 0:
            yield f"tick {point['tick']} recorded negative market cap ({point['market_cap']!r})"


def _volume_findings(volume: dict[str, Any]) -> Iterable[str]:
    for name, value in volume.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
            yield f"volume_breakdown.{name} is negative ({value!r})"


def check_accounting(
    before: tuple[Decimal, Decimal] | None,
    after: tuple[Decimal, Decimal] | None,
    *,
    pricing_mode: str,
) -> tuple[str, ...]:
    """Coins and cash must still add up to what the run started with.

    Read through ``CoinSimulator.accounting_totals``, the simulator's own
    exact ``Decimal`` tally, captured at construction and again at the
    end. AMM mode settles in ``Decimal`` and must match exactly; random
    walk settles float wallets and is allowed representation drift within
    ``RANDOM_WALK_CONSERVATION_TOLERANCE``, which is what the CLI's own
    accounting check reports the same way.
    """
    if before is None or after is None:
        return ("the run's accounting totals were never captured",)

    findings = []
    for index, label in enumerate(("coins", "cash")):
        start, end = before[index], after[index]
        if start == end:
            continue
        if pricing_mode == "amm":
            findings.append(f"{label} not conserved exactly in AMM mode: {start} -> {end}")
            continue
        scale = abs(start) if start else Decimal(1)
        drift = abs(end - start) / scale
        if drift > RANDOM_WALK_CONSERVATION_TOLERANCE:
            findings.append(
                f"{label} drifted by {drift:.3e} of the total ({start} -> {end}), "
                f"beyond rounding"
            )
    return tuple(findings)
