"""Synthetic deterministic analysis checks; values are not market observations."""
from datetime import UTC, datetime, timedelta, time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai.evidence import (
    CandleOrigin, CandleState, EvidenceCandle, EvidencePacket, InstrumentIdentity, InstrumentType,
    QualityStatus, SourceIdentity, Timeframe, TimeframeEvidence, TimeframeState, VolumeType,
)
from app.ai.evidence import DataQualityFlag
from app.ai.evidence import EvidenceType
from app.analysis.engine import AnalysisParameters, analyze_packet
from app.analysis.indicators import atr, ema, momentum, rsi, vwap
from app.analysis.market_structure import equal_levels, structure_events, swings, sweeps, support_resistance
from app.analysis.sessions import SessionDefinition, classify_sessions
from app.analysis.smc import fair_value_gaps, premium_discount

BASE = datetime(2026, 1, 15, 12, tzinfo=UTC)
IDENTITY = InstrumentIdentity(instrument_id="xau-usd:spot-synthetic", instrument_type=InstrumentType.OTC_SPOT)


def candle(i, *, close=None, high=None, low=None, open_=None, timeframe=Timeframe.H1, status=CandleState.CLOSED,
           volume=None, volume_type=VolumeType.UNSPECIFIED, opened_at=None):
    c = Decimal(close if close is not None else 100 + i)
    o = Decimal(open_ if open_ is not None else c)
    h = Decimal(high if high is not None else max(o, c) + 1)
    l = Decimal(low if low is not None else max(Decimal("0.1"), min(o, c) - 1))
    opened = opened_at or BASE - timedelta(hours=300-i)
    duration = {Timeframe.D1: timedelta(days=1), Timeframe.H4: timedelta(hours=4),
                Timeframe.H1: timedelta(hours=1), Timeframe.M15: timedelta(minutes=15),
                Timeframe.M5: timedelta(minutes=5)}[timeframe]
    return EvidenceCandle(candle_id=f"synthetic-{i}-{timeframe.value}", source_id="synthetic-source", timeframe=timeframe,
        opened_at=opened, closed_at=opened+duration, status=status, origin=CandleOrigin.NATIVE,
        open=o, high=h, low=l, close=c, volume_value=Decimal(volume) if volume is not None else None,
        volume_type=volume_type)


def packet(candles, *, flags=()):
    latest = candles[-1]
    retrieved = (latest.opened_at + timedelta(minutes=30) if latest.status == CandleState.FORMING
                 else max(c.closed_at for c in candles) + timedelta(minutes=1))
    source = SourceIdentity(source_id="synthetic-source", instrument=IDENTITY, provider_id="synthetic",
        feed_id="fixture", series_id="synthetic:1h", provider_symbol="XAUUSD", retrieved_at=retrieved,
        price_normalization="source_decimal_text", source_price_precision="fixture")
    tf = TimeframeEvidence(timeframe=Timeframe.H1, state=TimeframeState.AVAILABLE, origin=CandleOrigin.NATIVE,
        source_ids=(source.source_id,), candles=tuple(candles), quality_flags=tuple(flags))
    rest = tuple(TimeframeEvidence(timeframe=t, state=TimeframeState.UNAVAILABLE) for t in Timeframe if t != Timeframe.H1)
    return EvidencePacket(analysis_id="synthetic-analysis", analysis_at=retrieved, instrument=IDENTITY,
        sources=(source,), requested_timeframes=tuple(Timeframe), retrieved_at=retrieved,
        timeframes=(tf, *rest), quality_flags=tuple(flags))


def test_ema_sma_seed_recurrence_warmup_and_determinism():
    cs = [candle(i, close=str(v)) for i, v in enumerate([1, 2, 3, 4, 5])]
    assert not ema(cs[:2], 3)
    assert ema(cs, 3)[0].value == Decimal(2)
    assert ema(cs, 3)[-1].value == Decimal("4.00")
    assert ema(cs, 3, latest_only=True)[0] == ema(cs, 3)[-1]
    assert ema(cs, 3)[-1].calculated_at == cs[-1].closed_at


