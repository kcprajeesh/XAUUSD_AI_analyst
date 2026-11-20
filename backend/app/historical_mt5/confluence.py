"""As-of historical MT5 evidence snapshot; this module emits no trade signals."""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from app.analysis.sessions import DEFAULT_SESSIONS, SessionDefinition, classify_sessions
from app.data.mt5_import import (
    BROKER, INTERVALS, PROVIDER, SOURCE_CLASSIFICATION, SYMBOL, TIMEZONE_POLICY,
)
from app.historical_mt5.indicators import (
    ALGORITHM_VERSION as INDICATOR_VERSION,
    IndicatorObservation,
    IndicatorRun,
    IndicatorStatus,
    align_indicators,
)
from app.historical_mt5.models import CandleEligibility, HistoricalRun
from app.historical_mt5.structure import (
    ALGORITHM_VERSION as STRUCTURE_VERSION,
    HistoricalStructureRun,
    StructureDiagnostics,
    StructureEvent,
)
from app.historical_mt5.structure import SWING_LEFT_BARS, SWING_RIGHT_BARS

TIMEFRAMES = ("H1", "M15")
DISPLAY_ZONE = "Asia/Qatar"
REPORT_VERSION = "mt5-historical-confluence-v1"


@dataclass(frozen=True, slots=True)
class SessionView:
    timeframe: str
    source_file: str
    source_sha256: str
    source_row: int
    opened_at: datetime
    closed_at: datetime
    opened_qatar: datetime
    closed_qatar: datetime
    open_sessions: tuple[str, ...]
    close_sessions: tuple[str, ...]
    crosses_session_boundary: bool


@dataclass(frozen=True, slots=True)
class FVGView:
    formation: StructureEvent
    status: str
    latest_transition: StructureEvent | None


