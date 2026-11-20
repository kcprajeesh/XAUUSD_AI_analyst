"""Phase 1 importer integration and cutoff eligibility; no signals or persistence."""
from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from app.data.mt5_import import (
    BROKER, HEADERS, INTERVALS, PROVIDER, SOURCE_CLASSIFICATION, SYMBOL,
    TIMEZONE_POLICY, SOURCE_OFFSET, import_mt5_files,
)
from app.historical_mt5.models import (
    CandleEligibility, HistoricalCandle, HistoricalRun, HistoricalRunReport,
    HistoricalSeries, SeriesRunReport,
)

RUN_VERSION = "historical-mt5-phase1-v1"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("analysis_cutoff must be timezone-aware")
    return value.astimezone(UTC)


def _check_series(timeframe: str, candles, digest: str) -> None:
    expected_id = f"{PROVIDER}:{SYMBOL}:{timeframe}:{TIMEZONE_POLICY}"
    previous = None
    seen = set()
    for candle in candles:
        if (candle.provider != PROVIDER or candle.broker != BROKER or candle.symbol != SYMBOL
                or candle.source_classification != SOURCE_CLASSIFICATION or candle.timeframe != timeframe
                or candle.series_id != expected_id or candle.source_sha256 != digest
                or candle.timezone_policy != TIMEZONE_POLICY):
            raise ValueError(f"{timeframe} importer output has mixed source identity or provenance")
        if candle.opened_at.tzinfo is None or candle.opened_at.utcoffset() != timedelta(0):
            raise ValueError(f"{timeframe} importer output timestamp is not UTC")
        if candle.opened_at in seen or previous is not None and candle.opened_at <= previous:
            raise ValueError(f"{timeframe} importer output is duplicated or out of order")
        seen.add(candle.opened_at)
        previous = candle.opened_at
        source_format = "%Y.%m.%d" if timeframe == "Daily" else "%Y.%m.%d %H:%M:%S"
        broker_time = datetime.strptime(candle.source_timestamp, source_format).replace(tzinfo=SOURCE_OFFSET)
        if broker_time.astimezone(UTC) != candle.opened_at:
            raise ValueError(f"{timeframe} source timestamp does not match fixed UTC+02:00 conversion")


def build_historical_run(files: dict[str, str | Path], *, analysis_cutoff: datetime) -> HistoricalRun:
    """Import three separate series in memory and mark cutoff eligibility."""
    if set(files) != set(HEADERS):
        raise ValueError("Provide exactly the Daily, H1 and M15 MT5 files")
    cutoff = _utc(analysis_cutoff)
    imported = import_mt5_files(files)
    imported_series = dict(imported.series)
    if set(imported_series) != set(HEADERS):
        raise ValueError("Importer did not return all expected timeframe series")
    hashes = dict(imported.report.files)
    names = {timeframe: Path(path).name for timeframe, path in files.items()}
    built = []
    reports = []
    for timeframe in HEADERS:
        source_candles = imported_series[timeframe]
        digest = hashes[names[timeframe]]
        _check_series(timeframe, source_candles, digest)
        eligibility = []
        for source in source_candles:
            if timeframe == "Daily":
                status, close_at = CandleEligibility.UNKNOWN_BOUNDARY, None
            else:
                close_at = source.opened_at + INTERVALS[timeframe]
                status = (CandleEligibility.ELIGIBLE_CLOSED if close_at <= cutoff
                          else CandleEligibility.NOT_CLOSED_AT_CUTOFF)
            eligibility.append(HistoricalCandle(source, status, close_at))
        series_id = f"{PROVIDER}:{SYMBOL}:{timeframe}:{TIMEZONE_POLICY}"
        built.append(HistoricalSeries(timeframe, series_id, names[timeframe], digest,
                                      TIMEZONE_POLICY, tuple(eligibility)))
        issues = tuple(issue for issue in imported.report.issues if issue.source_file == names[timeframe])
        issue_counts = Counter(issue.code for issue in issues)
        source_rows = max(0, sum(1 for line in Path(files[timeframe]).read_text(encoding="utf-8-sig").splitlines()
                                 if line.strip()) - 1)
        reports.append(SeriesRunReport(
            timeframe=timeframe, series_id=series_id, source_file=names[timeframe], source_sha256=digest,
            source_rows=source_rows, accepted_candles=len(eligibility),
            eligible_closed_candles=sum(c.eligibility == CandleEligibility.ELIGIBLE_CLOSED for c in eligibility),
            not_closed_at_cutoff=sum(c.eligibility == CandleEligibility.NOT_CLOSED_AT_CUTOFF for c in eligibility),
            unknown_boundary_candles=sum(c.eligibility == CandleEligibility.UNKNOWN_BOUNDARY for c in eligibility),
            identical_duplicates_collapsed=sum(issue.code == "duplicate_identical" for issue in issues),
            conflicting_duplicate_rows=sum(issue.code == "duplicate_conflict" for issue in issues),
            issue_counts=tuple(sorted(issue_counts.items())),
            first_broker_timestamp=eligibility[0].source.source_timestamp if eligibility else None,
            last_broker_timestamp=eligibility[-1].source.source_timestamp if eligibility else None,
            first_utc_timestamp=eligibility[0].source.opened_at if eligibility else None,
            last_utc_timestamp=eligibility[-1].source.opened_at if eligibility else None,
        ))
    identity = "|".join((RUN_VERSION, cutoff.isoformat(), TIMEZONE_POLICY,
                         *(f"{tf}:{hashes[names[tf]]}" for tf in HEADERS)))
    run_id = "mt5run-" + sha256(identity.encode()).hexdigest()[:24]
    report = HistoricalRunReport(run_id, cutoff, PROVIDER, BROKER, SYMBOL, SOURCE_CLASSIFICATION,
        "UTC+02:00 fixed", TIMEZONE_POLICY, tuple(reports))
    return HistoricalRun(report, tuple(built), imported.report.issues)