def test_rsi_wilder_rising_falling_flat_and_warmup():
    rising = [candle(i, close=str(10+i)) for i in range(15)]
    falling = [candle(i, close=str(30-i)) for i in range(15)]
    flat = [candle(i, close="10") for i in range(15)]
    assert not rsi(rising[:14])
    assert rsi(rising)[0].value == Decimal(100)
    assert rsi(falling)[0].value == Decimal(0)
    assert rsi(flat)[0].value == Decimal(50)


def test_close_momentum_is_percent_change_with_explicit_warmup():
    rising = [candle(i, close=str(100+i)) for i in range(11)]
    falling = [candle(i, close=str(110-i)) for i in range(11)]
    flat = [candle(i, close="100") for i in range(11)]
    assert momentum(rising[:10]) is None
    assert momentum(rising).value == Decimal(10)
    assert momentum(falling).value == Decimal("-9.090909090909090909090909090909091")
    assert momentum(flat).value == 0


def test_atr_wilder_gap_and_warmup():
    cs = [candle(0, open_="10", high="12", low="9", close="11"),
          candle(1, open_="20", high="22", low="19", close="21"),
          candle(2, open_="21", high="23", low="20", close="22")]
    assert not atr(cs, 4)
    values = atr(cs, 2)
    assert values[0].value == Decimal("7")  # TR: 3 and 11
    assert values[1].value == Decimal("5")  # Wilder: (7 + 3) / 2


def test_swing_confirmation_structure_and_liquidity_sweep():
    cs = [candle(0, high="10", low="5", close="8"), candle(1, high="12", low="6", close="9"),
          candle(2, high="11", low="7", close="9"), candle(3, high="10", low="8", close="9"),
          candle(4, high="14", low="8", close="13")]
    pts = swings(cs, 1, 1)
    high = next(s for s in pts if s.high)
    assert high.index == 1
    assert not structure_events(cs[:3], pts, 1)  # right candle needed before confirmation
    ev = structure_events(cs, pts, 1)
    assert ev and ev[-1].kind == "BOS" and ev[-1].direction == "bullish"
    swept = cs + [candle(5, high="14", low="8", close="11")]
    assert sweeps(swept, pts, 1)


def test_equal_swing_levels_within_and_outside_tolerance():
    cs = [candle(i, high=h, low="5", close=str(Decimal(h)-Decimal("0.5"))) for i, h in enumerate([8, 10, 8, 8, 10.05, 8, 7])]
    pts = swings(cs, 1, 1)
    assert any(label == "equal_highs" for label, *_ in equal_levels(pts, Decimal("0.1")))
    assert not any(label == "equal_highs" for label, *_ in equal_levels(pts, Decimal("0.01")))


def test_support_resistance_cluster_confirmed_swings_only():
    from app.analysis.market_structure import Swing
    cs = [candle(i, close="8", high=h, low=l) for i, (h, l) in enumerate(
        [("10", "5"), ("12", "6"), ("10.05", "5.04"), ("14", "4"), ("10.02", "5.02")])]
    points = (Swing(0, cs[0], True), Swing(1, cs[1], False), Swing(2, cs[2], True),
              Swing(3, cs[3], False), Swing(4, cs[4], False))
    levels = support_resistance(points, Decimal("0.1"))
    resistance = next(value for label, value, _ in levels if label == "resistance")
    support = [value for label, value, _ in levels if label == "support"]
    assert resistance == Decimal("10.025")
    assert support == [Decimal("4"), Decimal("5.02"), Decimal("6")]


