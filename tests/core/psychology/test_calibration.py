"""The momentum horizon normalization (Phase 18 calibration).

Phase 18 changed exactly one thing: ``momentum`` is divided by
``MOMENTUM_SCALE`` rather than by ``PRICE_MOVE_SCALE``. These tests pin
that relationship, which nothing pinned before — the existing signal
tests assert directions (fear rises, FOMO does not) and never asserted
what a given size of move is *worth*, which is how a four-interval
displacement came to be measured against a one-interval yardstick in the
first place.

Nothing here tests a property the implementation does not guarantee. In
particular there is no assertion that a market "should" feel any
particular way; the assertions are about arithmetic, bounds, determinism
and the horizon relationship.
"""

from __future__ import annotations

import math
import random

import pytest

from crypto_simulator.core.psychology.signals import (
    MOMENTUM_SCALE,
    PRICE_MOVE_SCALE,
    SIGNAL_WINDOW,
    TERM_CAP,
    VOLATILITY_SCALE,
    MarketSignals,
    compute_psychology,
    signals_from_closes,
)
from crypto_simulator.core.psychology.state import PsychologyState

ONE_UNIT = math.tanh(1.0)  # what a single unit of one-sided pressure is worth


def _psych(**kwargs) -> PsychologyState:
    return compute_psychology(MarketSignals(**kwargs))


# --- the constants ---------------------------------------------------------------------------------------


def test_the_one_interval_scale_is_unchanged():
    """Phase 18 changed the momentum scale and nothing else."""
    assert PRICE_MOVE_SCALE == 0.05


def test_the_momentum_scale_is_derived_from_the_window_not_written_down():
    assert MOMENTUM_SCALE == PRICE_MOVE_SCALE * math.sqrt(SIGNAL_WINDOW - 1)
    assert MOMENTUM_SCALE == 0.10


def test_the_other_calibration_constants_are_unchanged():
    assert VOLATILITY_SCALE == 0.10
    assert TERM_CAP == 20.0
    assert SIGNAL_WINDOW == 5


# --- the horizon relationship ----------------------------------------------------------------------------


def test_a_five_percent_move_over_one_interval_is_one_unit_of_pressure():
    """The documented meaning of PRICE_MOVE_SCALE, unchanged."""
    assert _psych(recent_return=PRICE_MOVE_SCALE).fomo == pytest.approx(ONE_UNIT)


def test_a_ten_percent_move_over_the_window_is_also_one_unit_of_pressure():
    """The calibration: momentum is worth a unit at its own horizon's
    scale, which is sqrt(4) = 2x the one-interval scale."""
    assert _psych(momentum=MOMENTUM_SCALE).fomo == pytest.approx(ONE_UNIT)


def test_the_two_horizons_are_measured_on_the_same_footing():
    """A move of each horizon's scale produces the identical state — the
    property the calibration exists to establish."""
    by_return = _psych(recent_return=PRICE_MOVE_SCALE)
    by_momentum = _psych(momentum=MOMENTUM_SCALE)
    assert by_return == by_momentum


def test_the_same_relationship_holds_downward():
    assert _psych(recent_return=-PRICE_MOVE_SCALE) == _psych(momentum=-MOMENTUM_SCALE)
    assert _psych(momentum=-MOMENTUM_SCALE).fear == pytest.approx(ONE_UNIT)


def test_momentum_now_counts_for_half_of_what_it_used_to():
    """The calibration's size, pinned: the divisor doubled, so a given
    momentum contributes half the pressure it did before Phase 18."""
    momentum = 0.08
    before_units = momentum / PRICE_MOVE_SCALE  # the pre-calibration term
    after_units = momentum / MOMENTUM_SCALE
    assert after_units == pytest.approx(before_units / 2)
    assert _psych(momentum=momentum).fomo == pytest.approx(math.tanh(after_units))


def test_a_run_of_the_windows_length_is_worth_less_than_it_was():
    """Stated as an inequality rather than a pinned number: the point is
    that ordinary drift no longer reads as an extreme trend."""
    state = _psych(momentum=0.10)
    assert state.fomo < math.tanh(0.10 / PRICE_MOVE_SCALE)


# --- what the calibration did not change -----------------------------------------------------------------


