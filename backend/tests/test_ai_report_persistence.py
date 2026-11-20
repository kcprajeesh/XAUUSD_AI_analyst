"""Synthetic AI report persistence and read-only projection checks."""
from datetime import UTC, datetime, timedelta
import json
import sqlite3
import threading
import time
import subprocess
import sys
from urllib.request import urlopen

import pytest

from app.ai.analyst import AnalystInterpretation, AnalystProvenance, AnalystResponseV1, AnalystStatus
from app.ai.config import Protocol
from app.ai.contracts import (AnalysisResponse, Bias, Claim, EvidenceSufficiencyLabel, ProviderMetadata,
    TimeframeAnalysis, TradeStance, ValidationState)
from app.ai.evidence import (CandleOrigin, CandleState, EvidenceCandle, EvidencePacket, EvidenceRecord,
    EvidenceType, InstrumentIdentity, InstrumentType, QualityStatus, SourceIdentity, Timeframe,
    TimeframeEvidence, TimeframeState)
from app.ai.persistence import run_and_persist_analyst
from app.analysis.projection import ProjectionError, project_analysis
from app.canonical import CanonicalLimits
from app.data.context import process_context
from app.data.evidence_contracts import structured_profile_registry
from app.analysis.provenance import persist_analysis
from app.analysis.engine import AnalysisParameters, analyze_packet
from app.data.archive_prototype import SyntheticArchive, TIMEFRAMES

from test_analysis_provenance import START, END, REGISTRY, setup_archive, analysis_packet

LIMITS = CanonicalLimits(4_000_000, 1_000, 1_000, 1_000, 4_000_000)


def _persist(archive, completion=None, packet=None, *, provider_id="synthetic-fixture", model_id="no-call",
             prompt_version="prompt-v1"):
    packet = packet or analysis_packet()
    _output, derived, analyzed = persist_analysis(archive, "input-1", packet, output_id="output-1",
        derived_id="derived-1", timeframe="1h", window_start=START, window_end=END, created_at=END,
        parameters=AnalysisParameters(), registry=REGISTRY, limits=LIMITS, max_payload_bytes=4_000_000,
        policy_id="synthetic-test-policy-v1", unavailable_inputs=("4h:H4-03",))
    digest = archive.connection.execute("SELECT digest FROM manifests WHERE manifest_id='input-1'").fetchone()[0]
    provenance = AnalystProvenance(input_manifest_id="input-1", input_manifest_digest=digest,
        derived_manifest_id="derived-1", derived_manifest_digest=derived.digest, provider_id="synthetic-fixture",
        model_id=model_id, analysis_request_id="request-1", prompt_version=prompt_version,
        configuration_metadata=(("external_calls_enabled", False), ("response_schema", "xau.analyst-response.v1")),
        created_at=END)
    return run_and_persist_analyst(archive, analyzed, process_context(retrieved_at=END,
        source_registry_version="fixture-only-v1"), provenance, completion, response_id="response-1",
        report_id="report-1", registry=REGISTRY, limits=LIMITS, max_payload_bytes=4_000_000)


def test_insufficient_report_is_persisted_linked_and_projection_is_read_only(tmp_path):
    archive = setup_archive(tmp_path / "ai.synthetic.sqlite3")
    try:
        result = _persist(archive)
        assert result.status == AnalystStatus.INSUFFICIENT_EVIDENCE
        before = tuple(archive.connection.execute(f"SELECT * FROM {table}").fetchall()
                       for table in ("ai_requests", "ai_responses", "ai_reports"))
        view = project_analysis(archive.connection, "output-1", limits=LIMITS, max_payload_bytes=100_000)
        after = tuple(archive.connection.execute(f"SELECT * FROM {table}").fetchall()
                      for table in ("ai_requests", "ai_responses", "ai_reports"))
        assert before == after
        assert view.ai_report.report_id == "report-1"
        report_record = json.loads(archive.connection.execute("SELECT payload FROM ai_reports WHERE report_id='report-1'").fetchone()[0])
        assert report_record["canonicalization_profile"] == "xau.canon.json-utf8-nfc-decimal-utc6.v1"
        assert report_record["framing_version"] == 1
        assert view.ai_report.status == "insufficient_evidence"
        assert view.analyst_outcome == "insufficient_evidence"
        assert view.ai_report.report["analysis"]["trade_stance"] == "NO TRADE"
        assert _persist(archive).status == AnalystStatus.INSUFFICIENT_EVIDENCE
        assert archive.connection.execute("SELECT count(*) FROM ai_reports").fetchone()[0] == 1
        with pytest.raises(ValueError, match="already exists"):
            _persist(archive, prompt_version="prompt-v2")
        archive.invalidate_revision("invalidate-after-report", "revision-1", END + timedelta(minutes=1), "correction")
        historical = project_analysis(archive.connection, "output-1", limits=LIMITS, max_payload_bytes=500_000)
        assert historical.status == "historical_invalidated"
        assert historical.ai_report.report_id == "report-1"
        assert historical.invalidation_warnings
        _assert_http_report(archive, "output-1")
        archive.verify_integrity()
    finally:
        archive.close()