def test_vwap_requires_complete_usable_volume_and_uses_hlc3():
    valid = [candle(0, open_="10", high="13", low="7", close="10", volume="2",
                    volume_type=VolumeType.EXCHANGE_TRADED),
             candle(1, open_="10", high="16", low="10", close="13", volume="1",
                    volume_type=VolumeType.EXCHANGE_TRADED)]
    point = vwap(valid)
    assert point.value == Decimal("11")
    assert point.method == "vwap_hlc3_retrieval_window_exchange_or_contract_volume_v1"
    ticks = [candle(0, volume="10", volume_type=VolumeType.TICK_COUNT)]
    assert vwap(ticks) is None
    assert vwap(valid + [candle(2)]) is None
    zero = [candle(0, volume="0", volume_type=VolumeType.CONTRACT)]
    assert vwap(zero) is None


def test_engine_emits_vwap_unavailable_for_tick_counts_and_atr_relative_volatility():
    cs = [candle(i, close=str(2000+i), volume="100", volume_type=VolumeType.TICK_COUNT) for i in range(30)]
    output = analyze_packet(packet(cs))
    assert any(record.evidence_type == EvidenceType.VWAP and record.quality == QualityStatus.UNSUPPORTED
               for record in output.evidence)
    volatility = next(record for record in output.evidence if record.evidence_type == EvidenceType.VOLATILITY)
    assert volatility.value is not None and volatility.units == "percent_of_close"


def test_engine_reports_partial_multitimeframe_ema_alignment_with_missing_h4():
    hourly = tuple(candle(i, close=str(2000+i), timeframe=Timeframe.H1) for i in range(220))
    fifteen = tuple(candle(i, close=str(2000+i), timeframe=Timeframe.M15,
                           opened_at=BASE - timedelta(minutes=3300) + timedelta(minutes=15*i)) for i in range(220))
    retrieved = max(item.closed_at for item in hourly + fifteen) + timedelta(minutes=1)
    source = SourceIdentity(source_id="synthetic-source", instrument=IDENTITY, provider_id="synthetic",
        feed_id="fixture", series_id="synthetic:multi", provider_symbol="XAUUSD", retrieved_at=retrieved,
        price_normalization="source_decimal_text", source_price_precision="fixture")
    frames = (
        TimeframeEvidence(timeframe=Timeframe.H1, state=TimeframeState.AVAILABLE, origin=CandleOrigin.NATIVE,
            source_ids=(source.source_id,), candles=hourly),
        TimeframeEvidence(timeframe=Timeframe.M15, state=TimeframeState.AVAILABLE, origin=CandleOrigin.NATIVE,
            source_ids=(source.source_id,), candles=fifteen),
        TimeframeEvidence(timeframe=Timeframe.H4, state=TimeframeState.UNSUPPORTED,
            quality_flags=(DataQualityFlag.UNSUPPORTED_DERIVATION,)),
    )
    fixture = EvidencePacket(analysis_id="synthetic-mtf", analysis_at=retrieved, instrument=IDENTITY,
        sources=(source,), requested_timeframes=(Timeframe.H1, Timeframe.M15, Timeframe.H4),
        retrieved_at=retrieved, timeframes=frames)
    record = next(item for item in analyze_packet(fixture).evidence
                  if item.calculation_method == "multitimeframe_ema20_50_200_alignment_v1")
    assert record.quality == QualityStatus.INSUFFICIENT
    assert "partial" in record.description and "4H" in record.description and "bullish" in record.description


def test_fvg_and_mitigation_state_and_premium_discount():
    cs = [candle(0, high="10", low="8", close="9"), candle(1, high="12", low="10", close="11"),
          candle(2, high="15", low="13", close="14"), candle(3, high="14", low="11", close="12")]
    zones = fair_value_gaps(cs)
    assert zones[0].kind == "bullish_fvg" and zones[0].low == 10 and zones[0].high == 13
    assert zones[0].mitigation == "partial"
    cs.append(candle(4, high="14", low="9", close="10"))
    assert fair_value_gaps(cs)[0].mitigation == "full"
    pts = swings(cs, 1, 1)
    if len(pts) >= 2:
        result = premium_discount(pts)
        assert result is None or result[0] <= result[2] <= result[1]


