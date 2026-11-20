"""Deterministic confirmed swings, close-based structure breaks and liquidity."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Sequence
from app.ai.evidence import EvidenceCandle

@dataclass(frozen=True)
class Swing:
    index: int
    candle: EvidenceCandle
    high: bool
    confirmation_index: int | None = None
    source_refs: tuple[str, ...] = ()

@dataclass(frozen=True)
class StructureEvent:
    kind: str
    direction: str
    level: Decimal
    candle_refs: tuple[str, ...]
    confirmation_index: int


def swings(candles: Sequence[EvidenceCandle], left: int = 2, right: int = 2) -> tuple[Swing, ...]:
    if type(left) is not int or type(right) is not int or left < 1 or right < 1:
        raise ValueError("left and right confirmation widths must be positive")
    output = []
    for i in range(left, len(candles) - right):
        window = candles[i-left:i+right+1]
        if all(candles[i].high > c.high for j, c in enumerate(window) if j != left):
            output.append(Swing(i, candles[i], True, i + right,
                                tuple(c.candle_id for c in window)))
        if all(candles[i].low < c.low for j, c in enumerate(window) if j != left):
            output.append(Swing(i, candles[i], False, i + right,
                                tuple(c.candle_id for c in window)))
    return tuple(output)


def structure_events(candles: Sequence[EvidenceCandle], swing_points: Sequence[Swing], right: int = 2) -> tuple[StructureEvent, ...]:
    """Breaks use candle close; swing becomes usable only from its right-confirmation index."""
    if type(right) is not int or right < 1:
        raise ValueError("right confirmation width must be a positive integer")
    events = []
    bias = None
    for i, candle in enumerate(candles):
        eligible = [s for s in swing_points if s.index + right <= i]
        highs = [s for s in eligible if s.high and s.index < i]
        lows = [s for s in eligible if not s.high and s.index < i]
        candidates = []
        if highs:
            level = max(highs, key=lambda s: s.index)
            if candle.close > level.candle.high and (i == 0 or candles[i-1].close <= level.candle.high):
                candidates.append(("bullish", level))
        if lows:
            level = max(lows, key=lambda s: s.index)
            if candle.close < level.candle.low and (i == 0 or candles[i-1].close >= level.candle.low):
                candidates.append(("bearish", level))
        for direction, level in candidates:
            kind = "BOS" if bias in (None, direction) else "CHoCH"
            refs = tuple(dict.fromkeys((level.candle.candle_id, *level.source_refs, candle.candle_id)))
            events.append(StructureEvent(kind, direction, level.candle.high if level.high else level.candle.low,
                refs, i))
            bias = direction
    return tuple(events)


def equal_levels(points: Sequence[Swing], tolerance: Decimal) -> tuple[tuple[str, Decimal, tuple[str, ...]], ...]:
    if not isinstance(tolerance, Decimal) or not tolerance.is_finite() or tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    highs = [p for p in points if p.high]
    lows = [p for p in points if not p.high]
    found = []
    for label, side in (("equal_highs", highs), ("equal_lows", lows)):
        for i, first in enumerate(side):
            for second in side[i+1:]:
                a = first.candle.high if first.high else first.candle.low
                b = second.candle.high if second.high else second.candle.low
                if abs(a-b) <= tolerance:
                    refs = tuple(dict.fromkeys((*first.source_refs, *second.source_refs)))
                    with localcontext() as context:
                        context.prec = 34
                        level = (a + b) / Decimal(2)
                    found.append((label, level, refs or (first.candle.candle_id, second.candle.candle_id)))
    return tuple(found)


def support_resistance(points: Sequence[Swing], tolerance: Decimal) -> tuple[tuple[str, Decimal, tuple[str, ...]], ...]:
    """Cluster confirmed swing lows/highs by absolute price tolerance, anchored to each cluster mean."""
    if not isinstance(tolerance, Decimal) or not tolerance.is_finite() or tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    found = []
    for high, label in ((False, "support"), (True, "resistance")):
        side = sorted((point for point in points if point.high == high),
                      key=lambda point: point.candle.high if high else point.candle.low)
        clusters: list[list[Swing]] = []
        with localcontext() as context:
            context.prec = 34
            for point in side:
                level = point.candle.high if high else point.candle.low
                if clusters:
                    prior = clusters[-1]
                    prior_mean = sum(((item.candle.high if high else item.candle.low) for item in prior), Decimal(0)) / len(prior)
                    if abs(level - prior_mean) <= tolerance:
                        prior.append(point)
                        continue
                clusters.append([point])
            for cluster in clusters:
                levels = [(point.candle.high if high else point.candle.low) for point in cluster]
                refs = tuple(dict.fromkeys(ref for point in cluster for ref in (point.source_refs or (point.candle.candle_id,))))
                found.append((label, sum(levels, Decimal(0)) / len(levels), refs))
    return tuple(found)


def sweeps(candles: Sequence[EvidenceCandle], points: Sequence[Swing], right: int = 2) -> tuple[StructureEvent, ...]:
    if type(right) is not int or right < 1:
        raise ValueError("right confirmation width must be a positive integer")
    result = []
    for i, candle in enumerate(candles):
        for point in points:
            if point.index + right > i:
                continue
            level = point.candle.high if point.high else point.candle.low
            swept = candle.high > level and candle.close < level if point.high else candle.low < level and candle.close > level
            if swept:
                refs = tuple(dict.fromkeys((point.candle.candle_id, *point.source_refs, candle.candle_id)))
                result.append(StructureEvent("LIQUIDITY_SWEEP", "bearish" if point.high else "bullish", level,
                    refs, i))
    return tuple(result)
