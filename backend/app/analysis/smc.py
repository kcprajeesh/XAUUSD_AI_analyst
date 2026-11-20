"""Objective three-candle gaps, rule-bound order blocks and same-leg range context."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Sequence
from app.ai.evidence import EvidenceCandle
from app.analysis.market_structure import StructureEvent, Swing

@dataclass(frozen=True)
class Zone:
    kind: str
    low: Decimal
    high: Decimal
    source_refs: tuple[str, ...]
    formed_at: str
    status: str
    mitigation: str


def fair_value_gaps(candles: Sequence[EvidenceCandle]) -> tuple[Zone, ...]:
    zones = []
    for i in range(2, len(candles)):
        a, b, c = candles[i-2:i+1]
        if a.high < c.low:
            kind, low, high = "bullish_fvg", a.high, c.low
        elif a.low > c.high:
            kind, low, high = "bearish_fvg", c.high, a.low
        else:
            continue
        touched = False
        fully = False
        mitigation_refs = []
        for later in candles[i+1:]:
            if later.low <= high and later.high >= low:
                touched = True
                mitigation_refs.append(later.candle_id)
            if (kind == "bullish_fvg" and later.low <= low) or (kind == "bearish_fvg" and later.high >= high):
                fully = True
                if later.candle_id not in mitigation_refs:
                    mitigation_refs.append(later.candle_id)
                break
        zones.append(Zone(kind, low, high, (a.candle_id, b.candle_id, c.candle_id, *mitigation_refs), (c.closed_at or c.opened_at).isoformat(),
            "mitigated" if fully else "active", "full" if fully else "partial" if touched else "unfilled"))
    return tuple(zones)


def order_blocks(candles: Sequence[EvidenceCandle], events: Sequence[StructureEvent], atr_values: dict[str, Decimal],
                 displacement_atr: Decimal = Decimal("1.5")) -> tuple[Zone, ...]:
    """Last opposing candle before a close break, confirmed only if break candle range >= ATR multiple."""
    if displacement_atr <= 0:
        raise ValueError("displacement_atr must be positive")
    index = {c.candle_id: i for i, c in enumerate(candles)}
    zones = []
    for event in events:
        if event.kind not in ("BOS", "CHoCH") or len(event.candle_refs) < 2:
            continue
        break_candle = candles[index[event.candle_refs[-1]]]
        atr_value = atr_values.get(break_candle.candle_id)
        tr = break_candle.high - break_candle.low
        if atr_value is None or tr < displacement_atr * atr_value:
            continue
        level_index = index[event.candle_refs[0]]
        candidates = [c for c in candles[level_index+1:event.confirmation_index]
                      if (c.close < c.open if event.direction == "bullish" else c.close > c.open)]
        if not candidates:
            continue
        source = candidates[-1]
        low, high = source.low, source.high
        later = candles[event.confirmation_index+1:]
        invalidation_refs = [c.candle_id for c in later if c.close < low] if event.direction == "bullish" else [c.candle_id for c in later if c.close > high]
        mitigation_refs = [c.candle_id for c in later if c.low <= high and c.high >= low]
        invalidated = bool(invalidation_refs)
        mitigated = bool(mitigation_refs)
        refs = tuple(dict.fromkeys((source.candle_id, *event.candle_refs, *mitigation_refs, *invalidation_refs)))
        zones.append(Zone("bullish_order_block" if event.direction == "bullish" else "bearish_order_block",
            low, high, refs, break_candle.closed_at.isoformat(),
            "confirmed", "invalidated" if invalidated else "mitigated" if mitigated else "unmitigated"))
    return tuple(zones)


def premium_discount(points: Sequence[Swing]) -> tuple[Decimal, Decimal, Decimal, tuple[str, ...]] | None:
    """Latest consecutive opposite confirmed swings define one range; midpoint is equilibrium."""
    ordered = sorted(points, key=lambda item: item.index)
    pair = next(((a, b) for a, b in reversed(tuple(zip(ordered, ordered[1:]))) if a.high != b.high and a.index != b.index), None)
    if pair is None:
        return None
    a, b = pair
    low = min(a.candle.low if not a.high else a.candle.high, b.candle.low if not b.high else b.candle.high)
    high = max(a.candle.low if not a.high else a.candle.high, b.candle.low if not b.high else b.candle.high)
    refs = tuple(dict.fromkeys((a.candle.candle_id, *a.source_refs, b.candle.candle_id, *b.source_refs)))
    with localcontext() as context:
        context.prec = 34
        equilibrium = (low + high) / Decimal(2)
    return low, high, equilibrium, refs
