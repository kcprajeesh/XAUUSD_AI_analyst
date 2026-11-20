"""Synthetic immutable input-to-analysis provenance workflow."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json

import pytest

from app.ai.evidence import (CandleOrigin, CandleState, EvidenceCandle, EvidencePacket, InstrumentIdentity,
    InstrumentType, SourceIdentity, Timeframe, TimeframeEvidence, TimeframeState)
from app.analysis import provenance as workflow
from app.analysis.engine import AnalysisParameters
from app.ai.analyst import AnalystProvenance, AnalystStatus, run_analyst
from app.data.context import process_context
from app.canonical import CanonicalLimits
from app.data.archive_prototype import SyntheticArchive, TIMEFRAMES
from app.data.evidence_contracts import structured_profile_registry
from app.data.archive_prototype import _utc


START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=1)
LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
REGISTRY = structured_profile_registry()


def setup_archive(path, revision="revision-1", *, start=START, end=END):
    archive = SyntheticArchive(path, create=True, busy_timeout_ms=25)
    archive.store_evidence("complete", "synthetic-provider", "raw_provider_body", start, b"fixture",
        payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
    for timeframe in TIMEFRAMES:
        retrieval = f"retrieval-{timeframe}"
        archive.begin_retrieval(retrieval, f"series-{timeframe}", "xau-usd:synthetic", "synthetic-provider",
            timeframe, start, end, start)
        rev = revision if timeframe == "1h" else f"revision-{timeframe}"
        archive.add_revision(rev, f"logical-{timeframe}", retrieval, 0)
        archive.finish_retrieval(retrieval, "verified", end, "complete")
        archive.promote_retrieval(retrieval)
    manifest_created_at = START + timedelta(hours=1) if (start, end) == (START, END) else end + timedelta(hours=1)
    archive.create_manifest("input-1", {tf: (start, end) for tf in TIMEFRAMES}, manifest_created_at,
        limits=LIMITS, registry=REGISTRY, max_payload_bytes=100_000)
    return archive


def analysis_packet(revision="revision-1"):
    instrument = InstrumentIdentity(instrument_id="xau-usd:spot-synthetic", instrument_type=InstrumentType.OTC_SPOT)
    source = SourceIdentity(source_id="source-1", retrieval_id="retrieval-1h", instrument=instrument,
        provider_id="synthetic-provider", feed_id="fixture", series_id="series-1h", provider_symbol="XAUUSD",
        retrieved_at=END, price_normalization="source_decimal_text")
    candle = EvidenceCandle(candle_id="candle-1", source_id="source-1", retrieval_id="retrieval-1h",
        revision_id=revision, timeframe=Timeframe.H1, opened_at=START, closed_at=START + timedelta(hours=1),
        status=CandleState.CLOSED, origin=CandleOrigin.NATIVE, open=Decimal("2000"), high=Decimal("2002"),
        low=Decimal("1999"), close=Decimal("2001"))
    frames = [TimeframeEvidence(timeframe=tf, state=TimeframeState.UNAVAILABLE) for tf in Timeframe]
    frames[list(Timeframe).index(Timeframe.H1)] = TimeframeEvidence(timeframe=Timeframe.H1,
        state=TimeframeState.AVAILABLE, origin=CandleOrigin.NATIVE, source_ids=("source-1",), candles=(candle,))
    return EvidencePacket(analysis_id="analysis-1", analysis_at=END, instrument=instrument, sources=(source,),
        requested_timeframes=tuple(Timeframe), retrieved_at=END, timeframes=tuple(frames))


def run(archive, packet=None, *, output="output-1", derived="derived-1", window_start=START,
        window_end=END, created_at=END):
    return workflow.persist_analysis(archive, "input-1", packet or analysis_packet(), output_id=output,
        derived_id=derived, timeframe="1h", window_start=window_start, window_end=window_end, created_at=created_at,
        parameters=AnalysisParameters(), registry=REGISTRY, limits=LIMITS, max_payload_bytes=100_000,
        policy_id="synthetic-test-policy-v1", unavailable_inputs=("4h:H4-03",))


def test_same_input_algorithm_and_parameters_reproduce_and_replay_is_immutable(tmp_path):
    archive = setup_archive(tmp_path / "analysis.synthetic.sqlite3")
    try:
        first = run(archive)
        assert run(archive)[:2] == first[:2]
        rows = archive.connection.execute("SELECT count(*) FROM analysis_outputs").fetchone()[0]
        assert rows == 1
        assert archive.connection.execute("SELECT count(*) FROM derived_manifests").fetchone()[0] == 1
        saved = json.loads(archive.connection.execute(
            "SELECT payload FROM derived_manifests WHERE derived_id='derived-1'").fetchone()[0])
        assert "4H:unavailable" in saved["unavailable_inputs"]
        assert saved["input_manifest_digest"] == archive.connection.execute(
            "SELECT digest FROM manifests WHERE manifest_id='input-1'").fetchone()[0]
        changed = analysis_packet()
        frames = list(changed.timeframes)
        selected = frames[list(Timeframe).index(Timeframe.H1)]
        changed_candle = selected.candles[0].model_copy(update={"close": Decimal("2001.5")})
        frames[list(Timeframe).index(Timeframe.H1)] = selected.model_copy(update={"candles": (changed_candle,)})
        changed = changed.model_copy(update={"timeframes": tuple(frames)})
        with pytest.raises(ValueError, match="already exists"):
            run(archive, changed)
        archive.verify_integrity()
    finally:
        archive.close()


def test_revision_and_algorithm_version_change_provenance(tmp_path, monkeypatch):
    first_archive = setup_archive(tmp_path / "first.synthetic.sqlite3", "revision-1")
    second_archive = setup_archive(tmp_path / "second.synthetic.sqlite3", "revision-2")
    try:
        first = run(first_archive)
        changed_revision = run(second_archive, analysis_packet("revision-2"))
        assert first[0].digest != changed_revision[0].digest
        assert first[1].digest != changed_revision[1].digest
        monkeypatch.setattr(workflow, "ANALYSIS_ALGORITHM_VERSION", "2")
        versioned = run(second_archive, analysis_packet("revision-2"), output="output-v2", derived="derived-v2")
        assert versioned[1].digest != changed_revision[1].digest
        payload = json.loads(second_archive.connection.execute(
            "SELECT payload FROM derived_manifests WHERE derived_id='derived-v2'").fetchone()[0])
        assert payload["algorithm_version"] == "2"
    finally:
        first_archive.close()
        second_archive.close()


def test_invalidated_inputs_reject_new_analysis_but_keep_history_warning(tmp_path):
    archive = setup_archive(tmp_path / "analysis.synthetic.sqlite3")
    try:
        run(archive)
        archive.invalidate_revision("invalidate-1", "revision-1", END + timedelta(minutes=1), "correction")
        assert archive.provenance_warnings("derived-1") == ("revision-1",)
        with pytest.raises(ValueError, match="invalidated"):
            run(archive, output="output-2", derived="derived-2")
        assert archive.connection.execute("SELECT count(*) FROM derived_manifests").fetchone()[0] == 1
    finally:
        archive.close()


def test_missing_packet_revision_cannot_become_valid_and_failed_pair_rolls_back(tmp_path):
    archive = setup_archive(tmp_path / "analysis.synthetic.sqlite3")
    try:
        with pytest.raises(ValueError, match="lineage outside"):
            run(archive, analysis_packet("not-selected"))
        archive.connection.execute("CREATE TRIGGER reject_derived BEFORE INSERT ON derived_manifests "
                                   "BEGIN SELECT RAISE(ABORT,'synthetic interruption'); END")
        with pytest.raises(Exception, match="synthetic interruption"):
            run(archive)
        assert archive.connection.execute("SELECT count(*) FROM analysis_outputs").fetchone()[0] == 0
        assert archive.connection.execute("SELECT count(*) FROM derived_manifests").fetchone()[0] == 0
        archive.connection.execute("DROP TRIGGER reject_derived")
        run(archive)
        archive.verify_integrity()
    finally:
        archive.close()


def test_process_crash_during_output_manifest_pair_insert_recovers_without_orphan(tmp_path):
    path = tmp_path / "crash.synthetic.sqlite3"
    archive = setup_archive(path)
    archive.close()
    code = (
        "import os,sys; from app.data.archive_prototype import SyntheticArchive; "
        "a=SyntheticArchive(sys.argv[1],busy_timeout_ms=25); a.connection.execute('BEGIN IMMEDIATE'); "
        "a.connection.execute(\"INSERT INTO analysis_outputs VALUES ('crash-output','input-1','x','xau.analysis-output.v1',x'00')\"); "
        "os._exit(19)"
    )
    import subprocess, sys
    child = subprocess.run([sys.executable, "-c", code, str(path)], check=False, capture_output=True)
    assert child.returncode == 19
    with SyntheticArchive(path, busy_timeout_ms=25) as recovered:
        assert recovered.connection.execute("SELECT count(*) FROM analysis_outputs").fetchone()[0] == 0
        assert recovered.connection.execute("SELECT count(*) FROM derived_manifests").fetchone()[0] == 0
        recovered.verify_integrity()


def test_end_to_end_manifest_analysis_context_ai_insufficient_evidence(tmp_path):
    archive = setup_archive(tmp_path / "end-to-end.synthetic.sqlite3")
    try:
        output_meta, derived_meta, analyzed = run(archive)
        input_digest = archive.connection.execute("SELECT digest FROM manifests WHERE manifest_id='input-1'").fetchone()[0]
        provenance = AnalystProvenance(input_manifest_id="input-1", input_manifest_digest=input_digest,
            derived_manifest_id="derived-1", derived_manifest_digest=derived_meta.digest,
            provider_id="synthetic-no-call", model_id="not-invoked", analysis_request_id="request-not-invoked",
            prompt_version="analyst-prompt-v1",
            configuration_metadata=(("response_schema", "1.0"), ("external_calls_enabled", False)), created_at=END)
        context = process_context(retrieved_at=END, source_registry_version="fixture-only-v1")
        result = run_analyst(analyzed, context, provenance, None,
            verify_binding=lambda p: archive.verify_analyst_binding(p.input_manifest_id, p.input_manifest_digest,
                p.derived_manifest_id, p.derived_manifest_digest))
        assert output_meta.digest and result.status == AnalystStatus.INSUFFICIENT_EVIDENCE
        assert result.analysis.trade_stance.value == "NO TRADE"
        assert result.context_status["macro"].value == "unavailable"
        archive.invalidate_revision("e2e-invalidation", "revision-1", END + timedelta(minutes=1), "correction")
        with pytest.raises(ValueError, match="invalidated"):
            archive.verify_analyst_binding("input-1", input_digest, "derived-1", derived_meta.digest)
        assert archive.provenance_warnings("derived-1") == ("revision-1",)
        archive.verify_integrity()
    finally:
        archive.close()