def test_the_one_interval_return_still_uses_the_original_scale():
    assert _psych(recent_return=0.10).fomo == pytest.approx(math.tanh(0.10 / PRICE_MOVE_SCALE))


def test_neutral_inputs_still_give_the_neutral_state():
    assert compute_psychology(MarketSignals()) == PsychologyState.neutral()


def test_volatility_still_reaches_uncertainty_at_its_own_scale():
    assert _psych(volatility=VOLATILITY_SCALE).uncertainty == pytest.approx(ONE_UNIT)


def test_news_terms_are_untouched_by_the_calibration():
    """Sentiment and attention never went through a price scale."""
    assert _psych(event_sentiment=0.5, attention=2.0).fomo == pytest.approx(math.tanh(1.0))


def test_opposing_pressures_still_damp_each_other():
    both = _psych(recent_return=PRICE_MOVE_SCALE, momentum=-MOMENTUM_SCALE)
    assert both.fomo < ONE_UNIT and both.fear < ONE_UNIT
    assert both.uncertainty > 0, "conflict still raises uncertainty"


def test_conviction_is_still_net_bullish_pressure_eroded_by_uncertainty():
    state = _psych(momentum=MOMENTUM_SCALE * 2)
    assert 0 < state.conviction <= 1


# --- invariants ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("momentum", [-1.0, -0.5, -0.1, 0.0, 0.1, 0.5, 1.0, 1e6, 1e308])
def test_every_component_stays_within_bounds_at_any_momentum(momentum):
    state = _psych(momentum=momentum, recent_return=0.02, volatility=0.05,
                   event_sentiment=-0.4, event_severity=0.7, attention=3.0)
    for name in ("fear", "fomo", "conviction", "uncertainty"):
        assert 0.0 <= getattr(state, name) <= 1.0, name


def test_an_enormous_momentum_is_still_finite():
    """TERM_CAP keeps a huge but finite input from overflowing."""
    state = _psych(momentum=1e308)
    assert state.fomo == pytest.approx(1.0)
    assert all(math.isfinite(getattr(state, n))
               for n in ("fear", "fomo", "conviction", "uncertainty"))


def test_the_most_negative_possible_momentum_is_accepted():
    """A price cannot fall more than 100%."""
    assert _psych(momentum=-1.0).fear > 0
    with pytest.raises(ValueError):
        _psych(momentum=-1.5)


# --- monotonicity the implementation actually guarantees ---------------------------------------------------


def test_fomo_rises_monotonically_with_momentum():
    values = [_psych(momentum=m).fomo for m in (0.0, 0.05, 0.1, 0.2, 0.4)]
    assert values == sorted(values)
    assert values[0] == 0.0


def test_fear_rises_monotonically_as_momentum_falls():
    values = [_psych(momentum=m).fear for m in (0.0, -0.05, -0.1, -0.2, -0.4)]
    assert values == sorted(values)


def test_positive_momentum_never_creates_fear():
    for momentum in (0.01, 0.1, 0.5, 5.0):
        assert _psych(momentum=momentum).fear == 0.0


def test_negative_momentum_never_creates_fomo():
    for momentum in (-0.01, -0.1, -0.5, -0.9):
        assert _psych(momentum=momentum).fomo == 0.0


# --- determinism -----------------------------------------------------------------------------------------


def test_the_calculation_is_deterministic():
    signals = MarketSignals(recent_return=0.013, momentum=-0.037, volatility=0.031,
                            event_sentiment=0.27, event_severity=0.6, attention=1.4)
    first = compute_psychology(signals)
    assert all(compute_psychology(signals) == first for _ in range(50))


def test_the_calculation_draws_no_randomness():
    before = random.getstate()
    for step in range(200):
        _psych(momentum=step / 100 - 1.0, recent_return=step / 200 - 0.5)
    assert random.getstate() == before


def test_the_window_helper_feeds_momentum_over_the_whole_window():
    """signals_from_closes still measures momentum across the window, so
    the scale it is divided by is the matching one."""
    closes = [1.0, 1.02, 1.04, 1.06, 1.10]
    signals = signals_from_closes(closes)
    assert signals.momentum == pytest.approx(closes[-1] / closes[0] - 1.0)
    assert signals.recent_return == pytest.approx(closes[-1] / closes[-2] - 1.0)
    assert len(closes) == SIGNAL_WINDOW
