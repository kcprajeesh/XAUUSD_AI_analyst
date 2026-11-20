from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from app.data.mt5_import import HEADERS
from app.historical_mt5 import (
    analyze_market_structure, build_confluence_snapshot, build_historical_run,
    calculate_indicators,
)
from app.historical_mt5.sequential import (
    SequentialConfig, fingerprint_fvgs, fingerprint_indicators,
    fingerprint_structure, process_sequential,
)

BASE = datetime(2026, 2, 1, tzinfo=UTC)
OFFSET = timedelta(hours=2)


def make_run(tmp_path, count=72):
    files = {}
    for timeframe in ("Daily", "H1", "M15"):
        path = tmp_path / f"{timeframe}.csv"
        lines = [" ".join(f"<{name}>" for name in HEADERS[timeframe])]
        if timeframe == "Daily":
            lines.append("2026.02.01 2000 2001 1999 2000 1 0 1")
        else:
            step = timedelta(hours=1) if timeframe == "H1" else timedelta(minutes=15)
            for i in range(count):
                # Repeating ranges create pivots, equal levels and gaps for parity coverage.
                level = Decimal(2000 + ((i * 7) % 13) - 6)
                width = Decimal("0.2") if i % 5 else Decimal("0.05")
                high, low = level + width, level - width
                broker = BASE + i * step + OFFSET
                lines.append(f"{broker:%Y.%m.%d} {broker:%H:%M:%S} {level} {high} {low} {level} 10 0 2")
        path.write_text("\n".join(lines) + "\n")
        files[timeframe] = path
    return build_historical_run(files, analysis_cutoff=BASE + timedelta(hours=count))


def test_sequential_matches_full_reference_for_sorted_asof_snapshots(tmp_path):
    run = make_run(tmp_path)
    indicators = calculate_indicators(run)
    structure = analyze_market_structure(run, equal_level_tolerance=Decimal("0.15"))
    evaluations = (BASE, BASE + timedelta(hours=37), run.report.analysis_cutoff)
    sequential = process_sequential(run, SequentialConfig(evaluations, Decimal("0.15")))

    assert tuple(report.evaluation_at for report in sequential.snapshots) == evaluations
    for expected, actual in zip(evaluations, sequential.snapshots):
        reference = build_confluence_snapshot(run, indicators, structure, evaluation_at=expected)
        assert actual.to_json() == reference.to_json()

    assert tuple((frame.timeframe, frame.indicator_observation_count,
                  frame.indicator_fingerprint) for frame in sequential.frames) == fingerprint_indicators(indicators)
    assert tuple((frame.timeframe, frame.structure_event_count,
                  frame.structure_event_fingerprint) for frame in sequential.frames) == fingerprint_structure(structure)
    assert tuple((frame.timeframe, frame.final_fvg_count,
                  frame.final_fvg_fingerprint) for frame in sequential.frames) == fingerprint_fvgs(structure)
    assert sequential.to_json() == process_sequential(
        run, SequentialConfig(evaluations, Decimal("0.15"))).to_json()


def test_evaluation_instants_must_be_sorted_unique_and_within_cutoff(tmp_path):
    run = make_run(tmp_path, count=8)
    with pytest.raises(ValueError, match="strictly increasing"):
        SequentialConfig((BASE + timedelta(hours=2), BASE + timedelta(hours=1)))
    with pytest.raises(ValueError, match="strictly increasing"):
        SequentialConfig((BASE + timedelta(hours=1), BASE + timedelta(hours=1)))
    with pytest.raises(ValueError, match="cutoff"):
        process_sequential(run, SequentialConfig((run.report.analysis_cutoff + timedelta(seconds=1),)))


