"""Real Ed25519 adapter tests; existing HMAC suites remain control-flow fixtures."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.canonical import CanonicalLimits, canonical_json
from app.canonical_digest import digest_structured, frame_payload
from app.data.evidence_contracts import (
    REGISTRY_APPROVAL_SIGNING_V2_SCHEMA,
    REGISTRY_APPROVAL_V2_SCHEMA,
    structured_profile_registry,
)
from app.data.registry_approval import ApprovalError, ApprovalKey, create_approval, verify_approval
from app.data.registry_prototype import RegistrarAuthority, SyntheticRegistry
from app.data.registry_signatures import ed25519_signer, ed25519_verify
from app.data.registry_trust import (
    ZERO_DIGEST,
    verify_checkpoint_bundle,
    create_checkpoint,
    create_genesis_manifest,
    create_revocation,
    key_id,
)


NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)
LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
REGISTRY_ID = "xau.registry.ed25519-fixture"
REGISTRARS = (RegistrarAuthority("fixture-registrar", frozenset({"schema", "bundle"})),)


def raw_public(private_key):
    return private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def approval_key(private_key, name):
    public = raw_public(private_key)
    return ApprovalKey(key_id(public), 1, name, public, "Ed25519", "active",
                       NOW - timedelta(days=1), NOW + timedelta(days=10))


def catalog(path):
    return SyntheticRegistry(path, registry_id=REGISTRY_ID, create=True, busy_timeout_ms=100,
        authorities=REGISTRARS, digest_registry=structured_profile_registry(), limits=LIMITS,
        max_payload_bytes=100_000)


def test_rfc8032_vector_raw_public_key_and_key_id():
    seed = bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc4"
        "4449c5697b326919703bac031cae7f60"
    )
    expected_public = bytes.fromhex(
        "d75a980182b10ab7d54bfed3c964073a"
        "0ee172f3daa62325af021a68f707511a"
    )
    expected_signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a"
        "84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46b"
        "d25bf5f0595bbe24655141438e7a100b"
    )
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = raw_public(private)
    assert len(public) == 32
    assert public == expected_public
    assert key_id(public) == hashlib.sha256(b"XAU-REGISTRY-ED25519-v1\x00" + public).hexdigest()
    assert private.sign(b"") == expected_signature
    assert ed25519_verify(public, b"", expected_signature)


def test_adapter_rejects_bad_signature_and_malformed_key_inputs():
    private = Ed25519PrivateKey.generate()
    public = raw_public(private)
    signature = private.sign(b"bound message")
    assert ed25519_verify(public, b"bound message", signature)
    assert not ed25519_verify(public, b"different message", signature)
    assert not ed25519_verify(public[:-1], b"bound message", signature)
    assert not ed25519_verify(public, b"bound message", signature[:-1])
    with pytest.raises(ValueError, match="public key does not match"):
        ed25519_signer({b"x" * 32: private})


def test_registry_approval_v2_uses_existing_framed_signing_bytes_and_rejects_tampering(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = raw_public(private)
    key = approval_key(private, "synthetic-owner")
    signer = ed25519_signer({public: private})

    with catalog(tmp_path / "approval-ed25519.synthetic.sqlite3") as cat:
        release = cat.export_release(created_at=NOW, prepared_by_registrar_id="fixture-registrar",
                                     change_reference="synthetic://ed25519")
        record = create_approval(
            approval_id="ed25519-approval", registry_id=REGISTRY_ID, registry_version=1,
            release=release, key=key, approval_timestamp=NOW, decision="approve",
            compatibility_metadata={"classification": "compatible", "migration_notes": "fixture"},
            digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=signer,
        )
        signing_profile = next(item for item in cat.digest_registry.entries
                               if item.domain == "registry.approval-signing.v2")
        message = frame_payload(canonical_json(record.signing_value(),
                                  REGISTRY_APPROVAL_SIGNING_V2_SCHEMA, LIMITS),
                                signing_profile, cat.digest_registry, 100_000)
        assert bytes.fromhex(record.signature) == private.sign(message)
        assert verify_approval(record, release, keys=(key,), digest_registry=cat.digest_registry,
            limits=LIMITS, max_payload_bytes=100_000, verifier=ed25519_verify, now=NOW, new_approval=True)
        assert cat.record_approval(record, release, keys=(key,), verifier=ed25519_verify, now=NOW)
        assert cat.verify_recorded_approval("ed25519-approval", release, keys=(key,),
            verifier=ed25519_verify, now=NOW)

        tampered = replace(record, decision="reject", record_digest="")
        profile = next(item for item in cat.digest_registry.entries
                       if item.domain == "registry.approval-record.v2")
        tampered = replace(tampered, record_digest=digest_structured(
            tampered.record_value(), REGISTRY_APPROVAL_V2_SCHEMA, profile, cat.digest_registry,
            LIMITS, 100_000).digest)
        with pytest.raises(ApprovalError, match="signature_invalid"):
            verify_approval(tampered, release, keys=(key,), digest_registry=cat.digest_registry,
                limits=LIMITS, max_payload_bytes=100_000, verifier=ed25519_verify, now=NOW)

        wrong_registry = replace(record, registry_id="xau.registry.other", record_digest="")
        wrong_registry = replace(wrong_registry, record_digest=digest_structured(
            wrong_registry.record_value(), REGISTRY_APPROVAL_V2_SCHEMA, profile, cat.digest_registry,
            LIMITS, 100_000).digest)
        with pytest.raises(ApprovalError, match="registry_identity_or_release_format_mismatch"):
            verify_approval(wrong_registry, release, keys=(key,), digest_registry=cat.digest_registry,
                limits=LIMITS, max_payload_bytes=100_000, verifier=ed25519_verify, now=NOW)


def test_real_ed25519_key_is_rejected_after_synthetic_revocation(tmp_path):
    primary_private = Ed25519PrivateKey.generate()
    recovery_private = Ed25519PrivateKey.generate()
    primary_public, recovery_public = raw_public(primary_private), raw_public(recovery_private)
    primary, recovery = approval_key(primary_private, "synthetic-owner"), approval_key(recovery_private, "synthetic-owner")
    signer = ed25519_signer({primary_public: primary_private, recovery_public: recovery_private})
    keys = (primary, recovery)

    with catalog(tmp_path / "revoked-ed25519.synthetic.sqlite3") as cat:
        release = cat.export_release(created_at=NOW, prepared_by_registrar_id="fixture-registrar",
                                     change_reference="synthetic://revocation")
        approval = create_approval(approval_id="before-revocation", registry_id=REGISTRY_ID,
            registry_version=1, release=release, key=primary, approval_timestamp=NOW,
            decision="approve", compatibility_metadata={"classification": "compatible", "migration_notes": "fixture"},
            digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=signer)
        assert verify_approval(approval, release, keys=keys, digest_registry=cat.digest_registry,
            limits=LIMITS, max_payload_bytes=100_000, verifier=ed25519_verify, now=NOW)

        manifest = create_genesis_manifest(registry_id=REGISTRY_ID, primary_public_key=primary_public,
            recovery_public_key=recovery_public, primary_key=primary, recovery_key=recovery, created_at=NOW,
            initial_checkpoint_id="checkpoint-0", digest_registry=cat.digest_registry, limits=LIMITS,
            max_payload_bytes=100_000, signer=signer)
        initial = create_checkpoint(checkpoint_id="checkpoint-0", registry_id=REGISTRY_ID, sequence=0,
            previous_checkpoint_digest=None, revocation_digest=ZERO_DIGEST,
            trust_manifest_digest=manifest.digest, created_at=NOW, authority_key=primary,
            digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=signer)
        cat.install_genesis_trust(manifest, initial, pinned_manifest_digest=manifest.digest,
            pinned_primary_fingerprint=primary.key_id, keys=keys, verifier=ed25519_verify)
        event = create_revocation(event_id="revoke-primary", registry_id=REGISTRY_ID, sequence=1,
            target_kind="key", target_id=primary.key_id, target_digest=None, reason_code="test_revocation",
            effective_at=NOW + timedelta(minutes=1), timestamp=NOW + timedelta(minutes=1),
            previous_checkpoint_digest=initial.digest, authority_key=recovery,
            digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000, signer=signer)
        checkpoint = create_checkpoint(checkpoint_id="checkpoint-1", registry_id=REGISTRY_ID, sequence=1,
            previous_checkpoint_digest=initial.digest, revocation_digest=event.digest,
            trust_manifest_digest=manifest.digest, created_at=NOW + timedelta(minutes=1),
            authority_key=recovery, digest_registry=cat.digest_registry, limits=LIMITS,
            max_payload_bytes=100_000, signer=signer)
        cat.append_revocation(event, checkpoint, trusted_checkpoint_digest=initial.digest,
            authorized_authority_key_ids=frozenset({primary.key_id, recovery.key_id}), keys=keys,
            verifier=ed25519_verify)
        cat.verify_revocation_integrity()
        assert verify_checkpoint_bundle(manifest=manifest, checkpoints=(initial, checkpoint),
            revocations=(event,), pinned_manifest_digest=manifest.digest,
            pinned_primary_fingerprint=primary.key_id, pinned_checkpoint_digest=checkpoint.digest,
            keys=keys, digest_registry=cat.digest_registry, limits=LIMITS,
            max_payload_bytes=100_000, verifier=ed25519_verify)

        with pytest.raises(ApprovalError, match="approval_key_revoked"):
            verify_approval(approval, release, keys=(replace(primary, status="revoked"), recovery),
                digest_registry=cat.digest_registry, limits=LIMITS, max_payload_bytes=100_000,
                verifier=ed25519_verify, now=NOW)
