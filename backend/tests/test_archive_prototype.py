"""Disposable synthetic state-machine tests; no existing database or network is used."""

from datetime import UTC, datetime, timedelta
import sqlite3
import subprocess
import sys

import pytest

from app.data.archive_prototype import RETENTION_DAYS, SyntheticArchive, TIMEFRAMES
from app.canonical import CanonicalLimits
from app.data.evidence_contracts import structured_profile_registry


START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 2, tzinfo=UTC)
TEST_BUSY_TIMEOUT_MS = 25
TEST_LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
TEST_REGISTRY = structured_profile_registry()


def create_manifest(archive, manifest_id, requested_ranges, created_at):
    return archive.create_manifest(manifest_id, requested_ranges, created_at, limits=TEST_LIMITS,
                                   registry=TEST_REGISTRY, max_payload_bytes=100_000)


def make_archive(tmp_path):
    path = tmp_path / "archive.synthetic.sqlite3"
    return path, SyntheticArchive(path, create=True, busy_timeout_ms=TEST_BUSY_TIMEOUT_MS)


def seed_evidence(archive, evidence_id="contract-evidence", at=START):
    archive.store_evidence(evidence_id, "synthetic-provider", "raw_provider_body", at,
                           b"synthetic completeness evidence", payload_retention_permitted=True,
                           metadata_retention_permitted=True, credential_free=True)


def seed_retrieval(archive, timeframe, retrieval_id=None, *, started=START,
                   requested_start=START, requested_end=END, revision_id=None):
    retrieval_id = retrieval_id or f"retrieval-{timeframe}"
    revision_id = revision_id or f"{retrieval_id}-revision"
    archive.begin_retrieval(retrieval_id, f"series-{timeframe}", "xau-usd:synthetic", "synthetic-provider", timeframe,
                            requested_start, requested_end, started)
    archive.add_revision(revision_id, f"logical-{timeframe}", retrieval_id, 0)
    archive.finish_retrieval(retrieval_id, "verified", started + timedelta(minutes=1), "contract-evidence")
    return retrieval_id, revision_id


def seed_all(archive):
    seed_evidence(archive)
    for timeframe in sorted(TIMEFRAMES):
        retrieval_id, _ = seed_retrieval(archive, timeframe)
        assert archive.promote_retrieval(retrieval_id) == 1


def ranges():
    return {timeframe: (START, END) for timeframe in TIMEFRAMES}


