from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.data.mt5_import import HEADERS
from app.historical_mt5 import (
    CandleEligibility, IndicatorStatus, analyze_market_structure,
    build_confluence_snapshot, build_historical_run, calculate_indicators,
)
from app.historical_mt5.structure import StructureEvent

BASE = datetime(2026, 1, 1, tzinfo=UTC)
OFFSET = timedelta(hours=2)


def setup_runs(tmp_path, count=220, *, cutoff_index=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for tf in ("Daily", "H1", "M15"):
        path = tmp_path / f"{tf}.csv"
        rows = [" ".join(f"<{item}>" for item in HEADERS[tf])]
        if tf == "Daily":
            rows.append("2026.01.01 2000 2001 1999 2000 10 0 2")
        else:
            step = timedelta(hours=1) if tf == "H1" else timedelta(minutes=15)
            offsets = (0, 1, 3, 1, 0, -1, -3, -1)
            for i in range(count):
                broker = BASE + i * step + OFFSET
                close = Decimal("2000") + Decimal(i) / 10
                offset = offsets[i % len(offsets)]
                high = close + 2 + max(offset, 0)
                low = close - 2 + min(offset, 0)
                rows.append(f"{broker:%Y.%m.%d} {broker:%H:%M:%S} {close} {high} {low} {close} 10 0 2")
        path.write_text("\n".join(rows) + "\n")
        paths[tf] = path
    step = timedelta(hours=1)
    cutoff = BASE + (count if cutoff_index is None else cutoff_index) * step
    run = build_historical_run(paths, analysis_cutoff=cutoff)
    return run, calculate_indicators(run), analyze_market_structure(run)


def test_snapshot_is_asof_provenanced_qatar_display_and_daily_excluded(tmp_path):
    run, indicators, structure = setup_runs(tmp_path)
    at = BASE + timedelta(hours=205)
    report = build_confluence_snapshot(run, indicators, structure, evaluation_at=at)
    assert report.evaluation_at == at
    assert tuple(tf.timeframe for tf in report.timeframes) == ("H1", "M15")
    assert dict(report.source_hashes) == {
        tf: run.series_for(tf).source_sha256 for tf in ("Daily", "H1", "M15")
    }
    assert report.excluded_timeframes == (("Daily", CandleEligibility.UNKNOWN_BOUNDARY.value),)
    for frame in report.timeframes:
        assert all(o.closed_at <= at and o.eligibility == CandleEligibility.ELIGIBLE_CLOSED
                   for o in frame.indicator_observations)
        assert all(any(o is candidate for track in indicators.timeframe(frame.timeframe).tracks
                       for candidate in track.observations) for o in frame.indicator_observations)
        assert frame.latest_swing_high is None or frame.latest_swing_high.knowable_at <= at
        assert frame.latest_swing_low is None or frame.latest_swing_low.knowable_at <= at
    assert report.session_views
    assert all(item.opened_qatar.utcoffset() == timedelta(hours=3) for item in report.session_views)
    assert report.to_json() == build_confluence_snapshot(run, indicators, structure,
                                                           evaluation_at=at).to_json()
    assert '"timeframe":"Daily"' not in report.to_json()


def test_swing_confirmation_and_fvg_lifecycle_are_filtered_by_knowable_time(tmp_path):
    run, indicators, structure = setup_runs(tmp_path)
    frame = structure.timeframe("H1")
    swing = next(event for event in frame.events if event.event_type == "SWING_HIGH")
    assert swing.event_at < swing.knowable_at
    at = swing.event_at
    snapshot = build_confluence_snapshot(run, indicators, structure, evaluation_at=at)
    assert snapshot.timeframes[0].latest_swing_high is None

    source = run.series_for("H1").candles[0].source
    formed_at = source.opened_at + timedelta(hours=1)
    formed = StructureEvent("test-fvg", "alpari_mt5", "Alpari MT5 Demo", "XAUUSD_i", "H1",
        "FVG_FORMED", "test", formed_at, formed_at, (source,), (), "TEST", False,
        price_low=Decimal("2000"), price_high=Decimal("2001"), direction="BULLISH", state="UNFILLED")
    partial_at, full_at = formed_at + timedelta(hours=1), formed_at + timedelta(hours=2)
    partial = replace(formed, event_id="test-partial", event_type="FVG_PARTIAL_MITIGATION",
                      event_at=partial_at, knowable_at=partial_at, state="PARTIALLY_MITIGATED",
                      reference_event_ids=(formed.event_id,))
    full = replace(formed, event_id="test-full", event_type="FVG_FULL_MITIGATION",
                   event_at=full_at, knowable_at=full_at, state="FULLY_MITIGATED",
                   reference_event_ids=(formed.event_id,))
    changed_frame = replace(frame, events=frame.events + (formed, partial, full))
    changed_run = replace(structure, timeframes=tuple(changed_frame if f.timeframe == "H1" else f
                                                      for f in structure.timeframes))
    formed_snapshot = build_confluence_snapshot(run, indicators, changed_run, evaluation_at=formed_at)
    assert {f.formation.event_id: f.status for f in formed_snapshot.timeframes[0].active_fvgs}[formed.event_id] == "UNFILLED"
    partial_snapshot = build_confluence_snapshot(run, indicators, changed_run, evaluation_at=partial_at)
    assert {f.formation.event_id: f.status for f in partial_snapshot.timeframes[0].active_fvgs}[formed.event_id] == "PARTIALLY_MITIGATED"
    full_snapshot = build_confluence_snapshot(run, indicators, changed_run, evaluation_at=full_at)
    assert formed.event_id not in {f.formation.event_id for f in full_snapshot.timeframes[0].active_fvgs}


def test_future_cutoff_and_mismatched_runs_are_rejected(tmp_path):
    run, indicators, structure = setup_runs(tmp_path)
    with pytest.raises(ValueError, match="cutoff"):
        build_confluence_snapshot(run, indicators, structure,
                                  evaluation_at=run.report.analysis_cutoff + timedelta(seconds=1))
    altered_indicators = replace(indicators, source_run_id="different-run")
    with pytest.raises(ValueError, match="same historical run"):
        build_confluence_snapshot(run, altered_indicators, structure,
                                  evaluation_at=BASE)


def test_m15_directional_disagreement_is_reported_without_score(tmp_path):
    run, indicators, structure = setup_runs(tmp_path)
    frames = []
    for frame in indicators.timeframes:
        if frame.timeframe != "M15":
            frames.append(frame)
            continue
        tracks = []
        for track in frame.tracks:
            if not track.observations:
                tracks.append(track)
                continue
            observation = track.observations[-1]
            name = observation.indicator
            value = observation.value
            if name == "EMA":
                period = dict(observation.parameters)["period"]
                value = {20: Decimal("1"), 50: Decimal("2"), 200: Decimal("3")}[period]
            elif name == "MACD_LINE": value = Decimal("-2")
            elif name == "MACD_SIGNAL": value = Decimal("-1")
            elif name == "MOMENTUM_ROC": value = Decimal("-1")
            changed = replace(observation, value=value)
            tracks.append(replace(track, observations=track.observations[:-1] + (changed,)))
        frames.append(replace(frame, tracks=tuple(tracks)))
    altered_indicators = replace(indicators, timeframes=tuple(frames))
    structs = tuple(replace(frame, events=tuple(e for e in frame.events
                     if e.event_type not in {"BOS", "CHOCH"})) if frame.timeframe == "M15" else frame
                    for frame in structure.timeframes)
    altered_structure = replace(structure, timeframes=structs)
    report = build_confluence_snapshot(run, altered_indicators, altered_structure,
                                       evaluation_at=run.report.analysis_cutoff)
    assert report.timeframes[0].context == "BULLISH CONTEXT"
    assert report.timeframes[1].context == "BEARISH CONTEXT"
    assert report.overall_context == "MIXED CONTEXT"
    assert report.alignment == "DISAGREEMENT"


def test_short_series_has_explicit_missing_warmup_and_no_future_observations(tmp_path):
    run, indicators, structure = setup_runs(tmp_path, count=8)
    snapshot = build_confluence_snapshot(run, indicators, structure, evaluation_at=run.report.analysis_cutoff)
    assert snapshot.overall_context == "INSUFFICIENT EVIDENCE"
    for frame in snapshot.timeframes:
        assert "EMA_ALIGNMENT" in frame.missing_evidence
        assert any(status == IndicatorStatus.WARMING_UP.value for _, status in frame.indicator_statuses)
        assert all(o.closed_at <= snapshot.evaluation_at for o in frame.indicator_observations)


def test_snapshot_is_prefix_invariant_at_same_evaluation_instant(tmp_path):
    full_run, full_indicators, full_structure = setup_runs(tmp_path / "full", count=220)
    prefix_run, prefix_indicators, prefix_structure = setup_runs(
        tmp_path / "prefix", count=220, cutoff_index=205)
    at = BASE + timedelta(hours=205)
    full = build_confluence_snapshot(full_run, full_indicators, full_structure, evaluation_at=at)
    prefix = build_confluence_snapshot(prefix_run, prefix_indicators, prefix_structure, evaluation_at=at)
    assert full.overall_context == prefix.overall_context
    assert full.alignment == prefix.alignment
    for full_frame, prefix_frame in zip(full.timeframes, prefix.timeframes):
        assert full_frame.context == prefix_frame.context
        assert [(o.indicator, o.parameters, o.value, o.closed_at) for o in full_frame.indicator_observations] == [
            (o.indicator, o.parameters, o.value, o.closed_at) for o in prefix_frame.indicator_observations]
        assert tuple(e.event_id if e else None for e in
                     (full_frame.latest_swing_high, full_frame.latest_swing_low, full_frame.latest_break)) == tuple(
            e.event_id if e else None for e in
            (prefix_frame.latest_swing_high, prefix_frame.latest_swing_low, prefix_frame.latest_break))