@dataclass(frozen=True, slots=True)
class TimeframeSnapshot:
    timeframe: str
    series_id: str
    source_file: str
    source_sha256: str
    indicator_observations: tuple[IndicatorObservation, ...]
    indicator_statuses: tuple[tuple[str, str], ...]
    latest_swing_high: StructureEvent | None
    latest_swing_low: StructureEvent | None
    latest_break: StructureEvent | None
    latest_equal_highs: StructureEvent | None
    latest_equal_lows: StructureEvent | None
    liquidity_levels: tuple[tuple[StructureEvent, str, StructureEvent | None], ...]
    active_fvgs: tuple[FVGView, ...]
    premium_discount: StructureEvent | None
    diagnostics: StructureDiagnostics
    context: str
    context_components: tuple[tuple[str, str], ...]
    missing_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConfluenceSnapshot:
    evaluation_at: datetime
    analysis_cutoff: datetime
    run_id: str
    provider: str
    broker: str
    symbol: str
    source_classification: str
    configured_timezone: str
    timezone_policy: str
    source_hashes: tuple[tuple[str, str], ...]
    timeframes: tuple[TimeframeSnapshot, ...]
    overall_context: str
    alignment: str
    supporting_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    data_quality_warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    session_views: tuple[SessionView, ...]
    session_definitions: tuple[SessionDefinition, ...]
    excluded_timeframes: tuple[tuple[str, str], ...]
    indicator_algorithm: str
    structure_algorithm: str
    equal_level_tolerance: Decimal
    report_version: str = REPORT_VERSION

    def to_dict(self) -> dict:
        """Serialize only selected evidence references; never deep-copy histories."""
        def stamp(value: datetime | None) -> str | None:
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None

        def source(event: StructureEvent) -> list[dict]:
            return [{"file": c.source_file, "sha256": c.source_sha256,
                     "row": c.source_row, "broker_timestamp": c.source_timestamp,
                     "utc": stamp(c.opened_at)} for c in event.source_candles]

        def event_ref(event: StructureEvent | None) -> dict | None:
            if event is None:
                return None
            return {"id": event.event_id, "type": event.event_type,
                    "event_at": stamp(event.event_at), "knowable_at": stamp(event.knowable_at),
                    "label": event.label, "state": event.state, "direction": event.direction,
                    "level": str(event.price_level) if event.price_level is not None else None,
                    "low": str(event.price_low) if event.price_low is not None else None,
                    "high": str(event.price_high) if event.price_high is not None else None,
                    "value": str(event.price_value) if event.price_value is not None else None,
                    "references": list(event.reference_event_ids),
                    "parameters": list(event.parameters),
                    "quality": event.quality_status, "gap_context": event.gap_context,
                    "source_candles": source(event)}

        frames = []
        for frame in self.timeframes:
            observations = [{"indicator": o.indicator, "parameters": list(o.parameters),
                            "algorithm": o.algorithm_version, "value": str(o.value),
                            "status": o.status.value, "eligibility": o.eligibility.value,
                            "opened_at": stamp(o.opened_at), "closed_at": stamp(o.closed_at),
                            "source": {"file": o.source_candle.source_file,
                                       "sha256": o.source_candle.source_sha256,
                                       "row": o.source_candle.source_row,
                                       "broker_timestamp": o.source_candle.broker_timestamp,
                                       "utc": stamp(o.source_candle.utc_timestamp),
                                       "timezone_policy": o.source_candle.timezone_policy}}
                           for o in frame.indicator_observations]
            frames.append({"timeframe": frame.timeframe, "series_id": frame.series_id,
                "source_file": frame.source_file, "source_sha256": frame.source_sha256,
                "indicators": observations, "indicator_statuses": dict(frame.indicator_statuses),
                "latest_swing_high": event_ref(frame.latest_swing_high),
                "latest_swing_low": event_ref(frame.latest_swing_low),
                "latest_break": event_ref(frame.latest_break),
                "latest_equal_highs": event_ref(frame.latest_equal_highs),
                "latest_equal_lows": event_ref(frame.latest_equal_lows),
                "liquidity_levels": [{"reference": event_ref(e), "status": status,
                                       "status_event": event_ref(status_event)}
                                      for e, status, status_event in frame.liquidity_levels],
                "active_fvgs": [{"formation": event_ref(f.formation), "status": f.status,
                                 "latest_transition": event_ref(f.latest_transition)}
                                for f in frame.active_fvgs],
                "premium_discount": event_ref(frame.premium_discount),
                "diagnostics": {name: getattr(frame.diagnostics, name)
                                for name in frame.diagnostics.__dataclass_fields__},
                "context": frame.context, "context_components": dict(frame.context_components),
                "missing_evidence": list(frame.missing_evidence)})
        return {"report_version": self.report_version,
            "evaluation_at_utc": stamp(self.evaluation_at), "analysis_cutoff_utc": stamp(self.analysis_cutoff),
            "evaluation_at_qatar": self.evaluation_at.astimezone(ZoneInfo(DISPLAY_ZONE)).isoformat(),
            "run_id": self.run_id, "provider": self.provider, "broker": self.broker,
            "symbol": self.symbol, "source_classification": self.source_classification,
            "configured_timezone": self.configured_timezone, "timezone_policy": self.timezone_policy,
            "source_hashes": dict(self.source_hashes), "timeframes": frames,
            "interpretation": {"context": self.overall_context, "alignment": self.alignment,
                "supporting_evidence": list(self.supporting_evidence),
                "conflicting_evidence": list(self.conflicting_evidence),
            "missing_evidence": list(self.missing_evidence),
            "data_quality_warnings": list(self.data_quality_warnings),
            "limitations": list(self.limitations)},
            "session_context": {"display_timezone": DISPLAY_ZONE,
                "evaluation_sessions": list(classify_sessions(self.evaluation_at, self.session_definitions)),
                "definitions": [{"name": s.name, "timezone": s.timezone,
                                 "start": s.start.isoformat(), "end": s.end.isoformat()}
                                for s in self.session_definitions],
                "selected_candles": [{"timeframe": s.timeframe, "source_file": s.source_file,
                    "source_sha256": s.source_sha256, "source_row": s.source_row,
                    "opened_at_utc": stamp(s.opened_at), "closed_at_utc": stamp(s.closed_at),
                    "opened_at_qatar": s.opened_qatar.isoformat(),
                    "closed_at_qatar": s.closed_qatar.isoformat(),
                    "open_sessions": list(s.open_sessions), "close_sessions": list(s.close_sessions),
                    "crosses_session_boundary": s.crosses_session_boundary} for s in self.session_views]},
            "excluded_timeframes": dict(self.excluded_timeframes),
            "algorithms": {"indicator": self.indicator_algorithm,
                           "structure": self.structure_algorithm},
            "configuration": {"swing_left_bars": SWING_LEFT_BARS,
                "swing_right_bars": SWING_RIGHT_BARS,
                "equal_level_tolerance": str(self.equal_level_tolerance),
                "indicator_parameters": [{"timeframe": o.timeframe, "indicator": o.indicator,
                    "parameters": list(o.parameters)} for frame in self.timeframes
                    for o in frame.indicator_observations]}}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _event_context(frame_events: tuple[StructureEvent, ...], evaluation: datetime,
                   timeframe: str, source_hash: str) -> tuple:
    high = low = latest_break = eqh = eql = premium = None
    level_status: dict[str, tuple[str, StructureEvent | None]] = {}
    active_gaps: dict[str, tuple[StructureEvent, str, StructureEvent | None]] = {}
    for event in frame_events:
        if event.knowable_at > evaluation:
            continue
        if (event.timeframe != timeframe or event.provider != PROVIDER or event.broker != BROKER
                or event.symbol != SYMBOL):
            raise ValueError("structure events contain mixed source identity")
        if any(c.source_sha256 != source_hash for c in event.source_candles):
            raise ValueError("structure event source hash does not match Phase 1")
        if event.event_type == "SWING_HIGH":
            high = event
            level_status[event.event_id] = ("POTENTIAL", None)
        elif event.event_type == "SWING_LOW":
            low = event
            level_status[event.event_id] = ("POTENTIAL", None)
        elif event.event_type in {"BOS", "CHOCH"}:
            latest_break = event
            for ref in event.reference_event_ids:
                if ref in level_status:
                    level_status[ref] = ("CLOSED_THROUGH", event)
        elif event.event_type in {"BUY_SIDE_SWEEP", "SELL_SIDE_SWEEP"}:
            for ref in event.reference_event_ids:
                if ref in level_status:
                    level_status[ref] = ("SWEPT", event)
        elif event.event_type == "EQUAL_HIGHS":
            eqh = event
        elif event.event_type == "EQUAL_LOWS":
            eql = event
        elif event.event_type == "PREMIUM_DISCOUNT":
            premium = event
        elif event.event_type == "FVG_FORMED":
            active_gaps[event.event_id] = (event, "UNFILLED", None)
        elif event.event_type in {"FVG_PARTIAL_MITIGATION", "FVG_FULL_MITIGATION"}:
            for ref in event.reference_event_ids:
                if ref in active_gaps:
                    formation = active_gaps[ref][0]
                    if event.event_type == "FVG_FULL_MITIGATION":
                        del active_gaps[ref]
                    else:
                        active_gaps[ref] = (formation, "PARTIALLY_MITIGATED", event)
    latest = (high, low, latest_break, eqh, eql, premium)
    liquidity = tuple((event, *level_status.get(event.event_id, ("POTENTIAL", None)))
                      for event in (high, low) if event is not None)
    fvgs = tuple(FVGView(*item) for item in active_gaps.values())
    return (*latest, liquidity, fvgs)


