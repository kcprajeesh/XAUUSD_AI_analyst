"""Pure deterministic calculations over a validated Stage 5C evidence packet."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
from typing import Iterable
from zoneinfo import ZoneInfo

from app.ai.evidence import (
    CandleState, DataQualityFlag, EvidenceCandle, EvidencePacket, EvidenceRecord, EvidenceType,
    QualityStatus, Timeframe, TimeframeState, VolumeType,
)
from app.analysis.indicators import atr, atr_series, ema, momentum, rsi, vwap
from app.analysis.market_structure import equal_levels, structure_events, swings, sweeps, support_resistance
from app.analysis.smc import fair_value_gaps, order_blocks, premium_discount
from app.analysis.sessions import DEFAULT_SESSIONS, SessionDefinition, classify_sessions

ANALYSIS_ALGORITHM_ID = "xau.deterministic.research"
ANALYSIS_ALGORITHM_VERSION = "1"

@dataclass(frozen=True)
class AnalysisParameters:
    swing_left: int = 2
    swing_right: int = 2
    equal_level_tolerance: Decimal = Decimal("0.10")
    order_block_displacement_atr: Decimal = Decimal("1.5")
    session_definitions: tuple[SessionDefinition, ...] = DEFAULT_SESSIONS

    def __post_init__(self):
        if any(isinstance(width, bool) or not isinstance(width, int) for width in (self.swing_left, self.swing_right)):
            raise ValueError("swing widths must be integers")
        if not isinstance(self.equal_level_tolerance, Decimal) or not self.equal_level_tolerance.is_finite():
            raise ValueError("equal-level tolerance must be a finite Decimal")
        if not isinstance(self.order_block_displacement_atr, Decimal) or not self.order_block_displacement_atr.is_finite():
            raise ValueError("order-block displacement must be a finite Decimal")
        if self.swing_left < 1 or self.swing_right < 1 or self.equal_level_tolerance < 0:
            raise ValueError("swing widths must be positive and equality tolerance non-negative")
        if self.order_block_displacement_atr <= 0:
            raise ValueError("order-block displacement multiple must be positive")


def _id(source_id: str, timeframe: Timeframe, kind: str, method: str, refs: tuple[str, ...], suffix: str) -> str:
    basis = "|".join((source_id, timeframe.value, kind, method, ",".join(refs), suffix))
    return "det-" + hashlib.sha256(basis.encode()).hexdigest()[:24]


def _quality(timeframe_flags: Iterable[DataQualityFlag], candles: tuple[EvidenceCandle, ...]) -> QualityStatus:
    flags = set(timeframe_flags)
    if DataQualityFlag.INVALID_CANDLES in flags:
        return QualityStatus.INVALID
    if DataQualityFlag.STALE in flags:
        return QualityStatus.STALE
    if DataQualityFlag.UNSUPPORTED_DERIVATION in flags:
        return QualityStatus.UNSUPPORTED
    if DataQualityFlag.FORMING_CANDLE in flags:
        return QualityStatus.PROVISIONAL
    if DataQualityFlag.INCOMPLETE_CONTEXT in flags:
        return QualityStatus.INSUFFICIENT
    if DataQualityFlag.RETRIEVAL_INCOMPLETE in flags:
        return QualityStatus.INSUFFICIENT
    if flags & {DataQualityFlag.OUTLIER, DataQualityFlag.MISSING_CANDLES,
                DataQualityFlag.DUPLICATE_CANDLES, DataQualityFlag.CONFLICTING_SOURCE}:
        return QualityStatus.INSUFFICIENT
    if any(c.status != CandleState.CLOSED for c in candles):
        return QualityStatus.PROVISIONAL
    return QualityStatus.VERIFIED


def analyze_packet(packet: EvidencePacket, parameters: AnalysisParameters | None = None) -> EvidencePacket:
    """Append deterministic records; does not mutate input or access providers/storage."""
    packet = EvidencePacket.model_validate(packet.model_dump(mode="python"))
    parameters = parameters or AnalysisParameters()
    conflict = any(source.instrument != packet.instrument for source in packet.sources)
    records = list(packet.evidence)
    timeframe_records = []
    timeframe_alignments = {}
    for item in packet.timeframes:
        added: list[EvidenceRecord] = []
        output_item = item
        if item.state == TimeframeState.AVAILABLE:
            all_candles = item.candles
            out_of_order = any(before.opened_at > after.opened_at for before, after in zip(all_candles, all_candles[1:]))
            duplicate_openings = len({c.opened_at for c in all_candles}) != len(all_candles)
            effective_flags = item.quality_flags + ((DataQualityFlag.DUPLICATE_CANDLES,) if duplicate_openings else ())
            if out_of_order:
                effective_flags += (DataQualityFlag.INVALID_CANDLES,)
            candles = () if duplicate_openings or out_of_order else tuple(c for c in all_candles if c.status == CandleState.CLOSED)
            if duplicate_openings or out_of_order:
                output_item = item.model_copy(update={"quality_flags": tuple(dict.fromkeys(effective_flags))})
            source_id = item.source_ids[0]
            quality = _quality((*packet.quality_flags, *effective_flags,
                                *((DataQualityFlag.CONFLICTING_SOURCE,) if conflict else ()),
                                *(flag for candle in all_candles for flag in candle.quality_flags)), all_candles)

            def emit(kind: EvidenceType, label: str, value: Decimal | None, units: str | None,
                     refs: tuple[str, ...], method: str, suffix: str = "", volume_type: VolumeType | None = None,
                     quality_override: QualityStatus | None = None) -> None:
                # Keep output provenance minimal and deterministic; never blend feeds.
                if not refs:
                    return
                record = EvidenceRecord(evidence_id=_id(source_id, item.timeframe, kind.value, method, refs,
                                                        f"{suffix}|{label}|{value}"),
                    evidence_type=kind, description=label, value=value, units=units, timeframe=item.timeframe,
                    observed_at=max((next(c.closed_at for c in candles if c.candle_id == ref)
                                     for ref in refs), default=packet.retrieved_at),
                    source_ids=(source_id,), calculation_method=method,
                    quality=quality_override if quality == QualityStatus.VERIFIED and quality_override else quality, candle_refs=refs,
                    volume_type=volume_type)
                if record.evidence_id not in {r.evidence_id for r in records}:
                    added.append(record)

            def emit_unsupported(kind: EvidenceType, label: str, method: str, suffix: str) -> None:
                refs = tuple(c.candle_id for c in candles)
                observed = candles[-1].closed_at if candles else packet.retrieved_at
                record_id = _id(source_id, item.timeframe, kind.value, method, refs, "unsupported:" + suffix + ":" + label)
                if record_id in {record.evidence_id for record in records + added}:
                    return
                added.append(EvidenceRecord(evidence_id=record_id,
                    evidence_type=kind, description=label, timeframe=item.timeframe, observed_at=observed,
                    source_ids=(source_id,), calculation_method=method, quality=quality if quality != QualityStatus.VERIFIED else QualityStatus.UNSUPPORTED,
                    candle_refs=refs))

            ema_points_by_period = {}
            for period in (20, 50, 200):
                ema_points = ema(candles, period, latest_only=True)
                if ema_points:
                    ema_points_by_period[period] = ema_points[0]
                if not ema_points:
                    emit_unsupported(EvidenceType.EMA, f"EMA {period} unavailable: warm-up requires {period} closed candles",
                                     "ema_sma_seed_alpha_2_over_n_plus_1_v1", str(period))
                for point in ema_points:
                    emit(EvidenceType.EMA, f"EMA {period} = {point.value}", point.value, "USD_per_troy_ounce",
                         point.candle_refs, point.method, f"{period}:{point.candle_refs[-1]}")
            if len(ema_points_by_period) == 3:
                values = {period: point.value for period, point in ema_points_by_period.items()}
                alignment = ("bullish EMA alignment" if values[20] > values[50] > values[200] else
                             "bearish EMA alignment" if values[20] < values[50] < values[200] else "mixed EMA alignment")
                refs = tuple(dict.fromkeys(ref for point in ema_points_by_period.values() for ref in point.candle_refs))
                emit(EvidenceType.TREND, alignment, None, None, refs,
                     "ema_20_50_200_ordering_v1", alignment)
                timeframe_alignments[item.timeframe] = (alignment.split()[0], refs, source_id, quality)
            rsi_points = rsi(candles, latest_only=True)
            if not rsi_points:
                emit_unsupported(EvidenceType.RSI, "RSI 14 unavailable: warm-up requires 15 closed candles",
                                 "rsi_wilder_sma_seed_zero_loss_100_flat_50_v1", "14")
            for point in rsi_points:
                emit(EvidenceType.RSI, f"RSI 14 = {point.value}", point.value, "index_0_to_100",
                     point.candle_refs, point.method, point.candle_refs[-1])
            momentum_point = momentum(candles, 10)
            if momentum_point is None:
                emit_unsupported(EvidenceType.MOMENTUM,
                    "Momentum unavailable: warm-up requires 11 closed candles",
                    "close_rate_of_change_percent_v1", "10")
            else:
                emit(EvidenceType.MOMENTUM, f"10-interval close rate of change = {momentum_point.value}%",
                     momentum_point.value, "percent", momentum_point.candle_refs,
                     momentum_point.method, momentum_point.candle_refs[-1])
            atr_points = atr(candles, latest_only=True)
            if not atr_points:
                emit_unsupported(EvidenceType.ATR, "ATR 14 unavailable: warm-up requires 14 closed candles",
                                 "atr_true_range_wilder_sma_seed_v1", "14")
            for point in atr_points:
                emit(EvidenceType.ATR, f"ATR 14 = {point.value}", point.value, "USD_per_troy_ounce",
                     point.candle_refs, point.method, point.candle_refs[-1])
                if candles and candles[-1].close > 0:
                    with localcontext() as context:
                        context.prec = 34
                        relative = point.value / candles[-1].close * Decimal(100)
                    emit(EvidenceType.VOLATILITY, f"ATR 14 is {relative}% of latest close", relative,
                         "percent_of_close", point.candle_refs, "atr14_over_close_percent_v1", point.candle_refs[-1])
            vwap_point = vwap(candles)
            if vwap_point is None:
                emit_unsupported(EvidenceType.VWAP,
                    "VWAP unavailable: retrieval window requires complete exchange-traded or contract volume",
                    "vwap_hlc3_retrieval_window_exchange_or_contract_volume_v1", "window")
            else:
                emit(EvidenceType.VWAP, f"Retrieval-window VWAP = {vwap_point.value}", vwap_point.value,
                     "USD_per_troy_ounce", vwap_point.candle_refs, vwap_point.method, vwap_point.candle_refs[-1])
            points = swings(candles, parameters.swing_left, parameters.swing_right)
            for point in points:
                emit(EvidenceType.SWING_HIGH if point.high else EvidenceType.SWING_LOW,
                     f"Confirmed swing {'high' if point.high else 'low'} at {point.candle.high if point.high else point.candle.low}",
                     point.candle.high if point.high else point.candle.low, "USD_per_troy_ounce",
                     point.source_refs or (point.candle.candle_id,), f"swing_strict_extreme_left_{parameters.swing_left}_right_{parameters.swing_right}_v1",
                     point.candle.candle_id)
            events = structure_events(candles, points, parameters.swing_right)
            for event in events:
                kind = EvidenceType.BOS if event.kind == "BOS" else EvidenceType.CHOCH
                emit(kind, f"{event.direction} {event.kind} close break at {event.level}", event.level,
                     "USD_per_troy_ounce", event.candle_refs, "structure_confirmed_close_break_v1",
                     event.candle_refs[-1])
            for point in points:
                level = point.candle.high if point.high else point.candle.low
                emit(EvidenceType.LIQUIDITY_HIGH if point.high else EvidenceType.LIQUIDITY_LOW,
                     f"Potential {'buy-side' if point.high else 'sell-side'} liquidity at confirmed swing {level}",
                     level, "USD_per_troy_ounce", point.source_refs or (point.candle.candle_id,), "confirmed_swing_liquidity_reference_v1",
                     point.candle.candle_id)
            for label, level, refs in equal_levels(points, parameters.equal_level_tolerance):
                emit(EvidenceType.LIQUIDITY_HIGH if label == "equal_highs" else EvidenceType.LIQUIDITY_LOW,
                     f"Potential {label.replace('_', ' ')} liquidity level {level}", level,
                     "USD_per_troy_ounce", refs, f"equal_swing_levels_abs_tolerance_{parameters.equal_level_tolerance}_v1",
                     ",".join(refs))
            for label, level, refs in support_resistance(points, parameters.equal_level_tolerance):
                emit(EvidenceType.SUPPORT if label == "support" else EvidenceType.RESISTANCE,
                     f"Confirmed swing {label} level {level}", level, "USD_per_troy_ounce", refs,
                     f"confirmed_swing_{label}_cluster_abs_tolerance_{parameters.equal_level_tolerance}_v1",
                     ",".join(refs))
            for event in sweeps(candles, points, parameters.swing_right):
                emit(EvidenceType.LIQUIDITY_SWEEP,
                     f"Confirmed {'buy-side' if event.direction == 'bearish' else 'sell-side'} liquidity sweep; close rejected level {event.level}",
                     event.level, "USD_per_troy_ounce", event.candle_refs, "sweep_wick_through_close_back_v1",
                     event.candle_refs[-1])
            for zone in fair_value_gaps(candles):
                refs = zone.source_refs
                for edge, value in (("low", zone.low), ("high", zone.high)):
                    emit(EvidenceType.FAIR_VALUE_GAP,
                         f"{zone.kind} {edge} boundary {value}; detected_at={zone.formed_at}; status={zone.status}; fill={zone.mitigation}",
                         value, "USD_per_troy_ounce", refs, "fvg_three_candle_nonoverlap_v1", f"{zone.formed_at}:{edge}")
            atr_by_candle = atr_series(candles, 14)
            for zone in order_blocks(candles, events, atr_by_candle, parameters.order_block_displacement_atr):
                for edge, value in (("low", zone.low), ("high", zone.high)):
                    emit(EvidenceType.ORDER_BLOCK,
                         f"{zone.kind} {edge} {value}; confirmed_at={zone.formed_at}; confirmation={zone.status}; mitigation={zone.mitigation}",
                         value, "USD_per_troy_ounce", zone.source_refs,
                         f"last_opposing_candle_close_break_displacement_{parameters.order_block_displacement_atr}_atr_v1",
                         f"{zone.formed_at}:{edge}")
            range_result = premium_discount(points)
            if range_result:
                low, high, equilibrium, refs = range_result
                for label, value in (("range_low", low), ("equilibrium", equilibrium), ("range_high", high)):
                    emit(EvidenceType.TREND,
                         f"Premium/discount {label} {value}; same-leg swing range", value,
                         "USD_per_troy_ounce", refs, "latest_consecutive_opposite_confirmed_swings_midpoint_v1", label)
                if candles:
                    current = candles[-1]
                    zone = "premium" if current.close > equilibrium else "discount" if current.close < equilibrium else "equilibrium"
                    emit(EvidenceType.TREND, f"Close is in range {zone}; range {low} to {high}", None, None,
                         refs + (current.candle_id,), "premium_discount_latest_opposite_swing_range_v1", zone)
            for candle in candles[-1:]:
                sessions = classify_sessions(candle.opened_at, parameters.session_definitions)
                qatar_local = candle.opened_at.astimezone(ZoneInfo("Asia/Qatar")).isoformat()
                emit(EvidenceType.SESSION, "Session context: " + (", ".join(sessions) if sessions else "outside configured sessions")
                     + f"; Asia/Qatar local time={qatar_local}",
                     None, None, (candle.candle_id,), "iana_timezone_configured_wall_clock_sessions_v1",
                     candle.opened_at.isoformat())
            # Record observed volume only with its source's explicit semantics; never infer traded volume.
            for candle in candles[-1:]:
                if candle.volume_value is not None:
                    emit(EvidenceType.VOLUME, f"Source volume observation {candle.volume_value} ({candle.volume_type.value})",
                         candle.volume_value, None, (candle.candle_id,), "source_reported_volume_preserved_v1",
                         candle.candle_id, candle.volume_type,
                         QualityStatus.INSUFFICIENT if DataQualityFlag.UNVERIFIED_TICK_COUNT_RANGE in candle.quality_flags else None)
        records.extend(added)
        timeframe_records.append(output_item.model_copy(update={"evidence_ids": tuple(dict.fromkeys(output_item.evidence_ids + tuple(r.evidence_id for r in added))) }))
    values = packet.model_dump(mode="python")
    aligned = [(tf, *value) for tf, value in timeframe_alignments.items()]
    if len(aligned) >= 2:
        directions = {entry[1] for entry in aligned}
        all_requested = (len(timeframe_alignments) == len(packet.requested_timeframes)
                         and all(entry[4] == QualityStatus.VERIFIED for entry in aligned))
        direction = next(iter(directions)) if len(directions) == 1 else "mixed"
        quality = (QualityStatus.VERIFIED if all_requested and all(entry[4] == QualityStatus.VERIFIED for entry in aligned)
                   else QualityStatus.INSUFFICIENT)
        labels = ", ".join(f"{tf.value} {value}" for tf, value, *_ in aligned)
        missing = sorted(tf.value for tf in packet.requested_timeframes
                         if tf not in timeframe_alignments or timeframe_alignments[tf][3] != QualityStatus.VERIFIED)
        suffix = f"; unavailable or insufficient: {', '.join(missing)}" if missing else ""
        refs = tuple(dict.fromkeys(ref for _, _, item_refs, _, _ in aligned for ref in item_refs))
        sources = tuple(dict.fromkeys(source for _, _, _, source, _ in aligned))
        observed = max(next(c.closed_at for tf in packet.timeframes for c in tf.candles if c.candle_id == ref)
                       for ref in refs)
        records.append(EvidenceRecord(evidence_id="det-" + hashlib.sha256(
                ("mtf_ema_alignment_v1|" + "|".join(refs) + "|" + direction).encode()).hexdigest()[:24],
            evidence_type=EvidenceType.DIRECTIONAL_STRUCTURE,
            description=f"Multi-timeframe EMA alignment ({'complete' if all_requested else 'partial'}): {labels}; result={direction}{suffix}",
            observed_at=observed, source_ids=sources, calculation_method="multitimeframe_ema20_50_200_alignment_v1",
            quality=quality, candle_refs=refs))
    values["timeframes"] = tuple(timeframe_records)
    values["evidence"] = tuple(records)
    return EvidencePacket.model_validate(values)