def test_sessions_use_configured_iana_zones_and_dst():
    defs = (SessionDefinition("london", "Europe/London", time(8), time(9)),
            SessionDefinition("new_york", "America/New_York", time(8), time(9)))
    # London 08:30 local, winter = UTC; DST = UTC+1.
    assert classify_sessions(datetime(2026, 1, 15, 8, 30, tzinfo=UTC), defs) == ("london",)
    assert classify_sessions(datetime(2026, 7, 15, 7, 30, tzinfo=UTC), defs) == ("london",)
    assert classify_sessions(datetime(2026, 1, 15, 13, 30, tzinfo=UTC)) == ("london", "new_york", "london_new_york_overlap")
    assert classify_sessions(datetime(2026, 7, 15, 12, 30, tzinfo=UTC)) == ("london", "new_york", "london_new_york_overlap")
    with pytest.raises(ValueError):
        classify_sessions(datetime(2026, 1, 1, 8))


def test_engine_evidence_packet_provenance_idempotence_forming_and_tick_semantics():
    cs = [candle(i, close=str(2000+i), volume="600000", volume_type=VolumeType.TICK_COUNT) for i in range(220)]
    original = packet(cs)
    result = analyze_packet(original)
    assert original.evidence == ()
    assert result.evidence
    assert len({r.evidence_id for r in result.evidence}) == len(result.evidence)
    assert all(r.source_ids == ("synthetic-source",) and r.calculation_method for r in result.evidence)
    assert EvidencePacket.model_validate(result.model_dump()) == result
    pivot_candles = [candle(300+i, close=str(v), high=str(h), low=str(l)) for i, (v, h, l) in enumerate(
        [(2001, 2002, 2000), (2002, 2004, 2001), (2003, 2010, 2002),
         (2004, 2005, 2003), (2005, 2006, 2004)])]
    swing_result = analyze_packet(packet(pivot_candles))
    swing_record = next(r for r in swing_result.evidence if r.evidence_type == EvidenceType.SWING_HIGH)
    assert len(swing_record.candle_refs) == 5  # pivot plus the complete confirmation window
    assert swing_record.observed_at == pivot_candles[4].closed_at
    volume = next(r for r in result.evidence if r.evidence_type == EvidenceType.VOLUME)
    assert volume.volume_type == VolumeType.TICK_COUNT and "tick_count" in volume.description
    assert not any(r.evidence_type == EvidenceType.VOLUME and "spike" in r.description for r in result.evidence)
    assert analyze_packet(original).evidence == result.evidence
    forming = packet(cs[:-1] + [candle(219, close="2219", status=CandleState.FORMING)])
    forming_output = analyze_packet(forming)
    assert all(r.quality == QualityStatus.PROVISIONAL for r in forming_output.evidence)


def test_engine_keeps_unavailable_timeframes_and_quality_flags_explicit():
    cs = [candle(i, close=str(2000+i)) for i in range(30)]
    result = analyze_packet(packet(cs, flags=(DataQualityFlag.MISSING_CANDLES,)))
    assert next(t for t in result.timeframes if t.timeframe == Timeframe.H4).state == TimeframeState.UNAVAILABLE
    assert all(r.quality == QualityStatus.INSUFFICIENT for r in result.evidence)


def test_contract_rejects_invalid_ohlc_and_float_prices():
    with pytest.raises(ValidationError):
        candle(1, high="1", low="2", close="1")
    with pytest.raises(ValidationError):
        EvidenceCandle(candle_id="x", source_id="synthetic-source", timeframe=Timeframe.H1,
            opened_at=BASE, status=CandleState.CLOSED, closed_at=BASE+timedelta(hours=1),
            open=1.1, high="2", low="1", close="1.5")
    with pytest.raises(ValidationError, match="align to a UTC timeframe boundary"):
        EvidenceCandle(candle_id="unaligned", source_id="synthetic-source", timeframe=Timeframe.M5,
            opened_at=BASE + timedelta(minutes=2), closed_at=BASE + timedelta(minutes=7),
            status=CandleState.CLOSED, open="1", high="2", low="1", close="1.5")


