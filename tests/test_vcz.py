"""Hand-verifiable Pine VCZ geometry and closed-candle causality."""
from dataclasses import asdict, replace
from datetime import timedelta

import pandas as pd
import pytest

from src.pvsra.models import CandleDirection, PVSRAClassification, PVSRAResult, VolumeSource
from src.research.vcz import (VCZSide, VCZStatus, _update, pvsra_flag,
                              replay_vcz, vcz_as_of)
from src.research.vcz_history import vcz_summary
from src.main import main


START = pd.Timestamp("2026-01-01T00:00:00Z")
C = PVSRAClassification.CLIMAX
A = PVSRAClassification.ABOVE_AVERAGE
N = PVSRAClassification.NORMAL


def fact(i, classification=N, direction=CandleDirection.BULLISH, minutes=15):
    return PVSRAResult((START + timedelta(minutes=minutes*i)).to_pydatetime(),
                       classification, direction, VolumeSource.TICK_VOLUME,
                       25., 20., 1.25, 10., 8., 1.25, 95., 3., 2., 1.5)


def bars(ohlc, minutes=15):
    return pd.DataFrame([{"time": START + timedelta(minutes=minutes*i),
                          "open": o, "high": h, "low": l, "close": c}
                         for i, (o, h, l, c) in enumerate(ohlc)])


def run(ohlc, classifications=None, *, timeframe="M15", directions=None, **kwargs):
    minutes = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}[timeframe]
    classifications = classifications or [N] * len(ohlc)
    directions = directions or [CandleDirection.BULLISH] * len(ohlc)
    return replay_vcz(bars(ohlc, minutes),
                      [fact(i, c, d, minutes) for i, (c, d) in enumerate(zip(classifications, directions))],
                      symbol="TEST", timeframe=timeframe, **kwargs)


def selected(replay, side, source_index=0):
    source = START + timedelta(minutes=15*source_index)
    return next(z for z in replay.zones if z.side == side and
                pd.Timestamp(z.source_bar_open_time) == source)


@pytest.mark.parametrize("classification,direction,flag", [
    (C, CandleDirection.BULLISH, 3), (C, CandleDirection.BEARISH, -3),
    (A, CandleDirection.BULLISH, 2), (A, CandleDirection.BEARISH, -2),
    (N, CandleDirection.BULLISH, 1), (N, CandleDirection.BEARISH, -1),
    (C, CandleDirection.NEUTRAL, -1),
    (PVSRAClassification.UNAVAILABLE, CandleDirection.BULLISH, None),
])
def test_exact_pine_flag_mapping(classification, direction, flag):
    assert pvsra_flag(fact(0, classification, direction)) == flag


@pytest.mark.parametrize("classification,direction", [
    (C, CandleDirection.BULLISH), (C, CandleDirection.BEARISH),
    (A, CandleDirection.BULLISH), (A, CandleDirection.BEARISH),
])
def test_only_vector_flags_create_two_fixed_direction_zones(classification, direction):
    replay = run([(95, 100, 90, 96), (85, 89, 80, 84)],
                 [classification, N], directions=[direction, CandleDirection.BEARISH])
    assert len(replay.zones) == 2
    assert {z.side for z in replay.zones} == {VCZSide.BELOW, VCZSide.ABOVE}
    assert all((z.original_bottom, z.original_top) == (90, 100) for z in replay.zones)
    assert selected(replay, VCZSide.ABOVE).status == VCZStatus.REMAINING
    assert selected(replay, VCZSide.BELOW).status == VCZStatus.FULLY_RECOVERED


@pytest.mark.parametrize("classification,direction", [
    (N, CandleDirection.BULLISH), (N, CandleDirection.BEARISH),
    (C, CandleDirection.NEUTRAL),
    (PVSRAClassification.UNAVAILABLE, CandleDirection.BULLISH),
])
def test_nonvector_and_unavailable_do_not_create(classification, direction):
    assert run([(95, 100, 90, 96), (85, 89, 80, 84)],
               [classification, N], directions=[direction, CandleDirection.BEARISH]).zones == ()


