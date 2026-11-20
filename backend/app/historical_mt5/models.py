"""Immutable Phase 1 run and provenance models for imported MT5 history."""
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import json

from app.data.mt5_import import ImportIssue, MT5Candle


class CandleEligibility(StrEnum):
    ELIGIBLE_CLOSED = "ELIGIBLE_CLOSED"
    NOT_CLOSED_AT_CUTOFF = "NOT_CLOSED_AT_CUTOFF"
    UNKNOWN_BOUNDARY = "UNKNOWN_BOUNDARY"


@dataclass(frozen=True)
class HistoricalCandle:
    source: MT5Candle
    eligibility: CandleEligibility
    nominal_close_at: datetime | None


@dataclass(frozen=True)
class HistoricalSeries:
    timeframe: str
    series_id: str
    source_file: str
    source_sha256: str
    timezone_policy: str
    candles: tuple[HistoricalCandle, ...]


@dataclass(frozen=True)
class SeriesRunReport:
    timeframe: str
    series_id: str
    source_file: str
    source_sha256: str
    source_rows: int
    accepted_candles: int
    eligible_closed_candles: int
    not_closed_at_cutoff: int
    unknown_boundary_candles: int
    identical_duplicates_collapsed: int
    conflicting_duplicate_rows: int
    issue_counts: tuple[tuple[str, int], ...]
    first_broker_timestamp: str | None
    last_broker_timestamp: str | None
    first_utc_timestamp: datetime | None
    last_utc_timestamp: datetime | None


@dataclass(frozen=True)
class HistoricalRunReport:
    run_id: str
    analysis_cutoff: datetime
    provider: str
    broker: str
    symbol: str
    source_classification: str
    configured_timezone: str
    timezone_policy: str
    series: tuple[SeriesRunReport, ...]

    def to_json(self) -> str:
        """Stable summary serialization; candles remain available separately in memory."""
        return json.dumps(asdict(self), default=lambda value: value.isoformat(),
                          sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class HistoricalRun:
    report: HistoricalRunReport
    series: tuple[HistoricalSeries, ...]
    importer_issues: tuple[ImportIssue, ...]

    def series_for(self, timeframe: str) -> HistoricalSeries:
        matches = tuple(item for item in self.series if item.timeframe == timeframe)
        if len(matches) != 1:
            raise KeyError(timeframe)
        return matches[0]