def test_bearish_fvg_and_structure_change_of_character():
    from app.analysis.market_structure import Swing
    # The synthetic swing references are confirmed before the close breaks.
    cs = [candle(0, high="10", low="5", close="8"), candle(1, high="10", low="6", close="9"),
          candle(2, high="9", low="6", close="8"), candle(3, high="12", low="7", close="11"),
          candle(4, high="10", low="4", close="5")]
    points = (Swing(1, cs[1], True), Swing(2, cs[2], False))
    events = structure_events(cs, points, 1)
    assert [(e.kind, e.direction) for e in events] == [("BOS", "bullish"), ("CHoCH", "bearish")]
    bearish = fair_value_gaps([candle(10, high="14", low="12", close="13"),
        candle(11, high="13", low="11", close="12"), candle(12, high="10", low="8", close="9")])
    assert bearish and bearish[0].kind == "bearish_fvg" and bearish[0].low == 10 and bearish[0].high == 12


def test_order_block_requires_close_break_displacement_and_keeps_invalidation():
    from app.analysis.market_structure import StructureEvent
    from app.analysis.smc import order_blocks
    cs = [candle(0, high="12", low="8", close="10"),
          candle(1, open_="10", high="11", low="7", close="8"),
          candle(2, open_="8", high="15", low="8", close="14"),
          candle(3, open_="14", high="14", low="5", close="6")]
    event = StructureEvent("BOS", "bullish", Decimal("12"), (cs[0].candle_id, cs[2].candle_id), 2)
    zones = order_blocks(cs, (event,), {cs[2].candle_id: Decimal("2")}, Decimal("1.5"))
    assert len(zones) == 1
    assert cs[1].candle_id in zones[0].source_refs and cs[2].candle_id in zones[0].source_refs
    assert zones[0].status == "confirmed" and zones[0].mitigation == "invalidated" and cs[3].candle_id in zones[0].source_refs
    assert not order_blocks(cs, (event,), {}, Decimal("1.5"))


def test_short_history_reports_indicators_as_unsupported():
    result = analyze_packet(packet([candle(i, close=str(2000+i)) for i in range(5)]))
    unavailable = [record for record in result.evidence if record.evidence_type in
                   (EvidenceType.EMA, EvidenceType.RSI, EvidenceType.ATR)]
    assert unavailable and all(record.quality == QualityStatus.UNSUPPORTED for record in unavailable)


def test_stale_input_quality_propagates_without_age_threshold():
    result = analyze_packet(packet([candle(i, close=str(2000+i)) for i in range(25)],
                                   flags=(DataQualityFlag.STALE,)))
    assert result.evidence and all(record.quality == QualityStatus.STALE for record in result.evidence)