def _assert_http_report(archive, analysis_id):
    import uvicorn
    from app.main import app
    previous = app.state.analysis_projection
    connection = sqlite3.connect(f"file:{archive.path}?mode=ro", uri=True, check_same_thread=False)
    app.state.analysis_projection = lambda identity: project_analysis(connection, identity,
        limits=LIMITS, max_payload_bytes=500_000, registry=REGISTRY)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        with urlopen(f"http://127.0.0.1:{port}/api/v1/analysis/{analysis_id}") as response:
            payload = json.loads(response.read())
        assert payload["analysis_id"] == analysis_id
        assert payload["ai_report"]["report_id"] == "report-1"
        assert payload["ai_report"]["status"] == "insufficient_evidence"
        assert payload["ai_report"]["report"]["analysis"]["trade_stance"] == "NO TRADE"
        assert connection.execute("SELECT count(*) FROM ai_reports").fetchone()[0] == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        app.state.analysis_projection = previous
        connection.close()


def test_insufficient_evidence_skips_injected_completion_and_records_no_external_call(tmp_path):
    for identity in ("failed", "bad"):
        archive = setup_archive(tmp_path / f"{identity}.synthetic.sqlite3")
        try:
            # The incomplete evidence gate prevents dispatch in this fixture, so it persists NO TRADE.
            called = []
            assert _persist(archive, lambda prompt: called.append(prompt)).status == AnalystStatus.INSUFFICIENT_EVIDENCE
            assert called == []
            assert archive.connection.execute("SELECT count(*) FROM ai_reports").fetchone()[0] == 1
        finally:
            archive.close()


@pytest.mark.parametrize("status", [AnalystStatus.UNAVAILABLE, AnalystStatus.INVALID_RESPONSE])
def test_failed_or_rejected_response_is_archived_without_a_report(tmp_path, monkeypatch, status):
    import app.ai.persistence as persistence
    archive = setup_archive(tmp_path / f"{status.value}.synthetic.sqlite3")
    original = persistence.run_analyst
    def failed(*args, **kwargs):
        run = original(*args, **kwargs)
        return run.model_copy(update={"status": status, "analysis": None, "report": None,
                                      "failure_reason": "synthetic_failure"})
    monkeypatch.setattr(persistence, "run_analyst", failed)
    try:
        assert _persist(archive).status == status
        assert archive.connection.execute("SELECT count(*) FROM ai_requests").fetchone()[0] == 1
        assert archive.connection.execute("SELECT count(*) FROM ai_responses").fetchone()[0] == 1
        assert archive.connection.execute("SELECT count(*) FROM ai_reports").fetchone()[0] == 0
    finally:
        archive.close()


@pytest.mark.parametrize("table,identity", [
    ("ai_requests", "request-1"), ("ai_responses", "response-1"), ("ai_reports", "report-1"),
])
def test_ai_record_digest_mismatch_fails_projection(tmp_path, table, identity):
    archive = setup_archive(tmp_path / f"digest-{table}.synthetic.sqlite3")
    try:
        _persist(archive)
        archive.connection.execute(f"DROP TRIGGER {table}_no_update")
        key = {"ai_requests": "request_id", "ai_responses": "response_id", "ai_reports": "report_id"}[table]
        archive.connection.execute(f"UPDATE {table} SET digest=? WHERE {key}=?", ("0" * 64, identity))
        with pytest.raises(ProjectionError):
            project_analysis(archive.connection, "output-1", limits=LIMITS, max_payload_bytes=4_000_000)
    finally:
        archive.close()