def test_future_events_and_indicator_observations_do_not_enter_earlier_snapshot(tmp_path):
    run = make_run(tmp_path)
    indicators = calculate_indicators(run)
    structure = analyze_market_structure(run)
    evaluation = BASE + timedelta(hours=30)
    full = build_confluence_snapshot(run, indicators, structure, evaluation_at=evaluation)
    prefix_run = replace(run, report=replace(run.report, analysis_cutoff=evaluation))
    prefix = process_sequential(prefix_run, SequentialConfig((evaluation,))).snapshots[0]
    assert (prefix.overall_context, prefix.alignment) == (full.overall_context, full.alignment)
    for prefix_frame, full_frame in zip(prefix.timeframes, full.timeframes):
        assert [(item.indicator, item.parameters, item.value, item.closed_at)
                for item in prefix_frame.indicator_observations] == [
            (item.indicator, item.parameters, item.value, item.closed_at)
            for item in full_frame.indicator_observations]
        assert tuple(event.event_id if event else None for event in
                     (prefix_frame.latest_swing_high, prefix_frame.latest_swing_low,
                      prefix_frame.latest_break, prefix_frame.latest_equal_highs,
                      prefix_frame.latest_equal_lows, prefix_frame.premium_discount)) == tuple(
            event.event_id if event else None for event in
            (full_frame.latest_swing_high, full_frame.latest_swing_low,
             full_frame.latest_break, full_frame.latest_equal_highs,
             full_frame.latest_equal_lows, full_frame.premium_discount))
        assert [(item.formation.event_id, item.status,
                 item.latest_transition.event_id if item.latest_transition else None)
                for item in prefix_frame.active_fvgs] == [
            (item.formation.event_id, item.status,
             item.latest_transition.event_id if item.latest_transition else None)
            for item in full_frame.active_fvgs]
    assert all(obs.closed_at <= evaluation for frame in prefix.timeframes
               for obs in frame.indicator_observations)
    assert all(event is None or event.knowable_at <= evaluation
               for frame in prefix.timeframes
               for event in (frame.latest_swing_high, frame.latest_swing_low,
                             frame.latest_break, frame.latest_equal_highs,
                             frame.latest_equal_lows, frame.premium_discount))


def test_real_export_reference_counts_and_parity_when_enabled():
    from pathlib import Path
    import os

    root = Path(__file__).resolve().parents[2]
    data = root / "data/raw/mt5/alpari_xauusd_i/2026-11-19"
    if os.environ.get("RUN_MT5_REAL_PARITY") != "1" or not data.is_dir():
        pytest.skip("set RUN_MT5_REAL_PARITY=1 to run the full-export parity check")
    files = {"Daily": data / "XAUUSD_i_Daily_202101040000_202611190000.csv",
             "H1": data / "XAUUSD_i_H1_202101040100_202611191300.csv",
             "M15": data / "XAUUSD_i_M15_202101040100_202611191345.csv"}
    run = build_historical_run(files, analysis_cutoff=datetime(2026, 11, 19, 12, 0, tzinfo=UTC))
    sequential = process_sequential(run, SequentialConfig((run.report.analysis_cutoff,)))
    assert [(frame.timeframe, frame.indicator_observation_count) for frame in sequential.frames] == [
        ("H1", 304_750), ("M15", 1_219_348)]
    assert [(frame.timeframe, frame.structure_event_count) for frame in sequential.frames] == [
        ("H1", 63_342), ("M15", 266_606)]
    assert [(frame.timeframe, frame.final_fvg_count) for frame in sequential.frames] == [
        ("H1", 6_150), ("M15", 26_490)]
    assert tuple((frame.timeframe, frame.indicator_fingerprint) for frame in sequential.frames) == (
        ("H1", "a7ca71070b2533c52559905d776d7cce5386750c7b916f877658acf7a5ca3370"),
        ("M15", "69e0e1401bb9e65dfbea39076aa237571af5c81619a992dcf8d132fe422344e8"))
    assert tuple((frame.timeframe, frame.structure_event_fingerprint) for frame in sequential.frames) == (
        ("H1", "10f89b33456a07a194b15ea7f4b3b50f981304a5d399a6f261a5bdfa7bb50368"),
        ("M15", "264ab5d815ff3848011ff7e7f83ebbd96aa488921da7b31ed831e0af9c7c1b05"))
    assert tuple((frame.timeframe, frame.final_fvg_fingerprint) for frame in sequential.frames) == (
        ("H1", "608e34c48d0c46e623f93e1da7bdbe3612d24157f936af777e0a4193a1607afa"),
        ("M15", "ecb3fafd8dc008e00a483e2be0bac3e0eef680bc908bd88fcd936a84d118368e"))
    assert dict(sequential.source_hashes) == {
        "Daily": "4b2b796f61e76f607dfedf6a150ec6884f62081a107b17afcdc06b5a8f4812a5",
        "H1": "e1465d2ef9cbb089647933b6abee9ca68adc35d9be31f5d57c0cd4eff9500e64",
        "M15": "a9e177af909a6373db778c3e6f4c42a1353c3e5359b8ef49ac3fd152f0969efa",
    }
    assert sha256(sequential.snapshots[0].to_json().encode()).hexdigest() == \
        "c601a9c5cf7ea4d4c5f61415d016f882754d46aa17ea3576308d352ea633efb0"
