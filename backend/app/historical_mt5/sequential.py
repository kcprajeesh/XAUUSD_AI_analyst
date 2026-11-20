"""Opt-in compact historical MT5 processing; the full-history API remains the reference."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Protocol

from app.analysis.sessions import DEFAULT_SESSIONS, SessionDefinition
from app.data.mt5_import import MT5Candle
from app.historical_mt5.confluence import ConfluenceSnapshot, build_confluence_snapshot
from app.historical_mt5.indicators import (
    IndicatorObservation, IndicatorRun, IndicatorStatus, TimeframeIndicators,
    stream_indicators,
)
from app.historical_mt5.models import HistoricalRun
from app.historical_mt5.structure import (
    ALGORITHM_VERSION as STRUCTURE_VERSION, FairValueGapState,
    HistoricalStructureRun, StructureDiagnostics, StructureEvent,
    TimeframeMarketStructure, stream_market_structure,
)

TIMEFRAMES = ("H1", "M15")


@dataclass(frozen=True, slots=True)
class SequentialConfig:
    evaluation_instants: tuple[datetime, ...]
    equal_level_tolerance: Decimal = Decimal("0")
    session_definitions: tuple[SessionDefinition, ...] = DEFAULT_SESSIONS

    def __post_init__(self) -> None:
        if not self.evaluation_instants:
            raise ValueError("at least one evaluation instant is required")
        instants = tuple(_utc(value, "evaluation instant") for value in self.evaluation_instants)
        if instants != tuple(sorted(set(instants))):
            raise ValueError("evaluation instants must be strictly increasing and unique")
        object.__setattr__(self, "evaluation_instants", instants)
        if (not isinstance(self.equal_level_tolerance, Decimal)
                or not self.equal_level_tolerance.is_finite()
                or self.equal_level_tolerance < 0):
            raise ValueError("equal_level_tolerance must be a finite nonnegative Decimal")


@dataclass(frozen=True, slots=True)
class ProvenanceReference:
    timeframe: str
    series_id: str
    source_file: str
    source_sha256: str
    timezone_policy: str


@dataclass(frozen=True, slots=True)
class SequentialFrameReport:
    timeframe: str
    provenance: ProvenanceReference
    indicator_observation_count: int
    indicator_fingerprint: str
    structure_event_count: int
    structure_event_fingerprint: str
    final_fvg_count: int
    final_fvg_fingerprint: str
    diagnostics: StructureDiagnostics


@dataclass(frozen=True, slots=True)
class SequentialReport:
    run_id: str
    provider: str
    broker: str
    symbol: str
    source_hashes: tuple[tuple[str, str], ...]
    config: SequentialConfig
    frames: tuple[SequentialFrameReport, ...]
    snapshots: tuple[ConfluenceSnapshot, ...]

    def to_json(self) -> str:
        return json.dumps({
            "run_id": self.run_id, "provider": self.provider, "broker": self.broker,
            "symbol": self.symbol, "source_hashes": self.source_hashes,
            "evaluation_instants": [item.isoformat() for item in self.config.evaluation_instants],
            "equal_level_tolerance": str(self.config.equal_level_tolerance),
            "frames": [{"timeframe": frame.timeframe,
                        "provenance": {"series_id": frame.provenance.series_id,
                                       "source_file": frame.provenance.source_file,
                                       "source_sha256": frame.provenance.source_sha256,
                                       "timezone_policy": frame.provenance.timezone_policy},
                        "indicator_observation_count": frame.indicator_observation_count,
                        "indicator_fingerprint": frame.indicator_fingerprint,
                        "structure_event_count": frame.structure_event_count,
                        "structure_event_fingerprint": frame.structure_event_fingerprint,
                        "final_fvg_count": frame.final_fvg_count,
                        "final_fvg_fingerprint": frame.final_fvg_fingerprint,
                        "diagnostics": {name: getattr(frame.diagnostics, name)
                                        for name in frame.diagnostics.__dataclass_fields__}}
                       for frame in self.frames],
            "snapshots": [json.loads(snapshot.to_json()) for snapshot in self.snapshots],
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class IncrementalCollector(Protocol):
    """Callbacks consumed by the shared indicator and structure processors."""

    def on_observation(self, observation: IndicatorObservation) -> None: ...
    def on_candle(self, timeframe: str, closed_at: datetime, count: int) -> None: ...
    def on_event(self, event: StructureEvent) -> None: ...


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _stamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _candle_payload(candle: MT5Candle) -> dict:
    return {"provider": candle.provider, "broker": candle.broker, "symbol": candle.symbol,
            "source_classification": candle.source_classification, "timeframe": candle.timeframe,
            "series_id": candle.series_id, "opened_at": _stamp(candle.opened_at),
            "source_timestamp": candle.source_timestamp, "source_timezone": candle.source_timezone,
            "timezone_policy": candle.timezone_policy, "open": str(candle.open),
            "high": str(candle.high), "low": str(candle.low), "close": str(candle.close),
            "tick_volume": candle.tick_volume, "real_volume": candle.real_volume,
            "spread": candle.spread, "source_file": candle.source_file,
            "source_sha256": candle.source_sha256, "source_row": candle.source_row}


def _indicator_payload(item: IndicatorObservation) -> dict:
    return {"provider": item.provider, "broker": item.broker, "symbol": item.symbol,
            "timeframe": item.timeframe, "indicator": item.indicator,
            "parameters": item.parameters, "algorithm_version": item.algorithm_version,
            "opened_at": _stamp(item.opened_at), "closed_at": _stamp(item.closed_at),
            "source_candle": {name: getattr(item.source_candle, name)
                              for name in item.source_candle.__dataclass_fields__
                              if name not in {"utc_timestamp"}},
            "source_utc": _stamp(item.source_candle.utc_timestamp), "value": str(item.value),
            "status": item.status.value, "eligibility": item.eligibility.value,
            "gap_before": item.gap_before}


def _event_payload(event: StructureEvent) -> dict:
    return {name: ([_candle_payload(c) for c in value] if name == "source_candles" else
                   _stamp(value) if isinstance(value, datetime) else
                   str(value) if isinstance(value, Decimal) else
                   list(value) if isinstance(value, tuple) else value)
            for name in event.__dataclass_fields__
            for value in (getattr(event, name),)}


def _push(digest, value: dict) -> None:
    digest.update(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode())
    digest.update(b"\n")


def fingerprint_indicators(run: IndicatorRun) -> tuple[tuple[str, int, str], ...]:
    """Ordered fingerprints used to compare the compact path with the reference output."""
    result = []
    for frame in run.timeframes:
        digest = sha256()
        count = 0
        for track in frame.tracks:
            track_digest = sha256()
            track_count = 0
            for item in track.observations:
                _push(track_digest, _indicator_payload(item))
                count += 1
                track_count += 1
            _push(digest, {"indicator": track.spec.indicator,
                           "parameters": track.spec.parameters,
                           "count": track_count,
                           "fingerprint": track_digest.hexdigest()})
        result.append((frame.timeframe, count, digest.hexdigest()))
    return tuple(result)


def fingerprint_structure(run: HistoricalStructureRun) -> tuple[tuple[str, int, str], ...]:
    result = []
    for frame in run.timeframes:
        digest = sha256()
        for event in frame.events:
            _push(digest, _event_payload(event))
        result.append((frame.timeframe, len(frame.events), digest.hexdigest()))
    return tuple(result)


def _fvg_payload(zone: FairValueGapState) -> dict:
    return {"gap_id": zone.gap_id, "timeframe": zone.timeframe, "direction": zone.direction,
            "price_low": str(zone.price_low), "price_high": str(zone.price_high),
            "formed_at": _stamp(zone.formed_at), "knowable_at": _stamp(zone.knowable_at),
            "status": zone.status, "last_updated_at": _stamp(zone.last_updated_at),
            "source_candles": [_candle_payload(c) for c in zone.source_candles]}


def fingerprint_fvgs(run: HistoricalStructureRun) -> tuple[tuple[str, int, str], ...]:
    result = []
    for frame in run.timeframes:
        digest = sha256()
        for zone in frame.fair_value_gaps:
            _push(digest, _fvg_payload(zone))
        result.append((frame.timeframe, len(frame.fair_value_gaps), digest.hexdigest()))
    return tuple(result)


@dataclass(slots=True)
class _GapFingerprint:
    payload: dict


class _AsOfStructure:
    def __init__(self, evaluation_at: datetime):
        self.evaluation_at = evaluation_at
        self.high: tuple[int, StructureEvent] | None = None
        self.low: tuple[int, StructureEvent] | None = None
        self.high_status: tuple[str, tuple[int, StructureEvent] | None] = ("POTENTIAL", None)
        self.low_status: tuple[str, tuple[int, StructureEvent] | None] = ("POTENTIAL", None)
        self.latest_break = self.eqh = self.eql = self.premium = None
        self.active_gaps: dict[str, tuple[tuple[int, StructureEvent], str,
                                          tuple[int, StructureEvent] | None]] = {}

    def observe(self, sequence: int, event: StructureEvent) -> None:
        if event.knowable_at > self.evaluation_at:
            return
        item = (sequence, event)
        if event.event_type == "SWING_HIGH":
            self.high, self.high_status = item, ("POTENTIAL", None)
        elif event.event_type == "SWING_LOW":
            self.low, self.low_status = item, ("POTENTIAL", None)
        elif event.event_type in {"BOS", "CHOCH"}:
            self.latest_break = item
            if self.high and self.high[1].event_id in event.reference_event_ids:
                self.high_status = ("CLOSED_THROUGH", item)
            if self.low and self.low[1].event_id in event.reference_event_ids:
                self.low_status = ("CLOSED_THROUGH", item)
        elif event.event_type in {"BUY_SIDE_SWEEP", "SELL_SIDE_SWEEP"}:
            if self.high and self.high[1].event_id in event.reference_event_ids:
                self.high_status = ("SWEPT", item)
            if self.low and self.low[1].event_id in event.reference_event_ids:
                self.low_status = ("SWEPT", item)
        elif event.event_type == "EQUAL_HIGHS":
            self.eqh = item
        elif event.event_type == "EQUAL_LOWS":
            self.eql = item
        elif event.event_type == "PREMIUM_DISCOUNT":
            self.premium = item
        elif event.event_type == "FVG_FORMED":
            self.active_gaps[event.event_id] = (item, "UNFILLED", None)
        elif event.event_type in {"FVG_PARTIAL_MITIGATION", "FVG_FULL_MITIGATION"}:
            for reference in event.reference_event_ids:
                if reference not in self.active_gaps:
                    continue
                formation, _, _ = self.active_gaps[reference]
                if event.event_type == "FVG_FULL_MITIGATION":
                    del self.active_gaps[reference]
                else:
                    self.active_gaps[reference] = (formation, "PARTIALLY_MITIGATED", item)

    def relevant_events(self) -> tuple[StructureEvent, ...]:
        selected: dict[str, tuple[int, StructureEvent]] = {}

        def add(item):
            if item is not None:
                selected[item[1].event_id] = item

        add(self.high)
        add(self.high_status[1])
        add(self.low)
        add(self.low_status[1])
        for item in (self.latest_break, self.eqh, self.eql, self.premium):
            add(item)
        for formation, _, transition in self.active_gaps.values():
            add(formation)
            add(transition)
        return tuple(event for _, event in sorted(selected.values(), key=lambda pair: pair[0]))


@dataclass(slots=True)
class _EvaluationState:
    evaluation_at: datetime
    latest_indicators: dict[tuple[str, tuple], IndicatorObservation]
    eligible_count: int = 0
    structure: _AsOfStructure | None = None


class _FrameCollector:
    def __init__(self, timeframe: str, evaluations: tuple[datetime, ...]):
        self.timeframe = timeframe
        self.states = [_EvaluationState(at, {}, structure=_AsOfStructure(at)) for at in evaluations]
        self.indicator_digests: dict[tuple[str, tuple], object] = {}
        self.indicator_counts: dict[tuple[str, tuple], int] = {}
        self.indicator_count = 0
        self.event_digest = sha256()
        self.event_count = 0
        self.event_sequence = 0
        self.fvgs: dict[str, _GapFingerprint] = {}

    def on_observation(self, observation: IndicatorObservation) -> None:
        key = observation.indicator, observation.parameters
        digest = self.indicator_digests.setdefault(key, sha256())
        _push(digest, _indicator_payload(observation))
        self.indicator_counts[key] = self.indicator_counts.get(key, 0) + 1
        self.indicator_count += 1
        for state in self.states:
            if observation.closed_at <= state.evaluation_at:
                state.latest_indicators[key] = observation

    def on_candle(self, timeframe: str, closed_at: datetime, count: int) -> None:
        for state in self.states:
            if closed_at <= state.evaluation_at:
                state.eligible_count = count

    def on_event(self, event: StructureEvent) -> None:
        _push(self.event_digest, _event_payload(event))
        self.event_count += 1
        self.event_sequence += 1
        sequence = self.event_sequence
        for state in self.states:
            assert state.structure is not None
            state.structure.observe(sequence, event)
        if event.event_type == "FVG_FORMED":
            self.fvgs[event.event_id] = _GapFingerprint({
                "gap_id": event.event_id, "timeframe": event.timeframe,
                "direction": event.direction, "price_low": str(event.price_low),
                "price_high": str(event.price_high), "formed_at": _stamp(event.event_at),
                "knowable_at": _stamp(event.knowable_at), "status": "UNFILLED",
                "last_updated_at": _stamp(event.event_at),
                "source_candles": [_candle_payload(c) for c in event.source_candles],
            })
        elif event.event_type in {"FVG_PARTIAL_MITIGATION", "FVG_FULL_MITIGATION"}:
            for reference in event.reference_event_ids:
                if reference in self.fvgs:
                    self.fvgs[reference].payload["status"] = event.state
                    self.fvgs[reference].payload["last_updated_at"] = _stamp(event.knowable_at)

    def fvg_fingerprint(self) -> tuple[int, str]:
        digest = sha256()
        for item in self.fvgs.values():
            _push(digest, item.payload)
        return len(self.fvgs), digest.hexdigest()

    def indicator_fingerprint(self, meta: TimeframeIndicators) -> str:
        digest = sha256()
        for track in meta.tracks:
            key = track.spec.indicator, track.spec.parameters
            track_digest = self.indicator_digests.get(key, sha256())
            _push(digest, {"indicator": track.spec.indicator,
                           "parameters": track.spec.parameters,
                           "count": self.indicator_counts.get(key, 0),
                           "fingerprint": track_digest.hexdigest()})
        return digest.hexdigest()


def _compact_indicator_run(run: HistoricalRun, timeframe: str, meta: TimeframeIndicators,
                           state: _EvaluationState) -> IndicatorRun:
    tracks = []
    for track in meta.tracks:
        latest = [item for (name, params), item in state.latest_indicators.items()
                  if name == track.spec.indicator and params == track.spec.parameters]
        tracks.append(replace(track, eligible_candle_count=state.eligible_count,
                              status=(IndicatorStatus.READY if latest else
                                      IndicatorStatus.WARMING_UP if state.eligible_count else
                                      IndicatorStatus.NO_ELIGIBLE_CANDLES),
                              observations=tuple(latest)))
    compact = replace(meta, eligible_candle_count=state.eligible_count,
                      eligible_candle_closes=(), tracks=tuple(tracks))
    return IndicatorRun(run.report.run_id, run.report.analysis_cutoff, (compact,),
                        (("Daily", "UNKNOWN_BOUNDARY"),))


def process_sequential(run: HistoricalRun, config: SequentialConfig) -> SequentialReport:
    """Build compact snapshots in one forward pass per timeframe and algorithm."""
    if any(at > run.report.analysis_cutoff for at in config.evaluation_instants):
        raise ValueError("evaluation instants must not exceed the analysis cutoff")
    collectors = {timeframe: _FrameCollector(timeframe, config.evaluation_instants)
                  for timeframe in TIMEFRAMES}
    indicator_meta = {}
    structure_meta = {}
    for timeframe in TIMEFRAMES:
        collector = collectors[timeframe]
        indicator_meta[timeframe] = stream_indicators(
            run, timeframe, on_observation=collector.on_observation,
            on_candle=collector.on_candle)
        structure_meta[timeframe] = stream_market_structure(
            run, timeframe, on_event=collector.on_event,
            equal_level_tolerance=config.equal_level_tolerance)

    snapshots = []
    for index, evaluation in enumerate(config.evaluation_instants):
        indicators = []
        structures = []
        eligible_counts = {}
        for timeframe in TIMEFRAMES:
            state = collectors[timeframe].states[index]
            indicators.append(_compact_indicator_run(run, timeframe,
                                                       indicator_meta[timeframe], state).timeframes[0])
            structures.append(replace(structure_meta[timeframe],
                events=state.structure.relevant_events(), fair_value_gaps=()))
            eligible_counts[timeframe] = state.eligible_count
        compact_indicator_run = IndicatorRun(run.report.run_id, run.report.analysis_cutoff,
            tuple(indicators), (("Daily", "UNKNOWN_BOUNDARY"),))
        compact_structure_run = HistoricalStructureRun(run.report.run_id,
            run.report.analysis_cutoff, STRUCTURE_VERSION, config.equal_level_tolerance,
            tuple(structures), (("Daily", "UNKNOWN_BOUNDARY"),))
        snapshots.append(build_confluence_snapshot(run, compact_indicator_run,
            compact_structure_run, evaluation_at=evaluation,
            session_definitions=config.session_definitions,
            eligible_candle_counts=eligible_counts))

    frames = []
    for timeframe in TIMEFRAMES:
        source = run.series_for(timeframe)
        collector = collectors[timeframe]
        fvg_count, fvg_digest = collector.fvg_fingerprint()
        frames.append(SequentialFrameReport(timeframe,
            ProvenanceReference(timeframe, source.series_id, source.source_file,
                                source.source_sha256, source.timezone_policy),
            collector.indicator_count,
            collector.indicator_fingerprint(indicator_meta[timeframe]),
            collector.event_count, collector.event_digest.hexdigest(),
            fvg_count, fvg_digest, structure_meta[timeframe].diagnostics))
    source_hashes = tuple((series.timeframe, series.source_sha256) for series in run.series)
    return SequentialReport(run.report.run_id, run.report.provider, run.report.broker,
                            run.report.symbol, source_hashes, config, tuple(frames), tuple(snapshots))

