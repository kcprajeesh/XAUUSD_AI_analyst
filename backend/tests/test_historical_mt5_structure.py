from datetime import UTC, datetime, timedelta
from decimal import Decimal
from decimal import localcontext
import ast
from pathlib import Path

import pytest

from app.data.mt5_import import HEADERS
from app.historical_mt5 import analyze_market_structure, build_historical_run

BASE_UTC = datetime(2026, 1, 2, tzinfo=UTC)
OFFSET = timedelta(hours=2)


def bar(index, *, high="20", low="5", close="15", open_=None):
    open_ = close if open_ is None else open_
    return index, open_, high, low, close


def make_run(tmp_path, *, h1, m15=(), cutoff=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = {}
    latest_close = None
    for timeframe, values in (("Daily", ()), ("H1", h1), ("M15", m15)):
        path = tmp_path / f"{timeframe}.csv"
        lines = [" ".join(f"<{name}>" for name in HEADERS[timeframe])]
        if timeframe == "Daily":
            lines.append("2026.01.02 2000 2001 1999 2000 1 0 1")
        else:
            step = timedelta(hours=1) if timeframe == "H1" else timedelta(minutes=15)
            for index, open_, high, low, close in values:
                opened = BASE_UTC + index * step
                broker = opened + OFFSET
                lines.append(f"{broker:%Y.%m.%d} {broker:%H:%M:%S} {open_} {high} {low} {close} 10 0 2")
                latest_close = max(latest_close or opened + step, opened + step)
        path.write_text("\n".join(lines) + "\n")
        files[timeframe] = path
    return build_historical_run(files, analysis_cutoff=cutoff or latest_close or BASE_UTC)


def analyze(tmp_path, h1, *, tolerance=Decimal(0), m15=(), cutoff=None):
    run = make_run(tmp_path, h1=h1, m15=m15, cutoff=cutoff)
    return run, analyze_market_structure(run, equal_level_tolerance=tolerance)


def events(result, timeframe="H1", kind=None):
    found = result.timeframe(timeframe).events
    return tuple(item for item in found if kind is None or item.event_type == kind)


def test_swing_confirmed_only_after_two_right_bars_and_retains_provenance(tmp_path):
    rows = [bar(i, high=high, low="5", close="8")
            for i, high in enumerate([9, 10, 12, 10, 9, 8, 7])]
    run, result = analyze(tmp_path, rows)
    high = events(result, kind="SWING_HIGH")[0]
    assert high.event_at == BASE_UTC + timedelta(hours=3)  # pivot bar close at index 2
    assert high.knowable_at == BASE_UTC + timedelta(hours=5)  # index 4 closed
    assert len(high.source_candles) == 5
    assert high.source_candles[2].source_timestamp == "2026.01.02 04:00:00"
    assert high.source_candles[2].source_sha256 == run.series_for("H1").source_sha256
    assert high.source_candles[2].source_row == 4
    assert high.source_candles[2] is run.series_for("H1").candles[2].source
    assert high.liquidity_side == "BUY_SIDE"
    assert high.state == "POTENTIAL"


def test_equal_extrema_ties_do_not_form_pivots(tmp_path):
    rows = [bar(i, high=high, low="5", close="8")
            for i, high in enumerate([9, 12, 12, 10, 9, 8, 7])]
    _, result = analyze(tmp_path, rows)
    assert not events(result, kind="SWING_HIGH")
    assert result.timeframe("H1").diagnostics.tied_high_candidates_rejected == 1
    assert result.timeframe("H1").diagnostics.tied_low_candidates_rejected > 0


def test_confirmed_swing_classifications_hh_lh_and_hl_ll(tmp_path):
    high_levels = {2: "30", 6: "32", 10: "31", 14: "33"}
    highs = [bar(i, high=high_levels.get(i, "20"), low="5", close="15") for i in range(19)]
    _, high_result = analyze(tmp_path / "highs", highs)
    assert [e.label for e in events(high_result, kind="SWING_HIGH")] == ["INITIAL", "HH", "LH", "HH"]

    low_levels = {2: "10", 6: "8", 10: "9", 14: "7"}
    lows = [bar(i, high="30", low=low_levels.get(i, "20"), close="22") for i in range(19)]
    _, low_result = analyze(tmp_path / "lows", lows)
    assert [e.label for e in events(low_result, kind="SWING_LOW")] == ["INITIAL", "LL", "HL", "LL"]


def test_equal_high_and_low_tolerance_is_decimal_configurable(tmp_path):
    highs = {2: "30", 6: "32", 10: "30.05"}
    rows = [bar(i, high=highs.get(i, "20"), low="5", close="15") for i in range(15)]
    _, tolerant = analyze(tmp_path / "tolerant", rows, tolerance=Decimal("0.10"))
    _, exact = analyze(tmp_path / "exact", rows, tolerance=Decimal("0.01"))
    eqh = events(tolerant, kind="EQUAL_HIGHS")
    assert len(eqh) == 1 and eqh[0].price_level == Decimal("30.05")
    assert eqh[0].reference_event_ids[0] == events(tolerant, kind="SWING_HIGH")[0].event_id
    assert events(tolerant, kind="SWING_HIGH")[-1].label == "LH"
    assert not events(exact, kind="EQUAL_HIGHS")

    lows = {2: "10", 6: "8", 10: "10.05"}
    low_rows = [bar(i, high="30", low=lows.get(i, "20"), close="22") for i in range(15)]
    _, equal_lows = analyze(tmp_path / "equal_lows", low_rows, tolerance=Decimal("0.10"))
    assert len(events(equal_lows, kind="EQUAL_LOWS")) == 1
    with pytest.raises(ValueError, match="finite nonnegative Decimal"):
        analyze(tmp_path / "invalid", rows, tolerance=Decimal("-0.1"))


def test_first_close_break_seeds_bias_then_opposite_break_is_choch_once(tmp_path):
    rows = [
        bar(0, high="8", low="8", close="8"),
        bar(1, high="9", low="7", close="8"),
        bar(2, high="12", low="6", close="10"),
        bar(3, high="10", low="7", close="8"),
        bar(4, high="9", low="8", close="8"),
        bar(5, high="13", low="8", close="11"),  # wick above 12, close below: sweep only
        bar(6, high="14", low="8", close="13"),  # first close break: BOS, bullish bias
        bar(7, high="8", low="3", close="4"),    # opposite close break: CHoCH
        bar(8, high="7", low="4", close="4"),    # same level cannot fire twice
    ]
    _, result = analyze(tmp_path, rows)
    breaks = tuple(e for e in events(result) if e.event_type in {"BOS", "CHOCH"})
    assert [(e.event_type, e.direction, e.state, e.label) for e in breaks] == [
        ("BOS", "bullish", "BULLISH", "FIRST_BREAK"),
        ("CHOCH", "bearish", "BEARISH", None),
    ]
    assert result.timeframe("H1").final_bias == "BEARISH"
    assert all(e.event_at == e.knowable_at for e in breaks)


def test_wick_only_break_does_not_emit_bos(tmp_path):
    rows = [bar(i, high=h, low="5", close=c) for i, (h, c) in enumerate([
        (9, 8), (10, 8), (12, 10), (10, 8), (9, 8), (13, 11),
    ])]
    _, result = analyze(tmp_path, rows)
    assert not tuple(e for e in events(result) if e.event_type in {"BOS", "CHOCH"})
    assert events(result, kind="BUY_SIDE_SWEEP")


def test_new_confirmed_level_can_bos_again_but_same_level_cannot_repeat(tmp_path):
    rows = [
        bar(0, high="9", low="5", close="8"),
        bar(1, high="10", low="5", close="9"),
        bar(2, high="12", low="5", close="10"),
        bar(3, high="10", low="5", close="9"),
        bar(4, high="9", low="5", close="8"),
        bar(5, high="13", low="5", close="13"),  # BOS through 12
        bar(6, high="14", low="5", close="11"),  # returns below 12
        bar(7, high="15", low="5", close="13"),  # same 12 level cannot repeat
    ]
    _, result = analyze(tmp_path, rows)
    breaks = tuple(e for e in events(result) if e.event_type in {"BOS", "CHOCH"})
    assert len(breaks) == 1
    assert breaks[0].price_level == Decimal(12)


def test_same_direction_break_of_a_new_confirmed_level_remains_bos(tmp_path):
    rows = [
        bar(0, high="9", low="5", close="8"),
        bar(1, high="10", low="5", close="9"),
        bar(2, high="12", low="5", close="10"),
        bar(3, high="10", low="5", close="9"),
        bar(4, high="9", low="5", close="8"),
        bar(5, high="13", low="5", close="13"),  # BOS through 12
        bar(6, high="15", low="5", close="14"),  # new swing high, not a repeat
        bar(7, high="14", low="5", close="12"),
        bar(8, high="13", low="5", close="12"),  # confirms high 15
        bar(9, high="16", low="5", close="16"),  # BOS through new level 15
    ]
    _, result = analyze(tmp_path, rows)
    breaks = tuple(e for e in events(result) if e.event_type in {"BOS", "CHOCH"})
    assert [(event.event_type, event.price_level, event.state) for event in breaks] == [
        ("BOS", Decimal(12), "BULLISH"), ("BOS", Decimal(15), "BULLISH"),
    ]


def test_buy_side_and_sell_side_wick_closeback_sweeps(tmp_path):
    buy = [bar(i, high=h, low="5", close=c) for i, (h, c) in enumerate([
        (9, 8), (10, 8), (12, 10), (10, 8), (9, 8), (13, 11),
    ])]
    _, buy_result = analyze(tmp_path / "buy", buy)
    buy_sweep = events(buy_result, kind="BUY_SIDE_SWEEP")[0]
    swing_high = events(buy_result, kind="SWING_HIGH")[0]
    assert buy_sweep.reference_event_ids == (swing_high.event_id,)
    assert buy_sweep.source_candles[-1].source_row == 7
    assert buy_sweep.event_at == BASE_UTC + timedelta(hours=6)
    assert buy_sweep.price_level == Decimal(12)
    assert buy_sweep.state == "SWEPT"

    sell = [bar(i, high="30", low=low, close=c) for i, (low, c) in enumerate([
        (8, 10), (7, 10), (6, 8), (7, 10), (8, 10), (5, 7),
    ])]
    _, sell_result = analyze(tmp_path / "sell", sell)
    sell_sweep = events(sell_result, kind="SELL_SIDE_SWEEP")[0]
    assert sell_sweep.price_level == Decimal(6)
    assert sell_sweep.direction == "bullish"


@pytest.mark.parametrize(("rows", "direction", "low", "high"), [
    ([(0, "10", "7", "9"), (1, "11", "9", "10"), (2, "14", "12", "13")],
     "BULLISH", Decimal(10), Decimal(12)),
    ([(0, "15", "12", "13"), (1, "13", "11", "12"), (2, "10", "8", "9")],
     "BEARISH", Decimal(10), Decimal(12)),
])
def test_bullish_and_bearish_fvg_boundaries_and_unfilled_at_formation(
        tmp_path, rows, direction, low, high):
    candles = [bar(i, high=h, low=l, close=c) for i, h, l, c in rows]
    _, result = analyze(tmp_path, candles)
    formed = events(result, kind="FVG_FORMED")
    assert len(formed) == 1
    fvg = formed[0]
    assert fvg.direction == direction
    assert (fvg.price_low, fvg.price_high, fvg.state) == (low, high, "UNFILLED")
    assert len(fvg.source_candles) == 3
    assert fvg.event_at == fvg.knowable_at == BASE_UTC + timedelta(hours=3)
    assert result.timeframe("H1").fair_value_gaps[0].status == "UNFILLED"


def test_fvg_partial_then_full_mitigation_only_at_later_closes(tmp_path):
    rows = [
        bar(0, high="10", low="7", close="9"),
        bar(1, high="11", low="9", close="10"),
        bar(2, high="14", low="12", close="13"),
        bar(3, high="13", low="11", close="12"),
        bar(4, high="12", low="9", close="10"),
    ]
    _, result = analyze(tmp_path, rows)
    partial = events(result, kind="FVG_PARTIAL_MITIGATION")
    full = events(result, kind="FVG_FULL_MITIGATION")
    assert len(partial) == len(full) == 1
    assert partial[0].state == "PARTIALLY_MITIGATED"
    assert partial[0].event_at == BASE_UTC + timedelta(hours=4)
    assert full[0].state == "FULLY_MITIGATED"
    assert full[0].event_at == BASE_UTC + timedelta(hours=5)
    zone = result.timeframe("H1").fair_value_gaps[0]
    assert zone.status == "FULLY_MITIGATED"
    assert full[0].reference_event_ids == (zone.gap_id,)


def test_bearish_fvg_partial_then_full_mitigation(tmp_path):
    rows = [
        bar(0, high="15", low="12", close="13"),
        bar(1, high="13", low="11", close="12"),
        bar(2, high="10", low="8", close="9"),
        bar(3, high="11", low="9", close="10"),
        bar(4, high="13", low="10", close="12"),
    ]
    _, result = analyze(tmp_path, rows)
    zone = result.timeframe("H1").fair_value_gaps[0]
    assert zone.direction == "BEARISH"
    assert zone.status == "FULLY_MITIGATED"
    assert [e.event_type for e in events(result) if e.event_type.startswith("FVG_")] == [
        "FVG_FORMED", "FVG_PARTIAL_MITIGATION", "FVG_FULL_MITIGATION",
    ]


def test_fvg_mitigation_after_session_gap_is_marked_with_gap_context(tmp_path):
    rows = [bar(0, high="10", low="7", close="9"),
            bar(1, high="11", low="9", close="10"),
            bar(2, high="14", low="12", close="13"),
            bar(4, high="13", low="11", close="12")]
    _, result = analyze(tmp_path, rows)
    partial = events(result, kind="FVG_PARTIAL_MITIGATION")
    assert len(partial) == 1
    assert partial[0].gap_context
    assert partial[0].quality_status == "GAP_CONTEXT"


def test_fvg_does_not_bridge_missing_nominal_candle(tmp_path):
    rows = [bar(0, high="10", low="7", close="9"),
            bar(1, high="11", low="9", close="10"),
            bar(3, high="14", low="12", close="13"),
            bar(4, high="14", low="12", close="13"),
            bar(5, high="14", low="12", close="13")]
    _, result = analyze(tmp_path, rows)
    series = result.timeframe("H1")
    assert not events(result, kind="FVG_FORMED")
    assert series.diagnostics.fvg_patterns_rejected_for_gaps == 2
    assert series.diagnostics.swing_windows_rejected_for_gaps > 0
    assert series.diagnostics.nonconsecutive_intervals == 1


def test_break_and_sweep_after_gap_are_marked_with_gap_context(tmp_path):
    rows = [bar(0, high="9", low="5", close="8"),
            bar(1, high="10", low="5", close="8"),
            bar(2, high="12", low="5", close="10"),
            bar(3, high="10", low="5", close="8"),
            bar(4, high="9", low="5", close="8"),
            bar(6, high="13", low="5", close="11")]
    _, result = analyze(tmp_path, rows)
    sweep = events(result, kind="BUY_SIDE_SWEEP")[0]
    assert sweep.gap_context
    assert sweep.quality_status == "GAP_CONTEXT"


def test_premium_discount_uses_only_latest_confirmed_opposite_swings(tmp_path):
    rows = [bar(i, high={2: "14"}.get(i, "10"), low={6: "5"}.get(i, "7"),
                close={2: "11", 6: "8"}.get(i, "10")) for i in range(11)]
    run, result = analyze(tmp_path, rows)
    snapshot = events(result, kind="PREMIUM_DISCOUNT")[-1]
    assert snapshot.label == "PREMIUM"
    assert (snapshot.price_low, snapshot.price_high, snapshot.price_level) == (
        Decimal(5), Decimal(14), Decimal("9.5"))
    assert snapshot.price_value == Decimal(10)
    assert len(snapshot.source_candles) == 1
    assert snapshot.source_candles[0].source_timestamp == "2026.01.02 12:00:00"
    assert len(snapshot.reference_event_ids) == 2
    with localcontext() as context:
        context.prec = 34
        assert snapshot.position_percent == Decimal(5) / Decimal(9) * Decimal(100)

    prefix_cutoff = BASE_UTC + timedelta(hours=8)  # low pivot at index 6 is not confirmed yet
    prefix = analyze_market_structure(make_run(tmp_path / "prefix", h1=rows, cutoff=prefix_cutoff))
    assert not events(prefix, kind="PREMIUM_DISCOUNT")
    assert snapshot.knowable_at == run.report.analysis_cutoff


def test_prefix_invariance_deterministic_ids_and_independent_timeframes(tmp_path):
    rows = [bar(i, high={2: "14", 6: "13"}.get(i, "10"),
                low={4: "5"}.get(i, "7"), close="9") for i in range(12)]
    full_run = make_run(tmp_path / "full", h1=rows, m15=[bar(i, high="20", low="5", close="10")
                                                       for i in range(24)])
    full = analyze_market_structure(full_run, equal_level_tolerance=Decimal("0.05"))
    repeated = analyze_market_structure(full_run, equal_level_tolerance=Decimal("0.05"))
    assert full == repeated
    assert {item.timeframe for item in full.timeframes} == {"H1", "M15"}
    assert full.timeframe("H1").series_id != full.timeframe("M15").series_id
    assert full.excluded_timeframes == (("Daily", "UNKNOWN_BOUNDARY"),)
    assert all(event.provider == "alpari_mt5" and event.broker == "Alpari MT5 Demo"
               and event.symbol == "XAUUSD_i" and event.algorithm_version == full.algorithm_version
               for series in full.timeframes for event in series.events)
    assert all(event.source_candles for series in full.timeframes for event in series.events)
    all_events = tuple(event for series in full.timeframes for event in series.events)
    assert all(event.event_id.startswith("mt5evt-") for event in all_events)
    assert len({event.event_id for event in all_events}) == len(all_events)

    cutoff = BASE_UTC + timedelta(hours=8)
    prefix_run = make_run(tmp_path / "prefix_run", h1=rows, cutoff=cutoff)
    prefix = analyze_market_structure(prefix_run, equal_level_tolerance=Decimal("0.05"))
    full_prior = tuple(event for event in full.timeframe("H1").events if event.knowable_at <= cutoff)
    prefix_prior = prefix.timeframe("H1").events
    assert prefix_prior == full_prior
    assert all(event.knowable_at <= prefix_run.report.analysis_cutoff
               for event in prefix.timeframe("H1").events)


def test_only_eligible_closed_candles_are_analyzed_and_daily_stays_excluded(tmp_path):
    rows = [bar(i, high="10", low="5", close="8") for i in range(5)]
    cutoff = BASE_UTC + timedelta(hours=4)
    run = make_run(tmp_path, h1=rows, cutoff=cutoff)
    result = analyze_market_structure(run)
    assert result.timeframe("H1").diagnostics.eligible_candles == 4
    assert result.excluded_timeframes == (("Daily", "UNKNOWN_BOUNDARY"),)
    with pytest.raises(KeyError):
        result.timeframe("Daily")


def test_structure_module_has_no_live_api_database_or_sifting_imports():
    module = Path(__file__).parents[1] / "app" / "historical_mt5" / "structure.py"
    forbidden = {"sqlite3", "fastapi", "app.main", "app.data.siftingio", "app.data.storage"}
    tree = ast.parse(module.read_text())
    for node in ast.walk(tree):
        imported = ({alias.name for alias in node.names} if isinstance(node, ast.Import)
                    else {node.module or ""} if isinstance(node, ast.ImportFrom) else set())
        assert not any(name == target or name.startswith(target + ".")
                       for name in imported for target in forbidden)