def test_retention_permission_and_expiry_keep_audit_metadata(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        archive.store_evidence("allowed", "source", "raw_provider_body", START, b"body",
                               payload_retention_permitted=True, metadata_retention_permitted=True,
                               credential_free=True)
        archive.store_evidence("denied", "restricted", "raw_provider_body", START, b"secret body",
                               payload_retention_permitted=False, metadata_retention_permitted=True,
                               credential_free=True)
        archive.store_evidence("credential", "source", "ai_prompt_response", START, b"possible credential",
                               payload_retention_permitted=True, metadata_retention_permitted=True,
                               credential_free=False)
        assert not archive.store_evidence("no-metadata", "restricted", "raw_provider_body", START, b"body",
            payload_retention_permitted=False, metadata_retention_permitted=False, credential_free=True)
        assert archive.expire_evidence(START + timedelta(days=30)) == 1
        rows = {row["evidence_id"]: row for row in archive.connection.execute("SELECT * FROM evidence")}
        assert rows["allowed"]["payload"] is None
        assert rows["allowed"]["payload_length"] == 4
        assert rows["allowed"]["retention_state"] == "expired"
        assert rows["allowed"]["deleted_at"] == "2026-01-31T00:00:00.000000Z"
        assert rows["denied"]["payload"] is None
        assert rows["denied"]["retention_state"] == "permission_denied"
        assert rows["credential"]["payload"] is None
        assert rows["credential"]["retention_state"] == "permission_denied"
        assert "no-metadata" not in rows
    finally:
        archive.close()


def test_approved_evidence_retention_classes_are_exact():
    assert RETENTION_DAYS == {
        "raw_provider_body": 30,
        "ai_prompt_response": 30,
        "rejected_row": 90,
        "duplicate_occurrence": 90,
    }


def test_verified_whole_retrievals_promote_and_manifest_one_per_timeframe(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_all(archive)
        create_manifest(archive, "manifest-1", ranges(), START + timedelta(hours=1))
        items = archive.connection.execute(
            "SELECT timeframe,retrieval_id,generation FROM manifest_items WHERE manifest_id='manifest-1'").fetchall()
        assert len(items) == 5
        assert {row["timeframe"] for row in items} == TIMEFRAMES
        assert len({row["retrieval_id"] for row in items}) == 5
        assert all(row["generation"] == 1 for row in items)
    finally:
        archive.close()


def test_unverified_or_partial_retrieval_cannot_be_promoted_or_stitched(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_evidence(archive)
        for timeframe in sorted(TIMEFRAMES):
            end = END - timedelta(hours=1) if timeframe == "1h" else END
            retrieval_id, _ = seed_retrieval(archive, timeframe, requested_end=end)
            archive.promote_retrieval(retrieval_id)
        with pytest.raises(ValueError, match="does not cover"):
            create_manifest(archive, "stitched", ranges(), START + timedelta(hours=1))

        archive.begin_retrieval("unsupported", "series-5m", "xau-usd:synthetic", "synthetic-provider",
                                "5m", START, END, START)
        archive.finish_retrieval("unsupported", "unsupported", START + timedelta(minutes=1))
        with pytest.raises(ValueError, match="verified complete"):
            archive.promote_retrieval("unsupported")
    finally:
        archive.close()


def test_manifest_requires_all_timeframes_exact_range_and_common_instrument(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_all(archive)
        with pytest.raises(ValueError, match="all five"):
            create_manifest(archive, "partial", {"1h": (START, END)}, START)
        bad = ranges()
        bad["1h"] = (START + timedelta(hours=1), END)
        with pytest.raises(ValueError, match="exact requested range"):
            create_manifest(archive, "wrong-range", bad, START)
    finally:
        archive.close()


def test_completeness_evidence_must_belong_to_the_retrieval_provider(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_evidence(archive, evidence_id="other-provider", at=START)
        archive.begin_retrieval("foreign-evidence", "series-1h", "xau-usd:synthetic", "provider-a",
                                "1h", START, END, START)
        with pytest.raises(ValueError, match="belong to the retrieval provider"):
            archive.finish_retrieval("foreign-evidence", "verified", START + timedelta(minutes=1),
                                     "other-provider")
        assert archive.connection.execute(
            "SELECT completeness FROM retrievals WHERE retrieval_id='foreign-evidence'").fetchone()[0] == "collecting"
    finally:
        archive.close()


def test_invalidation_blocks_new_inputs_and_flags_existing_manifest(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_all(archive)
        create_manifest(archive, "before-invalidation", ranges(), START + timedelta(hours=1))
        archive.record_analysis("analysis-1", "before-invalidation", START + timedelta(hours=1, minutes=1))
        archive.invalidate_revision("event-1", "retrieval-1h-revision", START + timedelta(hours=2), "source_correction")
        assert archive.manifest_invalidation_warnings("before-invalidation") == ("retrieval-1h-revision",)
        assert archive.analysis_invalidation_warnings("analysis-1") == ("retrieval-1h-revision",)
        with pytest.raises(ValueError, match="invalidated evidence"):
            create_manifest(archive, "after-invalidation", ranges(), START + timedelta(hours=3))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            archive.connection.execute("DELETE FROM invalidations WHERE event_id='event-1'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable historical analysis"):
            archive.connection.execute("DELETE FROM analysis_records WHERE analysis_id='analysis-1'")
    finally:
        archive.close()


def test_generation_advances_only_to_newer_verified_retrieval(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_evidence(archive)
        first, _ = seed_retrieval(archive, "1h", "first", started=START)
        assert archive.promote_retrieval(first) == 1
        with pytest.raises(ValueError, match="newer whole retrieval"):
            archive.promote_retrieval(first)
        second, _ = seed_retrieval(archive, "1h", "second", started=START + timedelta(hours=1))
        assert archive.promote_retrieval(second) == 2
        delayed, _ = seed_retrieval(archive, "1h", "delayed", started=START + timedelta(minutes=30))
        with pytest.raises(ValueError, match="newer whole retrieval"):
            archive.promote_retrieval(delayed)
        assert tuple(archive.connection.execute(
            "SELECT generation,retrieval_id FROM generation_heads WHERE series_id='series-1h'").fetchone()) == (2, "second")
    finally:
        archive.close()


def test_partial_retrievals_cannot_be_stitched_and_old_generation_is_not_fallback(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_evidence(archive)
        for timeframe in sorted(TIMEFRAMES - {"1h"}):
            retrieval_id, _ = seed_retrieval(archive, timeframe)
            archive.promote_retrieval(retrieval_id)
        first, _ = seed_retrieval(archive, "1h", "first-half", requested_start=START,
                                  requested_end=START + timedelta(hours=12))
        archive.promote_retrieval(first)
        second, _ = seed_retrieval(archive, "1h", "second-half", started=START + timedelta(hours=1),
                                   requested_start=START + timedelta(hours=12), requested_end=END)
        archive.promote_retrieval(second)
        with pytest.raises(ValueError, match="does not cover"):
            create_manifest(archive, "stitched-halves", ranges(), START + timedelta(hours=2))
        assert archive.connection.execute(
            "SELECT retrieval_id FROM generation_heads WHERE series_id='series-1h'").fetchone()[0] == second
    finally:
        archive.close()


def test_manifest_generation_snapshot_does_not_follow_later_promotion(tmp_path):
    _, archive = make_archive(tmp_path)
    try:
        seed_all(archive)
        create_manifest(archive, "snapshot-1", ranges(), START + timedelta(hours=1))
        later, _ = seed_retrieval(archive, "1h", "later", started=START + timedelta(hours=2))
        assert archive.promote_retrieval(later) == 2
        create_manifest(archive, "snapshot-2", ranges(), START + timedelta(hours=3))
        snapshots = {row[0]: (row[1], row[2]) for row in archive.connection.execute(
            "SELECT manifest_id,retrieval_id,generation FROM manifest_items WHERE timeframe='1h'")}
        assert snapshots == {"snapshot-1": ("retrieval-1h", 1), "snapshot-2": ("later", 2)}
    finally:
        archive.close()


def test_transaction_rollback_and_reopen_recover_committed_state(tmp_path):
    path, archive = make_archive(tmp_path)
    try:
        seed_all(archive)
        with pytest.raises(RuntimeError):
            with archive._transaction():
                archive.connection.execute("INSERT INTO manifests VALUES ('uncommitted',?,?,?,?)",
                    ("2026-01-01T00:00:00.000000Z", "gold", b"partial", "f" * 64))
                raise RuntimeError("synthetic interruption")
    finally:
        archive.close()
    with SyntheticArchive(path, busy_timeout_ms=TEST_BUSY_TIMEOUT_MS) as reopened:
        assert reopened.connection.execute("SELECT count(*) FROM generation_heads").fetchone()[0] == 5
        assert reopened.connection.execute("SELECT count(*) FROM manifests").fetchone()[0] == 0
        reopened.verify_integrity()


def test_process_crash_rolls_back_uncommitted_transaction_without_blob_orphans(tmp_path):
    path, archive = make_archive(tmp_path)
    archive.close()
    code = (
        "import os, sys; from app.data.archive_prototype import SyntheticArchive; "
        "archive = SyntheticArchive(sys.argv[1], busy_timeout_ms=25); "
        "archive.connection.execute('BEGIN IMMEDIATE'); "
        "archive.connection.execute(\"INSERT INTO archive_metadata VALUES ('crash_probe','partial')\"); "
        "os._exit(17)"
    )
    child = subprocess.run([sys.executable, "-c", code, str(path)], check=False, capture_output=True)
    assert child.returncode == 17
    with SyntheticArchive(path, busy_timeout_ms=TEST_BUSY_TIMEOUT_MS) as recovered:
        assert recovered.connection.execute(
            "SELECT 1 FROM archive_metadata WHERE key='crash_probe'").fetchone() is None
        assert recovered.verify_integrity() is None


def test_creation_refuses_overwriting_an_existing_file(tmp_path):
    path = tmp_path / "archive.synthetic.sqlite3"
    path.write_bytes(b"preserve me")
    with pytest.raises(FileExistsError):
        SyntheticArchive(path, create=True, busy_timeout_ms=TEST_BUSY_TIMEOUT_MS)
    assert path.read_bytes() == b"preserve me"


def test_explicit_test_busy_timeout_and_two_connection_writer_ownership(tmp_path):
    path, first = make_archive(tmp_path)
    second = SyntheticArchive(path, busy_timeout_ms=0)
    try:
        seed_evidence(first)
        retrieval_id, _ = seed_retrieval(first, "1h")
        with first._transaction():
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                second.promote_retrieval(retrieval_id)
        assert second.promote_retrieval(retrieval_id) == 1
        assert second.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 0
        first.verify_integrity()
        second.verify_integrity()
    finally:
        second.close()
        first.close()
