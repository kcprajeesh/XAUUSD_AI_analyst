"""Trust, revocation, and checkpoint fixtures use injected HMAC only; not Ed25519 tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import sqlite3

import pytest

from app.canonical import CanonicalLimits
from app.canonical_digest import digest_structured
from app.data.evidence_contracts import (REGISTRY_CHECKPOINT_SCHEMA, REGISTRY_REVOCATION_SCHEMA,
                                         structured_profile_registry)
from app.data.registry_approval import ApprovalError, ApprovalKey
from app.data.registry_prototype import RegistrarAuthority, SyntheticRegistry
from app.data.registry_trust import (Checkpoint, Revocation, ZERO_DIGEST, create_checkpoint,
    create_genesis_manifest, create_revocation, key_id, verify_checkpoint_bundle)


NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
REGISTRY = "xau.registry.fixture"
PRIMARY_PUBLIC = b"P" * 32
RECOVERY_PUBLIC = b"R" * 32
PRIMARY = ApprovalKey(key_id(PRIMARY_PUBLIC), 1, "project-owner", b"test-primary-secret",
    "test-hmac-sha256", "active", NOW - timedelta(days=2), NOW + timedelta(days=365))
RECOVERY = ApprovalKey(key_id(RECOVERY_PUBLIC), 1, "project-owner", b"test-recovery-secret",
    "test-hmac-sha256", "active", NOW - timedelta(days=2), NOW + timedelta(days=365))
KEYS = (PRIMARY, RECOVERY)
AUTHORITIES = (RegistrarAuthority("fixture-registrar", frozenset({"schema", "bundle"})),)


def sign(key, message):
    return hmac.new(key, message, hashlib.sha256).digest()


def verify(key, message, signature):
    return hmac.compare_digest(sign(key, message), signature)


def catalog(path):
    return SyntheticRegistry(path, registry_id=REGISTRY, create=True, busy_timeout_ms=100,
        authorities=AUTHORITIES, digest_registry=structured_profile_registry(), limits=LIMITS,
        max_payload_bytes=100_000)


def setup_genesis(cat):
    manifest = create_genesis_manifest(registry_id=REGISTRY, primary_public_key=PRIMARY_PUBLIC,
        recovery_public_key=RECOVERY_PUBLIC, primary_key=PRIMARY, recovery_key=RECOVERY,
        created_at=NOW, initial_checkpoint_id="checkpoint-0", digest_registry=cat.digest_registry,
        limits=LIMITS, max_payload_bytes=100_000, signer=sign)
    initial = create_checkpoint(checkpoint_id="checkpoint-0", registry_id=REGISTRY, sequence=0,
        previous_checkpoint_digest=None, revocation_digest=ZERO_DIGEST, trust_manifest_digest=manifest.digest,
        created_at=NOW, authority_key=PRIMARY, digest_registry=cat.digest_registry, limits=LIMITS,
        max_payload_bytes=100_000, signer=sign)
    cat.install_genesis_trust(manifest, initial, pinned_manifest_digest=manifest.digest,
        pinned_primary_fingerprint=PRIMARY.key_id, keys=KEYS, verifier=verify)
    return manifest, initial


def revoke(cat, previous, *, sequence=1, effective_sequence=1, authority=RECOVERY, target_kind="key", target_id=None):
    target_id = target_id or PRIMARY.key_id
    event = create_revocation(event_id=f"revocation-{sequence}", registry_id=REGISTRY, sequence=sequence,
        target_kind=target_kind, target_id=target_id, target_digest=None, reason_code="key_compromise",
        effective_sequence=effective_sequence, effective_at=NOW + timedelta(minutes=sequence),
        timestamp=NOW + timedelta(minutes=sequence),
        previous_checkpoint_digest=previous.digest, authority_key=authority,
        digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=sign)
    checkpoint = create_checkpoint(checkpoint_id=f"checkpoint-{sequence}", registry_id=REGISTRY,
        sequence=sequence, previous_checkpoint_digest=previous.digest, revocation_digest=event.digest,
        trust_manifest_digest=cat.connection.execute("SELECT manifest_digest FROM registry_trust_manifest").fetchone()[0],
        created_at=NOW + timedelta(minutes=sequence), authority_key=authority,
        digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=sign)
    return event, checkpoint


def reseal(value, schema, domain, cat):
    profile = next(item for item in cat.digest_registry.entries if item.domain == domain)
    return digest_structured(value, schema, profile, cat.digest_registry, LIMITS, 100_000).digest


def append(cat, event, checkpoint, previous, keys=KEYS):
    return cat.append_revocation(event, checkpoint, trusted_checkpoint_digest=previous.digest,
        authorized_authority_key_ids=frozenset({PRIMARY.key_id, RECOVERY.key_id}), keys=keys, verifier=verify)


def test_genesis_is_pinned_out_of_band_and_binds_recovery_key(tmp_path):
    with catalog(tmp_path / "genesis.synthetic.sqlite3") as cat:
        manifest, initial = setup_genesis(cat)
        assert initial.value["sequence"] == 0
        assert initial.value["revocation_digest"] == ZERO_DIGEST
        with pytest.raises(ApprovalError, match="out_of_band_pin"):
            cat.install_genesis_trust(manifest, initial, pinned_manifest_digest="0" * 64,
                pinned_primary_fingerprint=PRIMARY.key_id, keys=KEYS, verifier=verify)
        with pytest.raises(ApprovalError, match="out_of_band_pin"):
            verify_checkpoint_bundle(manifest=manifest, checkpoints=(initial,), revocations=(),
                pinned_manifest_digest=manifest.digest, pinned_primary_fingerprint="wrong-fingerprint",
                pinned_checkpoint_digest=initial.digest, keys=KEYS, digest_registry=cat.digest_registry,
                limits=LIMITS, max_payload_bytes=100_000, verifier=verify)


def test_recovery_key_can_sign_emergency_compromise_revocation_and_checkpoint(tmp_path):
    with catalog(tmp_path / "recovery.synthetic.sqlite3") as cat:
        manifest, initial = setup_genesis(cat)
        event, checkpoint = revoke(cat, initial, authority=RECOVERY, effective_sequence=0)
        assert event.value["effective_sequence"] == 0
        assert append(cat, event, checkpoint, initial) == checkpoint.digest
        assert cat.verify_revocation_integrity() is None
        assert verify_checkpoint_bundle(manifest=manifest, checkpoints=(initial, checkpoint),
            revocations=(event,), pinned_manifest_digest=manifest.digest,
            pinned_primary_fingerprint=PRIMARY.key_id, pinned_checkpoint_digest=checkpoint.digest,
            keys=KEYS, digest_registry=cat.digest_registry, limits=LIMITS,
            max_payload_bytes=100_000, verifier=verify)
        compromised_event, compromised_checkpoint = revoke(cat, checkpoint, sequence=2, authority=PRIMARY)
        with pytest.raises(ApprovalError, match="revoked_authority"):
            append(cat, compromised_event, compromised_checkpoint, checkpoint)
        recovery_event, recovery_checkpoint = revoke(cat, checkpoint, sequence=2, authority=RECOVERY)
        assert append(cat, recovery_event, recovery_checkpoint, checkpoint) == recovery_checkpoint.digest


@pytest.mark.parametrize("tamper", ["unsigned", "invalid_signature", "broken_link"])
def test_unsigned_invalid_signature_and_broken_checkpoint_link_are_rejected(tmp_path, tamper):
    with catalog(tmp_path / f"{tamper}.synthetic.sqlite3") as cat:
        _, initial = setup_genesis(cat)
        event, checkpoint = revoke(cat, initial)
        if tamper == "unsigned":
            value = event.value | {"signature": ""}
            event = Revocation(value, reseal(value, REGISTRY_REVOCATION_SCHEMA, "registry.revocation", cat))
        elif tamper == "invalid_signature":
            value = event.value | {"signature": "00" * 32}
            event = Revocation(value, reseal(value, REGISTRY_REVOCATION_SCHEMA, "registry.revocation", cat))
        else:
            value = checkpoint.value | {"previous_checkpoint_digest": "f" * 64}
            checkpoint = Checkpoint(value, reseal(value, REGISTRY_CHECKPOINT_SCHEMA, "registry.checkpoint", cat))
        with pytest.raises(ApprovalError):
            append(cat, event, checkpoint, initial)
        assert cat.connection.execute("SELECT count(*) FROM registry_revocations").fetchone()[0] == 0


def test_duplicate_sequence_rollback_and_old_offline_checkpoint_replay_fail(tmp_path):
    with catalog(tmp_path / "sequence.synthetic.sqlite3") as cat:
        _, initial = setup_genesis(cat)
        event1, checkpoint1 = revoke(cat, initial)
        append(cat, event1, checkpoint1, initial)
        with pytest.raises(ApprovalError, match="checkpoint_mismatch"):
            append(cat, event1, checkpoint1, initial)
        event2, checkpoint2 = revoke(cat, checkpoint1, sequence=2)
        with pytest.raises(ApprovalError, match="checkpoint_mismatch"):
            append(cat, event2, checkpoint2, initial)
        assert append(cat, event2, checkpoint2, checkpoint1) == checkpoint2.digest


def test_deleted_revocation_is_detected_and_rows_are_immutable(tmp_path):
    with catalog(tmp_path / "delete.synthetic.sqlite3") as cat:
        _, initial = setup_genesis(cat)
        event, checkpoint = revoke(cat, initial)
        append(cat, event, checkpoint, initial)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            cat.connection.execute("DELETE FROM registry_revocations WHERE event_id=?", (event.value["event_id"],))
        cat.connection.execute("DROP TRIGGER registry_revocations_immutable_delete")
        cat.connection.execute("DELETE FROM registry_revocations WHERE event_id=?", (event.value["event_id"],))
        with pytest.raises(ValueError, match="incomplete"):
            cat.verify_revocation_integrity()


def test_independent_verifier_rejects_missing_event_and_replayed_checkpoint(tmp_path):
    with catalog(tmp_path / "external-checkpoint.synthetic.sqlite3") as cat:
        manifest, initial = setup_genesis(cat)
        event, checkpoint = revoke(cat, initial)
        append(cat, event, checkpoint, initial)
        args = dict(manifest=manifest, checkpoints=(initial, checkpoint), revocations=(event,),
            pinned_manifest_digest=manifest.digest, pinned_primary_fingerprint=PRIMARY.key_id,
            keys=KEYS, digest_registry=cat.digest_registry, limits=LIMITS,
            max_payload_bytes=100_000, verifier=verify)
        with pytest.raises(ApprovalError, match="history_incomplete"):
            verify_checkpoint_bundle(**(args | {"revocations": ()}), pinned_checkpoint_digest=checkpoint.digest)
        with pytest.raises(ApprovalError, match="pin_mismatch"):
            verify_checkpoint_bundle(**args, pinned_checkpoint_digest=initial.digest)

