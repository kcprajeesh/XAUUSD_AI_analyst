"""Causal market structure, liquidity and FVG analysis for historical MT5 candles.

Swings use strict unique extrema in a consecutive five-candle window (2 left,
2 right); a window touching a nominal-time gap is rejected. The first close
break is BOS and establishes bias; same-direction breaks remain BOS and an
opposite close break is CHoCH. Each latest confirmed high/low level breaks at
most once. Exact touch alone does not retire a liquidity level. Strict wick
penetration retires it; a sweep additionally requires strict close-back. A
penetrating wick followed by a close exactly on the level retires it without
a sweep. A confirmed BOS/CHoCH referencing a swing also retires that swing.
The equal-level tolerance defaults to Decimal zero (exact equality) and is
supplied in price units; no broker tick-size assumption is introduced. Swing
labels compare adjacent confirmed swings. Equal-pool events can also link to
an older same-side pivot, choosing the nearest matching level (most recent on
a tie), so an intervening non-equal swing does not erase a liquidity reference.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
import heapq
import json
from typing import Callable

from app.data.mt5_import import INTERVALS, MT5Candle
from app.historical_mt5.models import CandleEligibility, HistoricalRun

ALGORITHM_VERSION = "mt5-structure-liquidity-v1"
SWING_LEFT_BARS = 2
SWING_RIGHT_BARS = 2
PRECISION = 34


@dataclass(frozen=True, slots=True)
class StructureEvent:
    event_id: str
    provider: str
    broker: str
    symbol: str
    timeframe: str
    event_type: str
    algorithm_version: str
    event_at: datetime
    knowable_at: datetime
    source_candles: tuple[MT5Candle, ...]
    parameters: tuple[tuple[str, int | str], ...]
    quality_status: str
    gap_context: bool
    price_level: Decimal | None = None
    price_low: Decimal | None = None
    price_high: Decimal | None = None
    price_value: Decimal | None = None
    position_percent: Decimal | None = None
    label: str | None = None
    state: str | None = None
    direction: str | None = None
    liquidity_side: str | None = None
    reference_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FairValueGapState:
    gap_id: str
    timeframe: str
    direction: str
    price_low: Decimal
    price_high: Decimal
    formed_at: datetime
    knowable_at: datetime
    status: str
    last_updated_at: datetime
    source_candles: tuple[MT5Candle, MT5Candle, MT5Candle]


@dataclass(frozen=True, slots=True)
class StructureDiagnostics:
    eligible_candles: int
    nonconsecutive_intervals: int
    swing_windows_rejected_for_gaps: int
    tied_high_candidates_rejected: int
    tied_low_candidates_rejected: int
    fvg_patterns_rejected_for_gaps: int


@dataclass(frozen=True, slots=True)
class TimeframeMarketStructure:
    timeframe: str
    series_id: str
    source_file: str
    source_sha256: str
    final_bias: str
    diagnostics: StructureDiagnostics
    events: tuple[StructureEvent, ...]
    fair_value_gaps: tuple[FairValueGapState, ...]


@dataclass(frozen=True, slots=True)
class HistoricalStructureRun:
    source_run_id: str
    analysis_cutoff: datetime
    algorithm_version: str
    equal_level_tolerance: Decimal
    timeframes: tuple[TimeframeMarketStructure, ...]
    excluded_timeframes: tuple[tuple[str, str], ...]

    def timeframe(self, value: str) -> TimeframeMarketStructure:
        for item in self.timeframes:
            if item.timeframe == value:
                return item
        raise KeyError(value)


@dataclass(frozen=True, slots=True)
class _EventHandle:
    event_id: str
    event_at: datetime
    knowable_at: datetime

    @classmethod
    def from_event(cls, event: StructureEvent) -> "_EventHandle":
        return cls(event.event_id, event.event_at, event.knowable_at)


@dataclass(frozen=True, slots=True)
class _Swing:
    event: _EventHandle
    candle: MT5Candle
    price: Decimal


@dataclass(slots=True)
class _EqualBucket:
    minimum: _Swing
    maximum: _Swing
    latest: _Swing


@dataclass(slots=True)
class _Gap:
    formation: _EventHandle
    direction: str
    low: Decimal
    high: Decimal
    candles: tuple[MT5Candle, MT5Candle, MT5Candle]
    status: str = "UNFILLED"
    last_updated_at: datetime | None = None


def _event_parameters(event_type: str, tolerance: Decimal) -> tuple[tuple[str, int | str], ...]:
    if event_type.startswith("SWING_") or event_type in {"EQUAL_HIGHS", "EQUAL_LOWS"}:
        return (("left_bars", SWING_LEFT_BARS), ("right_bars", SWING_RIGHT_BARS),
                ("equal_level_tolerance", str(tolerance)))
    if event_type in {"BOS", "CHOCH"}:
        return (("break_rule", "strict_close_cross_latest_confirmed_swing"),
                ("first_break", "BOS_SEEDS_BIAS"), ("left_bars", SWING_LEFT_BARS),
                ("right_bars", SWING_RIGHT_BARS))
    if event_type in {"BUY_SIDE_SWEEP", "SELL_SIDE_SWEEP"}:
        return (("wick_cross", "strict"), ("close_back", "strict"),
                ("swing_confirmation", "2_left_2_right"))
    if event_type.startswith("FVG_"):
        return (("pattern", "three_candle_nonoverlap"),
                ("nominally_consecutive", 1), ("mitigation", "later_closed_candle_wick"))
    return (("range", "latest_confirmed_opposite_swings"), ("decimal_precision", PRECISION))


def _make_event(*, identity: tuple[str, str, str], timeframe: str, event_type: str,
                event_at: datetime, knowable_at: datetime, source_candles: tuple[MT5Candle, ...],
                parameters: tuple[tuple[str, int | str], ...], quality_status: str = "RULE_CONFIRMED",
                gap_context: bool = False, price_level: Decimal | None = None,
                price_low: Decimal | None = None, price_high: Decimal | None = None,
                price_value: Decimal | None = None, position_percent: Decimal | None = None,
                label: str | None = None, state: str | None = None, direction: str | None = None,
                liquidity_side: str | None = None,
                reference_event_ids: tuple[str, ...] = ()) -> StructureEvent:
    provider, broker, symbol = identity
    quality = "GAP_CONTEXT" if gap_context else quality_status
    payload = {
        "provider": provider, "broker": broker, "symbol": symbol, "timeframe": timeframe,
        "event_type": event_type, "algorithm_version": ALGORITHM_VERSION,
        "event_at": event_at.isoformat(), "knowable_at": knowable_at.isoformat(),
        "source_candles": [(c.source_file, c.source_sha256, c.source_row, c.source_timestamp,
                             c.opened_at.isoformat()) for c in source_candles],
        "parameters": parameters, "quality_status": quality, "gap_context": gap_context,
        "price_level": str(price_level) if price_level is not None else None,
        "price_low": str(price_low) if price_low is not None else None,
        "price_high": str(price_high) if price_high is not None else None,
        "price_value": str(price_value) if price_value is not None else None,
        "position_percent": str(position_percent) if position_percent is not None else None,
        "label": label, "state": state, "direction": direction,
        "liquidity_side": liquidity_side, "reference_event_ids": reference_event_ids,
    }
    event_id = "mt5evt-" + sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                              ensure_ascii=False).encode()).hexdigest()[:24]
    return StructureEvent(event_id, provider, broker, symbol, timeframe, event_type, ALGORITHM_VERSION,
                          event_at, knowable_at, source_candles, parameters, quality, gap_context,
                          price_level, price_low, price_high, price_value, position_percent,
                          label, state, direction, liquidity_side, reference_event_ids)


def _analyze_timeframe(run: HistoricalRun, timeframe: str, tolerance: Decimal,
                       on_event: Callable[[StructureEvent], None] | None = None,
                       *, retain: bool = True) -> TimeframeMarketStructure:
    series = run.series_for(timeframe)
    identity = (run.report.provider, run.report.broker, run.report.symbol)
    step = INTERVALS[timeframe]
    events: list[StructureEvent] = []
    gap_states: list[_Gap] = []
    window: deque[tuple[MT5Candle, object]] = deque(maxlen=SWING_LEFT_BARS + SWING_RIGHT_BARS + 1)
    prior_bars: deque[MT5Candle] = deque(maxlen=2)
    latest_high: _Swing | None = None
    latest_low: _Swing | None = None
    high_history: deque[_Swing] = deque(maxlen=2)
    low_history: deque[_Swing] = deque(maxlen=2)
    exact_highs: dict[Decimal, _Swing] = {}
    exact_lows: dict[Decimal, _Swing] = {}
    high_buckets: dict[int, _EqualBucket] = {}
    low_buckets: dict[int, _EqualBucket] = {}
    bias = "NEUTRAL"
    last_close: Decimal | None = None
    previous_open: datetime | None = None
    parameter_cache: dict[str, tuple[tuple[str, int | str], ...]] = {}
    candle_index = 0
    gap_count = swing_gap_rejections = tied_highs = tied_lows = fvg_gap_rejections = 0
    buy_levels: list[tuple[Decimal, int, _Swing]] = []
    sell_levels: list[tuple[Decimal, int, _Swing]] = []
    broken_levels: set[str] = set()
    level_sequence = 0
    bull_unfilled: list[tuple[Decimal, int, _Gap]] = []
    bull_partial: list[tuple[Decimal, int, _Gap]] = []
    bear_unfilled: list[tuple[Decimal, int, _Gap]] = []
    bear_partial: list[tuple[Decimal, int, _Gap]] = []

    def emit(event_type: str, event_at: datetime, knowable_at: datetime,
             source_candles: tuple[MT5Candle, ...], *, gap_context: bool = False,
             parameters: tuple[tuple[str, int | str], ...] | None = None, **kwargs) -> StructureEvent:
        if parameters is None:
            if event_type not in parameter_cache:
                parameter_cache[event_type] = _event_parameters(event_type, tolerance)
            parameters = parameter_cache[event_type]
        event = _make_event(identity=identity, timeframe=timeframe, event_type=event_type,
                            event_at=event_at, knowable_at=knowable_at, source_candles=source_candles,
                            parameters=parameters,
                            gap_context=gap_context, **kwargs)
        if retain:
            events.append(event)
        if on_event is not None:
            on_event(event)
        return event

    def change_gap_state(gap: _Gap, candle: MT5Candle, state: str, gap_context: bool) -> None:
        assert candle is not None
        event_type = "FVG_PARTIAL_MITIGATION" if state == "PARTIALLY_MITIGATED" else "FVG_FULL_MITIGATION"
        emit(event_type, candle.opened_at + step, candle.opened_at + step,
             (*gap.candles, candle), price_low=gap.low, price_high=gap.high,
             state=state, direction=gap.direction, gap_context=gap_context,
             reference_event_ids=(gap.formation.event_id,))
        gap.status = state
        gap.last_updated_at = candle.opened_at + step

    def emit_premium_snapshot(candle: MT5Candle, closed: datetime, gap_context: bool) -> None:
        pairs = [(high, low) for high in high_history for low in low_history
                 if high.event.event_at != low.event.event_at]
        if not pairs:
            return
        high_swing, low_swing = max(pairs, key=lambda pair: (
            max(pair[0].event.knowable_at, pair[1].event.knowable_at),
            min(pair[0].event.knowable_at, pair[1].event.knowable_at),
            pair[0].event.event_id, pair[1].event.event_id))
        range_high, range_low = max(high_swing.price, low_swing.price), min(high_swing.price, low_swing.price)
        with localcontext() as context:
            context.prec = PRECISION
            midpoint = (range_high + range_low) / Decimal(2)
            position = ((candle.close - range_low) / (range_high - range_low) * 100
                        if range_high != range_low else None)
        label = ("PREMIUM" if candle.close > midpoint else
                 "DISCOUNT" if candle.close < midpoint else "MIDPOINT")
        emit("PREMIUM_DISCOUNT", closed, closed,
             (candle,), gap_context=gap_context,
             price_level=midpoint, price_low=range_low, price_high=range_high,
             price_value=candle.close, position_percent=position, label=label,
             quality_status="ZERO_WIDTH_RANGE" if range_high == range_low else "RULE_CONFIRMED",
             reference_event_ids=(high_swing.event.event_id, low_swing.event.event_id))

    def equal_match(price: Decimal, exact: dict[Decimal, _Swing],
                    buckets: dict[int, _EqualBucket], *, add: _Swing | None = None) -> _Swing | None:
        if tolerance == 0:
            match = exact.get(price)
            if add is not None:
                exact[price] = add
            return match
        bucket_id = int(price // tolerance)
        candidates = []
        same = buckets.get(bucket_id)
        lower = buckets.get(bucket_id - 1)
        upper = buckets.get(bucket_id + 1)
        if same is not None:
            candidates.append(same.latest)
        if lower is not None:
            candidates.append(lower.maximum)
        if upper is not None:
            candidates.append(upper.minimum)
        matches = [candidate for candidate in candidates if abs(candidate.price - price) <= tolerance]
        match = None
        if matches:
            nearest = min(abs(candidate.price - price) for candidate in matches)
            match = max((candidate for candidate in matches if abs(candidate.price - price) == nearest),
                        key=lambda candidate: (candidate.event.knowable_at, candidate.event.event_id))
        if add is not None:
            if same is None:
                buckets[bucket_id] = _EqualBucket(add, add, add)
            else:
                if add.price < same.minimum.price:
                    same.minimum = add
                if add.price > same.maximum.price:
                    same.maximum = add
                same.latest = add
        return match

    for item in series.candles:
        if (item.eligibility != CandleEligibility.ELIGIBLE_CLOSED or item.nominal_close_at is None
                or item.nominal_close_at > run.report.analysis_cutoff):
            continue
        candle = item.source
        opened = candle.opened_at
        closed = item.nominal_close_at
        if previous_open is not None and opened <= previous_open:
            raise ValueError(f"{timeframe} eligible candles must be strictly chronological")
        gap_before = previous_open is not None and opened - previous_open != step
        gap_count += int(gap_before)

        # Process only levels and gaps known before this candle closes.
        while buy_levels and buy_levels[0][0] < candle.high:
            level, _, swing = heapq.heappop(buy_levels)
            if candle.close < level:
                emit("BUY_SIDE_SWEEP", closed, closed, (swing.candle, candle),
                     gap_context=gap_before, price_level=level, direction="bearish",
                     liquidity_side="BUY_SIDE", state="SWEPT",
                     reference_event_ids=(swing.event.event_id,))
        while sell_levels and -sell_levels[0][0] > candle.low:
            negative_level, _, swing = heapq.heappop(sell_levels)
            level = -negative_level
            if candle.close > level:
                emit("SELL_SIDE_SWEEP", closed, closed, (swing.candle, candle),
                     gap_context=gap_before, price_level=level, direction="bullish",
                     liquidity_side="SELL_SIDE", state="SWEPT",
                     reference_event_ids=(swing.event.event_id,))

        break_swing = None
        direction = None
        # A swing level may break once; a later confirmed swing is a new reference.
        if last_close is not None and latest_high is not None and latest_high.event.event_id not in broken_levels:
            if last_close <= latest_high.price < candle.close:
                break_swing, direction = latest_high, "BULLISH"
        if last_close is not None and latest_low is not None and latest_low.event.event_id not in broken_levels:
            if candle.close < latest_low.price <= last_close:
                if break_swing is not None:
                    raise ValueError("one close cannot break both opposing levels")
                break_swing, direction = latest_low, "BEARISH"
        if break_swing is not None:
            old_bias = bias
            event_type = "BOS" if old_bias in {"NEUTRAL", direction} else "CHOCH"
            bias = direction
            emit(event_type, closed, closed, (break_swing.candle, candle),
                 gap_context=gap_before, price_level=break_swing.price,
                 direction=direction.lower(), state=bias,
                 label="FIRST_BREAK" if old_bias == "NEUTRAL" else None,
                 reference_event_ids=(break_swing.event.event_id,))
            broken_levels.add(break_swing.event.event_id)

        # Existing FVGs transition only at this later candle's close.
        while bull_partial and -bull_partial[0][0] >= candle.low:
            _, _, gap = heapq.heappop(bull_partial)
            change_gap_state(gap, candle, "FULLY_MITIGATED", gap_before)
        while bull_unfilled and -bull_unfilled[0][0] >= candle.low:
            _, sequence, gap = heapq.heappop(bull_unfilled)
            if candle.low <= gap.low:
                change_gap_state(gap, candle, "FULLY_MITIGATED", gap_before)
            else:
                change_gap_state(gap, candle, "PARTIALLY_MITIGATED", gap_before)
                heapq.heappush(bull_partial, (-gap.low, sequence, gap))
        while bear_partial and bear_partial[0][0] <= candle.high:
            _, _, gap = heapq.heappop(bear_partial)
            change_gap_state(gap, candle, "FULLY_MITIGATED", gap_before)
        while bear_unfilled and bear_unfilled[0][0] <= candle.high:
            _, sequence, gap = heapq.heappop(bear_unfilled)
            if candle.high >= gap.high:
                change_gap_state(gap, candle, "FULLY_MITIGATED", gap_before)
            else:
                change_gap_state(gap, candle, "PARTIALLY_MITIGATED", gap_before)
                heapq.heappush(bear_partial, (gap.high, sequence, gap))

        # FVGs require three observed, nominally consecutive candles.
        if len(prior_bars) == 2:
            first, second = prior_bars
            if second.opened_at - first.opened_at != step or opened - second.opened_at != step:
                fvg_gap_rejections += 1
            elif first.high < candle.low:
                formation = emit("FVG_FORMED", closed, closed, (first, second, candle),
                                 price_low=first.high, price_high=candle.low,
                                 state="UNFILLED", direction="BULLISH")
                gap = _Gap(_EventHandle.from_event(formation), "BULLISH", first.high, candle.low, (first, second, candle),
                           last_updated_at=closed)
                if retain:
                    gap_states.append(gap)
                level_sequence += 1
                heapq.heappush(bull_unfilled, (-gap.high, level_sequence, gap))
            elif first.low > candle.high:
                formation = emit("FVG_FORMED", closed, closed, (first, second, candle),
                                 price_low=candle.high, price_high=first.low,
                                 state="UNFILLED", direction="BEARISH")
                gap = _Gap(_EventHandle.from_event(formation), "BEARISH", candle.high, first.low, (first, second, candle),
                           last_updated_at=closed)
                if retain:
                    gap_states.append(gap)
                level_sequence += 1
                heapq.heappush(bear_unfilled, (gap.low, level_sequence, gap))
        prior_bars.append(candle)

        # A pivot at i-2 becomes usable only now, after both right bars close.
        window.append((candle, gap_before))
        if len(window) == SWING_LEFT_BARS + SWING_RIGHT_BARS + 1:
            bars = tuple(entry[0] for entry in window)
            consecutive = all(right.opened_at - left.opened_at == step
                              for left, right in zip(bars, bars[1:]))
            if not consecutive:
                swing_gap_rejections += 1
            else:
                pivot = bars[SWING_LEFT_BARS]
                others = bars[:SWING_LEFT_BARS] + bars[SWING_LEFT_BARS + 1:]
                high_max = max(other.high for other in others)
                low_min = min(other.low for other in others)
                if pivot.high > high_max:
                    prev = latest_high
                    equal_prev = equal_match(pivot.high, exact_highs, high_buckets)
                    classification = "INITIAL" if prev is None else (
                        "EQH" if abs(pivot.high - prev.price) <= tolerance else
                        "HH" if pivot.high > prev.price else "LH")
                    high_event = emit("SWING_HIGH", pivot.opened_at + step, closed,
                        tuple(bars), quality_status="STRICT_UNIQUE_EXTREMUM", price_level=pivot.high,
                        label=classification, liquidity_side="BUY_SIDE", state="POTENTIAL",
                        reference_event_ids=(prev.event.event_id,) if prev else ())
                    swing = _Swing(_EventHandle.from_event(high_event), pivot, pivot.high)
                    latest_high = swing
                    high_history.append(swing)
                    equal_match(pivot.high, exact_highs, high_buckets, add=swing)
                    level_sequence += 1
                    heapq.heappush(buy_levels, (pivot.high, level_sequence, swing))
                    if equal_prev is not None:
                        emit("EQUAL_HIGHS", pivot.opened_at + step, closed,
                             (equal_prev.candle, pivot, candle), price_level=pivot.high,
                             reference_event_ids=(equal_prev.event.event_id, high_event.event_id))
                elif pivot.high == high_max:
                    tied_highs += 1
                if pivot.low < low_min:
                    prev = latest_low
                    equal_prev = equal_match(pivot.low, exact_lows, low_buckets)
                    classification = "INITIAL" if prev is None else (
                        "EQL" if abs(pivot.low - prev.price) <= tolerance else
                        "HL" if pivot.low > prev.price else "LL")
                    low_event = emit("SWING_LOW", pivot.opened_at + step, closed,
                        tuple(bars), quality_status="STRICT_UNIQUE_EXTREMUM", price_level=pivot.low,
                        label=classification, liquidity_side="SELL_SIDE", state="POTENTIAL",
                        reference_event_ids=(prev.event.event_id,) if prev else ())
                    swing = _Swing(_EventHandle.from_event(low_event), pivot, pivot.low)
                    latest_low = swing
                    low_history.append(swing)
                    equal_match(pivot.low, exact_lows, low_buckets, add=swing)
                    level_sequence += 1
                    heapq.heappush(sell_levels, (-pivot.low, level_sequence, swing))
                    if equal_prev is not None:
                        emit("EQUAL_LOWS", pivot.opened_at + step, closed,
                             (equal_prev.candle, pivot, candle), price_level=pivot.low,
                             reference_event_ids=(equal_prev.event.event_id, low_event.event_id))
                elif pivot.low == low_min:
                    tied_lows += 1

        last_close = candle.close
        previous_open = opened
        emit_premium_snapshot(candle, closed, gap_before)
        candle_index += 1

    diagnostics = StructureDiagnostics(candle_index, gap_count, swing_gap_rejections,
                                       tied_highs, tied_lows, fvg_gap_rejections)
    zones = tuple(FairValueGapState(gap.formation.event_id, timeframe, gap.direction, gap.low, gap.high,
                                    gap.formation.event_at, gap.formation.knowable_at, gap.status,
                                    gap.last_updated_at or gap.formation.event_at, gap.candles)
                  for gap in gap_states)
    return TimeframeMarketStructure(timeframe, series.series_id, series.source_file, series.source_sha256,
                                    bias, diagnostics, tuple(events), zones)


def analyze_market_structure(run: HistoricalRun, *,
                             equal_level_tolerance: Decimal = Decimal("0")) -> HistoricalStructureRun:
    """Analyze eligible closed H1/M15 bars; Daily stays excluded by its unknown boundary."""
    if not isinstance(equal_level_tolerance, Decimal) or not equal_level_tolerance.is_finite() \
            or equal_level_tolerance < 0:
        raise ValueError("equal_level_tolerance must be a finite nonnegative Decimal")
    timeframes = tuple(_analyze_timeframe(run, timeframe, equal_level_tolerance)
                       for timeframe in ("H1", "M15"))
    return HistoricalStructureRun(run.report.run_id, run.report.analysis_cutoff, ALGORITHM_VERSION,
                                  equal_level_tolerance, timeframes, (("Daily", "UNKNOWN_BOUNDARY"),))


def stream_market_structure(run: HistoricalRun, timeframe: str, *,
                            on_event: Callable[[StructureEvent], None],
                            equal_level_tolerance: Decimal = Decimal("0")) -> TimeframeMarketStructure:
    """Run the shared structure algorithm without retaining its full event/FVG history."""
    if timeframe not in {"H1", "M15"}:
        raise ValueError("Only H1 and M15 are analysis-eligible timeframes")
    if not isinstance(equal_level_tolerance, Decimal) or not equal_level_tolerance.is_finite() \
            or equal_level_tolerance < 0:
        raise ValueError("equal_level_tolerance must be a finite nonnegative Decimal")
    return _analyze_timeframe(run, timeframe, equal_level_tolerance, on_event, retain=False)
