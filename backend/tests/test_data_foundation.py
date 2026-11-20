"""Entirely synthetic offline data tests; no provider HTTP requests."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import socket
import sqlite3

import pytest
from pydantic import TypeAdapter, ValidationError

from app.data.contracts import (
    Candle, CandleStatus, Coverage, HistoricalRevision, IngestionRecord, Instrument,
    InstrumentKind, Interval, NormalizedBatch, ProviderSeries, QualityCode, XAU_USD_SPOT,
)
from app.data.policy import POLICIES, TimeframePolicy
from app.data.storage import CandleStore
from app.data.twelve_data import HistoricalRequest, PaginationDecision, TwelveDataAdapter, parse_source_timestamp

ADAPTER = TwelveDataAdapter()
OPEN = datetime(2026, 1, 15, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline tests must never open a network connection")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def payload():
    fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("synthetic_twelve_data.json").read_text())
    assert fixture["fixture_kind"] == "synthetic"
    return fixture["payload"]


def request(interval=Interval.M5, **changes):
    return HistoricalRequest(series=ADAPTER.series(interval), start_date=OPEN - timedelta(days=1),
        end_date=OPEN + timedelta(days=10), **changes)


def normalize(payload, interval=Interval.M5, retrieved_at=OPEN + timedelta(days=3)):
    payload = deepcopy(payload)
    payload["meta"]["interval"] = interval.value
    return ADAPTER.normalize(payload, request(interval), retrieved_at=retrieved_at, input_kind="synthetic")


def codes(batch):
    return {issue.code for issue in batch.report.issues}


def contract_schema():
    schema = TypeAdapter(Instrument | ProviderSeries | TimeframePolicy | HistoricalRequest |
        NormalizedBatch | HistoricalRevision | Coverage | IngestionRecord | PaginationDecision).json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "XAU/USD Offline Data Foundation v1.0"
    return schema


def test_versioned_schema_snapshot():
    path = Path(__file__).parents[2] / "docs/data-foundation.schema.json"
    assert contract_schema() == json.loads(path.read_text())


@pytest.mark.parametrize("interval,seconds", [(Interval.DAILY, 86400), (Interval.H4, 14400),
    (Interval.H1, 3600), (Interval.M15, 900), (Interval.M5, 300)])
def test_all_five_interval_mappings_and_boundaries(payload, interval, seconds):
    req = request(interval)
    assert req.parameters() == {"symbol": "XAU/USD", "interval": interval.value,
        "start_date": "2026-01-14 10:00:00", "end_date": "2026-01-25 10:00:00",
        "outputsize": 5000, "timezone": "UTC", "order": "asc"}
    policy = POLICIES[interval]
    assert policy.nominal_seconds == seconds
    assert not policy.calendar_verified
    candle = normalize(payload, interval).candles[0]
    if interval == Interval.DAILY:
        assert candle.closes_at is None and candle.status == CandleStatus.UNVERIFIED
    else:
        assert candle.closes_at == OPEN + timedelta(seconds=seconds)
        assert candle.status == CandleStatus.CLOSED


@pytest.mark.parametrize("stamp,expected", [
    ("2026-01-15 10:00:00", OPEN), ("2026-01-15T10:00:00Z", OPEN),
    ("2026-01-15T15:30:00+05:30", OPEN),
    ("2026-01-15T10:00:00.123456Z", OPEN.replace(microsecond=123456)),
])
def test_utc_parsing(stamp, expected):
    parsed = parse_source_timestamp(stamp)
    assert parsed == expected and parsed.tzinfo is UTC


@pytest.mark.parametrize("stamp", [None, "", "2026-01-15", "2026-02-30 10:00:00", "bad",
    "2026-01-15T10:00:00.1234567Z", 1768471200, "2026-01-15 25:00:00", "2026-01-15T10:00:00+99:00"])
def test_invalid_timestamp_parser(stamp):
    with pytest.raises(ValueError):
        parse_source_timestamp(stamp)


def test_decimal_precision_and_provenance(payload):
    batch = normalize(payload)
    candle = batch.candles[0]
    assert candle.open == Decimal(payload["values"][0]["open"])
    assert json.loads(candle.model_dump_json())["open"] == payload["values"][0]["open"]
    assert candle.source_timestamp == payload["values"][0]["datetime"]
    assert candle.source_timestamp_meaning == "candle_opening_time"
    assert candle.source_timezone == "UTC"
    assert candle.provenance == batch.provenance
    assert candle.provenance.input_kind == "synthetic"
    assert batch.source_rows[0].fields == payload["values"][0]
    assert candle.volume is None and candle.volume_semantics == "not_provided"


@pytest.mark.parametrize("changes", [
    {"open": "0"}, {"close": "-1"}, {"high": "Infinity"}, {"low": "NaN"},
    {"open": 2000.1}, {"open": True}, {"high": "1998"}, {"low": "2002"},
    {"open": None}, {"close": "invalid"}, {"low": "2010", "high": "2000"},
])
def test_ohlc_rejection_retains_original_rows(payload, changes):
    payload["values"][0].update(changes)
    batch = normalize(payload)
    assert QualityCode.INVALID_OHLC in codes(batch)
    assert len(batch.candles) == 2
    assert batch.source_rows[0].fields == payload["values"][0]


def test_partial_rows_missing_invalid_and_future_source_time(payload):
    payload["values"][0].pop("datetime")
    payload["values"][1]["datetime"] = "2026-01-15"
    payload["values"][2]["datetime"] = "2026-02-15 10:10:00"
    batch = normalize(payload)
    assert not batch.candles and len(batch.source_rows) == 3
    assert {QualityCode.MISSING_TIMESTAMP, QualityCode.INVALID_TIMESTAMP} <= codes(batch)
    assert all(issue.opened_at is None for issue in batch.report.issues)


@pytest.mark.parametrize("interval", [Interval.H4, Interval.H1, Interval.M15, Interval.M5])
def test_forming_exclusion_and_exact_close(payload, tmp_path, interval):
    payload["values"] = payload["values"][:1]
    closes_at = POLICIES[interval].close_for(OPEN)
    forming = normalize(payload, interval, closes_at - timedelta(microseconds=1))
    assert forming.candles[0].status == CandleStatus.FORMING
    assert QualityCode.FORMING_EXCLUDED in codes(forming)
    closed = normalize(payload, interval, closes_at)
    assert closed.candles[0].status == CandleStatus.CLOSED
    with CandleStore(tmp_path / "synthetic.db") as store:
        store.ingest(request(interval), forming)
        assert store.candles(forming.series.series_id) == ()
        assert len(store.candles(forming.series.series_id, closed_only=False)) == 1
        ingested = store.ingest(request(interval), closed)
        assert not ingested.report.revisions
        assert len(store.candles(closed.series.series_id)) == 1
        assert store.coverage(closed.series.series_id).forming_count == 0


def test_daily_boundary_and_date_only_ambiguity(payload, tmp_path):
    batch = normalize(payload, Interval.DAILY)
    assert all(c.status == CandleStatus.UNVERIFIED for c in batch.candles)
    assert QualityCode.BOUNDARY_UNVERIFIED in codes(batch)
    with CandleStore(tmp_path / "synthetic.db") as store:
        store.ingest(request(Interval.DAILY), batch)
        assert not store.candles(batch.series.series_id)
        assert store.coverage(batch.series.series_id).unverified_count == 3
    payload["values"][0]["datetime"] = "2026-01-15"
    assert QualityCode.INVALID_TIMESTAMP in codes(normalize(payload, Interval.DAILY))


def test_identical_and_conflicting_duplicates(payload):
    original = deepcopy(payload["values"][0])
    payload["values"].append(deepcopy(original))
    batch = normalize(payload)
    assert len(batch.candles) == 3 and len(batch.source_rows) == 4
    assert QualityCode.DUPLICATE in codes(batch)
    payload["values"][-1]["close"] = "2000.5"
    batch = normalize(payload)
    assert len(batch.candles) == 2 and QualityCode.CONFLICTING_DUPLICATE in codes(batch)
    payload["values"][-1]["close"] = "NaN"
    batch = normalize(payload)
    assert len(batch.candles) == 2 and QualityCode.CONFLICTING_DUPLICATE in codes(batch)
    assert QualityCode.INVALID_OHLC in codes(batch)


def test_gaps_are_unverified_candidates_and_no_fill(payload):
    payload["values"].pop(1)
    batch = normalize(payload)
    assert len(batch.candles) == 2
    assert QualityCode.GAP_CANDIDATES in codes(batch)
    assert batch.report.gaps[0].nominal_missing_count == 1
    assert not batch.report.gaps[0].calendar_verified
    payload["values"][1]["datetime"] = "2026-01-15 10:12:00"
    batch = normalize(payload)
    assert QualityCode.IRREGULAR_CADENCE in codes(batch) and not batch.report.gaps


def test_outlier_is_flagged_and_persisted(payload, tmp_path):
    payload["values"][1].update(open="3000", high="3500", low="2500", close="3200")
    batch = normalize(payload)
    assert len(batch.candles) == 3 and QualityCode.OUTLIER in codes(batch)
    with CandleStore(tmp_path / "synthetic.db") as store:
        store.ingest(request(), batch)
        assert len(store.candles(batch.series.series_id)) == 3
        assert QualityCode.OUTLIER in store.candles(batch.series.series_id)[1].quality_flags


@pytest.mark.parametrize("volume,valid", [("123.456", True), ("0", True), ("-1", False),
    ("NaN", False), (1.5, False), (True, False), ({"unexpected": "nested"}, False)])
def test_volume_semantics(payload, volume, valid):
    payload["values"][0]["volume"] = volume
    batch = normalize(payload)
    if valid:
        assert batch.candles[0].volume == Decimal(volume)
        assert batch.candles[0].volume_semantics == "provider_reported_unverified"
    else:
        assert len(batch.candles) == 2
        assert QualityCode.INVALID_VOLUME in codes(batch) or QualityCode.INVALID_ROW in codes(batch)


def test_sqlite_roundtrip_corrections_and_coverage(payload, tmp_path):
    path = tmp_path / "synthetic.db"
    first = normalize(payload)
    with CandleStore(path) as store:
        ingested = store.ingest(request(), first)
        assert store.get_ingestion(ingested.ingestion_id) == ingested
        assert store.get_instrument(XAU_USD_SPOT.instrument_id) == XAU_USD_SPOT
        assert store.candles(first.series.series_id) == first.candles
        assert store.coverage(first.series.series_id).closed_count == 3
        assert not store.coverage(first.series.series_id).complete
    corrected_payload = deepcopy(payload)
    corrected_payload["values"][0]["close"] = "2000.25"
    corrected = normalize(corrected_payload, retrieved_at=first.provenance.retrieved_at + timedelta(hours=1))
    with CandleStore(path) as store:
        ingested = store.ingest(request(), corrected)
        revision = ingested.report.revisions[0]
        assert revision.changed_fields == ("close",)
        assert revision.previous_record_id != revision.revised_record_id
        assert revision.detected_at == corrected.provenance.retrieved_at
        assert QualityCode.HISTORICAL_REVISION in {i.code for i in ingested.report.issues}
        assert store.history(first.series.series_id, OPEN) == (first.candles[0], corrected.candles[0])
        assert store.candles(first.series.series_id)[0].close == Decimal("2000.25")
        assert store.get_ingestion(1).source_rows[0].fields["close"] == "2001.00"
        assert store.get_ingestion(2).source_rows[0].fields["close"] == "2000.25"
        assert store.integrity_check() == (("ok",), ())
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert len(store.candles(first.series.series_id, start=OPEN + timedelta(minutes=5),
            end=OPEN + timedelta(minutes=5))) == 1
        repeated = normalize(corrected_payload, retrieved_at=corrected.provenance.retrieved_at + timedelta(hours=1))
        assert not store.ingest(request(), repeated).report.revisions
        stale = store.ingest(request(), first)
        assert QualityCode.STALE_OBSERVATION in {i.code for i in stale.report.issues}
        assert store.candles(first.series.series_id)[0].close == Decimal("2000.25")
        assert len(store.history(first.series.series_id, OPEN)) == 4


def test_provenance_representation_changes_are_not_price_revisions(payload, tmp_path):
    first = normalize(payload)
    payload["values"][0]["datetime"] = "2026-01-15T15:30:00+05:30"
    payload["values"][0]["close"] = "2001.00000"
    second = normalize(payload, retrieved_at=first.provenance.retrieved_at + timedelta(hours=1))
    with CandleStore(tmp_path / "synthetic.db") as store:
        store.ingest(request(), first)
        record = store.ingest(request(), second)
        assert not record.report.revisions
        history = store.history(first.series.series_id, OPEN)
        assert history[1].source_timestamp.endswith("+05:30")
        assert str(history[1].close) == "2001.00000"


def test_synthetic_sqlite_backup_restore_preserves_checkpoint_and_legacy_provenance(payload, tmp_path):
    first = normalize(payload)
    corrected_payload = deepcopy(payload)
    corrected_payload["values"][0]["close"] = "2000.25"
    corrected = normalize(corrected_payload, retrieved_at=first.provenance.retrieved_at + timedelta(hours=1))
    backup_path = tmp_path / "synthetic-backup.db"
    restored_path = tmp_path / "synthetic-restored.db"
    with CandleStore(tmp_path / "synthetic-original.db") as store:
        initial_record = store.ingest(request(), first)
        revision_record = store.ingest(request(), corrected)
        checkpoint = tuple(store.connection.iterdump())
        destination = sqlite3.connect(backup_path)
        try:
            store.connection.backup(destination)
        finally:
            destination.close()
        store.ingest(request(), first)
        assert tuple(store.connection.iterdump()) != checkpoint

    with CandleStore(backup_path) as saved:
        assert tuple(saved.connection.iterdump()) == checkpoint
        assert saved.get_ingestion(initial_record.ingestion_id) == initial_record
        assert saved.get_ingestion(revision_record.ingestion_id) == revision_record
        destination = sqlite3.connect(restored_path)
        try:
            saved.connection.backup(destination)
        finally:
            destination.close()

    with CandleStore(restored_path) as restored:
        assert tuple(restored.connection.iterdump()) == checkpoint
        assert restored.history(first.series.series_id, OPEN) == (first.candles[0], corrected.candles[0])
        assert restored.candles(first.series.series_id) == corrected.candles
        assert restored.integrity_check() == (("ok",), ())
        assert restored.connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_rejected_partial_rows_and_errors_persist(payload, tmp_path):
    payload["values"][0].pop("close")
    payload["values"].append(None)
    batch = normalize(payload)
    assert len(batch.candles) == 2
    assert {QualityCode.INVALID_OHLC, QualityCode.INVALID_ROW, QualityCode.MISSING_TIMESTAMP} <= codes(batch)
    with CandleStore(tmp_path / "synthetic.db") as store:
        ingested = store.ingest(request(), batch)
        assert ingested.source_rows == batch.source_rows
        error = ADAPTER.normalize({"status": "error", "code": 429, "message": "sensitive source text"},
            request(), retrieved_at=OPEN, input_kind="synthetic")
        failed = store.ingest(request(), error)
        assert failed.error.provider_code == 429
        assert store.coverage(batch.series.series_id).closed_count == 2
        assert store.integrity_check() == (("ok",), ())


@pytest.mark.parametrize("change", ["meta", "symbol", "interval", "timezone", "currency", "values", "status"])
def test_invalid_envelopes(payload, change):
    if change in ("symbol", "interval", "timezone", "currency"):
        payload["meta"][change] = "wrong"
    elif change == "meta":
        payload.pop("meta")
    elif change == "values":
        payload["values"] = None
    else:
        payload["status"] = "unexpected"
    batch = ADAPTER.normalize(payload, request(), retrieved_at=OPEN + timedelta(days=3), input_kind="synthetic")
    assert batch.error and QualityCode.INVALID_RESPONSE in codes(batch) and not batch.candles


def test_request_validation_and_overlap_pagination(payload):
    for changes in ({"outputsize": 5001}, {"outputsize": 0}, {"outputsize": 5.5}):
        with pytest.raises(ValidationError):
            request(**changes)
    with pytest.raises(ValidationError):
        HistoricalRequest(series=ADAPTER.series(Interval.M5), start_date=OPEN, end_date=OPEN)
    with pytest.raises(ValidationError):
        HistoricalRequest(series=ADAPTER.series(Interval.M5), start_date=OPEN.replace(tzinfo=None), end_date=OPEN)
    with pytest.raises(ValidationError):
        HistoricalRequest(series=ADAPTER.series(Interval.M5), start_date=OPEN.replace(microsecond=1), end_date=OPEN + timedelta(days=1))
    req = request()
    batch = normalize(payload)
    decision = ADAPTER.next_page(req, batch)
    assert decision.state == "next_page"
    assert decision.next_request.start_date == batch.candles[-1].opened_at
    assert decision.next_request.end_date == req.end_date
    one_row = deepcopy(payload)
    one_row["values"] = one_row["values"][-1:]
    assert ADAPTER.next_page(decision.next_request, normalize(one_row)).state == "indeterminate"
    payload["values"][0].pop("datetime")
    assert ADAPTER.next_page(req, normalize(payload)).state == "indeterminate"
    payload["values"] = []
    assert ADAPTER.next_page(req, normalize(payload)).state == "indeterminate"


def test_range_reached_and_response_cap(payload):
    req = HistoricalRequest(series=ADAPTER.series(Interval.M5), start_date=OPEN, end_date=OPEN + timedelta(minutes=10))
    batch = ADAPTER.normalize(payload, req, retrieved_at=OPEN + timedelta(hours=1), input_kind="synthetic")
    assert ADAPTER.next_page(req, batch).state == "range_boundary_reached"
    small = HistoricalRequest(series=req.series, start_date=req.start_date, end_date=req.end_date, outputsize=2)
    assert ADAPTER.normalize(payload, small, retrieved_at=OPEN + timedelta(hours=1), input_kind="synthetic").error


def test_distinct_instrument_identities():
    identities = [XAU_USD_SPOT,
        Instrument(instrument_id="xau-usd:cfd:synthetic-broker", kind=InstrumentKind.BROKER_CFD,
            broker="synthetic-broker", name="Synthetic broker gold CFD identity"),
        Instrument(instrument_id="comex:gc:2026-12", kind=InstrumentKind.COMEX_FUTURE,
            contract_month="2026-12", name="COMEX GC December 2026 identity"),
        Instrument(instrument_id="lbma:gold:usd:AM", kind=InstrumentKind.LBMA_BENCHMARK,
            benchmark_fix="AM", name="LBMA Gold Price USD AM identity")]
    assert len({instrument.instrument_id for instrument in identities}) == 4
    with pytest.raises(ValidationError):
        Instrument(instrument_id=XAU_USD_SPOT.instrument_id, kind=InstrumentKind.BROKER_CFD,
            broker="synthetic-broker", name="Invalid mixed identity")
    with pytest.raises(ValidationError):
        ProviderSeries(series_id="broker:XAUUSD:5min", interval=Interval.M5, native_symbol="XAUUSD")


def test_transaction_failure_rolls_back_entire_ingestion(payload, tmp_path):
    with CandleStore(tmp_path / "synthetic.db") as store:
        store.connection.execute("CREATE TRIGGER fail_coverage BEFORE INSERT ON coverage BEGIN SELECT RAISE(ABORT,'synthetic injected failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            store.ingest(request(), normalize(payload))
        for table in ("instruments", "provider_series", "ingestions", "candle_records", "current_candles", "quality_reports"):
            assert store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert store.integrity_check() == (("ok",), ())


@pytest.mark.parametrize("version", [0, 1, 2])
def test_unknown_schema_is_preserved(tmp_path, version):
    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE original (value TEXT)")
        connection.execute("INSERT INTO original VALUES ('preserve me')")
        connection.execute(f"PRAGMA user_version={version}")
    with pytest.raises(ValueError):
        CandleStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM original").fetchone()[0] == "preserve me"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version


def test_secret_fields_omitted_and_synthetic_real_mixing_rejected(payload, tmp_path):
    payload["apikey"] = "synthetic-secret-sentinel"
    payload["meta"]["apikey"] = "synthetic-secret-sentinel"
    payload["values"][0]["apikey"] = "synthetic-secret-sentinel"
    batch = normalize(payload)
    path = tmp_path / "synthetic.db"
    with CandleStore(path) as store:
        store.ingest(request(), batch)
        provider_batch = ADAPTER.normalize(payload, request(), retrieved_at=OPEN + timedelta(days=4), input_kind="provider_response")
        with pytest.raises(ValueError, match="separate databases"):
            store.ingest(request(), provider_batch)
        assert store.connection.execute("SELECT COUNT(*) FROM ingestions").fetchone()[0] == 1
    assert b"synthetic-secret-sentinel" not in path.read_bytes()


def test_contracts_fail_closed_on_corruption(payload):
    candle = normalize(payload).candles[0].model_dump()
    for changes in ({"status": "forming"}, {"closes_at": OPEN}, {"source_timestamp": "2026-01-15 09:00:00"},
                    {"opened_at": OPEN.replace(tzinfo=None)}, {"open": 2000.1}, {"schema_version": "2.0"}):
        with pytest.raises(ValidationError):
            Candle.model_validate({**candle, **changes})
    batch = normalize(payload).model_dump()
    batch["candles"][0]["series"]["interval"] = "1h"
    with pytest.raises(ValidationError):
        NormalizedBatch.model_validate(batch)


def test_source_price_mismatch_cannot_be_persisted(payload, tmp_path):
    batch = normalize(payload)
    changed = batch.model_dump()
    changed["candles"][0]["close"] = "2000.5"
    with pytest.raises(ValidationError, match="original decimal source"):
        NormalizedBatch.model_validate(changed)
    with CandleStore(tmp_path / "synthetic.db") as store:
        invalid = batch.model_copy(update={"candles": (batch.candles[0].model_copy(update={"close": Decimal("2000.5")}),)})
        with pytest.raises(ValidationError):
            store.ingest(request(), invalid)
        assert store.connection.execute("SELECT COUNT(*) FROM ingestions").fetchone()[0] == 0


def test_source_metadata_and_empty_coverage_remain_explicit(payload, tmp_path):
    payload["values"] = []
    batch = normalize(payload)
    assert batch.provenance.source_metadata == payload["meta"]
    assert QualityCode.EMPTY_RESPONSE in codes(batch)
    with CandleStore(tmp_path / "synthetic.db") as store:
        ingested = store.ingest(request(), batch)
        assert ingested.provenance.source_metadata == payload["meta"]
        coverage = store.coverage(batch.series.series_id)
        assert coverage.closed_count == 0 and coverage.first_closed_open is None
        assert not coverage.complete


@pytest.mark.parametrize("value", ["bad", "sNaN", "Infinity", None])
def test_malformed_raw_price_evidence_fails_closed(payload, value):
    from app.data.contracts import SourceRow, public_payload_hash
    batch = normalize(payload).model_dump()
    batch["source_rows"][0]["fields"]["open"] = value
    rows = tuple(SourceRow.model_validate(row) for row in batch["source_rows"])
    batch["provenance"]["payload_sha256"] = public_payload_hash(batch["provenance"]["source_metadata"], rows)
    for candle in batch["candles"]:
        candle["provenance"] = batch["provenance"]
    with pytest.raises(ValidationError):
        NormalizedBatch.model_validate(batch)


def test_provenance_fingerprint_detects_raw_evidence_changes(payload):
    batch = normalize(payload).model_dump()
    batch["source_rows"][0]["fields"]["datetime"] = "2026-01-15 09:00:00"
    with pytest.raises(ValidationError, match="fingerprint"):
        NormalizedBatch.model_validate(batch)


def test_boundary_overflow_and_naive_retrieval_fail_closed(payload):
    payload["values"] = payload["values"][:1]
    payload["values"][0]["datetime"] = "9999-12-31 23:59:59"
    maximum = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)
    req = HistoricalRequest(series=ADAPTER.series(Interval.M5), start_date=maximum - timedelta(days=1), end_date=maximum)
    batch = ADAPTER.normalize(payload, req, retrieved_at=maximum, input_kind="synthetic")
    assert not batch.candles and QualityCode.INVALID_TIMESTAMP in codes(batch)
    with pytest.raises(ValueError, match="aware"):
        ADAPTER.normalize(payload, req, retrieved_at=maximum.replace(tzinfo=None), input_kind="synthetic")


def test_response_cannot_exceed_5000_points(payload):
    payload["values"] = [payload["values"][0]] * 5001
    batch = normalize(payload)
    assert batch.error and not batch.candles and not batch.source_rows
    assert QualityCode.INVALID_RESPONSE in codes(batch)
