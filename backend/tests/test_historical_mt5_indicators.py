from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from app.data.mt5_import import HEADERS
from app.historical_mt5 import build_historical_run
from app.historical_mt5.indicators import (
    IndicatorStatus, align_indicators, calculate_indicators,
)


BASE_LOCAL = datetime(2026, 1, 2, 0, 0)


def make_run(tmp_path, *, h1=None, m15=None, cutoff=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    h1 = [(index, Decimal(2000 + index)) for index in range(40)] if h1 is None else h1
    m15 = [(index, Decimal(2100 + index)) for index in range(40)] if m15 is None else m15
    inputs = {}
    for timeframe, values in (("Daily", []), ("H1", h1), ("M15", m15)):
        path = tmp_path / f"{timeframe}.csv"
        rows = []
        for index, close in values:
            step = timedelta(hours=index) if timeframe == "H1" else timedelta(minutes=15 * index)
            broker = BASE_LOCAL + step
            stamp = broker.strftime("%Y.%m.%d %H:%M:%S")
            rows.append(f"{stamp} {close} {close + 1} {close - 1} {close} 10 0 2")
        if timeframe == "Daily":
            rows = ["2026.01.02 2000 2001 1999 2000 1 0 1"]
        path.write_text(" ".join(f"<{column}>" for column in HEADERS[timeframe]) + "\n" +
                        "\n".join(rows) + "\n")
        inputs[timeframe] = path
    latest = max((
        (BASE_LOCAL + (timedelta(hours=i) if tf == "H1" else timedelta(minutes=15 * i))
         + (timedelta(hours=1) if tf == "H1" else timedelta(minutes=15))).replace(
             tzinfo=UTC) - timedelta(hours=2)
        for tf, values in (("H1", h1), ("M15", m15)) for i, _ in values
    ), default=datetime(2026, 1, 2, tzinfo=UTC))
    return build_historical_run(inputs, analysis_cutoff=cutoff or latest)


def track(result, timeframe, name):
    return next(item for item in result.timeframe(timeframe).tracks if item.spec.indicator == name)


def test_ema20_warmup_seed_and_subsequent_updates(tmp_path):
    values = [(i, Decimal(i + 2)) for i in range(21)]
    run = make_run(tmp_path, h1=values, m15=[])
    result = calculate_indicators(run)
    ema = track(result, "H1", "EMA")
    assert ema.spec.parameters == (("period", 20),)
    assert len(ema.observations) == 2
    assert ema.observations[0].value == Decimal("11.5")
    assert abs(ema.observations[1].value - Decimal("12.5")) < Decimal("1e-28")
    assert all(o.status == IndicatorStatus.READY for o in ema.observations)
    assert ema.observations[0].provider == "alpari_mt5"
    assert ema.observations[0].broker == "Alpari MT5 Demo"
    assert ema.observations[0].source_candle.source_row == 21
    assert ema.observations[0].source_candle.utc_timestamp == ema.observations[0].opened_at
    assert ema.observations[0].source_candle.source_timezone == "UTC+02:00 fixed"
    assert ema.observations[0].source_candle.timezone_policy == run.report.timezone_policy
    assert ema.observations[0].algorithm_version == "mt5-decimal-indicators-v1"


def test_rsi14_sma_seed_and_wilder_update(tmp_path):
    closes = [Decimal(100 + i) for i in range(15)] + [Decimal(113)]
    result = calculate_indicators(make_run(tmp_path, h1=list(enumerate(closes)), m15=[]))
    rsi = track(result, "H1", "RSI")
    assert len(rsi.observations) == 2
    assert rsi.observations[0].value == Decimal(100)
    with localcontext() as context:
        context.prec = 34
        assert rsi.observations[1].value == Decimal(100) - Decimal(100) / Decimal(14)


def test_atr14_true_range_uses_previous_close_and_wilder_update(tmp_path):
    closes = [Decimal(10 + i) for i in range(14)] + [Decimal(23)]
    # The final candle spans 18..20 while the preceding close is 23, so TR is 5.
    closes[-1] = Decimal(19)
    result = calculate_indicators(make_run(tmp_path / "adjusted", h1=list(enumerate(closes)), m15=[]))
    atr = track(result, "H1", "ATR")
    with localcontext() as context:
        context.prec = 34
        assert [o.value for o in atr.observations] == [Decimal(2), Decimal(31) / Decimal(14)]


def test_macd_line_signal_seed_and_histogram_warmup(tmp_path):
    result = calculate_indicators(make_run(tmp_path, h1=[(i, Decimal(i + 2)) for i in range(40)], m15=[]))
    line = track(result, "H1", "MACD_LINE")
    signal = track(result, "H1", "MACD_SIGNAL")
    histogram = track(result, "H1", "MACD_HISTOGRAM")
    assert len(line.observations) == 15
    assert len(signal.observations) == len(histogram.observations) == 7
    assert abs(line.observations[0].value - Decimal(7)) < Decimal("1e-25")
    assert abs(signal.observations[0].value - Decimal(7)) < Decimal("1e-25")
    assert abs(histogram.observations[0].value) < Decimal("1e-25")
    assert signal.observations[0].opened_at == line.observations[8].opened_at


def test_ten_candle_close_roc_and_decimal_values(tmp_path):
    values = [(i, Decimal(100 + i)) for i in range(11)]
    result = calculate_indicators(make_run(tmp_path, h1=values, m15=[]))
    momentum = track(result, "H1", "MOMENTUM_ROC")
    assert len(momentum.observations) == 1
    assert momentum.observations[0].value == Decimal(10)
    assert isinstance(momentum.observations[0].value, Decimal)


def test_empty_short_and_daily_are_excluded(tmp_path):
    result = calculate_indicators(make_run(tmp_path, h1=[(0, Decimal(2000))], m15=[]))
    assert result.excluded_timeframes == (("Daily", "UNKNOWN_BOUNDARY"),)
    assert {item.timeframe for item in result.timeframes} == {"H1", "M15"}
    assert all(not item.observations for item in result.timeframe("H1").tracks)
    assert all(item.status == IndicatorStatus.WARMING_UP for item in result.timeframe("H1").tracks)
    assert all(item.status == IndicatorStatus.NO_ELIGIBLE_CANDLES for item in result.timeframe("M15").tracks)


def test_fully_empty_series_have_explicit_no_data_status(tmp_path):
    result = calculate_indicators(make_run(tmp_path, h1=[], m15=[]))
    assert all(track_item.status == IndicatorStatus.NO_ELIGIBLE_CANDLES
               for series in result.timeframes for track_item in series.tracks)


def test_ema50_and_ema200_warmup_seed_positions(tmp_path):
    result = calculate_indicators(make_run(tmp_path, h1=[(i, Decimal(i + 2)) for i in range(201)], m15=[]))
    ema_tracks = [item for item in result.timeframe("H1").tracks if item.spec.indicator == "EMA"]
    assert [item.warmup_bars_required for item in ema_tracks] == [20, 50, 200]
    assert [item.observations[0].value for item in ema_tracks] == [
        sum((Decimal(i + 2) for i in range(20)), Decimal(0)) / 20,
        sum((Decimal(i + 2) for i in range(50)), Decimal(0)) / 50,
        sum((Decimal(i + 2) for i in range(200)), Decimal(0)) / 200,
    ]


def test_gaps_are_reported_without_fabricating_candles(tmp_path):
    values = [(i, Decimal(2000 + i)) for i in range(22) if i != 20]
    result = calculate_indicators(make_run(tmp_path, h1=values, m15=[]))
    h1 = result.timeframe("H1")
    assert h1.eligible_candle_count == 21
    assert h1.gap_count == 1
    ema = track(result, "H1", "EMA")
    assert any(o.gap_before for o in ema.observations)
    assert len(ema.observations) == 2
    assert ema.observations[-1].gap_before


def test_h1_m15_series_are_independent_and_alignment_is_as_of(tmp_path):
    run = make_run(tmp_path, h1=[(i, Decimal(2000 + i)) for i in range(230)],
                   m15=[(i, Decimal(2100 + i)) for i in range(230)])
    result = calculate_indicators(run)
    assert result.timeframe("H1").series_id != result.timeframe("M15").series_id
    evaluation = run.report.analysis_cutoff
    aligned = align_indicators(result, evaluation)
    assert aligned.status == "COMPLETE"
    h1 = next(v for v in aligned.values if v.timeframe == "H1" and v.indicator == "EMA")
    m15 = next(v for v in aligned.values if v.timeframe == "M15" and v.indicator == "EMA")
    assert h1.observation.closed_at <= evaluation
    assert m15.observation.closed_at <= evaluation
    assert h1.observation.opened_at != m15.observation.opened_at
    assert h1.observation.source_candle.source_file == "H1.csv"
    assert m15.observation.source_candle.source_file == "M15.csv"


def test_alignment_marks_warmup_no_future_and_cutoff(tmp_path):
    run = make_run(tmp_path, h1=[(i, Decimal(2000 + i)) for i in range(19)], m15=[])
    result = calculate_indicators(run)
    evaluation = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    aligned = align_indicators(result, evaluation)
    ema = next(v for v in aligned.values if v.timeframe == "H1" and v.indicator == "EMA")
    assert ema.status == IndicatorStatus.WARMING_UP
    assert ema.observation is None
    with pytest.raises(ValueError, match="must not exceed"):
        align_indicators(result, run.report.analysis_cutoff + timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        align_indicators(result, datetime(2026, 1, 1))


def test_prefix_invariance_and_repeatability(tmp_path):
    values = [(i, Decimal(2000 + i) / Decimal("1.1")) for i in range(230)]
    prefix = calculate_indicators(make_run(tmp_path / "prefix", h1=values[:210], m15=[]))
    full = calculate_indicators(make_run(tmp_path / "full", h1=values, m15=[]))
    repeated = calculate_indicators(make_run(tmp_path / "full", h1=values, m15=[]))
    first = track(prefix, "H1", "EMA").observations
    second = tuple(o for o in track(full, "H1", "EMA").observations if o.opened_at <= first[-1].opened_at)
    assert [o.value for o in first] == [o.value for o in second]
    assert full == repeated
    assert all(isinstance(o.value, Decimal) for o in first)


def test_analysis_cutoff_excludes_incomplete_candles(tmp_path):
    base = BASE_LOCAL.replace(tzinfo=UTC) - timedelta(hours=2)
    cutoff = base + timedelta(hours=1)
    run = make_run(tmp_path, h1=[(0, Decimal(2000)), (1, Decimal(2001))], m15=[], cutoff=cutoff)
    result = calculate_indicators(run)
    assert result.timeframe("H1").eligible_candle_count == 1
    assert all(o.closed_at <= cutoff for track_item in result.timeframe("H1").tracks
               for o in track_item.observations)
