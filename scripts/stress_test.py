#!/usr/bin/env python
"""Stress the simulator with demanding configurations (Phase 16).

    python scripts/stress_test.py                 # the ordinary cases
    python scripts/stress_test.py --heavy          # those plus the costly ones
    python scripts/stress_test.py --only amm       # cases whose name contains "amm"
    python scripts/stress_test.py --list           # what would run, without running it

Each case is a configuration the simulator already accepts — or one it
should refuse — run through the ordinary entry points and then checked
for completion, sane numbers and conserved accounting. Nothing here adds
a market mechanic or a limit; it exercises what is already there.

A case that is refused when it was meant to be refused counts as a pass.
The command exits non-zero if any case did something it should not have.
"""

from __future__ import annotations

import argparse
import sys

from crypto_simulator.stress import (
    STRESS_CASES,
    StressStatus,
    heavy_cases,
    light_cases,
    run_stress_suite,
)


def _selected(args) -> tuple:
    cases = STRESS_CASES if args.heavy else light_cases()
    if args.only:
        cases = tuple(case for case in cases if args.only in case.name)
    return cases


def _print_case(outcome) -> None:
    mark = {
        StressStatus.PASSED: "ok",
        StressStatus.REJECTED: "refused",
        StressStatus.FAILED: "FAILED",
    }[outcome.status]
    runs = outcome.runs_completed + outcome.runs_failed
    detail = f"{outcome.runs_completed}/{runs} runs" if runs > 1 else ""
    print(f"  {outcome.case.name:<34} {mark:<8} {outcome.seconds:>7.2f}s  {detail}")
    if outcome.status is StressStatus.REJECTED:
        print(f"      refused as expected: {outcome.error}")
    for finding in outcome.findings:
        print(f"      ! {finding}")
    if outcome.status is StressStatus.FAILED and outcome.error:
        print(f"      ! {outcome.error}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--heavy", action="store_true",
                        help="also run the costly cases (maximum ticks x traders, maximum batch)")
    parser.add_argument("--only", metavar="TEXT",
                        help="run only cases whose name contains TEXT")
    parser.add_argument("--list", action="store_true",
                        help="print the selected cases and exit without running them")
    args = parser.parse_args()

    cases = _selected(args)
    if not cases:
        parser.error(f"no stress case matches {args.only!r}")

    if args.list:
        print(f"{len(cases)} stress cases")
        for case in cases:
            tier = "heavy" if case.heavy else "light"
            print(f"  {case.name:<34} {tier:<6} {case.description}")
        return

    print(f"Stressing the simulator with {len(cases)} cases"
          + (f" ({len(heavy_cases())} heavy included)" if args.heavy else ""))
    print()
    report = run_stress_suite(cases)
    for outcome in report.outcomes:
        _print_case(outcome)

    print()
    print(f"  ran            : {len(report.outcomes)} cases in {report.seconds:.2f}s")
    print(f"  completed      : {len(report.passed)}")
    print(f"  refused        : {len(report.rejected)} (invalid configurations, as intended)")
    print(f"  failed         : {len(report.failed)}")
    print()
    if report.ok:
        print("These cases exercise selected demanding configurations within the")
        print("simulator's defined limits. They do not prove it correct elsewhere.")
    else:
        print("Some cases did something they should not have; see the ! lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
