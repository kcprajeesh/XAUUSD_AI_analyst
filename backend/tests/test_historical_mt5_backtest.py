from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.data.mt5_import import HEADERS
from app.historical_mt5 import CandleEligibility, build_historical_run
from app.historical_mt5 import backtest as backtest_module
from app.historical_mt5.backtest import (
    AMBIGUOUS_ENTRY_BAR, AMBIGUOUS_ENTRY_INVALIDATION, BACKTEST_ALGORITHM,
    run_smc_backtests,
)
from app.analysis.sessions import DEFAULT_SESSIONS
from app.historical_mt5.indicators import (
    ALGORITHM_VERSION as INDICATOR_VERSION, CandleReference, IndicatorObservation,
    IndicatorRun, IndicatorSpec, IndicatorStatus, IndicatorTrack, TimeframeIndicators,
)
from app.historical_mt5.models import HistoricalRun
from app.historical_mt5.structure import (
    ALGORITHM_VERSION as STRUCTURE_VERSION, FairValueGapState, HistoricalStructureRun,
    StructureDiagnostics, StructureEvent, TimeframeMarketStructure, stream_market_structure,
)


def _event(event_id, timeframe, event_type, candle, *, direction=None, level=None,
           low=None, high=None, refs=(), sources=None, gap=False, known_at=None):
    close = known_at or candle.opened_at + (timedelta(hours=1) if timeframe == "H1" else timedelta(minutes=15))
    return StructureEvent(
        event_id, "alpari_mt5", "Alpari MT5 Demo", "XAUUSD_i", timeframe,
        event_type, STRUCTURE_VERSION, close, close,
        tuple(sources if sources is not None else (candle,)), (),
        "GAP_CONTEXT" if gap else "RULE_CONFIRMED", gap,
        price_level=Decimal(str(level)) if level is not None else None,
        price_low=Decimal(str(low)) if low is not None else None,
        price_high=Decimal(str(high)) if high is not None else None,
        direction=direction, reference_event_ids=tuple(refs),
    )


