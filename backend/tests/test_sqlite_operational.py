"""Disposable SQLite operational/failure tests. No existing databases are opened."""
from datetime import UTC, datetime, timedelta
import sqlite3
import subprocess
import sys

import pytest

from app.data.archive_prototype import SyntheticArchive


NOW = datetime(2026, 11, 18, tzinfo=UTC)
BUSY_MS = 0


def archive(tmp_path):
    path = tmp_path / "ops.synthetic.sqlite3"
    return path, SyntheticArchive(path, create=True, busy_timeout_ms=BUSY_MS)


def test_wal_full_synchronous_and_reader_snapshot_during_writer_commit(tmp_path):
    path, writer = archive(tmp_path)
    reader = SyntheticArchive(path, busy_timeout_ms=BUSY_MS)
    try:
        assert writer.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert writer.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        reader.connection.execute("BEGIN")
        assert reader.connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 0
        writer.store_evidence("committed", "fixture", "raw_provider_body", NOW, b"body",
            payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
        assert reader.connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 0
        checkpoint = writer.connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        assert len(checkpoint) == 3
        reader.connection.execute("COMMIT")
        assert reader.connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
        assert writer.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    finally:
        reader.close()
        writer.close()


def test_writer_lock_fails_without_hidden_retry_then_explicit_retry_succeeds(tmp_path):
    _, first = archive(tmp_path)
    second = SyntheticArchive(first.path, busy_timeout_ms=BUSY_MS)
    try:
        with first._transaction():
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                second.store_evidence("retry", "fixture", "raw_provider_body", NOW, b"body",
                    payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
        assert second.connection.execute("SELECT count(*) FROM evidence WHERE evidence_id='retry'").fetchone()[0] == 0
        assert second.store_evidence("retry", "fixture", "raw_provider_body", NOW, b"body",
            payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
    finally:
        second.close()
        first.close()


@pytest.mark.parametrize("stage", ["evidence", "manifest", "invalidation"])
def test_process_crash_before_commit_recovers_each_archive_write_class(tmp_path, stage):
    path, db = archive(tmp_path)
    if stage == "invalidation":
        db.store_evidence("complete", "fixture", "raw_provider_body", NOW, b"evidence",
            payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
        db.begin_retrieval("r", "s", "xau-usd:fixture", "fixture", "1h", NOW,
            NOW + timedelta(hours=1), NOW)
        db.add_revision("rev", "logical", "r", 0)
        db.finish_retrieval("r", "verified", NOW + timedelta(minutes=1), "complete")
    db.close()
    statements = {
        "evidence": "INSERT INTO evidence VALUES ('crash-evidence','fixture','raw_provider_body','2026-11-18T00:00:00.000000Z','2026-12-18T00:00:00.000000Z',x'41',1,'retained',NULL)",
        "manifest": "INSERT INTO manifests VALUES ('crash-manifest','2026-11-18T00:00:00.000000Z','xau-usd:fixture',x'7b7d','" + "a" * 64 + "')",
        "invalidation": "INSERT INTO invalidations VALUES ('crash-event','rev','2026-11-18T00:00:00.000000Z','fixture')",
    }
    code = ("import os,sys; from app.data.archive_prototype import SyntheticArchive; "
            "a=SyntheticArchive(sys.argv[1],busy_timeout_ms=0); a.connection.execute('BEGIN IMMEDIATE'); "
            f"a.connection.execute({statements[stage]!r}); os._exit(31)")
    child = subprocess.run([sys.executable, "-c", code, str(path)], check=False, capture_output=True)
    assert child.returncode == 31
    with SyntheticArchive(path, busy_timeout_ms=BUSY_MS) as recovered:
        table, key = {"evidence": ("evidence", "evidence_id"), "manifest": ("manifests", "manifest_id"),
                      "invalidation": ("invalidations", "event_id")}[stage]
        assert recovered.connection.execute(f"SELECT 1 FROM {table} WHERE {key} LIKE 'crash-%'").fetchone() is None
        recovered.verify_integrity()


def test_disk_full_fault_rolls_back_without_partial_evidence(tmp_path):
    _, db = archive(tmp_path)
    try:
        pages = db.connection.execute("PRAGMA page_count").fetchone()[0]
        db.connection.execute(f"PRAGMA max_page_count={pages + 1}")
        with pytest.raises(sqlite3.OperationalError, match="full"):
            db.store_evidence("too-large", "fixture", "raw_provider_body", NOW, b"x" * 250_000,
                payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
        assert db.connection.execute("SELECT 1 FROM evidence WHERE evidence_id='too-large'").fetchone() is None
        db.verify_integrity()
    finally:
        db.close()


def test_online_backup_restore_keeps_archive_content_and_integrity(tmp_path):
    path, db = archive(tmp_path)
    db.store_evidence("checkpoint", "fixture", "raw_provider_body", NOW, b"checkpoint",
        payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
    backup_path = tmp_path / "backup.synthetic.sqlite3"
    target = sqlite3.connect(backup_path)
    try:
        db.connection.backup(target)
    finally:
        target.close()
        db.close()
    with SyntheticArchive(backup_path, busy_timeout_ms=BUSY_MS) as restored:
        assert restored.connection.execute("SELECT payload FROM evidence WHERE evidence_id='checkpoint'").fetchone()[0] == b"checkpoint"
        restored.verify_integrity()
