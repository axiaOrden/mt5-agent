"""Encounter geometry, sequencing, causal context and raw forward movement."""
from dataclasses import replace

import pandas as pd

from src.research.vcz_encounters import (RecoveryEffect, encounters_frame,
                                          replay_vcz_encounters)
from src.research.vcz import VCZSide
from tests.test_vcz import A, C, N, bars, fact


def observe(ohlc, classes=None, *, horizons=(1, 2)):
    candles = bars(ohlc)
    classes = classes or [N] * len(candles)
    facts = [fact(i, c) for i, c in enumerate(classes)]
    return replay_vcz_encounters(candles, facts, symbol="TEST", timeframe="M15",
                                  horizons=horizons)


def test_pre_bar_survivors_boundary_contact_and_creation_exclusion():
    result = observe([(95, 100, 90, 96), (105, 110, 100, 105),
                      (105, 110, 100, 105)], [C, N, N])
    # Creation occurs on index 1; index 2 touches the surviving BELOW zone.
    assert len(result.encounters) == 1
    event = result.encounters[0]
    assert event.side == VCZSide.BELOW
    assert event.zone_age_bars == 1
    assert event.overlap_height == 0
    assert event.penetration_fraction == 0
    assert event.encounter_ordinal == 1


def test_multiple_zones_and_consecutive_ordinal():
    result = observe([(95, 100, 90, 96), (95, 99, 91, 95),
                      (95, 99, 91, 95), (95, 99, 91, 95)], [C, C, N, N])
    events = result.encounters
    assert len({e.zone_id for e in events}) >= 2
    assert len(events) >= 3
    first_zone = [e for e in events if e.zone_id == events[0].zone_id]
    assert [e.encounter_ordinal for e in first_zone] == list(range(1, len(first_zone) + 1))
    assert len({e.encounter_id for e in events}) == len(events)


def test_recovery_effect_and_pre_post_geometry():
    result = observe([(95, 100, 90, 96), (105, 110, 101, 105),
                      (105, 109, 95, 105)], [C, N, N])
    event = result.encounters[0]
    assert event.side == VCZSide.BELOW
    assert (event.pre_bottom, event.pre_top) == (90, 100)
    assert event.recovery_effect == RecoveryEffect.PARTIALLY_RECOVERED
    assert event.post_top == 95
    assert event.outcomes[0].zone_fully_recovered is None


def test_future_outcomes_and_append_causality():
    original = [(95, 100, 90, 96), (105, 110, 101, 105),
                (105, 109, 95, 105), (107, 112, 103, 110)]
    earlier = observe(original[:3], [C, N, N])
    later = observe(original, [C, N, N, N])
    assert replace(earlier.encounters[0], outcomes=()) == replace(later.encounters[0], outcomes=())
    assert earlier.encounters[0].outcomes[0].available is False
    outcome = later.encounters[0].outcomes[0]
    assert outcome.available is True
    assert outcome.future_close == 110
    assert outcome.upward_excursion == 7
    assert outcome.downward_excursion == 2
    assert outcome.close_return == 110 / 105 - 1


def test_as_of_truncates_future_and_context_unavailable():
    ohlc = [(95, 100, 90, 96), (105, 110, 101, 105),
            (105, 109, 95, 105), (107, 112, 103, 110)]
    all_bars = bars(ohlc)
    facts = [fact(i, c) for i, c in enumerate([C, N, N, N])]
    cutoff = pd.Timestamp(all_bars.time.iloc[2]) + pd.Timedelta(minutes=15)
    result = replay_vcz_encounters(all_bars, facts, symbol="TEST", timeframe="M15",
                                   horizons=(1,), as_of=cutoff)
    assert result.candles_processed == 3
    assert len(result.encounters) == 1
    assert result.encounters[0].price_vs_kumo == "UNAVAILABLE"
    assert result.encounters[0].outcomes[0].available is False


def test_flat_export_has_primitive_horizon_columns():
    result = observe([(95, 100, 90, 96), (105, 110, 101, 105),
                      (105, 109, 95, 105), (107, 112, 103, 110)], [A, N, N, N])
    frame = encounters_frame(result)
    assert frame.iloc[0].side == "BELOW"
    assert frame.iloc[0].h1_available
    assert "h2_future_highest_high" in frame


def test_one_bar_can_encounter_both_sides_and_recover_both():
    result = observe([(95, 100, 90, 96), (95, 99, 91, 95),
                      (95, 101, 89, 95)], [C, N, N])
    events = result.encounters
    assert len(events) == 2
    assert {e.side for e in events} == {VCZSide.ABOVE, VCZSide.BELOW}
    assert all(e.recovery_effect == RecoveryEffect.FULLY_RECOVERED for e in events)
    assert all(e.previous_close_position in {"ABOVE_ZONE", "BELOW_ZONE"} for e in events)


def test_exact_boundary_contact_has_zero_penetration():
    result = observe([(95, 100, 90, 96), (105, 110, 100, 105),
                      (105, 110, 100, 105)], [C, N, N])
    event = result.encounters[0]
    assert event.overlap_bottom == event.overlap_top == 100
    assert event.penetration_fraction == 0
    assert event.source_pvsra_flag == 3
    assert event.original_bottom == 90
    assert event.original_top == 100


def test_invalid_horizons_rejected():
    import pytest
    candles = bars([(95, 100, 90, 96)])
    with pytest.raises(ValueError, match="horizons"):
        replay_vcz_encounters(candles, [fact(0)], symbol="TEST", timeframe="M15", horizons=(1, 1))