def test_previous_completed_bar_timing_metadata_and_original_bounds():
    source = [(95, 100, 90, 96)]
    assert run(source, [C]).zones == ()
    replay = run(source + [(85, 92, 80, 84)], [C, N])
    above = selected(replay, VCZSide.ABOVE)
    assert above.source_bar_open_time == START.to_pydatetime()
    assert above.source_bar_close_time == (START + timedelta(minutes=15)).to_pydatetime()
    assert above.created_at == (START + timedelta(minutes=30)).to_pydatetime()
    assert (above.original_bottom, above.original_top) == (90, 100)
    assert (above.current_bottom, above.current_top) == (92, 100)
    assert above.volume == 25 and above.volume_ma == 20
    assert above.partial_update_count == 1 and above.remaining_fraction == pytest.approx(.8)


def test_normal_candles_progressively_shrink_then_wick_recovers_upward():
    ohlc = [(95, 100, 90, 96), (88, 92, 85, 89),
            (93, 95, 91, 93), (95, 98, 94, 95), (98, 100, 97, 98)]
    partial = run(ohlc[:4], [C, N, N, N])
    up = selected(partial, VCZSide.ABOVE)
    assert up.current_bottom == 98 and up.partial_update_count == 3
    assert up.original_bottom == 90 and up.original_top == 100
    assert up.remaining_fraction == pytest.approx(.2)
    final = run(ohlc, [C, N, N, N, N])
    recovered = selected(final, VCZSide.ABOVE)
    assert recovered.status == VCZStatus.FULLY_RECOVERED
    assert recovered.bars_until_recovery == 3
    assert recovered not in final.surviving_zones
    assert recovered in final.fully_recovered_zones


def test_normal_candles_progressively_shrink_then_wick_recovers_downward():
    ohlc = [(95, 100, 90, 96), (102, 105, 98, 102),
            (99, 101, 95, 99), (96, 98, 92, 96), (91, 93, 90, 91)]
    partial = run(ohlc[:4], [C, N, N, N])
    down = selected(partial, VCZSide.BELOW)
    assert down.current_top == 92 and down.partial_update_count == 3
    assert down.original_top == 100
    assert selected(run(ohlc, [C, N, N, N, N]), VCZSide.BELOW).status == VCZStatus.FULLY_RECOVERED


def test_nonintersecting_candle_leaves_geometry_unchanged():
    replay = run([(95, 100, 90, 96), (85, 89, 80, 84), (75, 79, 70, 74)], [C, N, N])
    up = selected(replay, VCZSide.ABOVE)
    assert (up.current_bottom, up.current_top, up.partial_update_count) == (90, 100, 0)


def test_precedence_and_close_branch_literal_fidelity():
    base = selected(run([(95, 100, 90, 96), (85, 89, 80, 84)], [C, N]), VCZSide.ABOVE)
    at = base.created_at + timedelta(minutes=15)
    assert _update(base, VCZSide.ABOVE, 95, 100, 92, at, 2).status == VCZStatus.FULLY_RECOVERED
    assert _update(base, VCZSide.BELOW, 95, 99, 90, at, 2).status == VCZStatus.FULLY_RECOVERED
    # The close-only branch cannot occur with valid OHLC (high >= close,
    # low <= close). Direct branch checks preserve Pine's written order.
    assert _update(base, VCZSide.ABOVE, 94, 89, 85, at, 2).current_bottom == 94
    assert _update(base, VCZSide.BELOW, 96, 105, 101, at, 2).current_top == 96


def test_new_qualifying_source_during_old_zone_recovery_and_overlap():
    ohlc = [(95, 100, 90, 96), (88, 94, 85, 89), (92, 97, 91, 93),
            (94, 98, 92, 95)]
    replay = run(ohlc, [C, A, N, N])
    assert len(replay.zones) == 4
    assert len({z.zone_id for z in replay.zones}) == 4
    older = selected(replay, VCZSide.ABOVE, 0)
    newer = selected(replay, VCZSide.ABOVE, 1)
    assert older.current_bottom == 98
    assert newer.original_top == 94
    assert older.zone_id != newer.zone_id


def test_stable_identity_replay_and_native_timeframes():
    ohlc = [(95, 100, 90, 96), (85, 92, 80, 84)]
    first = run(ohlc, [C, N])
    assert first == run(ohlc, [C, N])
    h1 = run(ohlc, [C, N], timeframe="H1")
    assert {z.zone_id for z in first.zones}.isdisjoint(z.zone_id for z in h1.zones)
    assert {z.timeframe for z in h1.zones} == {"H1"}


