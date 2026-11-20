import ast
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from app.data.mt5_import import HEADERS
from app.historical_mt5 import CandleEligibility, build_historical_run


def input_files(tmp_path):
    values = {
        "Daily": ["2026.11.18 2000 2010 1990 2005 12 0 25"],
        "H1": ["2026.11.18 01:00:00 2000 2010 1990 2005 12 0 25",
               "2026.11.18 02:00:00 2001 2011 1991 2006 13 0 26"],
        "M15": ["2026.11.18 01:00:00 2000 2010 1990 2005 12 0 25",
                "2026.11.18 01:15:00 2001 2011 1991 2006 13 0 26"],
    }
    result = {}
    for timeframe, rows in values.items():
        path = tmp_path / f"{timeframe}.csv"
        path.write_text("\t".join(f"<{field}>" for field in HEADERS[timeframe]) + "\n" +
                        "\n".join(rows) + "\n")
        result[timeframe] = path
    return result


def test_importer_integration_hash_timestamp_provenance_and_series_separation(tmp_path):
    files = input_files(tmp_path)
    run = build_historical_run(files, analysis_cutoff=datetime(2026, 11, 18, 0, tzinfo=UTC))
    assert tuple(series.timeframe for series in run.series) == ("Daily", "H1", "M15")
    assert len({series.series_id for series in run.series}) == 3
    h1 = run.series_for("H1").candles[0].source
    assert h1.source_timestamp == "2026.11.18 01:00:00"
    assert h1.opened_at == datetime(2026, 11, 17, 23, tzinfo=UTC)
    assert h1.timezone_policy == run.report.timezone_policy
    assert h1.source_timezone == "UTC+02:00 fixed"
    assert h1.source_sha256 == sha256(files["H1"].read_bytes()).hexdigest()
    assert h1.source_row == 2
    assert run.report.provider == "alpari_mt5"
    assert run.report.broker == "Alpari MT5 Demo"
    assert run.report.source_classification == "historical_broker_cfd"
    assert run.importer_issues == ()


def test_cutoff_includes_closed_bar_at_boundary_and_excludes_later_bar(tmp_path):
    run = build_historical_run(input_files(tmp_path),
                               analysis_cutoff=datetime(2026, 11, 18, 0, tzinfo=UTC))
    h1 = run.series_for("H1").candles
    assert h1[0].nominal_close_at == datetime(2026, 11, 18, 0, tzinfo=UTC)
    assert h1[0].eligibility == CandleEligibility.ELIGIBLE_CLOSED
    assert h1[1].eligibility == CandleEligibility.NOT_CLOSED_AT_CUTOFF
    assert run.report.series[1].eligible_closed_candles == 1
    assert run.report.series[1].not_closed_at_cutoff == 1


def test_cutoff_is_normalized_to_utc_and_must_be_aware(tmp_path):
    files = input_files(tmp_path)
    utc = build_historical_run(files, analysis_cutoff=datetime(2026, 11, 18, 0, tzinfo=UTC))
    offset = build_historical_run(files, analysis_cutoff=datetime(
        2026, 11, 18, 3, tzinfo=timezone(timedelta(hours=3))))
    assert utc.report.analysis_cutoff == offset.report.analysis_cutoff
    assert utc.report.run_id == offset.report.run_id
    with pytest.raises(ValueError, match="timezone-aware"):
        build_historical_run(files, analysis_cutoff=datetime(2026, 11, 19))


def test_daily_remains_inspectable_but_boundary_is_unknown(tmp_path):
    run = build_historical_run(input_files(tmp_path),
                               analysis_cutoff=datetime(2030, 1, 1, tzinfo=UTC))
    daily = run.series_for("Daily")
    assert len(daily.candles) == 1
    assert daily.candles[0].eligibility == CandleEligibility.UNKNOWN_BOUNDARY
    assert daily.candles[0].nominal_close_at is None
    report = next(item for item in run.report.series if item.timeframe == "Daily")
    assert report.unknown_boundary_candles == 1
    assert report.eligible_closed_candles == 0


def test_report_is_repeatable_for_same_inputs_and_cutoff(tmp_path):
    files = input_files(tmp_path)
    cutoff = datetime(2026, 11, 18, 0, tzinfo=UTC)
    first = build_historical_run(files, analysis_cutoff=cutoff)
    second = build_historical_run(files, analysis_cutoff=cutoff)
    assert first.report == second.report
    assert first.report.to_json() == second.report.to_json()
    assert first.report.run_id == second.report.run_id


def test_package_has_no_sifting_sqlite_or_api_dependencies():
    package = Path(__file__).parents[1] / "app" / "historical_mt5"
    forbidden = {"sqlite3", "fastapi", "app.main", "app.data.siftingio", "app.data.storage"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported = {node.module or ""}
            else:
                continue
            assert not any(name in forbidden or any(name.startswith(item + ".") for item in forbidden)
                           for name in imported), f"Forbidden dependency in {path.name}: {imported}"


def test_report_counts_source_rows_accepted_rows_and_import_issues(tmp_path):
    files = input_files(tmp_path)
    run = build_historical_run(files, analysis_cutoff=datetime(2026, 11, 18, 0, tzinfo=UTC))
    by_tf = {item.timeframe: item for item in run.report.series}
    assert (by_tf["Daily"].source_rows, by_tf["Daily"].accepted_candles) == (1, 1)
    assert (by_tf["H1"].source_rows, by_tf["H1"].accepted_candles) == (2, 2)
    assert (by_tf["M15"].source_rows, by_tf["M15"].accepted_candles) == (2, 2)
    assert all(not item.issue_counts for item in by_tf.values())
