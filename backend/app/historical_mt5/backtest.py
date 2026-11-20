"""Deterministic, offline SMC backtests over isolated Alpari MT5 history."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
import heapq
import json
from typing import Literal

from app.analysis.sessions import DEFAULT_SESSIONS, SessionDefinition, classify_sessions
from app.data.mt5_import import BROKER, PROVIDER, SOURCE_CLASSIFICATION, SYMBOL, TIMEZONE_POLICY
from app.historical_mt5.confluence import _direction
from app.historical_mt5.confluence import REPORT_VERSION as CONFLUENCE_ALGORITHM
from app.historical_mt5.engine import RUN_VERSION as PHASE1_ALGORITHM, _check_series
from app.historical_mt5.indicators import (
    ALGORITHM_VERSION as INDICATOR_ALGORITHM,
    IndicatorRun,
    IndicatorStatus,
)
from app.historical_mt5.models import CandleEligibility, HistoricalRun
from app.historical_mt5.sequential import _utc
from app.historical_mt5.structure import (
    ALGORITHM_VERSION as STRUCTURE_ALGORITHM,
    HistoricalStructureRun,
    StructureEvent,
)

BACKTEST_ALGORITHM = "mt5-smc-liquidity-sweep-mss-fvg-v1"
VARIANTS = ("A", "B", "C")
DIRECTIONS = {"SELL_SIDE_SWEEP": "long", "BUY_SIDE_SWEEP": "short"}
EVENT_TYPES = {"SWING_HIGH", "SWING_LOW", "BOS", "CHOCH", "BUY_SIDE_SWEEP",
               "SELL_SIDE_SWEEP", "FVG_FORMED"}
AMBIGUOUS_ENTRY_INVALIDATION = "AMBIGUOUS_ENTRY_INVALIDATION"
AMBIGUOUS_ENTRY_BAR = "AMBIGUOUS_ENTRY_BAR"
ZERO = Decimal("0")
TARGET_R = Decimal("2.00")
EXPIRY_BARS = 16
APPROVED_SOURCE_FILES = (
    ("H1", "XAUUSD_i_H1_202101040100_202611191300.csv"),
    ("M15", "XAUUSD_i_M15_202101040100_202611191345.csv"),
)
APPROVED_SOURCE_HASHES = (
    ("H1", "e1465d2ef9cbb089647933b6abee9ca68adc35d9be31f5d57c0cd4eff9500e64"),
    ("M15", "a9e177af909a6373db778c3e6f4c42a1353c3e5359b8ef49ac3fd152f0969efa"),
)
APPROVED_EVALUATION_START = datetime(2021, 1, 3, 23, tzinfo=UTC)
APPROVED_FIRST_COMMON_CLOSE = datetime(2021, 1, 4, 0, tzinfo=UTC)
APPROVED_ANALYSIS_CUTOFF = datetime(2026, 11, 19, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SetupResult:
    setup_id: str
    variant: str
    direction: str
    status: str
    sweep: StructureEvent
    selected_liquidity: StructureEvent
    h1_context: str | None
    h1_context_components: tuple[tuple[str, str], ...]
    h1_indicator_observations: tuple
    h1_missing_descriptive_components: tuple[str, ...]
    h1_break: StructureEvent | None
    mss: StructureEvent | None
    fvg: StructureEvent | None
    entry_at: datetime | None
    entry_price: Decimal | None
    stop_price: Decimal | None
    target_price: Decimal | None
    exit_at: datetime | None
    exit_price: Decimal | None
    exit_reason: str | None
    price_pnl: Decimal | None
    r_multiple: Decimal | None
    ambiguity_classes: tuple[str, ...]
    possible_outcomes: tuple[str, ...]
    gap_flags: tuple[str, ...]
    eligible_bars_after_formation: int


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    resolved_trade_count: int
    win_count: int
    loss_count: int
    win_rate: Decimal | None
    profit_factor: Decimal | None
    expectancy_r: Decimal | None
    max_drawdown_r: Decimal | None
    ambiguous_entry_invalidation_count: int
    ambiguous_entry_bar_count: int
    pending_at_cutoff_count: int
    open_at_cutoff_count: int


@dataclass(frozen=True, slots=True)
class VariantResult:
    variant: str
    setups: tuple[SetupResult, ...]
    metrics: VariantMetrics
    rejected_or_ignored_sweeps: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    report_id: str
    run_id: str
    provider: str
    broker: str
    symbol: str
    source_classification: str
    timezone_policy: str
    evaluation_start: datetime
    analysis_cutoff: datetime
    source_hashes: tuple[tuple[str, str], ...]
    source_series: tuple[tuple[str, str, str, str, str], ...]
    algorithm_versions: tuple[tuple[str, str], ...]
    configuration: tuple[tuple[str, str], ...]
    accounting: str
    variants: tuple[VariantResult, ...]
    report_version: str = BACKTEST_ALGORITHM

    def to_dict(self) -> dict:
        def stamp(value: datetime | None) -> str | None:
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None

        def event(event: StructureEvent | None) -> dict | None:
            if event is None:
                return None
            return {
                "id": event.event_id,
                "type": event.event_type,
                "direction": event.direction,
                "event_at": stamp(event.event_at),
                "knowable_at": stamp(event.knowable_at),
                "price_level": str(event.price_level) if event.price_level is not None else None,
                "price_low": str(event.price_low) if event.price_low is not None else None,
                "price_high": str(event.price_high) if event.price_high is not None else None,
                "gap_context": event.gap_context,
                "source_candles": [
                    {"timeframe": event.timeframe, "file": c.source_file,
                     "sha256": c.source_sha256, "row": c.source_row,
                     "broker_timestamp": c.source_timestamp, "utc_open": stamp(c.opened_at),
                     "series_id": c.series_id, "timezone_policy": c.timezone_policy,
                     "spread": c.spread, "tick_volume": c.tick_volume,
                     "real_volume": c.real_volume}
                    for c in event.source_candles
                ],
            }

        def observation(obs) -> dict:
            return {"indicator": obs.indicator, "parameters": list(obs.parameters),
                    "algorithm": obs.algorithm_version, "value": str(obs.value),
                    "status": obs.status.value, "opened_at": stamp(obs.opened_at),
                    "closed_at": stamp(obs.closed_at), "source_file": obs.source_candle.source_file,
                    "source_sha256": obs.source_candle.source_sha256,
                    "source_row": obs.source_candle.source_row,
                    "broker_timestamp": obs.source_candle.broker_timestamp,
                    "timezone_policy": obs.source_candle.timezone_policy}

        variants = []
        for result in self.variants:
            setups = []
            for setup in result.setups:
                setups.append({
                    "setup_id": setup.setup_id, "variant": setup.variant,
                    "direction": setup.direction, "status": setup.status,
                    "sweep": event(setup.sweep), "selected_liquidity": event(setup.selected_liquidity),
                    "h1": None if setup.h1_context is None else {
                        "context": setup.h1_context,
                        "components": list(setup.h1_context_components),
                        "indicators": [observation(o) for o in setup.h1_indicator_observations],
                        "missing_descriptive_components": list(setup.h1_missing_descriptive_components),
                        "latest_break": event(setup.h1_break)},
                    "mss": event(setup.mss), "fvg": event(setup.fvg),
                    "entry_at": stamp(setup.entry_at),
                    "entry_price": str(setup.entry_price) if setup.entry_price is not None else None,
                    "stop_price": str(setup.stop_price) if setup.stop_price is not None else None,
                    "target_price": str(setup.target_price) if setup.target_price is not None else None,
                    "exit_at": stamp(setup.exit_at),
                    "exit_price": str(setup.exit_price) if setup.exit_price is not None else None,
                    "exit_reason": setup.exit_reason,
                    "price_pnl": str(setup.price_pnl) if setup.price_pnl is not None else None,
                    "r_multiple": str(setup.r_multiple) if setup.r_multiple is not None else None,
                    "ambiguity_classes": list(setup.ambiguity_classes),
                    "possible_outcomes": list(setup.possible_outcomes),
                    "gap_flags": list(setup.gap_flags),
                    "eligible_bars_after_formation": setup.eligible_bars_after_formation,
                })
            metrics = result.metrics
            variants.append({"variant": result.variant, "setups": setups,
                "rejected_or_ignored_sweeps": dict(result.rejected_or_ignored_sweeps),
                "metrics": {name: str(value) if isinstance(value, Decimal) else value
                            for name, value in ((key, getattr(metrics, key))
                                                for key in metrics.__dataclass_fields__)}})
        return {"report_version": self.report_version, "report_id": self.report_id,
                "run_id": self.run_id, "provider": self.provider, "broker": self.broker,
                "symbol": self.symbol, "source_classification": self.source_classification,
                "timezone_policy": self.timezone_policy,
                "evaluation_start_utc": stamp(self.evaluation_start),
                "analysis_cutoff_utc": stamp(self.analysis_cutoff),
                "source_hashes": dict(self.source_hashes),
                "source_series": [{"timeframe": tf, "series_id": sid, "source_file": name,
                                   "source_sha256": digest, "timezone_policy": zone}
                                  for tf, sid, name, digest, zone in self.source_series],
                "algorithms": dict(self.algorithm_versions),
                "configuration": dict(self.configuration), "accounting": self.accounting,
                "variants": variants}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(slots=True)
class _Setup:
    variant: str
    direction: str
    sweep: StructureEvent
    liquidity: StructureEvent
    h1_context: str | None
    h1_components: tuple[tuple[str, str], ...]
    h1_observations: tuple[object, ...]
    h1_missing_descriptive: tuple[str, ...]
    h1_break: StructureEvent | None
    status: str = "WAIT_MSS"
    mss: StructureEvent | None = None
    fvg: StructureEvent | None = None
    activated_after_open: datetime | None = None
    expiry_count: int = 0
    entry_at: datetime | None = None
    entry_price: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    exit_at: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    pnl: Decimal | None = None
    r_multiple: Decimal | None = None
    ambiguities: tuple[str, ...] = ()
    possible: tuple[str, ...] = ()
    gaps: set[str] = field(default_factory=set)

    @property
    def setup_id(self) -> str:
        raw = f"{self.variant}|{self.sweep.event_id}"
        return "mt5setup-" + sha256(raw.encode()).hexdigest()[:24]


class _H1AsOf:
    def __init__(self, indicator_run: IndicatorRun, structure_run: HistoricalStructureRun):
        self.series = indicator_run.timeframe("H1")
        self.breaks = tuple(sorted((e for e in structure_run.timeframe("H1").events
                                    if e.event_type in {"BOS", "CHOCH"}),
                                   key=lambda e: (e.knowable_at, e.event_id)))
        self.break_times = tuple(e.knowable_at for e in self.breaks)

    def context(self, instant: datetime):
        observations = []
        statuses = []
        for track in self.series.tracks:
            idx = bisect_right(track.observations, instant, key=lambda item: item.closed_at) - 1
            if idx >= 0:
                observations.append(track.observations[idx])
                statuses.append((track.spec.indicator, IndicatorStatus.ALIGNED.value))
            else:
                count = bisect_right(self.series.eligible_candle_closes, instant)
                status = (IndicatorStatus.WARMING_UP if 0 < count < track.warmup_bars_required
                          else IndicatorStatus.NO_ELIGIBLE_CANDLE_AS_OF)
                statuses.append((track.spec.indicator, status.value))
        break_idx = bisect_right(self.break_times, instant) - 1
        latest_break = self.breaks[break_idx] if break_idx >= 0 else None
        label, components, missing = _direction(tuple(observations), latest_break, tuple(statuses))
        return label, components, tuple(observations), latest_break, missing


def _validate_inputs(run: HistoricalRun, indicators: IndicatorRun,
                     structure: HistoricalStructureRun) -> tuple[tuple[str, str], ...]:
    cutoff = _utc(run.report.analysis_cutoff, "analysis_cutoff")
    if indicators.source_run_id != run.report.run_id or structure.source_run_id != run.report.run_id:
        raise ValueError("Phase 1–3 inputs must belong to the same historical run")
    if structure.algorithm_version != STRUCTURE_ALGORITHM:
        raise ValueError("unsupported Phase 3 structure algorithm")
    if structure.equal_level_tolerance != Decimal("0"):
        raise ValueError("the approved Phase 3 equal-level tolerance is Decimal('0')")
    if _utc(indicators.analysis_cutoff, "indicator cutoff") != cutoff or \
            _utc(structure.analysis_cutoff, "structure cutoff") != cutoff:
        raise ValueError("Phase 1–3 analysis cutoffs must match")
    if (run.report.provider, run.report.broker, run.report.symbol,
            run.report.source_classification, run.report.timezone_policy) != \
            (PROVIDER, BROKER, SYMBOL, SOURCE_CLASSIFICATION, TIMEZONE_POLICY):
        raise ValueError("backtest requires the configured Alpari MT5 XAUUSD_i source")
    if any(c.eligibility != CandleEligibility.UNKNOWN_BOUNDARY
           for c in run.series_for("Daily").candles):
        raise ValueError("Daily candles must remain UNKNOWN_BOUNDARY")
    if {item.timeframe for item in run.series} != {"Daily", "H1", "M15"} or \
            {item.timeframe for item in indicators.timeframes} != {"H1", "M15"} or \
            {item.timeframe for item in structure.timeframes} != {"H1", "M15"}:
        raise ValueError("backtest inputs must contain separate Daily, H1 and M15 Phase 1 series and H1/M15 analyses")
    if structure.excluded_timeframes != (("Daily", "UNKNOWN_BOUNDARY"),) or \
            indicators.excluded_timeframes != (("Daily", "UNKNOWN_BOUNDARY"),):
        raise ValueError("Phase 2–3 must keep Daily excluded and H4 disabled")
    hashes = []
    for timeframe in ("H1", "M15"):
        phase1 = run.series_for(timeframe)
        phase2, phase3 = indicators.timeframe(timeframe), structure.timeframe(timeframe)
        if (phase1.series_id != phase2.series_id or phase1.series_id != phase3.series_id or
                phase1.source_sha256 != phase2.source_sha256 or phase1.source_sha256 != phase3.source_sha256):
            raise ValueError(f"{timeframe} provider series or source hash mismatch")
        if phase1.timezone_policy != TIMEZONE_POLICY:
            raise ValueError("MT5 fixed UTC+02:00 timezone policy mismatch")
        _check_series(timeframe, tuple(item.source for item in phase1.candles), phase1.source_sha256)
        for candle in phase1.candles:
            if candle.eligibility == CandleEligibility.ELIGIBLE_CLOSED and candle.nominal_close_at > cutoff:
                raise ValueError("eligible candle exceeds analysis cutoff")
        for event in phase3.events:
            if event.knowable_at.tzinfo is None or event.knowable_at.utcoffset() != timedelta(0) or \
                    event.event_at.tzinfo is None or event.event_at.utcoffset() != timedelta(0) or \
                    (event.provider, event.broker, event.symbol) != (PROVIDER, BROKER, SYMBOL) or \
                    event.timeframe != timeframe or event.knowable_at > cutoff or \
                    event.algorithm_version != STRUCTURE_ALGORITHM:
                raise ValueError(f"{timeframe} structure event is mixed, future, or unsupported")
            if any(c.source_sha256 != phase1.source_sha256 or c.series_id != phase1.series_id
                   or c.timezone_policy != TIMEZONE_POLICY or c.timeframe != timeframe
                   or (c.provider, c.broker, c.symbol, c.source_classification) !=
                   (PROVIDER, BROKER, SYMBOL, SOURCE_CLASSIFICATION)
                   for c in event.source_candles):
                raise ValueError(f"{timeframe} structure event provenance mismatch")
        for track in phase2.tracks:
            if track.spec.algorithm_version != INDICATOR_ALGORITHM:
                raise ValueError("unsupported Phase 2 indicator algorithm")
            if any(obs.closed_at.tzinfo is None or obs.closed_at.utcoffset() != timedelta(0) or
                   obs.opened_at.tzinfo is None or obs.opened_at.utcoffset() != timedelta(0) or
                   obs.closed_at > cutoff or obs.eligibility != CandleEligibility.ELIGIBLE_CLOSED or
                   (obs.provider, obs.broker, obs.symbol) != (PROVIDER, BROKER, SYMBOL) or
                   obs.timeframe != timeframe or
                   obs.source_candle.source_sha256 != phase1.source_sha256 or
                   obs.source_candle.series_id != phase1.series_id or
                   obs.source_candle.timezone_policy != TIMEZONE_POLICY for obs in track.observations):
                raise ValueError(f"{timeframe} indicator provenance or cutoff mismatch")
        hashes.append((timeframe, phase1.source_sha256))
    hashes.append(("Daily", run.series_for("Daily").source_sha256))
    return tuple(hashes)


def _validate_approved_comparison_scope(run: HistoricalRun,
                                        hashes: tuple[tuple[str, str], ...]) -> None:
    actual_hashes = dict(hashes)
    for timeframe, expected in APPROVED_SOURCE_HASHES:
        if actual_hashes.get(timeframe) != expected:
            raise ValueError(f"{timeframe} source SHA-256 does not match the approved comparison input")
    for timeframe, expected_name in APPROVED_SOURCE_FILES:
        if run.series_for(timeframe).source_file != expected_name:
            raise ValueError(f"{timeframe} source filename does not match the approved comparison input")

    cutoff = _utc(run.report.analysis_cutoff, "analysis_cutoff")
    if cutoff != APPROVED_ANALYSIS_CUTOFF:
        raise ValueError("analysis cutoff does not match the approved comparison cutoff")

    first_opens = {}
    closed_instants = {}
    for timeframe in ("H1", "M15"):
        eligible = tuple(c for c in run.series_for(timeframe).candles
                         if c.eligibility == CandleEligibility.ELIGIBLE_CLOSED)
        if not eligible:
            raise ValueError(f"{timeframe} has no eligible candles for the approved comparison window")
        first_opens[timeframe] = min(c.source.opened_at for c in eligible)
        closed_instants[timeframe] = {c.nominal_close_at for c in eligible}
        if cutoff not in closed_instants[timeframe]:
            raise ValueError(f"{timeframe} has no fully closed candle at the approved cutoff")

    if any(opened != APPROVED_EVALUATION_START for opened in first_opens.values()):
        raise ValueError("H1/M15 evaluation start does not match the approved first common candle open")
    common_closes = closed_instants["H1"] & closed_instants["M15"]
    if not common_closes or min(common_closes) != APPROVED_FIRST_COMMON_CLOSE or max(common_closes) != cutoff:
        raise ValueError("H1/M15 common closed-observation boundaries do not match the approved window")


def _metrics(setups: tuple[SetupResult, ...]) -> VariantMetrics:
    closed = [s for s in setups if s.exit_reason in {"STOP", "TARGET", "ADVERSE_GAP_STOP", "FAVORABLE_GAP_TARGET"}
              and not s.ambiguity_classes and s.r_multiple is not None]
    values = [s.r_multiple for s in closed]
    prices = [s.price_pnl for s in closed]
    wins = sum(value > 0 for value in prices)
    losses = sum(value < 0 for value in prices)
    gross_wins = sum((value for value in prices if value > 0), ZERO)
    gross_losses = -sum((value for value in prices if value < 0), ZERO)
    equity = peak = drawdown = ZERO
    with localcontext() as context:
        context.prec = 34
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        win_rate = Decimal(wins) / len(values) if values else None
        profit_factor = gross_wins / gross_losses if gross_losses else None
        expectancy = sum(values, ZERO) / len(values) if values else None
    return VariantMetrics(len(values), wins, losses,
        win_rate, profit_factor, expectancy,
        drawdown if values else None,
        sum(AMBIGUOUS_ENTRY_INVALIDATION in s.ambiguity_classes for s in setups),
        sum(AMBIGUOUS_ENTRY_BAR in s.ambiguity_classes for s in setups),
        sum(s.status == "PENDING_AT_CUTOFF" for s in setups),
        sum(s.status == "OPEN_AT_CUTOFF" for s in setups))


def _result(state: _Setup, eligible_bars_after_formation: int) -> SetupResult:
    state_reference_candles = (*state.sweep.source_candles, *state.liquidity.source_candles,
                               *(state.mss.source_candles if state.mss else ()),
                               *(state.fvg.source_candles if state.fvg else ()))
    if any(c.timezone_policy != TIMEZONE_POLICY for c in state_reference_candles):
        raise ValueError("setup contains a source candle with a different timezone policy")
    return SetupResult(state.setup_id, state.variant, state.direction, state.status,
        state.sweep, state.liquidity, state.h1_context, state.h1_components,
        state.h1_observations, state.h1_missing_descriptive, state.h1_break, state.mss, state.fvg,
        state.entry_at, state.entry_price, state.stop, state.target,
        state.exit_at, state.exit_price, state.exit_reason, state.pnl,
        state.r_multiple, state.ambiguities, state.possible, tuple(sorted(state.gaps)),
        eligible_bars_after_formation)


class _VariantMachine:
    def __init__(self, variant: str, run: HistoricalRun, h1: _H1AsOf,
                 session_definitions: tuple[SessionDefinition, ...]):
        self.variant = variant
        self.run = run
        self.h1 = h1
        self.sessions = session_definitions
        self.state: _Setup | None = None
        self.finished: list[SetupResult] = []
        self.latest_swings: dict[str, StructureEvent] = {}
        self.retired: set[str] = set()
        self.low_heap: list[tuple[Decimal, str]] = []
        self.high_heap: list[tuple[Decimal, str]] = []
        self._previous_open: datetime | None = None
        self.rejections: Counter[str] = Counter()

    def _finalize(self, status: str) -> None:
        if self.state is None:
            return
        self.state.status = status
        self.finished.append(_result(self.state, self.state.expiry_count))
        self.state = None

    def _eligible_sweep(self, sweep: StructureEvent, close: datetime):
        if sweep.gap_context:
            return None, "GAP_CONTEXT_SWEEP"
        if sweep.event_type not in DIRECTIONS:
            return None, "UNSUPPORTED_SWEEP_TYPE"
        direction = DIRECTIONS[sweep.event_type]
        side_type = "SWING_LOW" if direction == "long" else "SWING_HIGH"
        selected = self.latest_swings.get(side_type)
        if selected is None or selected.knowable_at >= close:
            return None, "NO_PREVIOUSLY_CONFIRMED_LIQUIDITY"
        if selected.event_id in self.retired:
            return None, "LATEST_LIQUIDITY_ALREADY_RETIRED"
        if selected.event_id not in sweep.reference_event_ids or sweep.price_level != selected.price_level:
            return None, "SWEEP_DOES_NOT_REFERENCE_LATEST_LIQUIDITY"
        h1_evidence = (None, (), (), None, ())
        if self.variant in {"A", "C"}:
            label, components, observations, latest_break, missing = self.h1.context(close)
            required_label = "BULLISH CONTEXT" if direction == "long" else "BEARISH CONTEXT"
            required_break = "bullish" if direction == "long" else "bearish"
            if label != required_label:
                return None, "A2_H1_CONTEXT_UNAVAILABLE_OR_DIRECTIONAL_MISMATCH"
            if latest_break is None or latest_break.direction != required_break:
                return None, "A2_H1_BREAK_UNAVAILABLE_OR_DIRECTIONAL_MISMATCH"
            h1_evidence = (label, components, observations, latest_break, missing)
        if self.variant == "C" and not classify_sessions(close, self.sessions):
            return None, "C_SWEEP_OUTSIDE_CONFIGURED_SESSIONS"
        return (selected, h1_evidence), None

    @staticmethod
    def _close_invalidated(state: _Setup, candle, later_events: tuple[StructureEvent, ...]) -> bool:
        extreme = state.sweep.source_candles[-1].low if state.direction == "long" else state.sweep.source_candles[-1].high
        through_extreme = candle.close < extreme if state.direction == "long" else candle.close > extreme
        opposite = "bearish" if state.direction == "long" else "bullish"
        opposite_break = any(e.event_type in {"BOS", "CHOCH"} and e.direction == opposite
                             and state.sweep.knowable_at < e.knowable_at for e in later_events)
        return through_extreme or opposite_break

    def _set_ambiguity(self, state: _Setup, classes: tuple[str, ...], possible: tuple[str, ...], at: datetime) -> None:
        state.ambiguities = classes
        state.possible = possible
        state.exit_at = at
        state.exit_reason = "AMBIGUOUS"
        self._finalize("AMBIGUOUS")

    def _manage_bar(self, item, close_events: tuple[StructureEvent, ...], step) -> None:
        if self.state is None:
            return
        state = self.state
        candle = item.source
        close = item.nominal_close_at
        if state.status == "PENDING" and state.fvg is not None:
            state.expiry_count += 1
            if state.fvg.gap_context:
                state.gaps.add("fvg_formation_gap_context")
            stop = state.stop
            if state.activated_after_open is not None and candle.opened_at > state.activated_after_open:
                state.activated_after_open = candle.opened_at
            at_or_after_activation = state.activated_after_open == candle.opened_at
            if at_or_after_activation:
                opening_through_stop = candle.open <= stop if state.direction == "long" else candle.open >= stop
                if opening_through_stop:
                    state.exit_at, state.exit_price = candle.opened_at, candle.open
                    state.exit_reason = "OPENING_AT_OR_BEYOND_STOP"
                    self._finalize("CANCELLED")
                    return
                with localcontext() as context:
                    context.prec = 34
                    limit = (state.fvg.price_low + state.fvg.price_high) / Decimal(2)
                if state.direction == "long":
                    fill = candle.open if candle.open <= limit else limit if candle.low <= limit else None
                else:
                    fill = candle.open if candle.open >= limit else limit if candle.high >= limit else None
                if fill is not None:
                    with localcontext() as context:
                        context.prec = 34
                        risk = fill - stop if state.direction == "long" else stop - fill
                        if risk <= ZERO:
                            state.exit_at, state.exit_price = candle.opened_at, fill
                            state.exit_reason = "INVALID_RISK"
                            self._finalize("REJECTED")
                            return
                        state.entry_at, state.entry_price = candle.opened_at, fill
                        state.target = fill + TARGET_R * risk if state.direction == "long" else fill - TARGET_R * risk
                        state.status = "OPEN"
                    stop_hit = candle.low <= stop if state.direction == "long" else candle.high >= stop
                    target_hit = candle.high >= state.target if state.direction == "long" else candle.low <= state.target
                    invalidated = self._close_invalidated(state, candle, close_events)
                    classes = []
                    possible = []
                    if invalidated:
                        classes.append(AMBIGUOUS_ENTRY_INVALIDATION)
                        possible.extend(("INVALIDATED_BEFORE_ENTRY", "ENTRY_BEFORE_INVALIDATION"))
                    if stop_hit or target_hit:
                        classes.append(AMBIGUOUS_ENTRY_BAR)
                        if stop_hit:
                            possible.append("STOP")
                        if target_hit:
                            possible.append("TARGET")
                        possible.append("REMAINS_OPEN")
                    if classes:
                        self._set_ambiguity(state, tuple(classes), tuple(possible), close)
                    return
            invalidated = self._close_invalidated(state, candle, close_events)
            expired = state.expiry_count >= EXPIRY_BARS
            if invalidated or expired:
                state.exit_at = close
                state.exit_reason = "INVALIDATED" if invalidated else "EXPIRED"
                self._finalize("CANCELLED" if invalidated else "EXPIRED")
            return
        if state.status == "OPEN":
            stop, target = state.stop, state.target
            if state.direction == "long":
                adverse_gap = candle.open < stop
                favorable_gap = candle.open > target
                stop_hit = candle.low <= stop
                target_hit = candle.high >= target
            else:
                adverse_gap = candle.open > stop
                favorable_gap = candle.open < target
                stop_hit = candle.high >= stop
                target_hit = candle.low <= target
            if adverse_gap:
                self._close_trade(candle.opened_at, candle.open, "ADVERSE_GAP_STOP", state)
            elif stop_hit and target_hit:
                self._close_trade(close, stop, "STOP", state)
            elif favorable_gap:
                self._close_trade(candle.opened_at, target, "FAVORABLE_GAP_TARGET", state)
            elif stop_hit:
                self._close_trade(close, stop, "STOP", state)
            elif target_hit:
                self._close_trade(close, target, "TARGET", state)

    def _close_trade(self, at: datetime, price: Decimal, reason: str, state: _Setup) -> None:
        assert state.entry_price is not None and state.stop is not None
        risk = state.entry_price - state.stop if state.direction == "long" else state.stop - state.entry_price
        pnl = price - state.entry_price if state.direction == "long" else state.entry_price - price
        state.exit_at, state.exit_price, state.exit_reason, state.pnl = at, price, reason, pnl
        with localcontext() as context:
            context.prec = 34
            state.r_multiple = pnl / risk
        self._finalize("CLOSED")

    def process(self, run_events: tuple[StructureEvent, ...], eligible_items: tuple, step) -> tuple[SetupResult, ...]:
        events_by_close: dict[datetime, list[StructureEvent]] = {}
        # Phase 3 emits deterministic order; preserve it for same-close events.
        for event in run_events:
            if event.event_type in EVENT_TYPES:
                events_by_close.setdefault(event.knowable_at, []).append(event)
        for item in eligible_items:
            candle, close = item.source, item.nominal_close_at
            at_close = tuple(events_by_close.get(close, ()))
            occupied_at_bar_open = self.state is not None
            if (self.state is not None and self._previous_open is not None
                    and candle.opened_at - self._previous_open != step):
                self.state.gaps.add("nonconsecutive_m15_interval")
            if any(event.gap_context for event in at_close if event.event_type in DIRECTIONS):
                if self.state is not None:
                    self.state.gaps.add("gap_context_on_bar")
            self._manage_bar(item, at_close, step)
            can_start_at_close = not occupied_at_bar_open
            if occupied_at_bar_open and self.state is None and self.finished:
                terminal_at = self.finished[-1].exit_at
                can_start_at_close = terminal_at is not None and terminal_at < close
            candidates = []
            for event in at_close:
                if event.event_type not in DIRECTIONS:
                    continue
                selected, rejection = self._eligible_sweep(event, close)
                if rejection is not None:
                    self.rejections[rejection] += 1
                else:
                    candidates.append((event.event_id, event, selected[0], selected[1]))
            # Apply permanent wick retirement after the current candle's sweep opportunity.
            while self.low_heap and -self.low_heap[0][0] > candle.low:
                _, event_id = heapq.heappop(self.low_heap)
                self.retired.add(event_id)
            while self.high_heap and self.high_heap[0][0] < candle.high:
                _, event_id = heapq.heappop(self.high_heap)
                self.retired.add(event_id)
            for event in at_close:
                if event.event_type in {"BOS", "CHOCH"}:
                    self.retired.update(event.reference_event_ids)
            # Newly confirmed pivots become candidates only after same-close sweeps and retirement.
            for event in at_close:
                if event.event_type in {"SWING_HIGH", "SWING_LOW"}:
                    self.latest_swings[event.event_type] = event
                    if event.event_type == "SWING_LOW":
                        heapq.heappush(self.low_heap, (-event.price_level, event.event_id))
                    else:
                        heapq.heappush(self.high_heap, (event.price_level, event.event_id))
            if self.state is not None:
                if self.state.fvg is None:
                    if self.state.mss is None:
                        required_mss_direction = "bullish" if self.state.direction == "long" else "bearish"
                        self.state.mss = next((e for e in at_close if e.event_type in {"BOS", "CHOCH"}
                            and e.direction == required_mss_direction
                            and e.knowable_at > self.state.sweep.knowable_at), None)
                        if self.state.mss is not None:
                            self.state.status = "WAIT_FVG"
                    if self.state.mss is not None:
                        self.state.fvg = next((e for e in at_close if e.event_type == "FVG_FORMED"
                            and e.direction == ("BULLISH" if self.state.direction == "long" else "BEARISH")
                            and e.knowable_at > self.state.mss.knowable_at), None)
                        if self.state.fvg is not None:
                            sweep_extreme = self.state.sweep.source_candles[-1].low if self.state.direction == "long" else self.state.sweep.source_candles[-1].high
                            self.state.stop = sweep_extreme
                            self.state.status = "PENDING"
                            self.state.activated_after_open = close
                            opposite = "bearish" if self.state.direction == "long" else "bullish"
                            opposite_break = any(
                                e.event_type in {"BOS", "CHOCH"} and e.direction == opposite
                                and self.state.sweep.knowable_at < e.knowable_at <= close
                                for e in at_close
                            )
                            if opposite_break:
                                self.state.exit_at = close
                                self.state.exit_reason = "INVALIDATED"
                                self._finalize("CANCELLED")
                elif self.state.status in {"PENDING", "OPEN"}:
                    if any(e.event_type == "BOS" or e.event_type == "CHOCH" for e in at_close):
                        pass
            if candidates:
                if self.state is not None:
                    self.rejections["IGNORED_WHILE_OCCUPIED"] += len(candidates)
                elif not can_start_at_close:
                    self.rejections["IGNORED_AT_TERMINAL_CLOSE"] += len(candidates)
                else:
                    _, sweep, liquidity, h1_evidence = min(candidates, key=lambda value: value[0])
                    self.rejections["LOWER_PRIORITY_SAME_CLOSE"] += len(candidates) - 1
                    direction = DIRECTIONS[sweep.event_type]
                    context, components, observations, latest_break, missing = h1_evidence
                    self.state = _Setup(self.variant, direction, sweep, liquidity,
                                        context, components, observations, missing, latest_break)
            self._previous_open = candle.opened_at
        if self.state is not None:
            cutoff = _utc(self.run.report.analysis_cutoff, "analysis_cutoff")
            if self.state.status == "PENDING":
                self._finalize("PENDING_AT_CUTOFF")
            elif self.state.status == "OPEN":
                self._finalize("OPEN_AT_CUTOFF")
            else:
                self._finalize(self.state.status)
        return tuple(self.finished)

    def rejection_report(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self.rejections.items()))


def run_smc_backtests(historical_run: HistoricalRun, indicator_run: IndicatorRun,
                      structure_run: HistoricalStructureRun, *,
                      session_definitions: tuple[SessionDefinition, ...] = DEFAULT_SESSIONS) -> BacktestReport:
    """Run A/B/C only on the approved Alpari comparison inputs and full-history window."""
    hashes = _validate_inputs(historical_run, indicator_run, structure_run)
    _validate_approved_comparison_scope(historical_run, hashes)
    if session_definitions != DEFAULT_SESSIONS:
        raise ValueError("session windows are owner-approved and cannot be overridden")
    cutoff = _utc(historical_run.report.analysis_cutoff, "analysis_cutoff")
    m15 = historical_run.series_for("M15")
    items = tuple(item for item in m15.candles
                  if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED
                  and item.nominal_close_at is not None and item.nominal_close_at <= cutoff)
    h1 = _H1AsOf(indicator_run, structure_run)
    variant_results = []
    step = timedelta(minutes=15)
    for variant in VARIANTS:
        machine = _VariantMachine(variant, historical_run, h1, session_definitions)
        setups = machine.process(structure_run.timeframe("M15").events, items, step)
        variant_results.append(VariantResult(variant, setups, _metrics(setups),
                                             machine.rejection_report()))
    versions = (("phase1", PHASE1_ALGORITHM),
                ("phase2", INDICATOR_ALGORITHM), ("phase3", STRUCTURE_ALGORITHM),
                ("phase4_context", CONFLUENCE_ALGORITHM),
                ("strategy", BACKTEST_ALGORITHM))
    first_opens = [item.source.opened_at for timeframe in ("H1", "M15")
                   for item in historical_run.series_for(timeframe).candles
                   if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED]
    if not first_opens:
        raise ValueError("no eligible H1/M15 observations are available")
    h1_closes = {item.nominal_close_at for item in historical_run.series_for("H1").candles
                 if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED}
    m15_closes = {item.nominal_close_at for item in historical_run.series_for("M15").candles
                  if item.eligibility == CandleEligibility.ELIGIBLE_CLOSED}
    common_closes = h1_closes & m15_closes
    source_series = tuple((tf, historical_run.series_for(tf).series_id,
                           historical_run.series_for(tf).source_file,
                           historical_run.series_for(tf).source_sha256,
                           historical_run.series_for(tf).timezone_policy)
                          for tf in ("Daily", "H1", "M15"))
    configuration = (
        ("variants", "A,B,C independent"),
        ("evaluation_window", f"{min(first_opens).isoformat()} through {cutoff.isoformat()} inclusive"),
        ("first_common_closed_observation", min(common_closes).isoformat() if common_closes else "unavailable"),
        ("same_close_event_order", "preserve Phase 3 event emission order for equal knowable_at; specification leaves competing same-close MSS selection unresolved"),
        ("h1_a2", "A/C only; Phase 4 label and latest confirmed H1 BOS/CHoCH both available and agree at sweep close; freeze then; missing descriptive components alone do not reject"),
        ("variant_b_h1", "bypass all H1 qualification; descriptive only"),
        ("b2", "latest confirmed same-side M15 swing before sweep close; retire on later strict wick-through or referenced BOS/CHoCH; exact touch survives; no reuse"),
        ("equal_level_tolerance", "Decimal(0)"),
        ("mss", "D1 first subsequent aligned BOS/CHoCH; knowable_at strictly after sweep close"),
        ("fvg", "first aligned M15 FVG strictly after MSS; midpoint limit; remains active through partial/full wick mitigation"),
        ("entry", "next eligible M15 open; buy open<=limit then open else limit if low<=limit; sell open>=limit then open else limit if high>=limit; cancel open at/beyond stop"),
        ("stop", "originating sweep low for long / high for short; buffer Decimal(0.00)"),
        ("target_r", str(TARGET_R)),
        ("expiry_eligible_m15_bars", str(EXPIRY_BARS)),
        ("minimum_risk_reward_filter", "disabled"),
        ("invalidation", "pending and untouched only; close through sweep extreme or later opposite confirmed BOS/CHoCH; same-candle entry/invalidation is ambiguous"),
        ("gap_policy", "reject gap_context sweeps; preserve/flag other gaps; no synthesized candles; gaps do not count toward expiry"),
        ("session_filter", "A/B disabled; C sweep close; Asia/Asia-Qatar 08:00-15:00; London/Europe-London 08:00-17:00; New York/America-New_York 08:00-17:00; IANA DST; start inclusive/end exclusive"),
        ("concurrency", "one pending/open setup per independent variant; ignore while occupied; lexicographically smallest stable event ID while flat; no retroactive sweeps"),
        ("ambiguous_execution", "exclude AMBIGUOUS_ENTRY_INVALIDATION and AMBIGUOUS_ENTRY_BAR from primary metrics; report classes and possible outcomes"),
        ("post_entry_exits", "later both touched=>stop; adverse gap=>next open; favorable target gap=>target; cutoff preserves pending/open"),
        ("position_size", "one abstract unit"),
        ("costs", "not estimated or deducted; GROSS-ONLY"),
    )
    report = BacktestReport("", historical_run.report.run_id, PROVIDER, BROKER, SYMBOL,
        SOURCE_CLASSIFICATION, TIMEZONE_POLICY, min(first_opens), cutoff, hashes,
        source_series, versions, configuration, "GROSS-ONLY", tuple(variant_results))
    payload = report.to_dict()
    payload.pop("report_id")
    report_id = "mt5backtest-" + sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=False).encode()).hexdigest()[:24]
    return replace(report, report_id=report_id)