def _pipeline(tmp_path, *, direction="long", count=24, broker_start="2021.01.04 08:00:00",
              gap_sweep=False, h1_break=True, h1_direction=None, h1_conflict=False,
              m15_overrides=None, extra_events=(), extra_swings=(), skip_rows=()):
    m15_overrides = m15_overrides or {}
    start = datetime.strptime(broker_start, "%Y.%m.%d %H:%M:%S")
    h1_start = start - timedelta(hours=1)
    h1_rows = []
    for index in range((count + 3) // 4 + 1):
        stamp = h1_start + timedelta(hours=index)
        h1_rows.append(f"{stamp:%Y.%m.%d} {stamp:%H:%M:%S} 101 103 100 102 10 0 4")
    daily_row = f"{start:%Y.%m.%d} 101 103 100 102 10 0 4"
    rows = []
    row_by_index = {}
    for index in range(count):
        if index in skip_rows:
            continue
        stamp = start + timedelta(minutes=15 * index)
        if direction == "long":
            values = ["101", "102", "100.8", "101.2"]
            if index == 2:
                values = ["100.5", "101", "99.5", "100.6"]
            if index == 5:
                values = ["101", "102", "100.4", "101"]
        else:
            values = ["101.8", "102", "101.3", "101.7"]
            if index == 2:
                values = ["102", "102.5", "101", "101.5"]
            if index == 5:
                values = ["101.8", "102", "101.4", "101.7"]
        values = list(m15_overrides.get(index, values))
        row = f"{stamp:%Y.%m.%d} {stamp:%H:%M:%S} {' '.join(values)} 12 0 4"
        row_by_index[index] = row
        rows.append(row)
    files = {}
    for timeframe, lines in (("Daily", [daily_row]), ("H1", h1_rows), ("M15", rows)):
        path = tmp_path / f"{timeframe}.csv"
        path.write_text("\t".join(f"<{name}>" for name in HEADERS[timeframe]) + "\n" +
                        "\n".join(lines) + "\n")
        files[timeframe] = path
    m15_last = start + timedelta(minutes=15 * (count - 1)) + timedelta(minutes=15)
    cutoff = m15_last.astimezone(UTC).replace(tzinfo=UTC) if m15_last.tzinfo else (m15_last - timedelta(hours=2)).replace(tzinfo=UTC)
    run = build_historical_run(files, analysis_cutoff=cutoff)
    m15 = run.series_for("M15").candles
    h1_candles = tuple(item.source for item in run.series_for("H1").candles)
    h1 = h1_candles[0]
    by_row = {item.source.source_timestamp: item.source for item in m15}
    candles = tuple(item.source for item in m15)
    # The Phase 3 fixture events share real imported candle provenance.
    pivot = candles[0]
    pivot_price = Decimal("100") if direction == "long" else Decimal("102")
    side_type = "SWING_LOW" if direction == "long" else "SWING_HIGH"
    swing = _event("swing-latest", "M15", side_type, pivot, level=pivot_price)
    m15_events = [swing]
    for event_id, price, index in extra_swings:
        m15_events.append(_event(event_id, "M15", side_type, candles[index], level=price))
    sweep_candle = candles[2]
    sweep_type = "SELL_SIDE_SWEEP" if direction == "long" else "BUY_SIDE_SWEEP"
    sweep_sources = (pivot, sweep_candle)
    sweep = _event("sweep-main", "M15", sweep_type, sweep_candle,
                   direction="bullish" if direction == "long" else "bearish",
                   level=pivot_price, refs=("swing-latest",), sources=sweep_sources,
                   gap=gap_sweep)
    m15_events.append(sweep)
    mss_direction = "bullish" if direction == "long" else "bearish"
    m15_events.append(_event("mss-first", "M15", "BOS", candles[3],
                             direction=mss_direction, refs=("swing-latest",)))
    m15_events.extend(extra_events)
    gap_low, gap_high = (Decimal("100"), Decimal("101")) if direction == "long" else (Decimal("101"), Decimal("102"))
    gap_direction = "BULLISH" if direction == "long" else "BEARISH"
    m15_events.append(_event("fvg-first", "M15", "FVG_FORMED", candles[4], direction=gap_direction,
                             low=gap_low, high=gap_high, sources=candles[2:5]))
    break_event = None
    if h1_break:
        break_direction = h1_direction or mss_direction
        break_event = _event("h1-break", "H1", "BOS", h1, direction=break_direction)
    h1_events = (break_event,) if break_event else ()
    if h1_conflict and break_event:
        # An opposing MACD pair makes Phase 4's actual shared label mixed.
        from app.historical_mt5.indicators import IndicatorSpec
        close_at = h1.opened_at + timedelta(hours=1)
        ref = CandleReference(h1.series_id, h1.source_file, h1.source_sha256, h1.source_row,
                              h1.source_timestamp, h1.opened_at, "UTC+02:00 fixed", h1.timezone_policy)
        tracks = []
        for name, value in (("MACD_LINE", Decimal("1")), ("MACD_SIGNAL", Decimal("2"))):
            spec = IndicatorSpec("alpari_mt5", "Alpari MT5 Demo", "XAUUSD_i", "H1", name, ())
            obs = IndicatorObservation(spec, h1.opened_at, close_at, ref, value,
                                       IndicatorStatus.READY, CandleEligibility.ELIGIBLE_CLOSED, False)
            tracks.append(IndicatorTrack(spec, 1, IndicatorStatus.READY, 1, (obs,)))
    else:
        tracks = []
    diagnostics = StructureDiagnostics(len(candles), 0, 0, 0, 0, 0)
    frames = []
    for timeframe in ("H1", "M15"):
        series = run.series_for(timeframe)
        events = h1_events if timeframe == "H1" else tuple(sorted(m15_events, key=lambda e: e.knowable_at))
        frames.append(TimeframeMarketStructure(timeframe, series.series_id, series.source_file,
            series.source_sha256, "BULLISH" if timeframe == "H1" else "NEUTRAL", diagnostics,
            events, ()))
    structure = HistoricalStructureRun(run.report.run_id, cutoff, STRUCTURE_VERSION, Decimal("0"),
                                       tuple(frames), (("Daily", "UNKNOWN_BOUNDARY"),))
    indicator_frames = []
    for timeframe in ("H1", "M15"):
        series = run.series_for(timeframe)
        frame_tracks = tuple(tracks) if timeframe == "H1" else ()
        closes = tuple(item.nominal_close_at for item in series.candles
                       if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED)
        indicator_frames.append(TimeframeIndicators(timeframe, series.series_id, series.source_file,
            series.source_sha256, len(closes), 0, closes, frame_tracks))
    indicators = IndicatorRun(run.report.run_id, cutoff, tuple(indicator_frames),
                              (("Daily", "UNKNOWN_BOUNDARY"),))
    return run, indicators, structure, sweep


def _synthetic_backtest(run, indicators, structure):
    # Synthetic hashes are isolated by a test-only patch; production has no bypass argument.
    with patch.object(backtest_module, "_validate_approved_comparison_scope", lambda *_: None):
        return run_smc_backtests(run, indicators, structure)


def _backtest(tmp_path, **kwargs):
    run, indicators, structure, sweep = _pipeline(tmp_path, **kwargs)
    return _synthetic_backtest(run, indicators, structure), sweep


def _patch_approved_source_identity(monkeypatch, run, *, h1_hash=None, m15_hash=None):
    monkeypatch.setattr(backtest_module, "APPROVED_SOURCE_FILES", tuple(
        (timeframe, run.series_for(timeframe).source_file) for timeframe in ("H1", "M15")))
    monkeypatch.setattr(backtest_module, "APPROVED_SOURCE_HASHES", (
        ("H1", h1_hash or run.series_for("H1").source_sha256),
        ("M15", m15_hash or run.series_for("M15").source_sha256),
    ))


def _variant(report, name):
    return next(item for item in report.variants if item.variant == name)


def test_a_c_require_two_a2_items_b_ignores_mixed_h1(tmp_path):
    report, _ = _backtest(tmp_path, h1_conflict=True)
    assert _variant(report, "A").setups == ()
    assert _variant(report, "C").setups == ()
    assert _variant(report, "B").setups[0].status == "OPEN_AT_CUTOFF"
    assert _variant(report, "B").setups[0].h1_context is None


def test_a_c_accept_directional_label_with_missing_descriptive_indicators(tmp_path):
    report, _ = _backtest(tmp_path)
    a_setup = _variant(report, "A").setups[0]
    c_setup = _variant(report, "C").setups[0]
    assert a_setup.h1_context == "BULLISH CONTEXT"
    assert c_setup.h1_context == "BULLISH CONTEXT"
    assert "EMA_ALIGNMENT" in a_setup.h1_missing_descriptive_components
    assert "MACD_LINE_OR_SIGNAL" in c_setup.h1_missing_descriptive_components
    assert _variant(report, "B").setups[0].h1_context is None


def test_a_c_reject_missing_h1_break_but_b_still_runs(tmp_path):
    report, _ = _backtest(tmp_path, h1_break=False)
    assert _variant(report, "A").setups == ()
    assert _variant(report, "C").setups == ()
    assert _variant(report, "B").setups


def test_h1_evidence_after_sweep_cannot_retroactively_change_a_c(tmp_path):
    run, indicators, structure, sweep = _pipeline(tmp_path)
    h1_candle = run.series_for("H1").candles[1].source
    later = _event("h1-later-opposite", "H1", "CHOCH", h1_candle,
                   direction="bearish", known_at=sweep.knowable_at + timedelta(minutes=15))
    frame = structure.timeframe("H1")
    structure = replace(structure, timeframes=(replace(frame, events=(*frame.events, later)),
                                                structure.timeframe("M15")))
    report = _synthetic_backtest(run, indicators, structure)
    assert _variant(report, "A").setups[0].status == "OPEN_AT_CUTOFF"
    assert _variant(report, "C").setups[0].status == "OPEN_AT_CUTOFF"


def test_future_only_h1_break_is_not_used_for_sweep_qualification(tmp_path):
    run, indicators, structure, sweep = _pipeline(tmp_path, h1_break=False)
    h1_candle = run.series_for("H1").candles[1].source
    future = _event("h1-future-break", "H1", "BOS", h1_candle,
                    direction="bullish", known_at=sweep.knowable_at + timedelta(minutes=15))
    frame = structure.timeframe("H1")
    structure = replace(structure, timeframes=(replace(frame, events=(future,)),
                                                structure.timeframe("M15")))
    report = _synthetic_backtest(run, indicators, structure)
    assert _variant(report, "A").setups == ()
    assert _variant(report, "C").setups == ()
    assert _variant(report, "B").setups


@pytest.mark.parametrize("direction,expected", [("long", "bullish"), ("short", "bearish")])
def test_h1_break_must_agree_with_setup_direction(tmp_path, direction, expected):
    wrong = "bearish" if expected == "bullish" else "bullish"
    report, _ = _backtest(tmp_path, direction=direction, h1_direction=wrong)
    assert _variant(report, "A").setups == ()
    assert _variant(report, "C").setups == ()
    assert _variant(report, "B").setups


def test_b2_retires_strict_wick_through_but_exact_touch_survives(tmp_path):
    exact = {1: ("101", "102", "100", "101.2")}
    report, _ = _backtest(tmp_path, m15_overrides=exact)
    assert _variant(report, "B").setups
    strict = {1: ("101", "102", "99.99", "101.2")}
    report, _ = _backtest(tmp_path, m15_overrides=strict)
    assert _variant(report, "B").setups == ()


def test_b2_does_not_fall_back_to_older_swing_when_latest_is_different(tmp_path):
    report, _ = _backtest(tmp_path, extra_swings=(("swing-newer", "99.8", 1),))
    assert _variant(report, "B").setups == ()


def _nested_low_retirements(tmp_path, candle_low):
    run, indicators, structure, _ = _pipeline(
        tmp_path, count=10, extra_swings=(("swing-95", "95", 1),),
        m15_overrides={2: ("101", "102", candle_low, "101.2")})
    machine = backtest_module._VariantMachine(
        "B", run, backtest_module._H1AsOf(indicators, structure), DEFAULT_SESSIONS)
    eligible = tuple(item for item in run.series_for("M15").candles
                     if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED)
    machine.process(structure.timeframe("M15").events, eligible, timedelta(minutes=15))
    return machine.retired


def test_b2_retires_crossed_higher_low_when_smaller_low_survives(tmp_path):
    retired = _nested_low_retirements(tmp_path, "98")
    assert "swing-latest" in retired
    assert "swing-95" not in retired


def test_b2_exact_touch_keeps_smaller_low_when_higher_low_is_crossed(tmp_path):
    retired = _nested_low_retirements(tmp_path, "95")
    assert "swing-latest" in retired
    assert "swing-95" not in retired


def test_first_aligned_mss_and_first_fvg_are_never_replaced(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path)
    candles = tuple(item.source for item in run.series_for("M15").candles)
    second_mss = _event("mss-later", "M15", "CHOCH", candles[4], direction="bullish")
    later_fvg = _event("fvg-later", "M15", "FVG_FORMED", candles[6], direction="BULLISH",
                       low="101", high="102", sources=candles[4:7])
    frame = structure.timeframe("M15")
    events = tuple(sorted((*frame.events, second_mss, later_fvg), key=lambda e: e.knowable_at))
    changed_frame = replace(frame, events=events)
    structure = replace(structure, timeframes=(structure.timeframe("H1"), changed_frame))
    result = _variant(_synthetic_backtest(run, indicators, structure), "B").setups[0]
    assert result.mss.event_id == "mss-first"
    assert result.fvg.event_id == "fvg-first"


@pytest.mark.parametrize("direction,values", [
    ("long", ("101.5", "102", "101.1", "101.5")),
    ("short", ("100.5", "100.9", "100.1", "100.5")),
])
def test_real_phase3_fvg_is_selected_independently_and_not_on_formation_bar(tmp_path, direction, values):
    run, indicators, structure, _ = _pipeline(tmp_path, direction=direction, count=5,
                                              m15_overrides={4: values})
    emitted = []
    stream_market_structure(run, "M15", on_event=emitted.append)
    formation_close = run.series_for("M15").candles[4].nominal_close_at
    fvg = next(e for e in emitted if e.event_type == "FVG_FORMED" and e.knowable_at == formation_close)
    frame = structure.timeframe("M15")
    events = tuple(fvg if e.event_id == "fvg-first" else e for e in frame.events)
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    report = _synthetic_backtest(run, indicators, structure)
    for variant in ("A", "B", "C"):
        setup = _variant(report, variant).setups[0]
        assert setup.fvg == fvg
        assert setup.fvg.event_id == fvg.event_id
        assert setup.fvg.event_at == fvg.event_at and setup.fvg.knowable_at == fvg.knowable_at
        assert setup.status == "PENDING_AT_CUTOFF"
        assert setup.entry_at is None


@pytest.mark.parametrize("setup_direction,fvg_direction", [
    ("long", "BEARISH"), ("short", "BULLISH"),
    ("long", None), ("long", "bullish"), ("short", "INVALID"),
])
def test_opposite_or_invalid_fvg_directions_fail_closed(tmp_path, setup_direction, fvg_direction):
    run, indicators, structure, _ = _pipeline(tmp_path, direction=setup_direction, count=6)
    frame = structure.timeframe("M15")
    events = tuple(replace(e, direction=fvg_direction) if e.event_id == "fvg-first" else e
                   for e in frame.events)
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    assert _variant(_synthetic_backtest(run, indicators, structure), "B").setups[0].status == "WAIT_FVG"


def test_fvg_at_mss_close_is_not_selected(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path, count=6)
    frame = structure.timeframe("M15")
    mss = next(e for e in frame.events if e.event_id == "mss-first")
    events = tuple(replace(e, event_at=mss.event_at, knowable_at=mss.knowable_at)
                   if e.event_id == "fvg-first" else e for e in frame.events)
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    assert _variant(_synthetic_backtest(run, indicators, structure), "B").setups[0].status == "WAIT_FVG"


def test_selected_diagnostic_events_reach_each_independent_variant():
    root = Path(__file__).resolve().parents[2]
    report_path = root / "reports/historical_mt5/phase5_4_abc_2026-11-19.json"
    data_dir = root / "data/raw/mt5/alpari_xauusd_i/2026-11-19"
    if not report_path.exists():
        pytest.skip("historical diagnostic artifacts are not available")
    original = json.loads(report_path.read_text())
    files = {s["timeframe"]: data_dir / s["source_file"] for s in original["source_series"]}
    if not all(path.exists() for path in files.values()):
        pytest.skip("historical source files are not available")
    assert sha256(report_path.read_bytes()).hexdigest() == "60c1761cb53e0f66db062d34f3ada26ac01445bf781bda96b291c88bb1371102"
    for timeframe, path in files.items():
        assert sha256(path.read_bytes()).hexdigest() == original["source_hashes"][timeframe]
    run = build_historical_run(files, analysis_cutoff=datetime(2021, 1, 4, 21, tzinfo=UTC))
    setups = {v["variant"]: v["setups"][0] for v in original["variants"]}
    expected = {"A": "mt5evt-1ab4b404fb29889f8dec474b",
                "B": "mt5evt-269073fc602c0aa596f8d341",
                "C": "mt5evt-1ab4b404fb29889f8dec474b"}
    ids = set(expected.values()) | {s[k]["id"] for s in setups.values()
                                    for k in ("sweep", "selected_liquidity", "mss")}
    found = {}
    stream_market_structure(run, "M15", on_event=lambda e: found.update({e.event_id: e})
                            if e.event_id in ids else None)
    assert set(found) == ids
    for variant, setup in setups.items():
        sweep, liquidity, mss = (found[setup[k]["id"]] for k in ("sweep", "selected_liquidity", "mss"))
        fvg = found[expected[variant]]
        machine = backtest_module._VariantMachine(variant, run, None, DEFAULT_SESSIONS)
        machine.state = backtest_module._Setup(variant, setup["direction"], sweep, liquidity,
                                                None, (), (), (), None, status="WAIT_FVG", mss=mss)
        formation_bar = next(item for item in run.series_for("M15").candles
                             if item.nominal_close_at == fvg.knowable_at)
        result = machine.process((fvg,), (formation_bar,), timedelta(minutes=15))[0]
        assert result.fvg == fvg
        assert result.fvg.event_id == expected[variant]
        assert result.fvg.event_at == fvg.event_at and result.fvg.knowable_at == fvg.knowable_at
        assert result.status == "PENDING_AT_CUTOFF" and result.entry_at is None


def test_same_close_mss_tie_preserves_phase3_order_and_reports_limitation(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path)
    candles = tuple(item.source for item in run.series_for("M15").candles)
    first = next(event for event in structure.timeframe("M15").events
                 if event.event_id == "mss-first")
    tied = _event("mss-emitted-first", "M15", "CHOCH", candles[3], direction="bullish",
                  known_at=first.knowable_at)
    frame = structure.timeframe("M15")
    events = tuple(sorted((tied, *frame.events), key=lambda event: event.knowable_at))
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    report = _synthetic_backtest(run, indicators, structure)
    setup = _variant(report, "B").setups[0]
    assert setup.mss.event_id == "mss-emitted-first"
    config = dict(report.configuration)
    assert "specification leaves competing same-close MSS selection unresolved" in config["same_close_event_order"]


def test_midpoint_fill_uses_observed_open_when_better_and_decimal_target(tmp_path):
    overrides = {5: ("100.4", "102", "100.2", "101")}
    report, _ = _backtest(tmp_path, m15_overrides=overrides)
    setup = _variant(report, "B").setups[0]
    assert setup.entry_price == Decimal("100.4")
    assert setup.stop_price == Decimal("99.5")
    assert setup.target_price == Decimal("102.2")
    assert setup.status == "OPEN_AT_CUTOFF"


def test_short_midpoint_limit_fill_and_target(tmp_path):
    overrides = {5: ("101.2", "101.8", "101", "101.5")}
    report, _ = _backtest(tmp_path, direction="short", m15_overrides=overrides)
    setup = _variant(report, "B").setups[0]
    assert setup.entry_price == Decimal("101.5")
    assert setup.stop_price == Decimal("102.5")
    assert setup.target_price == Decimal("99.5")


def test_sell_fill_at_open_when_open_is_at_or_better_than_limit(tmp_path):
    overrides = {5: ("101.8", "102", "101", "101.5")}
    report, _ = _backtest(tmp_path, direction="short", m15_overrides=overrides)
    assert _variant(report, "B").setups[0].entry_price == Decimal("101.8")


def test_pending_order_opening_at_or_beyond_stop_is_cancelled(tmp_path):
    overrides = {5: ("99", "101", "98", "100")}
    report, _ = _backtest(tmp_path, m15_overrides=overrides)
    setup = _variant(report, "B").setups[0]
    assert setup.status == "CANCELLED"
    assert setup.exit_reason == "OPENING_AT_OR_BEYOND_STOP"


def test_entry_bar_stop_target_ambiguity_is_separate(tmp_path):
    overrides = {5: ("101", "103", "99", "101")}
    report, _ = _backtest(tmp_path, m15_overrides=overrides)
    setup = _variant(report, "B").setups[0]
    assert setup.ambiguity_classes == (AMBIGUOUS_ENTRY_BAR,)
    assert setup.status == "AMBIGUOUS"
    assert setup.possible_outcomes == ("STOP", "TARGET", "REMAINS_OPEN")
    assert _variant(report, "B").metrics.ambiguous_entry_bar_count == 1
    assert _variant(report, "B").metrics.resolved_trade_count == 0


def test_entry_bar_target_only_reports_no_stop_outcome(tmp_path):
    report, _ = _backtest(tmp_path, m15_overrides={5: ("101", "103", "100", "101")})
    setup = _variant(report, "B").setups[0]
    assert setup.ambiguity_classes == (AMBIGUOUS_ENTRY_BAR,)
    assert setup.possible_outcomes == ("TARGET", "REMAINS_OPEN")


def test_entry_bar_stop_only_reports_no_target_outcome(tmp_path):
    report, _ = _backtest(tmp_path, m15_overrides={5: ("101", "102", "99", "101")})
    setup = _variant(report, "B").setups[0]
    assert setup.ambiguity_classes == (AMBIGUOUS_ENTRY_BAR,)
    assert setup.possible_outcomes == ("STOP", "REMAINS_OPEN")


def test_entry_and_invalidation_same_candle_keeps_both_ambiguities(tmp_path):
    overrides = {5: ("101", "102", "98", "98.5")}
    report, _ = _backtest(tmp_path, m15_overrides=overrides)
    setup = _variant(report, "B").setups[0]
    assert set(setup.ambiguity_classes) == {AMBIGUOUS_ENTRY_INVALIDATION, AMBIGUOUS_ENTRY_BAR}


def test_opposite_break_cancels_untouched_pending_order(tmp_path):
    run, indicators, structure, _ = _pipeline(
        tmp_path, m15_overrides={5: ("101", "102", "100.8", "101.2")})
    # The pending midpoint remains untouched before the opposite break closes.
    candle = run.series_for("M15").candles[5].source
    opposite = _event("opposite-break", "M15", "CHOCH", candle, direction="bearish")
    frame = structure.timeframe("M15")
    structure = replace(structure, timeframes=(structure.timeframe("H1"),
        replace(frame, events=tuple(sorted((*frame.events, opposite), key=lambda e: e.knowable_at)))))
    report = _synthetic_backtest(run, indicators, structure)
    setup = _variant(report, "B").setups[0]
    assert setup.status == "CANCELLED"
    assert setup.exit_reason == "INVALIDATED"


def test_opposite_break_at_first_fvg_close_cancels_before_activation(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path)
    candles = tuple(item.source for item in run.series_for("M15").candles)
    fvg = next(event for event in structure.timeframe("M15").events
               if event.event_id == "fvg-first")
    opposite = _event("opposite-at-fvg", "M15", "CHOCH", candles[4],
                       direction="bearish", known_at=fvg.knowable_at)
    frame = structure.timeframe("M15")
    events = tuple(sorted((*frame.events, opposite), key=lambda event: event.knowable_at))
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    report = _synthetic_backtest(run, indicators, structure)
    setup = _variant(report, "B").setups[0]
    assert setup.fvg.event_id == "fvg-first"
    assert setup.status == "CANCELLED"
    assert setup.exit_reason == "INVALIDATED"
    assert setup.exit_at == fvg.knowable_at
    assert setup.entry_at is None


@pytest.mark.parametrize("bar,reason,price", [
    (("101", "102", "99.4", "101"), "STOP", "99.5"),
    (("101", "102.6", "100", "102.5"), "TARGET", "102.5"),
    (("101", "103", "99", "101"), "STOP", "99.5"),
    (("99", "101", "98", "100"), "ADVERSE_GAP_STOP", "99"),
    (("103", "104", "102.8", "103.5"), "FAVORABLE_GAP_TARGET", "102.5"),
])
def test_later_bar_exit_policy(tmp_path, bar, reason, price):
    report, _ = _backtest(tmp_path, m15_overrides={6: bar})
    setup = _variant(report, "B").setups[0]
    assert setup.exit_reason == reason
    assert setup.exit_price == Decimal(price)
    assert setup.status == "CLOSED"


def test_sweeps_seen_while_occupied_are_not_retroactively_processed(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path, count=12,
        m15_overrides={6: ("101", "104", "99.7", "100"),
                       8: ("100", "101", "99.4", "99.7")})
    candles = tuple(item.source for item in run.series_for("M15").candles)
    new_swing = _event("swing-next", "M15", "SWING_LOW", candles[5], level="99.8")
    ignored_sweep = _event("sweep-ignored-while-open", "M15", "SELL_SIDE_SWEEP", candles[6],
                           direction="bullish", level="99.8", refs=("swing-next",),
                           sources=(candles[5], candles[6]))
    resumed_swing = _event("swing-resumed", "M15", "SWING_LOW", candles[7], level="99.5")
    resumed_sweep = _event("sweep-after-exit", "M15", "SELL_SIDE_SWEEP", candles[8],
                           direction="bullish", level="99.5", refs=("swing-resumed",),
                           sources=(candles[7], candles[8]))
    frame = structure.timeframe("M15")
    events = tuple(sorted((*frame.events, new_swing, ignored_sweep, resumed_swing, resumed_sweep),
                          key=lambda e: e.knowable_at))
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    report = _synthetic_backtest(run, indicators, structure)
    setups = _variant(report, "B").setups
    assert len(setups) == 2
    assert setups[0].status == "CLOSED"
    assert setups[0].exit_reason == "TARGET"
    assert setups[1].sweep.event_id == "sweep-after-exit"


def test_sweep_known_after_open_gap_exit_can_start_after_terminal_time(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path, count=10,
        m15_overrides={6: ("99", "101", "98", "100")})
    candles = tuple(item.source for item in run.series_for("M15").candles)
    new_swing = _event("swing-after-entry", "M15", "SWING_LOW", candles[5], level="98.5")
    new_sweep = _event("sweep-after-gap-exit", "M15", "SELL_SIDE_SWEEP", candles[6],
                       direction="bullish", level="98.5", refs=("swing-after-entry",),
                       sources=(candles[5], candles[6]))
    frame = structure.timeframe("M15")
    events = tuple(sorted((*frame.events, new_swing, new_sweep), key=lambda e: e.knowable_at))
    structure = replace(structure, timeframes=(structure.timeframe("H1"), replace(frame, events=events)))
    report = _synthetic_backtest(run, indicators, structure)
    setups = _variant(report, "B").setups
    assert setups[0].exit_reason == "ADVERSE_GAP_STOP"
    assert setups[1].sweep.event_id == "sweep-after-gap-exit"


def test_expiry_counts_sixteen_eligible_bars_after_formation(tmp_path):
    overrides = {5: ("101", "102", "100.8", "101.2")}
    report, _ = _backtest(tmp_path, count=25, m15_overrides=overrides, skip_rows=(6,))
    setup = _variant(report, "B").setups[0]
    assert setup.status == "EXPIRED"
    assert setup.eligible_bars_after_formation == 16


def test_sweep_gap_context_rejected_and_later_gap_flagged(tmp_path):
    rejected, _ = _backtest(tmp_path, gap_sweep=True)
    assert _variant(rejected, "B").setups == ()
    report, _ = _backtest(tmp_path, skip_rows=(6,))
    setup = _variant(report, "B").setups[0]
    assert "nonconsecutive_m15_interval" in setup.gap_flags


def test_session_variant_uses_sweep_close_and_a_b_have_no_filter(tmp_path):
    report, _ = _backtest(tmp_path, broker_start="2021.01.04 00:00:00")
    assert _variant(report, "A").setups
    assert _variant(report, "B").setups
    assert _variant(report, "C").setups == ()


@pytest.mark.parametrize("start,accepted", [
    ("2021.01.04 06:15:00", True),   # Asia/Qatar 08:00 inclusive
    ("2021.01.04 23:15:00", False),  # New York 17:00 exclusive in winter
    ("2021.01.04 22:45:00", True),   # New York 16:30 in winter
    ("2021.07.04 22:45:00", False),  # New York 17:30 in summer after DST
])
def test_session_window_boundaries_are_start_inclusive_end_exclusive(tmp_path, start, accepted):
    report, _ = _backtest(tmp_path, broker_start=start)
    assert bool(_variant(report, "C").setups) is accepted


def test_concurrency_chooses_smallest_stable_sweep_event_id(tmp_path):
    run, indicators, structure, sweep = _pipeline(tmp_path)
    smaller = replace(sweep, event_id="aaa-sweep")
    frame = structure.timeframe("M15")
    structure = replace(structure, timeframes=(structure.timeframe("H1"),
        replace(frame, events=tuple(sorted((*frame.events, smaller), key=lambda e: e.knowable_at)))))
    report = _synthetic_backtest(run, indicators, structure)
    assert _variant(report, "B").setups[0].sweep.event_id == "aaa-sweep"


def test_report_is_deterministic_and_contains_provenance_and_spread(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path)
    one = _synthetic_backtest(run, indicators, structure)
    two = _synthetic_backtest(run, indicators, structure)
    assert one.to_json() == two.to_json()
    data = one.to_dict()
    assert data["source_hashes"]["M15"] == run.series_for("M15").source_sha256
    assert data["timezone_policy"] == run.report.timezone_policy
    assert data["accounting"] == "GROSS-ONLY"
    assert data["algorithms"]["strategy"] == BACKTEST_ALGORITHM
    assert data["variants"][1]["setups"][0]["sweep"]["source_candles"][-1]["spread"] == 4


def test_input_source_or_cutoff_mismatch_is_rejected(tmp_path):
    run, indicators, structure, _ = _pipeline(tmp_path)
    wrong = replace(structure, analysis_cutoff=structure.analysis_cutoff + timedelta(minutes=1))
    with pytest.raises(ValueError, match="cutoffs must match"):
        _synthetic_backtest(run, indicators, wrong)
    wrong_tolerance = replace(structure, equal_level_tolerance=Decimal("0.01"))
    with pytest.raises(ValueError, match="tolerance is Decimal"):
        _synthetic_backtest(run, indicators, wrong_tolerance)


def test_public_entry_rejects_changed_approved_h1_hash(tmp_path, monkeypatch):
    run, indicators, structure, _ = _pipeline(tmp_path)
    _patch_approved_source_identity(monkeypatch, run)
    monkeypatch.setattr(backtest_module, "APPROVED_SOURCE_HASHES", (
        ("H1", "0" * 64), ("M15", run.series_for("M15").source_sha256)))
    with pytest.raises(ValueError, match="H1 source SHA-256"):
        run_smc_backtests(run, indicators, structure)


def test_public_entry_rejects_changed_approved_m15_hash(tmp_path, monkeypatch):
    run, indicators, structure, _ = _pipeline(tmp_path)
    _patch_approved_source_identity(monkeypatch, run)
    monkeypatch.setattr(backtest_module, "APPROVED_SOURCE_HASHES", (
        ("H1", run.series_for("H1").source_sha256), ("M15", "0" * 64)))
    with pytest.raises(ValueError, match="M15 source SHA-256"):
        run_smc_backtests(run, indicators, structure)


def test_public_entry_rejects_changed_evaluation_start(tmp_path, monkeypatch):
    run, indicators, structure, _ = _pipeline(tmp_path)
    _patch_approved_source_identity(monkeypatch, run)
    monkeypatch.setattr(backtest_module, "APPROVED_ANALYSIS_CUTOFF", run.report.analysis_cutoff)
    with pytest.raises(ValueError, match="evaluation start"):
        run_smc_backtests(run, indicators, structure)


def test_public_entry_rejects_changed_evaluation_cutoff(tmp_path, monkeypatch):
    run, indicators, structure, _ = _pipeline(tmp_path)
    _patch_approved_source_identity(monkeypatch, run)
    with pytest.raises(ValueError, match="analysis cutoff"):
        run_smc_backtests(run, indicators, structure)


def test_real_export_hash_and_common_cutoff_regression():
    root = Path(__file__).resolve().parents[2]
    data = root / "data/raw/mt5/alpari_xauusd_i/2026-11-19"
    if not data.is_dir():
        pytest.skip("real MT5 exports are not present in this checkout")
    files = {
        "Daily": data / "XAUUSD_i_Daily_202101040000_202611190000.csv",
        "H1": data / "XAUUSD_i_H1_202101040100_202611191300.csv",
        "M15": data / "XAUUSD_i_M15_202101040100_202611191345.csv",
    }
    expected_hashes = {
        "Daily": "4b2b796f61e76f607dfedf6a150ec6884f62081a107b17afcdc06b5a8f4812a5",
        "H1": "e1465d2ef9cbb089647933b6abee9ca68adc35d9be31f5d57c0cd4eff9500e64",
        "M15": "a9e177af909a6373db778c3e6f4c42a1353c3e5359b8ef49ac3fd152f0969efa",
    }
    run = build_historical_run(files, analysis_cutoff=datetime(2026, 11, 19, 12, tzinfo=UTC))
    assert {tf: series.source_sha256 for tf, series in
            ((tf, run.series_for(tf)) for tf in ("Daily", "H1", "M15"))} == expected_hashes
    for timeframe in ("H1", "M15"):
        eligible = [item for item in run.series_for(timeframe).candles
                    if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED]
        assert min(item.source.opened_at for item in eligible) == datetime(2021, 1, 3, 23, tzinfo=UTC)
        assert eligible[-1].nominal_close_at == datetime(2026, 11, 19, 12, tzinfo=UTC)
    common_closes = {
        timeframe: {item.nominal_close_at for item in run.series_for(timeframe).candles
                    if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED}
        for timeframe in ("H1", "M15")
    }
    shared = common_closes["H1"] & common_closes["M15"]
    assert min(shared) == datetime(2021, 1, 4, 0, tzinfo=UTC)
    assert max(shared) == datetime(2026, 11, 19, 12, tzinfo=UTC)
    assert backtest_module.APPROVED_EVALUATION_START == datetime(2021, 1, 3, 23, tzinfo=UTC)
    assert backtest_module.APPROVED_FIRST_COMMON_CLOSE == datetime(2021, 1, 4, 0, tzinfo=UTC)
    assert backtest_module.APPROVED_ANALYSIS_CUTOFF == datetime(2026, 11, 19, 12, tzinfo=UTC)
    assert all(item.eligibility == CandleEligibility.UNKNOWN_BOUNDARY
               for item in run.series_for("Daily").candles)