def test_complete_synthetic_response_is_persisted_and_projected_verbatim(tmp_path):
    archive = _complete_archive(tmp_path / "complete.synthetic.sqlite3")
    try:
        packet = _complete_packet()
        analyzed_packet = analyze_packet(packet)
        evidence_ids = {item.timeframe: next(record.evidence_id for record in analyzed_packet.evidence
            if record.timeframe == item.timeframe and record.quality == QualityStatus.VERIFIED)
            for item in analyzed_packet.timeframes}
        analysis = AnalysisResponse(analysis_id=packet.analysis_id, bias=Bias.NEUTRAL,
            trade_stance=TradeStance.WAIT,
            rationale=(Claim(text="Synthetic timeframe evidence is mixed.", evidence_ids=tuple(evidence_ids.values())),),
            evidence_sufficiency=EvidenceSufficiencyLabel.SUFFICIENT,
            timeframes=tuple(TimeframeAnalysis(timeframe=tf, direction="NEUTRAL",
                supporting_evidence_ids=(evidence_ids[tf],)) for tf in packet.requested_timeframes),
            confidence_explanation=(Claim(text="Evidence supports a cautious interpretation.",
                evidence_ids=(evidence_ids[Timeframe.H1],)),),
            provider_metadata=ProviderMetadata(provider_id="synthetic-fixture", model_id="synthetic-model",
                protocol=Protocol.OPENAI_CHAT_COMPLETIONS, analysis_request_id="request-1", generated_at=END,
                validation_status=ValidationState.UNVERIFIED))
        scenario = AnalystInterpretation(text="Wait for additional confirmation.",
            market_evidence_ids=(evidence_ids[Timeframe.H1],))
        response = AnalystResponseV1(analysis=analysis, bullish_scenario=scenario,
            bearish_scenario=scenario, neutral_conditions=scenario)
        result = _persist(archive, lambda _prompt: response.model_dump_json(), packet,
                          provider_id="synthetic-fixture", model_id="synthetic-model")
        assert result.status == AnalystStatus.COMPLETE
        projected = project_analysis(archive.connection, "output-1", limits=LIMITS, max_payload_bytes=4_000_000)
        assert projected.analyst_outcome == "complete"
        assert projected.timeframe_availability["4H"] == "unsupported"
        assert projected.ai_report.report["report"]["bullish_scenario"]["text"] == "Wait for additional confirmation."
        assert projected.ai_report.report["analysis"]["bias"] == "NEUTRAL"
    finally:
        archive.close()


def _complete_packet():
    instrument = InstrumentIdentity(instrument_id="xau-usd:spot-synthetic", instrument_type=InstrumentType.OTC_SPOT)
    frame_defs = ((Timeframe.D1, "1d", timedelta(days=1)), (Timeframe.H1, "1h", timedelta(hours=1)),
                  (Timeframe.M15, "15m", timedelta(minutes=15)), (Timeframe.M5, "5m", timedelta(minutes=5)))
    sources, frames, evidence = [], [], []
    for tf, suffix, duration in frame_defs:
        source_id = f"source-{suffix}"
        source = SourceIdentity(source_id=source_id, retrieval_id=f"retrieval-{suffix}", instrument=instrument,
            provider_id="synthetic-provider", feed_id="fixture", series_id=f"series-{suffix}",
            provider_symbol="XAUUSD", retrieved_at=END, price_normalization="source_decimal_text")
        sources.append(source)
        candles = []
        for index in range(200):
            opened = END - duration * (200 - index)
            candle = EvidenceCandle(candle_id=f"candle-{suffix}-{index}", source_id=source_id,
                retrieval_id=f"retrieval-{suffix}", revision_id=f"revision-{suffix}-{index}", timeframe=tf,
                opened_at=opened, closed_at=opened + duration, status=CandleState.CLOSED,
                origin=CandleOrigin.NATIVE, open="2000", high="2002", low="1999", close="2001")
            candles.append(candle)
        frames.append(TimeframeEvidence(timeframe=tf, state=TimeframeState.AVAILABLE,
            origin=CandleOrigin.NATIVE, source_ids=(source_id,), candles=tuple(candles)))
    return EvidencePacket(analysis_id="analysis-1", analysis_at=END, instrument=instrument, sources=tuple(sources),
        requested_timeframes=tuple(tf for tf, _, _ in frame_defs), retrieved_at=END,
        freshness_max_age_seconds={tf: 86400 for tf, _, _ in frame_defs},
        minimum_closed_candles={tf: 200 for tf, _, _ in frame_defs},
        timeframes=tuple(frames), evidence=tuple(evidence))


