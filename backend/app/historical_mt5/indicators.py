"""Causal Decimal indicators for eligible Alpari MT5 historical candles.

EMA seeds with the SMA of its first n observed closes, then uses alpha=2/(n+1).
RSI seeds with the first 14 close changes and applies Wilder smoothing; flat is
50 and zero average loss is 100. ATR seeds with the first 14 true ranges (the
first is high-low; later ranges include the previous observed close), then uses
Wilder smoothing. MACD uses SMA-seeded EMA12 and EMA26; its signal is an
SMA-seeded EMA9 over MACD values, so signal and histogram first appear at the
34th observed candle. Momentum is ten-observed-candle close ROC in percent.
Gaps remain gaps: no bars are synthesized, and indicators advance over source
candles while marking any output candle that follows a time gap.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Callable

from app.data.mt5_import import INTERVALS
from app.historical_mt5.models import CandleEligibility, HistoricalRun

PRECISION = 34
ALGORITHM_VERSION = "mt5-decimal-indicators-v1"
ANALYZED_TIMEFRAMES = ("H1", "M15")


class IndicatorStatus(StrEnum):
    READY = "READY"
    WARMING_UP = "WARMING_UP"
    NO_ELIGIBLE_CANDLES = "NO_ELIGIBLE_CANDLES"
    NO_ELIGIBLE_CANDLE_AS_OF = "NO_ELIGIBLE_CANDLE_AS_OF"
    MISSING_TIMEFRAME = "MISSING_TIMEFRAME"
    ALIGNED = "ALIGNED"


@dataclass(frozen=True, slots=True)
class CandleReference:
    series_id: str
    source_file: str
    source_sha256: str
    source_row: int
    broker_timestamp: str
    utc_timestamp: datetime
    source_timezone: str
    timezone_policy: str


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    provider: str
    broker: str
    symbol: str
    timeframe: str
    indicator: str
    parameters: tuple[tuple[str, int | str], ...]
    algorithm_version: str = ALGORITHM_VERSION


@dataclass(frozen=True, slots=True)
class IndicatorObservation:
    spec: IndicatorSpec
    opened_at: datetime
    closed_at: datetime
    source_candle: CandleReference
    value: Decimal
    status: IndicatorStatus
    eligibility: CandleEligibility
    gap_before: bool

    @property
    def provider(self) -> str:
        return self.spec.provider

    @property
    def broker(self) -> str:
        return self.spec.broker

    @property
    def symbol(self) -> str:
        return self.spec.symbol

    @property
    def timeframe(self) -> str:
        return self.spec.timeframe

    @property
    def indicator(self) -> str:
        return self.spec.indicator

    @property
    def parameters(self) -> tuple[tuple[str, int | str], ...]:
        return self.spec.parameters

    @property
    def algorithm_version(self) -> str:
        return self.spec.algorithm_version


@dataclass(frozen=True, slots=True)
class IndicatorTrack:
    spec: IndicatorSpec
    warmup_bars_required: int
    status: IndicatorStatus
    eligible_candle_count: int
    observations: tuple[IndicatorObservation, ...]


@dataclass(frozen=True, slots=True)
class TimeframeIndicators:
    timeframe: str
    series_id: str
    source_file: str
    source_sha256: str
    eligible_candle_count: int
    gap_count: int
    eligible_candle_closes: tuple[datetime, ...]
    tracks: tuple[IndicatorTrack, ...]


@dataclass(frozen=True, slots=True)
class IndicatorRun:
    source_run_id: str
    analysis_cutoff: datetime
    timeframes: tuple[TimeframeIndicators, ...]
    excluded_timeframes: tuple[tuple[str, str], ...]

    def timeframe(self, value: str) -> TimeframeIndicators:
        for item in self.timeframes:
            if item.timeframe == value:
                return item
        raise KeyError(value)


@dataclass(frozen=True, slots=True)
class AlignedValue:
    timeframe: str
    indicator: str
    evaluation_at: datetime
    status: IndicatorStatus
    observation: IndicatorObservation | None


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    evaluation_at: datetime
    status: str
    values: tuple[AlignedValue, ...]


def _spec(identity: tuple[str, str, str], timeframe: str, indicator: str,
          parameters: tuple[tuple[str, int | str], ...]) -> IndicatorSpec:
    return IndicatorSpec(*identity, timeframe, indicator, parameters)


def calculate_indicators(run: HistoricalRun) -> IndicatorRun:
    """Calculate all configured indicators in one streaming pass per H1/M15 series."""
    return _calculate_indicators(run)


def stream_indicators(run: HistoricalRun, timeframe: str, *,
                      on_observation: Callable[[IndicatorObservation], None],
                      on_candle: Callable[[str, datetime, int], None] | None = None) -> TimeframeIndicators:
    """Run the shared indicator algorithm without retaining its full observation history."""
    if timeframe not in ANALYZED_TIMEFRAMES:
        raise ValueError("Only H1 and M15 are analysis-eligible timeframes")
    return _calculate_indicators(run, (timeframe,), on_observation, on_candle,
                                 retain=False).timeframes[0]


def _calculate_indicators(run: HistoricalRun,
                          timeframes: tuple[str, ...] = ANALYZED_TIMEFRAMES,
                          on_observation: Callable[[IndicatorObservation], None] | None = None,
                          on_candle: Callable[[str, datetime, int], None] | None = None,
                          *, retain: bool = True) -> IndicatorRun:
    identities = (run.report.provider, run.report.broker, run.report.symbol)
    timeframe_results = []
    for timeframe in timeframes:
        series = run.series_for(timeframe)
        step = INTERVALS[timeframe]
        closes: list[datetime] = []
        gaps = 0
        eligible_count = 0

        definitions = (
            ("EMA", 20, 20), ("EMA", 50, 50), ("EMA", 200, 200),
            ("RSI", 14, 15), ("ATR", 14, 14),
            ("MACD_LINE", 26, 26), ("MACD_SIGNAL", 34, 34),
            ("MACD_HISTOGRAM", 34, 34), ("MOMENTUM_ROC", 10, 11),
        )
        specs = tuple(_spec(identities, timeframe, name,
                            (("period", period),) if name not in {"MACD_LINE", "MACD_SIGNAL", "MACD_HISTOGRAM"}
                            else (("fast", 12), ("slow", 26), ("signal", 9)))
                      for name, period, _ in definitions)
        outputs: list[list[IndicatorObservation]] = [[] for _ in specs]
        produced = [0 for _ in specs]

        def record(index: int, observation: IndicatorObservation) -> None:
            produced[index] += 1
            if retain:
                outputs[index].append(observation)
            if on_observation is not None:
                on_observation(observation)

        ema_periods = (20, 50, 200, 12, 26)
        ema_values: dict[int, Decimal | None] = {period: None for period in ema_periods}
        ema_seeds: dict[int, list[Decimal]] = {period: [] for period in ema_periods}
        previous_close: Decimal | None = None
        prior_close_for_true_range: Decimal | None = None
        gain_seed: list[Decimal] = []
        loss_seed: list[Decimal] = []
        avg_gain: Decimal | None = None
        avg_loss: Decimal | None = None
        tr_seed: list[Decimal] = []
        atr_value: Decimal | None = None
        macd_seed: list[Decimal] = []
        signal_value: Decimal | None = None
        close_window: list[Decimal] = []
        previous_open: datetime | None = None

        with localcontext() as ctx:
            ctx.prec = PRECISION
            alpha = {period: Decimal(2) / Decimal(period + 1) for period in ema_periods}
            for candle in series.candles:
                if (candle.eligibility != CandleEligibility.ELIGIBLE_CLOSED
                        or candle.nominal_close_at is None
                        or candle.nominal_close_at > run.report.analysis_cutoff):
                    continue
                source = candle.source
                opened = source.opened_at
                if previous_open is not None and opened <= previous_open:
                    raise ValueError(f"{timeframe} eligible candles must be in strictly increasing order")
                closed = candle.nominal_close_at
                assert closed is not None
                eligible_count += 1
                gap_before = previous_open is not None and opened - previous_open != step
                gaps += int(gap_before)
                previous_open = opened
                if retain:
                    closes.append(closed)
                reference = CandleReference(source.series_id, source.source_file, source.source_sha256,
                                            source.source_row, source.source_timestamp, opened,
                                            source.source_timezone, source.timezone_policy)
                close = source.close
                prior_close_for_true_range = previous_close
                for period in ema_periods:
                    value = ema_values[period]
                    if value is None:
                        seed = ema_seeds[period]
                        seed.append(close)
                        if len(seed) == period:
                            value = sum(seed, Decimal(0)) / period
                            ema_values[period] = value
                    else:
                        value = alpha[period] * close + (Decimal(1) - alpha[period]) * value
                        ema_values[period] = value
                    if period in (20, 50, 200) and value is not None:
                        idx = {20: 0, 50: 1, 200: 2}[period]
                        record(idx, IndicatorObservation(specs[idx], opened, closed, reference,
                            +value, IndicatorStatus.READY, candle.eligibility, gap_before))

                if previous_close is not None:
                    change = close - previous_close
                    gain = max(change, Decimal(0))
                    loss = max(-change, Decimal(0))
                    if avg_gain is None:
                        gain_seed.append(gain)
                        loss_seed.append(loss)
                        if len(gain_seed) == 14:
                            avg_gain = sum(gain_seed, Decimal(0)) / 14
                            avg_loss = sum(loss_seed, Decimal(0)) / 14
                    else:
                        assert avg_loss is not None
                        avg_gain = (avg_gain * 13 + gain) / 14
                        avg_loss = (avg_loss * 13 + loss) / 14
                    if avg_gain is not None and avg_loss is not None:
                        rsi_value = (Decimal(50) if avg_gain == avg_loss == 0 else
                                     Decimal(100) if avg_loss == 0 else
                                     Decimal(100) - Decimal(100) / (1 + avg_gain / avg_loss))
                        record(3, IndicatorObservation(specs[3], opened, closed, reference,
                            +rsi_value, IndicatorStatus.READY, candle.eligibility, gap_before))
                previous_close = close

                tr = source.high - source.low
                if prior_close_for_true_range is not None:
                    tr = max(tr, abs(source.high - prior_close_for_true_range),
                             abs(source.low - prior_close_for_true_range))
                if atr_value is None:
                    tr_seed.append(tr)
                    if len(tr_seed) == 14:
                        atr_value = sum(tr_seed, Decimal(0)) / 14
                else:
                    atr_value = (atr_value * 13 + tr) / 14
                if atr_value is not None:
                    record(4, IndicatorObservation(specs[4], opened, closed, reference,
                        +atr_value, IndicatorStatus.READY, candle.eligibility, gap_before))

                fast, slow = ema_values[12], ema_values[26]
                if fast is not None and slow is not None:
                    macd = fast - slow
                    macd_seed.append(macd)
                    if signal_value is None:
                        if len(macd_seed) == 9:
                            signal_value = sum(macd_seed, Decimal(0)) / 9
                    else:
                        signal_value = (Decimal(2) / 10) * macd + (Decimal(8) / 10) * signal_value
                    record(5, IndicatorObservation(specs[5], opened, closed, reference,
                        +macd, IndicatorStatus.READY, candle.eligibility, gap_before))
                    if signal_value is not None:
                        record(6, IndicatorObservation(specs[6], opened, closed, reference,
                            +signal_value, IndicatorStatus.READY, candle.eligibility, gap_before))
                        record(7, IndicatorObservation(specs[7], opened, closed, reference,
                            +(macd - signal_value), IndicatorStatus.READY, candle.eligibility, gap_before))

                close_window.append(close)
                if len(close_window) > 11:
                    close_window.pop(0)
                if len(close_window) == 11:
                    roc = (close_window[-1] - close_window[0]) / close_window[0] * Decimal(100)
                    record(8, IndicatorObservation(specs[8], opened, closed, reference,
                        +roc, IndicatorStatus.READY, candle.eligibility, gap_before))
                if on_candle is not None:
                    on_candle(timeframe, closed, eligible_count)

        tracks = tuple(IndicatorTrack(
            specs[index], required,
            IndicatorStatus.READY if produced[index] else
            IndicatorStatus.WARMING_UP if eligible_count else IndicatorStatus.NO_ELIGIBLE_CANDLES,
            eligible_count, tuple(outputs[index]))
            for index, (_, _, required) in enumerate(definitions))
        timeframe_results.append(TimeframeIndicators(
            timeframe, series.series_id, series.source_file, series.source_sha256,
            eligible_count, gaps, tuple(closes), tracks))
    return IndicatorRun(run.report.run_id, run.report.analysis_cutoff, tuple(timeframe_results),
                        (("Daily", "UNKNOWN_BOUNDARY"),))


def align_indicators(run: IndicatorRun, evaluation_at: datetime,
                     timeframes: tuple[str, ...] = ANALYZED_TIMEFRAMES,
                     *, eligible_candle_counts: dict[str, int] | None = None) -> AlignmentResult:
    """Return each timeframe's latest closed indicator values as of a UTC instant."""
    if evaluation_at.tzinfo is None or evaluation_at.utcoffset() is None:
        raise ValueError("evaluation_at must be timezone-aware")
    instant = evaluation_at.astimezone(UTC)
    if instant > run.analysis_cutoff:
        raise ValueError("evaluation_at must not exceed the historical analysis cutoff")
    if any(timeframe not in ANALYZED_TIMEFRAMES for timeframe in timeframes):
        raise ValueError("Only H1 and M15 are analysis-eligible timeframes")
    values: list[AlignedValue] = []
    for timeframe in timeframes:
        try:
            series = run.timeframe(timeframe)
        except KeyError:
            values.append(AlignedValue(timeframe, "*", instant, IndicatorStatus.MISSING_TIMEFRAME, None))
            continue
        candle_count_as_of = (eligible_candle_counts[timeframe] if eligible_candle_counts is not None
                              and timeframe in eligible_candle_counts else
                              bisect_right(series.eligible_candle_closes, instant))
        for track in series.tracks:
            index = bisect_right(track.observations, instant, key=lambda item: item.closed_at) - 1
            if index >= 0:
                observation = track.observations[index]
                status = IndicatorStatus.ALIGNED
            else:
                observation = None
                status = (IndicatorStatus.WARMING_UP if 0 < candle_count_as_of < track.warmup_bars_required
                          else IndicatorStatus.NO_ELIGIBLE_CANDLE_AS_OF)
            values.append(AlignedValue(timeframe, track.spec.indicator, instant, status, observation))
    complete = all(item.status == IndicatorStatus.ALIGNED for item in values)
    return AlignmentResult(instant, "COMPLETE" if complete else "PARTIAL", tuple(values))