def test_future_append_preserves_historical_snapshot():
    ohlc = [(95, 100, 90, 96), (88, 94, 85, 89),
            (95, 100, 92, 96), (97, 105, 94, 100)]
    facts = [fact(0, C), fact(1, N), fact(2, A), fact(3, N)]
    cutoff = START + timedelta(minutes=30)
    before = vcz_as_of(bars(ohlc[:2]), facts[:2], symbol="TEST", timeframe="M15", as_of=cutoff)
    after = vcz_as_of(bars(ohlc), facts, symbol="TEST", timeframe="M15", as_of=cutoff)
    assert asdict(before) == asdict(after)
    assert len(replay_vcz(bars(ohlc), facts, symbol="TEST", timeframe="M15").zones) > len(before.zones)


def test_pine_zonesmax_eviction_preserves_history():
    ohlc = [(95, 100, 90, 96), (85, 89, 80, 84),
            (75, 79, 70, 74), (65, 69, 60, 64)]
    full = run(ohlc, [C, C, C, N])
    limited = run(ohlc, [C, C, C, N], max_zones=1)
    assert len(full.zones) == len(limited.zones) == 6
    assert any(z.status == VCZStatus.DISPLAY_EVICTED for z in limited.zones)
    assert len(limited.surviving_zones) <= 2
    assert vcz_summary(limited)["zones_created"] == 6


def test_pine_preclean_length_evicts_oldest_even_if_newest_recovers():
    # At bar 2 the new ABOVE zone (from bar 1) is recovered immediately,
    # while the older ABOVE zone still has a remaining range. Pine nevertheless
    # pops the oldest slot because the pre-clean array length is two.
    replay = run([(95, 100, 90, 96), (88, 92, 85, 89),
                  (93, 95, 91, 93)], [C, C, N], max_zones=1)
    old = selected(replay, VCZSide.ABOVE, 0)
    new = selected(replay, VCZSide.ABOVE, 1)
    assert old.status == VCZStatus.DISPLAY_EVICTED
    assert new.status == VCZStatus.FULLY_RECOVERED
    assert old.current_bottom == 95  # current bar updated old before eviction


def test_empty_insufficient_and_zero_height():
    empty = replay_vcz(bars([]), [], symbol="TEST", timeframe="M15")
    assert empty.candles_processed == 0 and empty.zones == ()
    assert replay_vcz(bars([(95, 100, 90, 96), (85, 89, 80, 84)]),
                      [None, fact(1)], symbol="TEST", timeframe="M15").zones == ()
    flat = run([(100, 100, 100, 100), (105, 106, 104, 105)],
               [C, N], directions=[CandleDirection.NEUTRAL, CandleDirection.BULLISH])
    assert flat.zones == ()  # doji has no vector color
    base = selected(run([(95, 100, 90, 96), (85, 89, 80, 84)], [C, N]), VCZSide.ABOVE)
    assert replace(base, original_top=90, current_top=90).remaining_fraction is None


def test_input_validation():
    with pytest.raises(ValueError, match="one PVSRA"):
        replay_vcz(bars([(95, 100, 90, 96)]), [], symbol="TEST", timeframe="M15")
    with pytest.raises(ValueError, match="max_zones"):
        run([(95, 100, 90, 96)], [C], max_zones=0)
    with pytest.raises(ValueError, match="invalid OHLC"):
        run([(95, 89, 90, 96)], [C])


def test_offline_cli_uses_saved_history_without_config_or_provider(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("VCZ CLI must not load config or provider")
    monkeypatch.setattr("src.main.load_config", forbidden)
    monkeypatch.setattr("src.main.build_provider", forbidden)
    directory = tmp_path / "TEST"
    directory.mkdir()
    candles = bars([(95, 100, 90, 96), (85, 89, 80, 84)])
    candles["tick_volume"] = [10., 11.]
    candles["real_volume"] = [0., 0.]
    candles["spread"] = [1., 1.]
    candles.to_parquet(directory / "M15.parquet", index=False)
    candles.iloc[:1].to_parquet(directory / "D1.parquet", index=False)
    assert main(["vcz", "TEST", "--timeframe", "M15", "--research-history",
                 "--history-dir", str(tmp_path), "--sample", "0"]) == 0
    assert "zones_created: 0" in capsys.readouterr().out