def _direction(observations: tuple[IndicatorObservation, ...], latest_break: StructureEvent | None,
               statuses: tuple[tuple[str, str], ...]) -> tuple[str, tuple[tuple[str, str], ...], tuple[str, ...]]:
    by_name = {o.indicator: o for o in observations}
    by_ema = {dict(o.parameters).get("period"): o for o in observations if o.indicator == "EMA"}
    components: list[tuple[str, str]] = []
    missing = [f"{name}:{status}" for name, status in statuses if status != IndicatorStatus.ALIGNED.value]
    emas = [by_ema.get(period) for period in (20, 50, 200)]
    if all(emas):
        vals = [item.value for item in emas]
        if vals[0] > vals[1] > vals[2]: components.append(("EMA_ALIGNMENT", "BULLISH"))
        elif vals[0] < vals[1] < vals[2]: components.append(("EMA_ALIGNMENT", "BEARISH"))
        else: components.append(("EMA_ALIGNMENT", "NOT_ALIGNED"))
    else:
        missing.append("EMA_ALIGNMENT")
    line, signal = by_name.get("MACD_LINE"), by_name.get("MACD_SIGNAL")
    if line and signal:
        components.append(("MACD", "BULLISH" if line.value > signal.value else
                           "BEARISH" if line.value < signal.value else "NEUTRAL"))
    else: missing.append("MACD_LINE_OR_SIGNAL")
    momentum = by_name.get("MOMENTUM_ROC")
    if momentum:
        components.append(("MOMENTUM_ROC", "BULLISH" if momentum.value > 0 else
                           "BEARISH" if momentum.value < 0 else "NEUTRAL"))
    else: missing.append("MOMENTUM_ROC")
    if latest_break:
        components.append(("LATEST_STRUCTURE_BREAK", latest_break.direction.upper()
                           if latest_break.direction else "UNKNOWN"))
    else: missing.append("LATEST_STRUCTURE_BREAK")
    directions = {value for _, value in components if value in {"BULLISH", "BEARISH"}}
    context = ("INSUFFICIENT EVIDENCE" if not directions else "MIXED CONTEXT" if len(directions) > 1
               else f"{next(iter(directions))} CONTEXT")
    return context, tuple(components), tuple(sorted(set(missing)))