def _complete_archive(path):
    archive = SyntheticArchive(path, create=True, busy_timeout_ms=25)
    archive.store_evidence("complete", "synthetic-provider", "raw_provider_body", START, b"fixture",
        payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
    for timeframe in TIMEFRAMES:
        retrieval = f"retrieval-{timeframe}"
        archive.begin_retrieval(retrieval, f"series-{timeframe}", "xau-usd:synthetic", "synthetic-provider",
            timeframe, START, END, START)
        for index in range(200):
            archive.add_revision(f"revision-{timeframe}-{index}", f"logical-{timeframe}-{index}", retrieval, index)
        archive.finish_retrieval(retrieval, "verified", END, "complete")
        archive.promote_retrieval(retrieval)
    archive.create_manifest("input-1", {tf: (START, END) for tf in TIMEFRAMES}, END + timedelta(hours=1),
        limits=LIMITS, registry=REGISTRY, max_payload_bytes=4_000_000)
    return archive


def test_invalidated_source_rejects_new_persistence_and_history_remains(tmp_path):
    archive = setup_archive(tmp_path / "invalidated.synthetic.sqlite3")
    try:
        archive.invalidate_revision("invalidate-ai", "revision-1", END + timedelta(minutes=1), "correction")
        with pytest.raises(ValueError, match="invalidated"):
            _persist(archive)
        assert archive.connection.execute("SELECT count(*) FROM ai_requests").fetchone()[0] == 0
    finally:
        archive.close()


def test_atomic_ai_insert_rolls_back_and_crash_recovery_has_no_orphans(tmp_path):
    archive = setup_archive(tmp_path / "rollback.synthetic.sqlite3")
    try:
        archive.connection.execute("CREATE TRIGGER reject_ai_response BEFORE INSERT ON ai_responses "
                                   "BEGIN SELECT RAISE(ABORT,'synthetic crash'); END")
        with pytest.raises(Exception, match="synthetic crash"):
            _persist(archive)
        assert archive.connection.execute("SELECT count(*) FROM ai_requests").fetchone()[0] == 0
        assert archive.connection.execute("SELECT count(*) FROM ai_reports").fetchone()[0] == 0
    finally:
        archive.close()


def test_process_termination_during_ai_record_write_recovers_without_orphan(tmp_path):
    path = tmp_path / "ai-crash.synthetic.sqlite3"
    archive = setup_archive(path)
    persist_analysis(archive, "input-1", analysis_packet(), output_id="output-1", derived_id="derived-1",
        timeframe="1h", window_start=START, window_end=END, created_at=END,
        parameters=AnalysisParameters(), registry=REGISTRY, limits=LIMITS, max_payload_bytes=4_000_000,
        policy_id="synthetic-test-policy-v1")
    archive.close()
    code = ("import os,sys; from app.data.archive_prototype import SyntheticArchive; "
        "a=SyntheticArchive(sys.argv[1],busy_timeout_ms=25); a.connection.execute('BEGIN IMMEDIATE'); "
        "a.connection.execute(\"INSERT INTO ai_requests VALUES ('crash-request','output-1','x','xau.ai-request.v1',x'00')\"); "
        "os._exit(19)")
    child = subprocess.run([sys.executable, "-c", code, str(path)], check=False, capture_output=True)
    assert child.returncode == 19
    with SyntheticArchive(path, busy_timeout_ms=25) as recovered:
        assert recovered.connection.execute("SELECT count(*) FROM ai_requests").fetchone()[0] == 0
        assert recovered.connection.execute("SELECT count(*) FROM ai_responses").fetchone()[0] == 0
        assert recovered.connection.execute("SELECT count(*) FROM ai_reports").fetchone()[0] == 0
        recovered.verify_integrity()
