from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from app.data.mt5_import import HEADERS, import_mt5_files


def files(tmp_path, *, daily=None, h1=None, m15=None):
    values = {"Daily": daily or ["2026.11.18 2000.00 2010.00 1990.00 2005.00 12 3 25"],
              "H1": h1 or ["2026.11.18 01:00:00 2000.00 2010.00 1990.00 2005.00 12 3 25"],
              "M15": m15 or ["2026.11.18 01:15:00 2000.00 2010.00 1990.00 2005.00 12 3 25"]}
    result = {}
    for timeframe, rows in values.items():
        path = tmp_path / f"{timeframe}.csv"
        path.write_text("\t".join(HEADERS[timeframe]) + "\n" + "\n".join(rows) + "\n")
        result[timeframe] = path
    return result


def write_headers(source, *, bracketed=False, delimiter="\t"):
    for timeframe, path in source.items():
        columns = [f"<{name}>" if bracketed else name for name in HEADERS[timeframe]]
        rows = path.read_text().splitlines()[1:]
        path.write_text(delimiter.join(columns) + "\n" + "\n".join(rows) + "\n")


def candle(result, timeframe):
    return dict(result.series)[timeframe][0]


def test_parses_daily_h1_m15_and_preserves_source_and_provenance(tmp_path):
    source = files(tmp_path)
    result = import_mt5_files(source)
    daily, h1, m15 = (candle(result, tf) for tf in ("Daily", "H1", "M15"))
    assert daily.opened_at == datetime(2026, 11, 17, 22, tzinfo=UTC)
    assert h1.opened_at == datetime(2026, 11, 17, 23, tzinfo=UTC)
    assert m15.opened_at == datetime(2026, 11, 17, 23, 15, tzinfo=UTC)
    assert (h1.source_timestamp, h1.open) == ("2026.11.18 01:00:00", Decimal("2000.00"))
    assert (h1.tick_volume, h1.real_volume, h1.spread) == (12, 3, 25)
    assert h1.provider == "alpari_mt5" and h1.broker == "Alpari MT5 Demo"
    assert h1.source_classification == "historical_broker_cfd"
    assert h1.timezone_policy == "alpari-mt5-fixed-utc-plus-2-v1"
    assert h1.source_row == 2 and h1.source_file == source["H1"].name
    assert h1.source_sha256 == sha256(source["H1"].read_bytes()).hexdigest()
    assert result.report.rows_seen == 3 and result.report.candles_imported == 3
    assert len(result.series) == 3 and all(tf != "H4" for tf, _ in result.series)


def test_accepts_whitespace_separated_rows(tmp_path):
    source = files(tmp_path)
    source["H1"].write_text(" ".join(HEADERS["H1"]) + "\n2026.11.18 01:00:00 2000 2010 1990 2005 12 3 25\n")
    assert candle(import_mt5_files(source), "H1").close == Decimal("2005")


@pytest.mark.parametrize("bracketed,delimiter", [(True, "\t"), (True, " "), (False, "\t"), (False, " ")])
def test_accepts_bracketed_and_unbracketed_headers_for_all_timeframes(tmp_path, bracketed, delimiter):
    source = files(tmp_path)
    write_headers(source, bracketed=bracketed, delimiter=delimiter)
    result = import_mt5_files(source)
    assert result.report.candles_imported == 3
    assert all(len(candles) == 1 for _, candles in result.series)


@pytest.mark.parametrize("timeframe,header", [
    ("Daily", "<DATE> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>"),
    ("H1", "<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>"),
    ("M15", "<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>"),
])
def test_accepts_exact_real_mt5_headers(tmp_path, timeframe, header):
    source = files(tmp_path)
    path = source[timeframe]
    path.write_text(header + "\n" + " ".join(path.read_text().splitlines()[1:][0].split()) + "\n")
    result = import_mt5_files(source)
    assert len(dict(result.series)[timeframe]) == 1


@pytest.mark.parametrize("header", [
    "<DATE> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL>",
    "<DATE> <DATE> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>",
    "<DATE> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD> <EXTRA>",
    "<DATE> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <UNKNOWN>",
])
def test_rejects_missing_duplicated_extra_and_unknown_headers(tmp_path, header):
    source = files(tmp_path)
    source["Daily"].write_text(header + "\n2026.11.18 2000 2010 1990 2005 12 3 25\n")
    result = import_mt5_files(source)
    issue = next(item for item in result.report.issues if item.source_file == source["Daily"].name)
    assert issue.code == "invalid_header"


def test_fixed_offset_does_not_apply_daylight_saving(tmp_path):
    row = "2026.07.18 01:00:00 2000 2010 1990 2005 12 3 25"
    result = import_mt5_files(files(tmp_path, h1=[row]))
    assert candle(result, "H1").opened_at == datetime(2026, 7, 17, 23, tzinfo=UTC)
    assert candle(result, "H1").source_timezone == "UTC+02:00 fixed"


@pytest.mark.parametrize("row,code", [
    ("2026.02.30 01:00:00 2000 2010 1990 2005 12 3 25", "invalid_row"),
    ("2026.11.18 01:00:00 bad 2010 1990 2005 12 3 25", "invalid_row"),
    ("2026.11.18 01:00:00 2000 1990 2010 2005 12 3 25", "invalid_ohlc_order"),
    ("2026.11.18 01:00:00 2000 2010 1990 2005 -1 3 25", "invalid_volume_or_spread"),
    ("2026.11.18 01:00:00 2000 2010 1990 2005 12 3 -1", "invalid_volume_or_spread"),
    ("2026.11.18 01:00:00 0 2010 0 2005 12 3 25", "invalid_ohlc_numeric"),
])
def test_rejects_bad_numeric_rows(tmp_path, row, code):
    source = files(tmp_path, h1=[row])
    result = import_mt5_files(source)
    assert not dict(result.series)["H1"]
    assert code in [issue.code for issue in result.report.issues]


def test_identical_duplicates_collapse_and_conflicting_timestamp_is_excluded(tmp_path):
    first = "2026.11.18 01:00:00 2000 2010 1990 2005 12 3 25"
    changed = "2026.11.18 01:00:00 2001 2010 1990 2005 12 3 25"
    result = import_mt5_files(files(tmp_path, h1=[first, first, changed]))
    assert not dict(result.series)["H1"]
    assert result.report.duplicates_collapsed == 1
    assert result.report.conflicting_timestamps == 1
    assert {issue.code for issue in result.report.issues} >= {"duplicate_identical", "duplicate_conflict"}


def test_gap_diagnostics_are_advisory(tmp_path):
    rows = ["2026.11.18 01:00:00 2000 2010 1990 2005 12 3 25",
            "2026.11.18 03:00:00 2000 2010 1990 2005 12 3 25"]
    result = import_mt5_files(files(tmp_path, h1=rows))
    assert len(dict(result.series)["H1"]) == 2
    gap, = [gap for gap in result.report.gap_candidates if gap.timeframe == "H1"]
    assert gap.missing_intervals == 1 and gap.calendar_verified is False


def test_rejects_unexpected_file_set_and_header(tmp_path):
    source = files(tmp_path)
    with pytest.raises(ValueError, match="exactly"):
        import_mt5_files({"Daily": source["Daily"]})
    source["H1"].write_text("DATE TIME OPEN HIGH LOW CLOSE\n")
    result = import_mt5_files(source)
    assert "invalid_header" in [issue.code for issue in result.report.issues]
