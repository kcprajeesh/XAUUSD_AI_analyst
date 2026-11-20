"""Read-only persisted projection and local HTTP integration using disposable fixtures."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import sqlite3
import socket
import threading
import time
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest
import uvicorn

from app.ai.evidence import (CandleOrigin, CandleState, EvidenceCandle, EvidencePacket, InstrumentIdentity,
    InstrumentType, SourceIdentity, Timeframe, TimeframeEvidence, TimeframeState)
from app.analysis import provenance as workflow
from app.analysis.engine import AnalysisParameters
from app.analysis.projection import ProjectionError, ProjectionNotFound, project_analysis
from app.canonical import CanonicalLimits
from app.data.archive_prototype import SyntheticArchive, TIMEFRAMES
from app.data.evidence_contracts import AnalysisOutput, digest_analysis_output, structured_profile_registry

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=1)
LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
REGISTRY = structured_profile_registry()


def make_archive(path):
    archive = SyntheticArchive(path, create=True, busy_timeout_ms=25)
    archive.store_evidence("complete", "synthetic-provider", "raw_provider_body", START, b"fixture",
        payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
    for tf in TIMEFRAMES:
        retrieval = f"retrieval-{tf}"
        archive.begin_retrieval(retrieval, f"series-{tf}", "xau-usd:synthetic", "synthetic-provider", tf,
                                START, END, START)
        archive.add_revision(f"revision-{tf}", f"logical-{tf}", retrieval, 0)
        archive.finish_retrieval(retrieval, "verified", END, "complete")
        archive.promote_retrieval(retrieval)
    archive.create_manifest("input-1", {tf: (START, END) for tf in TIMEFRAMES}, START + timedelta(hours=1),
        limits=LIMITS, registry=REGISTRY, max_payload_bytes=100_000)
    instrument = InstrumentIdentity(instrument_id="xau-usd:spot-synthetic", instrument_type=InstrumentType.OTC_SPOT)
    source = SourceIdentity(source_id="source-1", retrieval_id="retrieval-1h", instrument=instrument,
        provider_id="synthetic-provider", feed_id="fixture", series_id="series-1h", provider_symbol="XAUUSD",
        retrieved_at=END, price_normalization="source_decimal_text")
    candle = EvidenceCandle(candle_id="candle-1", source_id="source-1", retrieval_id="retrieval-1h",
        revision_id="revision-1h", timeframe=Timeframe.H1, opened_at=START, closed_at=START + timedelta(hours=1),
        status=CandleState.CLOSED, origin=CandleOrigin.NATIVE, open=Decimal("2000"), high=Decimal("2002"),
        low=Decimal("1999"), close=Decimal("2001"))
    frames = [TimeframeEvidence(timeframe=tf,
        state=TimeframeState.UNSUPPORTED if tf == Timeframe.H4 else TimeframeState.UNAVAILABLE) for tf in Timeframe]
    frames[list(Timeframe).index(Timeframe.H1)] = TimeframeEvidence(timeframe=Timeframe.H1,
        state=TimeframeState.AVAILABLE, origin=CandleOrigin.NATIVE, source_ids=("source-1",), candles=(candle,))
    packet = EvidencePacket(analysis_id="analysis-packet-1", analysis_at=END, instrument=instrument,
        sources=(source,), requested_timeframes=tuple(Timeframe), retrieved_at=END, timeframes=tuple(frames))
    workflow.persist_analysis(archive, "input-1", packet, output_id="analysis-1", derived_id="derived-1",
        timeframe="1h", window_start=START, window_end=END, created_at=END, parameters=AnalysisParameters(),
        registry=REGISTRY, limits=LIMITS, max_payload_bytes=100_000, policy_id="synthetic-policy-v1",
        unavailable_inputs=("4H:H4-03",))
    return archive


def project(archive, identity="analysis-1"):
    return project_analysis(archive.connection, identity, limits=LIMITS, max_payload_bytes=100_000, registry=REGISTRY)


def test_valid_projection_is_exact_bound_and_does_not_mutate_archive(tmp_path):
    archive = make_archive(tmp_path / "projection.synthetic.sqlite3")
    try:
        before = {table: archive.connection.execute(f"SELECT * FROM {table}").fetchall() for table in
                  ("manifests", "manifest_items", "manifest_revisions", "analysis_outputs", "derived_manifests", "invalidations")}
        result = project(archive)
        after = {table: archive.connection.execute(f"SELECT * FROM {table}").fetchall() for table in before}
        assert after == before
        assert not archive.connection.in_transaction
        assert result.analysis_id == "analysis-1"
        assert result.analysis_output.analysis_id == "analysis-packet-1"
        assert "sources" not in result.analysis_output
        assert not hasattr(result.analysis_output.timeframes[0], "candles")
        assert result.input_manifest_id == "input-1" and result.derived_manifest_id == "derived-1"
        assert result.source_attribution == ("synthetic-provider",)
        assert result.source_eligibility_status == "unverified"
        assert result.analyst_outcome == "unavailable"
        assert result.timeframe_availability["4H"] == "unsupported"
        assert result.timeframe_availability["1M"] == "unsupported"
        assert "macro:no_persisted_context" in result.unavailable_inputs
        archive.connection.execute("BEGIN")
        with pytest.raises(ProjectionError, match="own_read_snapshot"):
            project(archive)
        archive.connection.execute("ROLLBACK")
    finally:
        archive.close()


def test_missing_analysis_or_provenance_is_unavailable_not_reconstructed(tmp_path):
    archive = make_archive(tmp_path / "missing.synthetic.sqlite3")
    try:
        with pytest.raises(ProjectionNotFound):
            project(archive, "missing")
        archive.connection.execute("PRAGMA foreign_keys=OFF")
        archive.connection.execute("DROP TRIGGER derived_manifests_no_delete")
        archive.connection.execute("DELETE FROM derived_manifests WHERE derived_id='derived-1'")
        with pytest.raises(ProjectionError, match="provenance_missing"):
            project(archive)
    finally:
        archive.close()


def test_missing_input_manifest_and_selected_retrieval_fail_closed(tmp_path):
    archive = make_archive(tmp_path / "missing-input.synthetic.sqlite3")
    try:
        archive.connection.execute("PRAGMA foreign_keys=OFF")
        archive.connection.execute("DROP TRIGGER manifests_no_delete")
        archive.connection.execute("DELETE FROM manifests WHERE manifest_id='input-1'")
        with pytest.raises(ProjectionError, match="provenance_missing"):
            project(archive)
    finally:
        archive.close()
    archive = make_archive(tmp_path / "missing-retrieval.synthetic.sqlite3")
    try:
        archive.connection.execute("PRAGMA foreign_keys=OFF")
        archive.connection.execute("DELETE FROM retrievals WHERE retrieval_id='retrieval-1h'")
        with pytest.raises(ProjectionError, match="selected_retrieval_missing"):
            project(archive)
    finally:
        archive.close()


def test_missing_source_attribution_is_explicit_and_not_filled_in(tmp_path):
    archive = make_archive(tmp_path / "missing-source.synthetic.sqlite3")
    try:
        archive.connection.execute("DROP TRIGGER retrievals_finalize_once")
        archive.connection.execute("UPDATE retrievals SET provider_id=''")
        result = project(archive)
        assert result.source_attribution == ()
        assert "market_data:source_attribution_unavailable" in result.unavailable_inputs
        assert result.market_data_status == "incomplete"
        archive.connection.execute("UPDATE retrievals SET provider_id='synthetic-provider'")
        archive.connection.execute("UPDATE retrievals SET completeness='incomplete' WHERE retrieval_id='retrieval-1h'")
        result = project(archive)
        assert result.retrieval_completeness["retrieval-1h"] == "incomplete"
        assert "retrieval:retrieval-1h:incomplete" in result.unavailable_inputs
    finally:
        archive.close()


@pytest.mark.parametrize("tamper", ["input_digest", "output_digest", "derived_digest", "linkage"])
def test_digest_or_manifest_linkage_mismatch_is_rejected(tmp_path, tamper):
    archive = make_archive(tmp_path / f"{tamper}.synthetic.sqlite3")
    try:
        if tamper == "input_digest":
            archive.connection.execute("DROP TRIGGER manifests_no_update")
            archive.connection.execute("UPDATE manifests SET digest=? WHERE manifest_id='input-1'", ("0" * 64,))
        elif tamper == "output_digest":
            archive.connection.execute("DROP TRIGGER analysis_outputs_no_update")
            archive.connection.execute("UPDATE analysis_outputs SET digest=? WHERE output_id='analysis-1'", ("0" * 64,))
        elif tamper == "derived_digest":
            archive.connection.execute("DROP TRIGGER derived_manifests_no_update")
            archive.connection.execute("UPDATE derived_manifests SET digest=? WHERE derived_id='derived-1'", ("0" * 64,))
        else:
            archive.create_manifest("input-2", {tf: (START, END) for tf in TIMEFRAMES}, END,
                limits=LIMITS, registry=REGISTRY, max_payload_bytes=100_000)
            archive.connection.execute("DROP TRIGGER derived_manifests_no_update")
            archive.connection.execute("UPDATE derived_manifests SET manifest_id='input-2' WHERE derived_id='derived-1'")
        with pytest.raises(ProjectionError):
            project(archive)
    finally:
        archive.close()


def test_invalidated_evidence_is_historical_warning_and_unsupported_states_preserved(tmp_path):
    archive = make_archive(tmp_path / "historical.synthetic.sqlite3")
    try:
        archive.invalidate_revision("invalidate-1", "revision-1h", END + timedelta(minutes=1), "correction")
        result = project(archive)
        assert result.status == "historical_invalidated"
        assert result.invalidation_warnings == ("invalidated_revision:revision-1h",)
        assert result.timeframe_availability["4H"] == "unsupported"
        assert "news:no_persisted_context" in result.unavailable_inputs
    finally:
        archive.close()


def test_malformed_persisted_packet_is_rejected(tmp_path):
    archive = make_archive(tmp_path / "malformed.synthetic.sqlite3")
    try:
        archive.connection.execute("DROP TRIGGER analysis_outputs_no_update")
        archive.connection.execute("DROP TRIGGER derived_manifests_no_update")
        row = archive.connection.execute("SELECT payload FROM analysis_outputs WHERE output_id='analysis-1'").fetchone()
        value = json.loads(bytes(row[0]))
        value["output_json"] = "{}"
        metadata = digest_analysis_output(AnalysisOutput("analysis-1", "input-1", "{}"), REGISTRY, LIMITS, 100_000)
        from app.data.evidence_contracts import canonical_json, ANALYSIS_OUTPUT_SCHEMA
        payload = canonical_json(value, ANALYSIS_OUTPUT_SCHEMA, LIMITS)
        archive.connection.execute("UPDATE analysis_outputs SET payload=?,digest=? WHERE output_id='analysis-1'",
                                   (payload, metadata.digest))
        derived = archive.connection.execute("SELECT payload FROM derived_manifests WHERE derived_id='derived-1'").fetchone()
        derived_value = json.loads(bytes(derived[0]))
        derived_value["analysis_output_digest"] = metadata.digest
        from app.data.evidence_contracts import DERIVED_MANIFEST_V2_SCHEMA
        from app.canonical_digest import digest_structured
        profile = next(item for item in REGISTRY.entries if item.domain == "evidence.derived-manifest.v2")
        derived_payload = canonical_json(derived_value, DERIVED_MANIFEST_V2_SCHEMA, LIMITS)
        derived_digest = digest_structured(derived_value, DERIVED_MANIFEST_V2_SCHEMA, profile, REGISTRY, LIMITS, 100_000).digest
        archive.connection.execute("UPDATE derived_manifests SET payload=?,digest=? WHERE derived_id='derived-1'",
                                   (derived_payload, derived_digest))
        with pytest.raises(ProjectionError, match="malformed"):
            project(archive)
    finally:
        archive.close()


def test_http_api_serializes_exact_projection_and_unconfigured_state(tmp_path):
    from app.main import app
    archive = make_archive(tmp_path / "http.synthetic.sqlite3")
    previous = app.state.analysis_projection
    readonly_connection = sqlite3.connect(f"file:{archive.path}?mode=ro", uri=True, check_same_thread=False)
    app.state.analysis_projection = lambda identity: project_analysis(readonly_connection, identity,
        limits=LIMITS, max_payload_bytes=100_000, registry=REGISTRY)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        with pytest.raises(sqlite3.OperationalError):
            readonly_connection.execute("DELETE FROM analysis_outputs")
        if readonly_connection.in_transaction:
            readonly_connection.rollback()
        with urlopen(f"http://127.0.0.1:{port}/api/v1/analysis/analysis-1") as response:
            value = json.loads(response.read())
        assert value["schema_version"] == "xau.dashboard-analysis.v1"
        assert value["analysis_id"] == "analysis-1"
        assert value["analysis_output"]["analysis_id"] == "analysis-packet-1"
        assert value["derived_manifest_id"] == "derived-1"
        with pytest.raises(HTTPError) as missing:
            urlopen(f"http://127.0.0.1:{port}/api/v1/analysis/missing")
        assert missing.value.code == 404
        app.state.analysis_projection = None
        with pytest.raises(HTTPError) as unavailable:
            urlopen(f"http://127.0.0.1:{port}/api/v1/analysis/analysis-1")
        assert unavailable.value.code == 503
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        app.state.analysis_projection = previous
        readonly_connection.close()
        archive.close()
