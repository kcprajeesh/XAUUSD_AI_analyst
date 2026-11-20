"""Approval contract and append-only history tests use synthetic HMAC keys only."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import subprocess
import sys
import sqlite3

import pytest

from app.canonical import CanonicalLimits
from app.canonical_digest import digest_structured
from app.data.evidence_contracts import REGISTRY_APPROVAL_V2_SCHEMA, structured_profile_registry
from app.data.registry_approval import (ApprovalError, ApprovalKey, create_approval,
                                        verify_approval)
from app.data.registry_prototype import (RegistrarAuthority, RegistryConflict, RegistryRelease,
                                         SyntheticRegistry)


NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
REGISTRARS = (RegistrarAuthority("fixture-registrar", frozenset({"schema", "bundle"})),)
KEY1 = ApprovalKey("synthetic-key", 1, "synthetic-project-owner", b"test-only-secret-v1",
                   "test-hmac-sha256", "active", NOW - timedelta(days=2), NOW + timedelta(days=2))


def sign(key, message):
    return hmac.new(key, message, hashlib.sha256).digest()


def verify(key, message, signature):
    return hmac.compare_digest(sign(key, message), signature)


def catalog(path, authorities=REGISTRARS):
    return SyntheticRegistry(path, registry_id="xau.registry.bundle", create=True, busy_timeout_ms=100, authorities=authorities,
        digest_registry=structured_profile_registry(), limits=LIMITS, max_payload_bytes=100_000)


def release(cat, *, previous=None, previous_digest=None, ref="synthetic://review-candidate"):
    return cat.export_release(created_at=NOW, prepared_by_registrar_id="fixture-registrar",
                              change_reference=ref, previous_release_id=previous, previous_release_digest=previous_digest)


def approval(cat, bundle, *, number=1, key=KEY1, decision="approve", approval_id=None,
             approver_id=None):
    signer_key = key
    if approver_id is not None:
        signer_key = replace(key, approver_id=approver_id)
    return create_approval(
        approval_id=approval_id or f"approval-{number}", registry_id=bundle.registry_id,
        registry_version=number, release=bundle, key=signer_key, approval_timestamp=NOW,
        decision=decision, compatibility_metadata={"classification": "compatible", "migration_notes": "synthetic fixture"},
        digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=sign,
    )


def verify_record(cat, record, bundle, keys=(KEY1,), *, new=False):
    return verify_approval(record, bundle, keys=keys, digest_registry=cat.digest_registry,
        limits=LIMITS, max_payload_bytes=100_000, verifier=verify, now=NOW, new_approval=new)


def reseal(cat, record):
    value = record.record_value()
    profile = next(item for item in cat.digest_registry.entries if item.domain == "registry.approval-record.v2")
    digest = digest_structured(value, REGISTRY_APPROVAL_V2_SCHEMA, profile, cat.digest_registry,
                               LIMITS, 100_000).digest
    return replace(record, record_digest=digest)


def test_valid_synthetic_signature_binds_exact_release_and_persists_once(tmp_path):
    with catalog(tmp_path / "approval.synthetic.sqlite3") as cat:
        bundle = release(cat)
        record = approval(cat, bundle)
        assert verify_record(cat, record, bundle, new=True)
        assert cat.record_approval(record, bundle, keys=(KEY1,), verifier=verify, now=NOW)
        assert not cat.record_approval(record, bundle, keys=(KEY1,), verifier=verify, now=NOW)
        assert cat.verify_recorded_approval(record.approval_id, bundle, keys=(KEY1,), verifier=verify, now=NOW)
        row, state = cat.approval_status(record.approval_id)
        assert (row["release_digest"], state) == (bundle.digest, "approve")
        cat.verify_integrity()


def test_invalid_signature_wrong_digest_and_tampered_release_are_rejected(tmp_path):
    with catalog(tmp_path / "bad-signature.synthetic.sqlite3") as cat:
        bundle = release(cat)
        record = approval(cat, bundle)
        wrong_key = replace(KEY1, verification_material=b"different-test-key")
        with pytest.raises(ApprovalError, match="signature_invalid"):
            verify_record(cat, record, bundle, keys=(wrong_key,))
        unknown_key = replace(KEY1, key_id="untrusted-key")
        unauthorized = approval(cat, bundle, key=unknown_key, approval_id="unauthorized")
        with pytest.raises(ApprovalError, match="key_unknown"):
            verify_record(cat, unauthorized, bundle, keys=(KEY1,))
        wrong_digest = reseal(cat, replace(record, release_digest="0" * 64))
        with pytest.raises(ApprovalError, match="binding_mismatch"):
            verify_record(cat, wrong_digest, bundle)
        tampered = replace(bundle, payload=bundle.payload.replace(b"fixture-registrar", b"forged-registrar"))
        with pytest.raises(ValueError, match="digest"):
            cat.record_approval(record, tampered, keys=(KEY1,), verifier=verify, now=NOW)


def test_release_registrar_cannot_self_approve_and_must_have_release_scope(tmp_path):
    path = tmp_path / "scope.synthetic.sqlite3"
    with catalog(path) as cat:
        bundle = release(cat)
        self_approved = approval(cat, bundle, approver_id="fixture-registrar")
        with pytest.raises(ApprovalError, match="self_approval"):
            verify_record(cat, self_approved, bundle,
                          keys=(replace(KEY1, approver_id="fixture-registrar"),))

    limited = SyntheticRegistry(path, registry_id="xau.registry.bundle", busy_timeout_ms=100,
        authorities=(RegistrarAuthority("fixture-registrar", frozenset({"schema"})),),
        digest_registry=structured_profile_registry(), limits=LIMITS, max_payload_bytes=100_000)
    try:
        with pytest.raises(PermissionError):
            limited.record_approval(approval(limited, bundle), bundle, keys=(KEY1,), verifier=verify, now=NOW)
    finally:
        limited.close()


def test_revoked_expired_and_superseded_keys_cannot_create_approvals(tmp_path):
    with catalog(tmp_path / "key-lifecycle.synthetic.sqlite3") as cat:
        bundle = release(cat)
        record = approval(cat, bundle)
        revoked = replace(KEY1, status="revoked")
        with pytest.raises(ApprovalError, match="key_revoked"):
            verify_record(cat, record, bundle, keys=(revoked,))
        expired = replace(KEY1, status="expired", valid_until=NOW - timedelta(seconds=1))
        with pytest.raises(ApprovalError, match="not_active"):
            verify_record(cat, record, bundle, keys=(expired,), new=True)
        superseded = replace(KEY1, status="superseded")
        with pytest.raises(ApprovalError, match="not_active"):
            verify_record(cat, record, bundle, keys=(superseded,), new=True)
        # A rotated-out key can still authenticate a historical decision made while it was valid.
        assert verify_record(cat, record, bundle, keys=(superseded,))


def test_key_rotation_versions_and_approval_revocation_are_immutable(tmp_path):
    with catalog(tmp_path / "key-rotation.synthetic.sqlite3") as cat:
        first_release = release(cat)
        first = approval(cat, first_release, number=1)
        assert cat.record_approval(first, first_release, keys=(KEY1,), verifier=verify, now=NOW)
        key2 = ApprovalKey("synthetic-key", 2, "synthetic-project-owner", b"test-only-secret-v2",
                           "test-hmac-sha256", "active", NOW, NOW + timedelta(days=30))
        second_release = release(cat, previous=first_release.release_id, previous_digest=first_release.digest, ref="synthetic://second-release")
        second = approval(cat, second_release, number=2, key=key2)
        assert cat.record_approval(second, second_release, keys=(key2,), verifier=verify, now=NOW)
        assert verify_record(cat, first, first_release, keys=(replace(KEY1, status="superseded"),))
        assert cat.verify_recorded_approval(second.approval_id, second_release,
                                            keys=(replace(KEY1, status="superseded"), key2),
                                            verifier=verify, now=NOW)
        with pytest.raises(ApprovalError, match="rollback_rejected"):
            cat.verify_recorded_approval(first.approval_id, first_release,
                keys=(replace(KEY1, status="superseded"), key2), verifier=verify, now=NOW)
        with pytest.raises(PermissionError, match="Unsigned local approval revocation is disabled"):
            cat.revoke_approval(first.approval_id, "revoke-1", "synthetic compromise rehearsal",
                actor_id="synthetic-project-owner", authorized_approver_ids=frozenset({"synthetic-project-owner"}),
                created_at=NOW + timedelta(minutes=1))
        assert cat.approval_status(first.approval_id)[1] == "approve"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            cat.connection.execute("UPDATE registry_approvals SET record_digest='x' WHERE approval_id=?",
                                  (first.approval_id,))
        cat.verify_integrity()


def test_approval_version_rollback_and_wrong_registry_version_fail(tmp_path):
    with catalog(tmp_path / "rollback.synthetic.sqlite3") as cat:
        first_release = release(cat)
        wrong_version = approval(cat, first_release, number=2)
        with pytest.raises(RegistryConflict, match="rollback"):
            cat.record_approval(wrong_version, first_release, keys=(KEY1,), verifier=verify, now=NOW)
        assert cat.connection.execute("SELECT count(*) FROM registry_approvals").fetchone()[0] == 0
        first = approval(cat, first_release, number=1)
        assert cat.record_approval(first, first_release, keys=(KEY1,), verifier=verify, now=NOW)
        second_release = release(cat, previous=first_release.release_id, previous_digest=first_release.digest, ref="synthetic://next")
        wrong_sequence = reseal(cat, replace(approval(cat, second_release, number=2), registry_version=3))
        with pytest.raises(ApprovalError, match="signature_invalid"):
            verify_record(cat, wrong_sequence, second_release)
        second = approval(cat, second_release, number=2)
        assert cat.record_approval(second, second_release, keys=(KEY1,), verifier=verify, now=NOW)


def test_approval_registry_identity_and_predecessor_digest_are_bound(tmp_path):
    with catalog(tmp_path / "approval-identity.synthetic.sqlite3") as cat:
        bundle = release(cat)
        record = approval(cat, bundle)
        substituted = reseal(cat, replace(record, registry_id="xau.registry.other"))
        with pytest.raises(ApprovalError, match="identity_or_release_format"):
            verify_record(cat, substituted, bundle)
        wrong_predecessor = reseal(cat, replace(record, previous_release_digest="f" * 64))
        with pytest.raises(ApprovalError, match="identity_or_release_format"):
            verify_record(cat, wrong_predecessor, bundle)

    other_path = tmp_path / "other-registry.synthetic.sqlite3"
    with catalog(other_path) as original:
        original_bundle = release(original)
        original_record = approval(original, original_bundle)
    other_path.unlink()
    other = SyntheticRegistry(other_path, registry_id="xau.registry.other", create=True, busy_timeout_ms=100,
        authorities=REGISTRARS, digest_registry=structured_profile_registry(), limits=LIMITS,
        max_payload_bytes=100_000)
    try:
        with pytest.raises(ValueError, match="Requested registry identity"):
            other.record_approval(original_record, original_bundle, keys=(KEY1,), verifier=verify, now=NOW)
    finally:
        other.close()


def test_process_crash_during_approval_insert_leaves_no_partial_history(tmp_path):
    path = tmp_path / "approval-crash.synthetic.sqlite3"
    catalog(path).close()
    code = ("import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); "
            "c.execute('INSERT INTO registry_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', "
            "('crash','xau.registry.bundle',1,'release','digest',None,'approve',b'{}','digest',"
            "'key',1,'owner','2026-11-19T12:00:00.000000Z')); os._exit(41)")
    child = subprocess.run([sys.executable, "-c", code, str(path)], check=False, capture_output=True)
    assert child.returncode == 41
    with SyntheticRegistry(path, registry_id="xau.registry.bundle", busy_timeout_ms=100, authorities=REGISTRARS,
            digest_registry=structured_profile_registry(), limits=LIMITS, max_payload_bytes=100_000) as restored:
        assert restored.connection.execute("SELECT count(*) FROM registry_approvals").fetchone()[0] == 0
        restored.verify_integrity()


def test_rejection_is_recorded_without_advancing_release_head(tmp_path):
    with catalog(tmp_path / "rejection.synthetic.sqlite3") as cat:
        bundle = release(cat)
        rejected = approval(cat, bundle, decision="reject", approval_id="rejected-candidate")
        assert cat.record_approval(rejected, bundle, keys=(KEY1,), verifier=verify, now=NOW)
        assert cat.approval_status(rejected.approval_id)[1] == "reject"
        approved = approval(cat, bundle, approval_id="approved-candidate")
        assert cat.record_approval(approved, bundle, keys=(KEY1,), verifier=verify, now=NOW)
