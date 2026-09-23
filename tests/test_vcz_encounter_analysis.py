"""Deterministic descriptive analysis of persisted encounter rows."""
import hashlib
import json

import pandas as pd
import pytest

from src.research.vcz_encounter_analysis import (
    AGE_LABELS, DIMENSIONS, age_bucket, cohort_study, export_study, inventory,
    population_frame, prepare_encounters, remaining_bucket, validate_encounters,
)


def fixture_frame():
    times = pd.to_datetime(["2025-12-31T00:00:00Z", "2026-01-01T00:00:00Z",
                            "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z"])
    return pd.DataFrame({
        "encounter_id": ["a", "b", "c", "d"], "zone_id": ["z1", "z1", "z2", "z3"],
        "symbol": ["TEST"] * 4, "timeframe": ["H4"] * 4,
        "candle_open_time": times, "source_bar_open_time": [times[0], times[0], times[1], times[1]],
        "encounter_ordinal": [1, 2, 1, 1], "zone_age_bars": [1, 4, 16, 1025],
        "original_bottom": [0.] * 4, "original_top": [100.] * 4,
        "pre_bottom": [0.] * 4, "pre_top": [90., 75., 50., 5.],
        "side": ["BELOW", "BELOW", "ABOVE", "ABOVE"],
        "candle_pvsra_classification": ["NORMAL", "CLIMAX", "ABOVE_AVERAGE", "UNAVAILABLE"],
        "source_pvsra_classification": ["CLIMAX", "CLIMAX", "ABOVE_AVERAGE", "CLIMAX"],
        "source_pvsra_direction": ["BULLISH", "BULLISH", "BEARISH", "NEUTRAL"],
        "recovery_effect": ["UNCHANGED", "PARTIALLY_RECOVERED", "FULLY_RECOVERED", "UNCHANGED"],
        "price_vs_kumo": ["ABOVE", "INSIDE", "BELOW", "UNAVAILABLE"],
        "price_vs_kijun": ["ABOVE_ZONE", "AT", "BELOW_ZONE", "UNAVAILABLE"],
        "kumo_orientation": ["BULLISH", "BEARISH", "FLAT", "UNAVAILABLE"],
        "h1_available": [True, True, True, False],
        "h1_upward_excursion": [1., 2., 3., None],
        "h1_downward_excursion": [4., 5., 6., None],
        "h1_close_return": [-0.1, 0.2, -0.3, None],
        "h1_zone_fully_recovered": [False, False, True, None],
        "h1_bars_until_full_recovery": [None, None, 0., None],
    })


@pytest.mark.parametrize("age,label", [(0,"0-1"),(1,"0-1"),(2,"2-4"),(4,"2-4"),
                                      (5,"5-16"),(16,"5-16"),(17,"17-64"),(64,"17-64"),
                                      (65,"65-256"),(256,"65-256"),(257,"257-1024"),
                                      (1024,"257-1024"),(1025,"1025+")])
def test_age_boundaries(age, label):
    assert age_bucket(age) == label


@pytest.mark.parametrize("value,label", [(1.,">0.75"),(.750001,">0.75"),(.75,"0.50-0.75"),
                                         (.5,"0.25-0.50"),(.25,"0.10-0.25"),(.1,"0.10-0.25"),
                                         (.0999,"<0.10"),(0.,"<0.10")])
def test_remaining_boundaries(value, label):
    assert remaining_bucket(value) == label


def test_population_inventory_and_source_pair_awareness():
    frame = prepare_encounters(fixture_frame())
    assert len(population_frame(frame, "ALL")) == 4
    first = population_frame(frame, "FIRST")
    assert len(first) == first.zone_id.nunique() == 3
    assert inventory(frame) == dict(encounters=4, unique_zones=3,
                                    unique_source_candles=2, first_encounters=3,
                                    later_encounters=1, encounter_candles_1_zone=2,
                                    encounter_candles_2_zones=1,
                                    encounter_candles_3plus_zones=0)


