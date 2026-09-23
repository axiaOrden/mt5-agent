"""Phase 1.10 consumes saved outcomes without deriving new market facts."""
from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from src.main import main
from src.research.analysis import (cohort_statistics, filter_events, load_replay,
                                   report_groups, resolve_fields, segment_events)


def artifact(tmp_path):
    rows = []
    for date, label, pvsra, h1, available, value, mfe, mae in (
        ("2025-12-31T23:45:00Z", "BUY", "CLIMAX", "BULLISH", True, .02, .04, .01),
        ("2026-01-01T00:15:00Z", "BUY", "CLIMAX", "BEARISH", True, -.01, .01, .03),
        ("2026-01-02T00:15:00Z", "SELL", "NORMAL", None, True, 0., .02, .02),
        ("2026-01-03T00:15:00Z", "BUY", "CLIMAX", "BULLISH", False, None, None, None),
    ):
        rows.append({"symbol": "TEST", "event_timeframe": "M15",
                     "event_knowledge_time": date, "event_type": "VWAP_CROSS_BULLISH",
                     "event_direction": "BULLISH", "label": label,
                     "previous_state": "FLAT", "new_state": "LONG",
                     "pvsra_classification": pvsra, "h1_direction": h1,
                     "forward_1_available": available,
                     "forward_1_directional_return": value,
                     "forward_1_mfe": mfe, "forward_1_mae": mae})
    path = tmp_path / "events.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def test_cohort_uses_only_available_saved_outcomes(tmp_path):
    frame = load_replay(artifact(tmp_path))
    assert resolve_fields(frame, "direction,pvsra_classification") == ("label", "pvsra_classification")
    result = cohort_statistics(frame, ("label", "pvsra_classification"), (1,))
    buy = result.loc[result.label.eq("BUY")].iloc[0]
    assert buy.n == 3 and buy.available_n == 2
    assert buy.mean_directional_return == pytest.approx(.005)
    assert buy.median_directional_return == pytest.approx(.005)
    assert buy.median_mfe == pytest.approx(.025)
    assert buy.median_mae == pytest.approx(.02)
    assert buy.median_mfe_minus_median_mae == pytest.approx(.005)
    assert (buy.positive_count, buy.negative_count, buy.zero_count) == (1, 1, 0)
    assert buy.positive_pct == 50
    sell = result.loc[result.label.eq("SELL")].iloc[0]
    assert (sell.positive_count, sell.negative_count, sell.zero_count) == (0, 0, 1)
    assert cohort_statistics(frame, ("label",), (1,), min_samples=3).label.tolist() == ["BUY"]


def test_filter_validation_and_unavailable_context(tmp_path):
    frame = load_replay(artifact(tmp_path))
    filtered = filter_events(frame, ["direction=BUY", "pvsra_classification=CLIMAX"])
    assert len(filtered) == 3
    assert filter_events(frame, ["h1_direction=<MISSING>"]).label.tolist() == ["SELL"]
    grouped = cohort_statistics(frame, ("h1_direction",), (1,))
    assert "<MISSING>" in grouped.h1_direction.tolist()
    for bad, message in (("unknown=BUY", "Unknown filter"), ("direction=LONG", "Invalid"),
                         ("direction", "Malformed"), ("direction=", "empty")):
        with pytest.raises(ValueError, match=message):
            filter_events(frame, [bad])
    with pytest.raises(ValueError, match="Unknown grouping"):
        resolve_fields(frame, "unknown")


def test_calendar_segmentation_uses_knowledge_time(tmp_path):
    frame = load_replay(artifact(tmp_path))
    assert segment_events(frame, "year").period.tolist() == ["2025", "2026", "2026", "2026"]
    assert segment_events(frame, "quarter").period.tolist() == ["2025-Q4", "2026-Q1", "2026-Q1", "2026-Q1"]
    assert segment_events(frame, "month").period.tolist() == ["2025-12", "2026-01", "2026-01", "2026-01"]
    assert len(cohort_statistics(segment_events(frame, "year"), ("period", "label"), (1,))) == 3


def test_reports_only_use_persisted_context_columns(tmp_path):
    frame = load_replay(artifact(tmp_path))
    assert report_groups(frame, "higher-timeframe") == [
        ("h1_direction", ("h1_direction",)), ("combined directions", ("h1_direction",))]
    assert report_groups(frame, "structural-alignment") == []


def test_incompatible_artifact_and_offline_cli(tmp_path, monkeypatch, capsys):
    path = artifact(tmp_path)
    frame = pd.read_parquet(path).drop(columns="forward_1_mfe")
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="incomplete outcome horizon"):
        load_replay(path)
    artifact(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("configuration must not be loaded")
    monkeypatch.setattr("src.main.load_config", forbidden)
    output = tmp_path / "cohorts.csv"
    assert main(["research-analyze", str(path), "--group-by", "direction",
                 "--where", "direction=BUY", "--segment-by", "year",
                 "--output", str(output)]) == 0
    saved = pd.read_csv(output)
    assert saved.n.sum() == 3
    assert saved.available_n.sum() == 2
    assert "2025" in capsys.readouterr().out


def test_stability_exports_are_deterministic_and_source_is_untouched(tmp_path):
    path = artifact(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    base = ["research-analyze", str(path), "--where", "direction=BUY",
            "--where", "pvsra_classification=CLIMAX", "--segment-by", "year",
            "--horizons", "1"]
    csv_path = tmp_path / "by_year.csv"
    parquet_path = tmp_path / "by_year.parquet"
    assert main([*base, "--output", str(csv_path)]) == 0
    first_csv = csv_path.read_bytes()
    first_metadata = (tmp_path / "by_year.csv.meta.json").read_bytes()
    assert main([*base, "--output", str(csv_path)]) == 0
    assert csv_path.read_bytes() == first_csv
    assert (tmp_path / "by_year.csv.meta.json").read_bytes() == first_metadata
    assert main([*base, "--output", str(parquet_path)]) == 0
    table = pd.read_parquet(parquet_path)
    assert table.period.tolist() == ["2025", "2026"]
    assert table.n.tolist() == [1, 2]
    assert table.available_n.tolist() == [1, 1]
    assert table.loc[1, "mean_directional_return"] == pytest.approx(-.01)
    assert "median_mfe" in table and "median_mae" in table
    metadata = json.loads((tmp_path / "by_year.parquet.meta.json").read_text())
    assert metadata["filters"] == ["direction=BUY", "pvsra_classification=CLIMAX"]
    assert metadata["grouping_dimensions"] == {"all events": ["period"]}
    assert metadata["horizons"] == [1]
    assert metadata["source_sha256"] == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_explicit_unavailable_is_distinct_from_null(tmp_path):
    path = artifact(tmp_path)
    frame = pd.read_parquet(path)
    frame.loc[0, "h1_direction"] = "UNAVAILABLE"
    frame.to_parquet(path, index=False)
    loaded = load_replay(path)
    grouped = cohort_statistics(loaded, ("h1_direction",), (1,))
    assert set(grouped.h1_direction) >= {"UNAVAILABLE", "<MISSING>"}
    assert filter_events(loaded, ["h1_direction=UNAVAILABLE"]).index.tolist() == [0]
    assert filter_events(loaded, ["h1_direction=<MISSING>"]).index.tolist() == [2]
