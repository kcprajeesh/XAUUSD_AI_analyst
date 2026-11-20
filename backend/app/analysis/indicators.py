"""Exact-decimal deterministic EMA, Wilder RSI and ATR calculations."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Sequence

from app.ai.evidence import EvidenceCandle, VolumeType

PRECISION = 34
VWAP_VOLUME_TYPES = frozenset({VolumeType.EXCHANGE_TRADED, VolumeType.CONTRACT})


@dataclass(frozen=True)
class IndicatorPoint:
    name: str
    period: int
    value: Decimal
    calculated_at: datetime
    candle_refs: tuple[str, ...]
    method: str


def ema(candles: Sequence[EvidenceCandle], period: int, *, latest_only: bool = False) -> tuple[IndicatorPoint, ...]:
    """SMA-seeded EMA; first output at period-th close, then alpha=2/(period+1)."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be positive")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        alpha = Decimal(2) / Decimal(period + 1)
        result = []
        value = None
        for index, candle in enumerate(candles):
            if index == period - 1:
                value = sum((item.close for item in candles[:period]), Decimal(0)) / Decimal(period)
            elif index >= period and value is not None:
                value = alpha * candle.close + (Decimal(1) - alpha) * value
            if value is not None and (not latest_only or index == len(candles) - 1):
                result.append(IndicatorPoint(f"EMA{period}", period, +value, candle.closed_at or candle.opened_at,
                    tuple(item.candle_id for item in candles[:index + 1]), "ema_sma_seed_alpha_2_over_n_plus_1_v1"))
        return tuple(result)


def rsi(candles: Sequence[EvidenceCandle], period: int = 14, *, latest_only: bool = False) -> tuple[IndicatorPoint, ...]:
    """Wilder RSI; first value needs period price changes; flat series yields 50."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be positive")
    if len(candles) <= period:
        return ()
    with localcontext() as ctx:
        ctx.prec = PRECISION
        changes = [candles[i].close - candles[i - 1].close for i in range(1, len(candles))]
        gains = [max(change, Decimal(0)) for change in changes]
        losses = [max(-change, Decimal(0)) for change in changes]
        avg_gain = sum(gains[:period], Decimal(0)) / period
        avg_loss = sum(losses[:period], Decimal(0)) / period
        result = []
        for end in range(period, len(changes) + 1):
            if end > period:
                avg_gain = (avg_gain * (period - 1) + gains[end - 1]) / period
                avg_loss = (avg_loss * (period - 1) + losses[end - 1]) / period
            value = (Decimal(50) if avg_gain == avg_loss == 0 else Decimal(100) if avg_loss == 0
                     else Decimal(0) if avg_gain == 0 else Decimal(100) - Decimal(100) / (1 + avg_gain / avg_loss))
            if not latest_only or end == len(changes):
                result.append(IndicatorPoint("RSI", period, +value, candles[end].closed_at or candles[end].opened_at,
                tuple(item.candle_id for item in candles[:end + 1]), "rsi_wilder_sma_seed_zero_loss_100_flat_50_v1"))
        return tuple(result)


def atr(candles: Sequence[EvidenceCandle], period: int = 14, *, latest_only: bool = False) -> tuple[IndicatorPoint, ...]:
    """Wilder ATR; first TR is high-low, later TR includes prior-close gap distance."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be positive")
    if len(candles) < period:
        return ()
    with localcontext() as ctx:
        ctx.prec = PRECISION
        trs = []
        for index, candle in enumerate(candles):
            tr = candle.high - candle.low
            if index:
                previous = candles[index - 1].close
                tr = max(tr, abs(candle.high - previous), abs(candle.low - previous))
            trs.append(tr)
        value = sum(trs[:period], Decimal(0)) / period
        result = []
        for end in range(period, len(candles) + 1):
            if end > period:
                value = (value * (period - 1) + trs[end - 1]) / period
            if not latest_only or end == len(candles):
                result.append(IndicatorPoint("ATR", period, +value, candles[end - 1].closed_at or candles[end - 1].opened_at,
                tuple(item.candle_id for item in candles[:end]), "atr_true_range_wilder_sma_seed_v1"))
        return tuple(result)


def atr_series(candles: Sequence[EvidenceCandle], period: int = 14) -> dict[str, Decimal]:
    """Warm-up-aware ATR values keyed by candle ID for downstream deterministic rules."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be positive")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        out: dict[str, Decimal] = {}
        value = None
        for i, candle in enumerate(candles):
            tr = candle.high - candle.low
            if i:
                previous = candles[i - 1].close
                tr = max(tr, abs(candle.high - previous), abs(candle.low - previous))
            if i == period - 1:
                value = sum((max(c.high-c.low, abs(c.high-candles[j-1].close), abs(c.low-candles[j-1].close))
                             if j else c.high-c.low for j, c in enumerate(candles[:period])), Decimal(0)) / period
            elif i >= period and value is not None:
                value = (value * (period - 1) + tr) / period
            if value is not None:
                out[candle.candle_id] = +value
        return out


def vwap(candles: Sequence[EvidenceCandle]) -> IndicatorPoint | None:
    """HLC3 VWAP over this retrieval window; tick counts and mixed/missing volume are unusable."""
    if not candles or any(c.volume_value is None or c.volume_type not in VWAP_VOLUME_TYPES for c in candles):
        return None
    total = sum((c.volume_value for c in candles), Decimal(0))
    if total <= 0:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        weighted = sum(((c.high + c.low + c.close) / Decimal(3) * c.volume_value for c in candles), Decimal(0))
        return IndicatorPoint("VWAP", len(candles), +(weighted / total),
            candles[-1].closed_at or candles[-1].opened_at, tuple(c.candle_id for c in candles),
            "vwap_hlc3_retrieval_window_exchange_or_contract_volume_v1")


def momentum(candles: Sequence[EvidenceCandle], period: int = 10) -> IndicatorPoint | None:
    """Simple close rate-of-change over N intervals, expressed as percent."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be a positive integer")
    if len(candles) <= period:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        start, end = candles[-period - 1], candles[-1]
        value = (end.close - start.close) / start.close * Decimal(100)
        return IndicatorPoint("Momentum", period, +value, end.closed_at or end.opened_at,
            tuple(c.candle_id for c in candles[-period - 1:]), "close_rate_of_change_percent_v1")