def build_confluence_snapshot(historical_run: HistoricalRun, indicator_run: IndicatorRun,
                              structure_run: HistoricalStructureRun, *, evaluation_at: datetime,
                              session_definitions: tuple[SessionDefinition, ...] = DEFAULT_SESSIONS,
                              eligible_candle_counts: dict[str, int] | None = None
                              ) -> ConfluenceSnapshot:
    """Combine only same-run H1/M15 evidence knowable at the UTC evaluation instant."""
    evaluation = _utc(evaluation_at, "evaluation_at")
    report = historical_run.report
    cutoff = _utc(report.analysis_cutoff, "analysis_cutoff")
    if evaluation > cutoff or evaluation > _utc(indicator_run.analysis_cutoff, "indicator cutoff") \
            or evaluation > _utc(structure_run.analysis_cutoff, "structure cutoff"):
        raise ValueError("evaluation_at must not exceed every Phase 1–3 analysis cutoff")
    if indicator_run.source_run_id != report.run_id or structure_run.source_run_id != report.run_id:
        raise ValueError("Phase 1–3 inputs must belong to the same historical run")
    if _utc(indicator_run.analysis_cutoff, "indicator cutoff") != cutoff or \
            _utc(structure_run.analysis_cutoff, "structure cutoff") != cutoff:
        raise ValueError("Phase 1–3 analysis cutoffs must match")
    if (report.provider, report.broker, report.symbol, report.source_classification,
            report.timezone_policy) != (PROVIDER, BROKER, SYMBOL, SOURCE_CLASSIFICATION, TIMEZONE_POLICY):
        raise ValueError("Phase 1 run is not the configured Alpari MT5 XAUUSD_i source")
    if any(c.eligibility != CandleEligibility.UNKNOWN_BOUNDARY
           for c in historical_run.series_for("Daily").candles):
        raise ValueError("Daily candles must remain UNKNOWN_BOUNDARY")
    align = align_indicators(indicator_run, evaluation,
                             eligible_candle_counts=eligible_candle_counts)
    aligned_by_tf: dict[str, list] = {tf: [] for tf in TIMEFRAMES}
    status_by_tf: dict[str, list[tuple[str, str]]] = {tf: [] for tf in TIMEFRAMES}
    for value in align.values:
        if value.timeframe in aligned_by_tf:
            status_by_tf[value.timeframe].append((value.indicator, value.status.value))
            if value.observation is not None:
                aligned_by_tf[value.timeframe].append(value.observation)
    hashes: list[tuple[str, str]] = []
    frames: list[TimeframeSnapshot] = []
    retained_events: list[StructureEvent] = []
    for timeframe in TIMEFRAMES:
        phase1 = historical_run.series_for(timeframe)
        phase2, phase3 = indicator_run.timeframe(timeframe), structure_run.timeframe(timeframe)
        if (phase1.series_id != phase2.series_id or phase1.series_id != phase3.series_id or
                phase1.source_sha256 != phase2.source_sha256 or phase1.source_sha256 != phase3.source_sha256):
            raise ValueError(f"{timeframe} provider series or source hash mismatch")
        if phase1.timezone_policy != report.timezone_policy:
            raise ValueError("source timezone policy mismatch")
        for obs in aligned_by_tf[timeframe]:
            if obs.timeframe != timeframe or obs.closed_at > evaluation or obs.eligibility != CandleEligibility.ELIGIBLE_CLOSED:
                raise ValueError("indicator alignment includes ineligible or future evidence")
            if ((obs.provider, obs.broker, obs.symbol) != (report.provider, report.broker, report.symbol)
                    or obs.source_candle.series_id != phase1.series_id
                    or obs.source_candle.timezone_policy != phase1.timezone_policy
                    or obs.source_candle.source_sha256 != phase1.source_sha256):
                raise ValueError("indicator source hash does not match Phase 1")
        all_events = phase3.events
        selected = _event_context(all_events, evaluation, timeframe, phase1.source_sha256)
        high, low, latest_break, eqh, eql, premium, liquidity, fvgs = selected
        chosen_events = [e for e in (high, low, latest_break, eqh, eql, premium) if e]
        chosen_events += [e for e, _, _ in liquidity]
        for fvg in fvgs:
            chosen_events.append(fvg.formation)
            if fvg.latest_transition: chosen_events.append(fvg.latest_transition)
        retained_events.extend(chosen_events)
        observations = tuple(sorted(aligned_by_tf[timeframe], key=lambda o: (o.indicator, o.parameters)))
        statuses = tuple(sorted(status_by_tf[timeframe]))
        context, components, missing = _direction(observations, latest_break, statuses)
        frames.append(TimeframeSnapshot(timeframe, phase1.series_id, phase1.source_file,
            phase1.source_sha256, observations, statuses, high, low, latest_break, eqh, eql,
            liquidity, fvgs, premium, phase3.diagnostics, context, components, missing))
        hashes.append((timeframe, phase1.source_sha256))
    # Daily is deliberately represented only as excluded Phase 1 data, never as context.
    missing = tuple(f"{frame.timeframe}:{item}" for frame in frames for item in frame.missing_evidence)
    directions = {frame.timeframe: frame.context for frame in frames}
    h1, m15 = directions["H1"], directions["M15"]
    if h1 in {"BULLISH CONTEXT", "BEARISH CONTEXT"} and m15 == h1:
        overall, alignment = h1, "ALIGNED"
    elif h1 in {"BULLISH CONTEXT", "BEARISH CONTEXT"} and m15 in {"BULLISH CONTEXT", "BEARISH CONTEXT"}:
        overall, alignment = "MIXED CONTEXT", "DISAGREEMENT"
    elif "MIXED CONTEXT" in directions.values():
        overall, alignment = "MIXED CONTEXT", "PARTIAL"
    else:
        overall, alignment = "INSUFFICIENT EVIDENCE", "PARTIAL"
    support = tuple(f"{frame.timeframe}:{name}={direction}" for frame in frames
                    for name, direction in frame.context_components if direction in {"BULLISH", "BEARISH"})
    conflict_items = [f"{frame.timeframe}:{name}={direction}" for frame in frames
                      for name, direction in frame.context_components
                      if (direction == "BEARISH" and any(other == "BULLISH" for _, other in frame.context_components))
                      or (direction == "BULLISH" and any(other == "BEARISH" for _, other in frame.context_components))]
    if h1 == "BULLISH CONTEXT" and m15 == "BEARISH CONTEXT" or \
            h1 == "BEARISH CONTEXT" and m15 == "BULLISH CONTEXT":
        conflict_items.extend((f"H1={h1}", f"M15={m15}"))
    conflict = tuple(conflict_items)
    # Session views are limited to the selected immutable indicator/event candle references.
    session_keys: dict[tuple[str, str, int], tuple[datetime, datetime]] = {}
    for frame in frames:
        step = INTERVALS[frame.timeframe]
        for obs in frame.indicator_observations:
            ref = obs.source_candle
            session_keys[(frame.timeframe, ref.source_file, ref.source_row)] = (obs.opened_at, obs.closed_at)
    for event in retained_events:
        step = INTERVALS[event.timeframe]
        for candle in event.source_candles:
            session_keys[(event.timeframe, candle.source_file, candle.source_row)] = (candle.opened_at, candle.opened_at + step)
    qatar = ZoneInfo(DISPLAY_ZONE)
    session_views = []
    phase1_by_tf = {tf: historical_run.series_for(tf) for tf in TIMEFRAMES}
    for (timeframe, filename, row), (opened, closed) in sorted(session_keys.items()):
        digest = phase1_by_tf[timeframe].source_sha256
        open_sessions = classify_sessions(opened, session_definitions)
        close_sessions = classify_sessions(closed, session_definitions)
        session_views.append(SessionView(timeframe, filename, digest, row, opened, closed,
            opened.astimezone(qatar), closed.astimezone(qatar), open_sessions, close_sessions,
            open_sessions != close_sessions))
    excluded = (("Daily", CandleEligibility.UNKNOWN_BOUNDARY.value),)
    for series in historical_run.series:
        if series.timeframe == "Daily":
            hashes.append(("Daily", series.source_sha256))
    warnings = tuple(f"{frame.timeframe} contains {frame.diagnostics.nonconsecutive_intervals} nonconsecutive intervals; gaps are retained and not filled"
                     for frame in frames if frame.diagnostics.nonconsecutive_intervals)
    source_warnings = tuple(f"{item.timeframe} import reported {item.issue_counts}"
                            for item in report.series if item.issue_counts)
    warnings += source_warnings
    limitations = (
        "Daily candles are excluded because the broker session boundary is unknown.",
        "H4 is disabled.",
        "Historical broker CFD observations are not live or executable prices.",
        "Directional labels use agreement among available EMA alignment, MACD line/signal, momentum sign and latest break; RSI, ATR and premium/discount are descriptive only.",
        "Session labels reuse the existing configured wall-clock windows; they are context labels, not verified market-session boundaries.",
        "Session-boundary checks cover the candles referenced by selected snapshot evidence only.",
    )
    return ConfluenceSnapshot(evaluation, cutoff, report.run_id, report.provider, report.broker,
        report.symbol, report.source_classification, report.configured_timezone, report.timezone_policy,
        tuple(hashes), tuple(frames), overall, alignment, support, conflict, missing, warnings, limitations,
        tuple(session_views), tuple(session_definitions), excluded, INDICATOR_VERSION, STRUCTURE_VERSION,
        structure_run.equal_level_tolerance)