def test_every_dimension_and_period_is_separate():
    result = cohort_study(fixture_frame(), dimensions=DIMENSIONS, horizons=(1,), min_sample=3)
    assert set(result.dimension) == set(DIMENSIONS) | {"overall"}
    assert set(result.period_type) == {"full", "year"}
    assert "ordinal" not in set(result.loc[result.population.eq("FIRST"), "dimension"])
    assert set(result.loc[result.dimension.eq("kumo-position"), "cohort"]) == {
        "ABOVE_KUMO", "INSIDE_KUMO", "BELOW_KUMO", "UNAVAILABLE"}
    assert set(result.loc[result.dimension.eq("kijun-position"), "cohort"]) == {
        "ABOVE_KIJUN", "AT_KIJUN", "BELOW_KIJUN", "UNAVAILABLE"}
    assert set(result.loc[result.dimension.eq("ordinal"), "cohort"]) == {"1", "2"}
    assert set(result.loc[result.dimension.eq("source-direction"), "cohort"]) == {
        "BULLISH", "BEARISH", "NEUTRAL"}
    assert result.small_sample.any()  # retained, not discarded
    quarter = cohort_study(fixture_frame(), dimensions=("age",), segment="quarter", horizons=(1,))
    assert {"2025-Q4", "2026-Q1", "2026-Q2"} <= set(quarter.period)


def test_outcome_counts_medians_quantiles_and_ordering():
    result = cohort_study(fixture_frame(), dimensions=("selector",), horizons=(1,))
    row = result.query("population == 'ALL' and period == 'FULL' and dimension == 'overall'").iloc[0]
    assert row.n == 4 and row.n_available == 3
    assert row.median_upward_excursion == 2
    assert row.q25_upward_excursion == 1.5 and row.q75_upward_excursion == 2.5
    assert row.median_downward_excursion == 5
    assert row.median_close_return == -.1
    assert row.median_absolute_close_return == .2
    assert row.same_candle_full_count == 1
    assert row.same_candle_full_rate == .25
    assert row.same_candle_partial_rate == .25
    assert row.same_candle_unchanged_rate == .5
    assert row.full_recovery_by_horizon_count == 1
    assert row.median_bars_until_full_recovery == 0
    assert result.equals(cohort_study(fixture_frame(), dimensions=("selector",), horizons=(1,)))
    assert result.dimension.tolist() == sorted(result.dimension.tolist())


def test_export_is_deterministic_and_metadata_has_input_hash(tmp_path):
    source = tmp_path / "encounters.parquet"
    fixture_frame().to_parquet(source, index=False)
    result = cohort_study(fixture_frame(), dimensions=("age",), horizons=(1,))
    path = tmp_path / "study.csv"
    kwargs = dict(input_path=source, symbol="TEST", timeframe="H4", populations=("ALL", "FIRST"),
                  segment="year", dimensions=("age",), horizons=(1,), min_sample=30)
    export_study(result, path, **kwargs)
    content = path.read_bytes()
    metadata = path.with_name(path.name + ".meta.json")
    meta_content = metadata.read_bytes()
    assert json.loads(meta_content)["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    export_study(result, path, **kwargs)
    assert path.read_bytes() == content and metadata.read_bytes() == meta_content
    parquet = tmp_path / "study.parquet"
    export_study(result, parquet, **kwargs)
    assert pd.read_parquet(parquet).equals(result)


def test_validation_rejects_mixed_timeframes_and_missing_available_outcome():
    frame = fixture_frame()
    frame.loc[0, "timeframe"] = "D1"
    with pytest.raises(ValueError, match="one symbol and native timeframe"):
        validate_encounters(frame)
    frame = fixture_frame()
    frame.loc[0, "h1_close_return"] = None
    with pytest.raises(ValueError, match="available outcomes"):
        validate_encounters(frame)


def test_validation_rejects_incomplete_horizon_schema():
    frame = fixture_frame().drop(columns="h1_downward_excursion")
    with pytest.raises(ValueError, match="incomplete outcome horizon"):
        validate_encounters(frame)


def test_offline_cli_uses_persisted_encounters_without_provider(tmp_path, monkeypatch):
    from src.main import main
    history = tmp_path / "history" / "TEST"
    history.mkdir(parents=True)
    (history / "H4.parquet").touch()  # Presence resolves exact symbol; never loaded.
    encounters = tmp_path / "vcz"
    encounters.mkdir()
    artifact = encounters / "TEST_H4_encounters.parquet"
    fixture_frame().to_parquet(artifact, index=False)
    before = artifact.read_bytes()
    monkeypatch.setattr("src.main.build_provider", lambda *_: pytest.fail("provider was called"))
    output = tmp_path / "study.csv"
    assert main(["vcz-encounter-study", "TEST", "--timeframe", "H4",
                 "--research-history", "--history-dir", str(history.parent),
                 "--encounter-dir", str(encounters), "--horizons", "1",
                 "--output", str(output)]) == 0
    assert output.exists() and artifact.read_bytes() == before
