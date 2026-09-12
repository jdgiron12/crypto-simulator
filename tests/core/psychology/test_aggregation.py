"""The Step 3 helpers that feed ``compute_psychology`` from simulator data:
``aggregate_event_severity`` and ``signals_from_closes``."""

import itertools
import math
import random

import pytest

from crypto_simulator.core.psychology import MarketSignals, aggregate_event_severity, signals_from_closes

# --- aggregate_event_severity ------------------------------------------------------------------


def test_no_live_events_means_zero_severity():
    assert aggregate_event_severity([]) == 0.0
    assert aggregate_event_severity(iter(())) == 0.0


def test_one_live_event_is_its_severity_at_its_current_intensity():
    assert aggregate_event_severity([(0.7, 1.0)]) == 0.7
    assert aggregate_event_severity([(0.8, 0.5)]) == 0.8 * 0.5
    assert aggregate_event_severity([(0.8, 0.0)]) == 0.0


def test_overlapping_events_take_the_strongest_rather_than_adding_up():
    assert aggregate_event_severity([(0.9, 1.0), (0.8, 1.0), (0.7, 1.0)]) == 0.9
    assert aggregate_event_severity([(1.0, 1.0)] * 5) == 1.0
    # A big event that has mostly faded is weaker than a fresh small one.
    assert aggregate_event_severity([(1.0, 0.25), (0.5, 1.0)]) == 0.5


def test_a_stronger_or_less_decayed_event_is_never_less_severe():
    severities = [aggregate_event_severity([(s, 1.0), (0.3, 1.0)]) for s in (0.1, 0.3, 0.5, 0.9, 1.0)]
    assert severities == sorted(severities) and severities[0] < severities[-1]
    fading = [aggregate_event_severity([(0.8, i)]) for i in (1.0, 0.75, 0.5, 0.25, 0.0)]
    assert fading == sorted(fading, reverse=True)


def test_the_aggregate_is_order_independent_and_bounded():
    rng = random.Random(7)
    for _ in range(200):
        pairs = [(rng.random(), rng.random()) for _ in range(rng.randint(1, 5))]
        result = aggregate_event_severity(pairs)
        assert 0.0 <= result <= 1.0
        assert all(aggregate_event_severity(p) == result for p in itertools.permutations(pairs))


@pytest.mark.parametrize(
    "pair, name",
    [((1.1, 1.0), "severity"), ((-0.1, 1.0), "severity"), ((math.nan, 1.0), "severity"),
     ((0.5, 1.5), "intensity"), ((0.5, -0.5), "intensity"), ((0.5, math.inf), "intensity")],
)
def test_out_of_range_pairs_are_rejected(pair, name):
    with pytest.raises(ValueError, match=name):
        aggregate_event_severity([pair])


# --- signals_from_closes -------------------------------------------------------------------------


def test_a_single_close_gives_neutral_price_signals():
    assert signals_from_closes([2.0]) == MarketSignals()


def test_price_signals_follow_their_documented_definitions():
    closes = [1.0, 1.1, 0.99, 1.2]
    signals = signals_from_closes(closes)
    logs = [math.log(1.1), math.log(0.99 / 1.1), math.log(1.2 / 0.99)]
    mean = math.fsum(logs) / 3
    assert signals.recent_return == 1.2 / 0.99 - 1.0
    assert signals.momentum == 1.2 / 1.0 - 1.0
    assert signals.volatility == pytest.approx(math.sqrt(math.fsum((x - mean) ** 2 for x in logs) / 2))
    two = signals_from_closes([1.0, 1.05])
    assert (two.recent_return, two.momentum, two.volatility) == (1.05 - 1.0, 1.05 - 1.0, 0.0)


def test_flat_closes_give_neutral_price_signals_and_news_passes_through():
    signals = signals_from_closes([1.5] * 6, event_sentiment=-0.4, event_severity=0.7, attention=2.0)
    assert signals == MarketSignals(event_sentiment=-0.4, event_severity=0.7, attention=2.0)


@pytest.mark.parametrize("closes", [[], [1.0, 0.0], [1.0, -2.0], [1.0, math.nan]])
def test_empty_or_non_positive_closes_are_rejected(closes):
    with pytest.raises(ValueError, match="close"):
        signals_from_closes(closes)