def test_aggregated_four_hour_is_preserved_and_never_created_by_engine():
    t0 = BASE - timedelta(hours=8)
    h1 = []
    for i in range(4):
        h1.append(EvidenceCandle(candle_id=f"h1-{i}", source_id="synthetic-source", timeframe=Timeframe.H1,
            opened_at=t0+timedelta(hours=i), closed_at=t0+timedelta(hours=i+1), status=CandleState.CLOSED,
            origin=CandleOrigin.NATIVE, open=str(100+i), high=str(102+i), low=str(99+i), close=str(101+i)))
    h4 = EvidenceCandle(candle_id="h4-aggregate", source_id="synthetic-source", timeframe=Timeframe.H4,
        opened_at=t0, closed_at=t0+timedelta(hours=4), status=CandleState.CLOSED, origin=CandleOrigin.AGGREGATED,
        open="100", high="105", low="99", close="104", source_candle_ids=tuple(c.candle_id for c in h1))
    retrieved = t0 + timedelta(hours=5)
    source = SourceIdentity(source_id="synthetic-source", instrument=IDENTITY, provider_id="synthetic", feed_id="fixture",
        series_id="synthetic:all", provider_symbol="XAUUSD", retrieved_at=retrieved,
        price_normalization="source_decimal_text", source_price_precision="fixture")
    one = TimeframeEvidence(timeframe=Timeframe.H1, state=TimeframeState.AVAILABLE, origin=CandleOrigin.NATIVE,
        source_ids=(source.source_id,), candles=tuple(h1))
    four = TimeframeEvidence(timeframe=Timeframe.H4, state=TimeframeState.AVAILABLE, origin=CandleOrigin.AGGREGATED,
        source_ids=(source.source_id,), candles=(h4,))
    p = EvidencePacket(analysis_id="agg-fixture", analysis_at=retrieved, instrument=IDENTITY, sources=(source,),
        requested_timeframes=(Timeframe.H1, Timeframe.H4), retrieved_at=retrieved, timeframes=(one, four))
    out = analyze_packet(p)
    assert next(t for t in out.timeframes if t.timeframe == Timeframe.H4).origin == CandleOrigin.AGGREGATED
    assert len(next(t for t in out.timeframes if t.timeframe == Timeframe.H4).candles) == 1
    assert EvidencePacket.model_validate(out.model_dump()) == out


def test_engine_records_traceable_gap_mitigation_candles():
    from app.analysis.smc import fair_value_gaps
    cs = [candle(0, high="10", low="8", close="9"), candle(1, high="12", low="10", close="11"),
          candle(2, high="15", low="13", close="14"), candle(3, high="14", low="11", close="12")]
    zone = fair_value_gaps(cs)[0]
    assert cs[3].candle_id in zone.source_refs


def test_bearish_break_and_equal_lows_use_confirmed_swings():
    from app.analysis.market_structure import Swing
    cs = [candle(0, high="14", low="9", close="11"), candle(1, high="12", low="8", close="10"),
          candle(2, high="13", low="9", close="11"), candle(3, high="11", low="7", close="7.5")]
    event = structure_events(cs, (Swing(1, cs[1], False, 2, tuple(c.candle_id for c in cs[:3])),), 1)
    assert event and event[0].kind == "BOS" and event[0].direction == "bearish"
    lows = [8, 10, 8.05, 11, 8.08, 12, 9]
    series = [candle(i, low=str(v), high=str(Decimal(v)+3), close=str(Decimal(v)+1)) for i, v in enumerate(lows)]
    points = swings(series, 1, 1)
    assert any(label == "equal_lows" for label, *_ in equal_levels(points, Decimal("0.1")))


def test_forming_right_side_candle_cannot_confirm_a_swing():
    cs = [candle(0, high="10", low="8", close="9"), candle(1, high="12", low="9", close="10"),
          candle(2, high="10", low="8", close="9", status=CandleState.FORMING)]
    output = analyze_packet(packet(cs), AnalysisParameters(swing_left=1, swing_right=1))
    assert not any(record.evidence_type == EvidenceType.SWING_HIGH for record in output.evidence)


def test_native_four_hour_identity_is_preserved():
    opened = BASE - timedelta(hours=8)
    item = EvidenceCandle(candle_id="native-h4", source_id="synthetic-source", timeframe=Timeframe.H4,
        opened_at=opened, closed_at=opened+timedelta(hours=4), status=CandleState.CLOSED,
        origin=CandleOrigin.NATIVE, open="100", high="105", low="99", close="104")
    retrieved = opened + timedelta(hours=5)
    source = SourceIdentity(source_id="synthetic-source", instrument=IDENTITY, provider_id="synthetic", feed_id="h4",
        series_id="synthetic:h4", provider_symbol="XAUUSD", retrieved_at=retrieved,
        price_normalization="source_decimal_text", source_price_precision="fixture")
    timeframe = TimeframeEvidence(timeframe=Timeframe.H4, state=TimeframeState.AVAILABLE,
        origin=CandleOrigin.NATIVE, source_ids=(source.source_id,), candles=(item,))
    output = analyze_packet(EvidencePacket(analysis_id="native-h4", analysis_at=retrieved, instrument=IDENTITY,
        sources=(source,), requested_timeframes=(Timeframe.H4,), retrieved_at=retrieved, timeframes=(timeframe,)))
    assert output.timeframes[0].origin == CandleOrigin.NATIVE
    assert output.timeframes[0].candles == (item,)


