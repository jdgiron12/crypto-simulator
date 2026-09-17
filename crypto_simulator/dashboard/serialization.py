"""The dashboard's serialization boundary (Phase 10, Step 1).

One job: turn the frozen analytics objects a finished run produces into
plain JSON-compatible Python (``dict``/``list``/``str``/``float``/``int``/
``bool``/``None``), so the dashboard never handles Python-specific objects
and the same payload could later cross a process boundary unchanged.

It is a *translation* layer, not an analytics layer: it reads declared
fields and converts their types. It computes no figure — no sum, ratio,
average or label — so every value it emits is exactly the value the
analytics put there, and a missing value stays missing.

**Conversion rules**, applied recursively and nowhere else:

===============================  ==========================================
``None``                         ``null``
``bool``                         ``true`` / ``false`` (checked before ``int``)
``int`` / ``str``                unchanged
``float``                        unchanged; a non-finite float is an error
``decimal.Decimal``              ``float`` (see below)
``enum.Enum``                    its ``value``, converted by these rules
frozen/plain dataclass instance  object of its *declared* fields, in
                                 declaration order
``tuple`` / ``list``             array, order preserved
``Mapping``                      object keyed by ``str(key)``, sorted by
                                 that key
anything else                    ``TypeError``
===============================  ==========================================

**Nothing is stringified as a fallback.** An unsupported type raises
``TypeError`` naming the offending path and type rather than emitting
``str(obj)``/``repr(obj)``, so an internal Python representation can never
reach the browser unnoticed. Properties are never evaluated: only fields
the dataclass declares are emitted, so a derived figure appears in a
payload only when the analytics declare it as a field.

**Determinism.** The rules depend only on the value, never on identity,
memory address, insertion order or the clock: mapping keys are sorted,
dataclass fields keep declaration order, and no identifier or timestamp is
invented. Equal inputs therefore always serialize to equal output.

**Decimals become floats.** The AMM's exact ``Decimal`` figures (pool
fees, price impact, exact flows) are converted with ``float()``, which is
deterministic but not exact. The ``SimulationReport`` itself remains the
exact source of truth; the serialized payload is a display copy. Nothing
in the simulator or the analytics reads this module.
"""

from __future__ import annotations

import math
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from crypto_simulator.analytics.report import SimulationReport

__all__ = ["to_jsonable", "report_to_dict"]

ROOT_PATH = "$"


def to_jsonable(value: Any, *, path: str = ROOT_PATH) -> Any:
    """Convert ``value`` to JSON-compatible Python by the module's rules.

    ``path`` names the position inside the structure (``$.market.ticks``
    style) and is only used to make errors locatable.

    Raises:
        TypeError: ``value`` (or something inside it) has no conversion
            rule, or a mapping's keys collide once converted to strings.
        ValueError: a ``float``/``Decimal`` is not finite, so it has no
            JSON representation.
    """
    if value is None:
        return None
    # Before the scalar check: a str/int Enum member is an instance of both.
    if isinstance(value, Enum):
        return to_jsonable(value.value, path=f"{path}.value")
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return _finite(value, path)
    if isinstance(value, Decimal):
        return _finite(float(value), path)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name), path=f"{path}.{field.name}")
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return _mapping(value, path)
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise TypeError(f"{path}: no serialization rule for {type(value).__name__}")


def report_to_dict(report: SimulationReport) -> dict[str, Any]:
    """Serialize a whole ``SimulationReport``.

    Every section is carried across as the analytics produced it — a
    section that is ``None`` (``event_windows`` without a timeline) stays
    ``null`` rather than becoming an empty object.
    """
    if not isinstance(report, SimulationReport):
        raise TypeError(f"expected a SimulationReport, got {type(report).__name__}")
    return to_jsonable(report, path=ROOT_PATH)


def _finite(number: float, path: str) -> float:
    if not math.isfinite(number):
        raise ValueError(f"{path}: {number} has no JSON representation")
    return number


def _mapping(value: Mapping, path: str) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key in sorted(value, key=str):
        name = str(key)
        if name in converted:
            raise TypeError(f"{path}: mapping keys {key!r} collide as {name!r} once stringified")
        converted[name] = to_jsonable(value[key], path=f"{path}.{name}")
    return converted
