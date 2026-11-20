from dataclasses import replace

import pytest

from app.canonical import CanonicalError, CanonicalLimits, canonical_json
from app.canonical_digest import digest_structured
from app.canonical_identity import allocate_id
from app.data.evidence_contracts import (
    DerivedManifest, InputManifest, MANIFEST_SCHEMA, ManifestItem, SCHEMAS, TIMEFRAMES,
    digest_derived_manifest, identity_namespace_registry, serialize_derived_manifest,
    serialize_manifest, structured_profile_registry,
)


LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
EXPECTED_MANIFEST = b'{"created_at":"2026-01-02T01:00:00.000000Z","instrument_id":"xauusd","items":[{"generation":1,"requested_end":"2026-01-02T00:00:00.000000Z","requested_start":"2026-01-01T00:00:00.000000Z","retrieval_id":"ret-1d","revisions":["rev-1d"],"timeframe":"1d"},{"generation":2,"requested_end":"2026-01-02T00:00:00.000000Z","requested_start":"2026-01-01T00:00:00.000000Z","retrieval_id":"ret-4h","revisions":["rev-4h"],"timeframe":"4h"},{"generation":3,"requested_end":"2026-01-02T00:00:00.000000Z","requested_start":"2026-01-01T00:00:00.000000Z","retrieval_id":"ret-1h","revisions":["rev-1h"],"timeframe":"1h"},{"generation":4,"requested_end":"2026-01-02T00:00:00.000000Z","requested_start":"2026-01-01T00:00:00.000000Z","retrieval_id":"ret-15m","revisions":["rev-15m"],"timeframe":"15m"},{"generation":5,"requested_end":"2026-01-02T00:00:00.000000Z","requested_start":"2026-01-01T00:00:00.000000Z","retrieval_id":"ret-5m","revisions":["rev-5m"],"timeframe":"5m"}],"manifest_id":"manifest-vector"}'


def manifest():
    return InputManifest(
        "manifest-vector", "xauusd", "2026-01-02T01:00:00Z",
        tuple(ManifestItem(tf, n, "ret-" + tf, "2026-01-01T00:00:00Z",
                           "2026-01-02T00:00:00Z", ("rev-" + tf,))
              for n, tf in enumerate(TIMEFRAMES, 1)),
    )


def test_manifest_canonical_and_digest_vector_is_stable():
    value = manifest()
    assert serialize_manifest(value, LIMITS) == EXPECTED_MANIFEST
    registry = structured_profile_registry()
    profile = next(p for p in registry.entries if p.domain == "evidence.input-manifest")
    digest = digest_structured(value.payload(LIMITS), MANIFEST_SCHEMA, profile, registry, LIMITS, 100_000)
    assert digest.digest == "438ec321bd920761dda168801882784a0df18b5ee0aaa4251b44c351bd86ea1b"
    assert len(SCHEMAS) == 34


@pytest.mark.parametrize("change", [
    lambda items: items[:-1],
    lambda items: items[:-1] + (items[0],),
    lambda items: items[:-1] + (replace(items[-1], retrieval_id=items[0].retrieval_id),),
    lambda items: items[:-1] + (replace(items[-1], generation=0),),
    lambda items: items[:-1] + (replace(items[-1], requested_start="2026-02-01T00:00:00Z"),),
    lambda items: items[:-1] + (replace(items[-1], revisions=("same", "same")),),
])
def test_manifest_rejects_incomplete_duplicate_or_invalid_lineage(change):
    with pytest.raises(ValueError):
        replace(manifest(), items=change(manifest().items)).payload(LIMITS)


@pytest.mark.parametrize("bad", [
    {"created_at": "2026-01-02T01:00:00Z"},
    {"unknown": "field"},
])
def test_registered_schema_rejects_missing_and_unknown_fields(bad):
    with pytest.raises(CanonicalError):
        canonical_json(bad, MANIFEST_SCHEMA, LIMITS)


def test_identity_and_profile_registrations_are_explicit_and_stable():
    registry = identity_namespace_registry()
    assert {entry.object_category for entry in registry.entries} == {
        "raw_evidence", "observation", "revision", "retrieval", "input_manifest",
        "page", "row_occurrence", "invalidation", "derived_manifest", "digest_metadata",
        "raw_digest_metadata", "analysis_record", "analysis", "analysis_output", "registry_entry", "registry_release", "registry_approval",
            "registry_trust_manifest", "registry_revocation", "registry_checkpoint",
        "ai_request", "ai_prompt", "ai_response", "ai_report",
    }
    recorded = []
    result = allocate_id("input_manifest", registry, lambda identity: recorded.append(identity) is None)
    assert result == recorded[0] and result.value.startswith("xau.input.manifest.v1:")
    profiles = structured_profile_registry()
    assert len(profiles.entries) == 32
    assert len({(p.domain, p.profile_id, p.framing_version) for p in profiles.entries}) == 32


def test_derived_manifest_is_frozen_and_binds_input_algorithm_policy_and_parameters():
    value = DerivedManifest("derived-1", "manifest-1", "a" * 64, "xau.deterministic.analysis",
        "1", "b" * 64, "synthetic-policy-v1", "xau.analysis-record.v1", "2026-01-02T01:00:00Z")
    encoded = serialize_derived_manifest(value, LIMITS)
    assert b'"input_manifest_digest":"' + b"a" * 64 + b'"' in encoded
    registry = structured_profile_registry()
    first = digest_derived_manifest(value, registry, LIMITS, 100_000)
    assert digest_derived_manifest(value, registry, LIMITS, 100_000) == first
    with pytest.raises((AttributeError, TypeError)):
        value.algorithm_version = "2"
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        serialize_derived_manifest(replace(value, parameter_digest="not-a-digest"), LIMITS)


def test_raw_digest_metadata_schema_keeps_capture_identity_outside_hashed_bytes():
    from app.data.evidence_contracts import RAW_DIGEST_METADATA_SCHEMA
    metadata = {"algorithm": "sha256", "byte_length": 12, "byte_reference": "synthetic:bytes:1",
        "digest": "a" * 64, "domain": "evidence.raw", "framing_version": 1,
        "object_category": "raw_evidence", "profile_id": "xau.raw-bytes.synthetic-fixture.v1",
        "representation_id": "xau.evidence-representation.synthetic-fixture.v1", "schema_version": "1"}
    assert canonical_json(metadata, RAW_DIGEST_METADATA_SCHEMA, LIMITS)
    with pytest.raises(CanonicalError):
        canonical_json({**metadata, "unknown": "field"}, RAW_DIGEST_METADATA_SCHEMA, LIMITS)