def test_decimal_analysis_parameters_reject_binary_float_tolerance():
    with pytest.raises(ValueError):
        AnalysisParameters(equal_level_tolerance=0.1)


def test_duplicate_openings_are_flagged_and_excluded_from_calculation():
    first = candle(1, close="2001")
    duplicate = first.model_copy(update={"candle_id": "synthetic-duplicate-opening"})
    result = analyze_packet(packet([first, duplicate]))
    timeframe = next(item for item in result.timeframes if item.timeframe == Timeframe.H1)
    assert DataQualityFlag.DUPLICATE_CANDLES in timeframe.quality_flags
    assert all(record.quality == QualityStatus.INSUFFICIENT for record in result.evidence)


def test_out_of_order_candles_are_invalid_and_never_reordered_into_analysis():
    cs = [candle(i, close=str(2000+i)) for i in range(30)]
    result = analyze_packet(packet(tuple(reversed(cs))))
    timeframe = next(item for item in result.timeframes if item.timeframe == Timeframe.H1)
    assert DataQualityFlag.INVALID_CANDLES in timeframe.quality_flags
    assert not any(record.evidence_type in (EvidenceType.SWING_HIGH, EvidenceType.SWING_LOW,
        EvidenceType.BOS, EvidenceType.CHOCH, EvidenceType.LIQUIDITY_SWEEP) for record in result.evidence)


def test_incomplete_context_is_not_marked_verified():
    result = analyze_packet(packet([candle(i, close=str(2000+i)) for i in range(25)],
                                   flags=(DataQualityFlag.INCOMPLETE_CONTEXT,)))
    assert result.evidence and all(record.quality == QualityStatus.INSUFFICIENT for record in result.evidence)


@pytest.mark.parametrize("flag,expected", [(DataQualityFlag.STALE, QualityStatus.STALE),
                                         (DataQualityFlag.INVALID_CANDLES, QualityStatus.INVALID),
                                         (DataQualityFlag.FORMING_CANDLE, QualityStatus.PROVISIONAL),
                                         (DataQualityFlag.UNSUPPORTED_DERIVATION, QualityStatus.UNSUPPORTED),
                                         (DataQualityFlag.MISSING_CANDLES, QualityStatus.INSUFFICIENT)])
def test_unverified_tick_volume_preserves_input_quality(flag, expected):
    cs = [candle(i, close=str(2000+i), volume="600000", volume_type=VolumeType.TICK_COUNT) for i in range(25)]
    cs[-1] = cs[-1].model_copy(update={"quality_flags": (DataQualityFlag.UNVERIFIED_TICK_COUNT_RANGE,)})
    result = analyze_packet(packet(cs, flags=(flag,)))
    volume = next(record for record in result.evidence if record.evidence_type == EvidenceType.VOLUME)
    assert volume.quality == expected


def test_unverified_tick_volume_does_not_disqualify_price_indicators():
    cs = [candle(i, close=str(2000+i), volume="600000", volume_type=VolumeType.TICK_COUNT) for i in range(25)]
    cs[-1] = cs[-1].model_copy(update={"quality_flags": (DataQualityFlag.UNVERIFIED_TICK_COUNT_RANGE,)})
    result = analyze_packet(packet(cs))
    assert next(record for record in result.evidence if record.evidence_type == EvidenceType.VOLUME).quality == QualityStatus.INSUFFICIENT
    assert next(record for record in result.evidence if record.evidence_type == EvidenceType.EMA and record.value is not None).quality == QualityStatus.VERIFIED
