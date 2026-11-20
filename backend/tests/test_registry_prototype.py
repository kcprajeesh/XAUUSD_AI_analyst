"""Synthetic versioned registry ownership and conflict tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import sqlite3

import pytest

from app.canonical import CanonicalLimits
from app.data.evidence_contracts import structured_profile_registry
from app.data.registry_prototype import RegistrarAuthority, RegistryConflict, SyntheticRegistry


NOW = datetime(2026, 11, 18, tzinfo=UTC)
LIMITS = CanonicalLimits(100_000, 1_000, 1_000, 1_000, 10_000)
REGISTRARS = (RegistrarAuthority("fixture-owner", frozenset({"schema", "profile", "algorithm", "capture", "bundle"})),)


def catalog(path):
    return SyntheticRegistry(path, registry_id="xau.registry.catalog", create=True, busy_timeout_ms=100, authorities=REGISTRARS,
        digest_registry=structured_profile_registry(), limits=LIMITS, max_payload_bytes=100_000)


def register(cat, registry, key, version, definition, *, previous, refs=(), actor="fixture-owner"):
    return cat.register(registry, key, version, definition, references=refs, registrar_id=actor,
                        expected_previous_version=previous, registered_at=NOW,
                        change_reference="fixture://change-review")


def test_duplicate_replay_conflict_and_version_reuse(tmp_path):
    with catalog(tmp_path / "registry.synthetic.sqlite3") as cat:
        assert register(cat, "schema", "candle", 1, {"fields": ["open", "high"]}, previous=0)
        assert not register(cat, "schema", "candle", 1, {"fields": ["open", "high"]}, previous=0)
        with pytest.raises(RegistryConflict, match="conflicting content"):
            register(cat, "schema", "candle", 1, {"fields": ["close"]}, previous=0)
        with pytest.raises(RegistryConflict, match="version conflict"):
            register(cat, "schema", "candle", 3, {"fields": ["close"]}, previous=1)
        assert register(cat, "schema", "candle", 2, {"fields": ["open", "high", "close"]}, previous=1)
        cat.verify_integrity()


def test_unauthorized_and_unknown_cross_registry_references_fail(tmp_path):
    with catalog(tmp_path / "registry.synthetic.sqlite3") as cat:
        with pytest.raises(PermissionError):
            register(cat, "schema", "blocked", 1, {}, previous=0, actor="unlisted")
        with pytest.raises(ValueError, match="reference is unknown"):
            register(cat, "profile", "canon", 1, {"domain": "xau"}, previous=0,
                     refs=("schema/candle@1",))
        with pytest.raises(ValueError, match="reference is unknown"):
            register(cat, "capture", "raw-body", 1, {"boundary": "bytes"}, previous=0,
                     refs=("profile/missing@1",))
        with pytest.raises(ValueError, match="type is inconsistent"):
            register(cat, "profile", "wrong-kind", 1, {"domain": "xau"}, previous=0,
                     refs=("algorithm/indicator@1",))
        register(cat, "schema", "candle", 1, {"fields": ["open"]}, previous=0)
        assert register(cat, "profile", "canon", 1, {"domain": "xau"}, previous=0,
                        refs=("schema/candle@1",))
        with pytest.raises(ValueError, match="Unknown registry entry"):
            cat.resolve("profile", "absent", 1)


def test_deprecated_historical_and_invalidated_registration_states(tmp_path):
    with catalog(tmp_path / "registry.synthetic.sqlite3") as cat:
        register(cat, "schema", "candle", 1, {"fields": ["open"]}, previous=0)
        cat.event("deprecate-1", "schema", "candle", 1, "deprecated", "superseded",
                  registrar_id="fixture-owner", created_at=NOW)
        with pytest.raises(ValueError, match="not active"):
            cat.resolve("schema", "candle", 1)
        assert cat.resolve("schema", "candle", 1, historical=True)[1] == "deprecated"
        with pytest.raises(ValueError, match="reference is unknown"):
            register(cat, "profile", "old-dependent", 1, {"profile": "p"}, previous=0,
                     refs=("schema/candle@1",))
        register(cat, "schema", "candle", 2, {"fields": ["open", "close"]}, previous=1)
        cat.event("invalidate-2", "schema", "candle", 2, "invalidated", "bad definition",
                  registrar_id="fixture-owner", created_at=NOW)
        with pytest.raises(ValueError, match="not active"):
            cat.resolve("schema", "candle", 2, historical=True)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            cat.connection.execute("UPDATE registry_entries SET digest='x' WHERE entry_key='candle'")


def test_concurrent_version_registration_has_one_winner(tmp_path):
    path = tmp_path / "registry.synthetic.sqlite3"
    catalog(path).close()
    def attempt(field):
        cat = SyntheticRegistry(path, registry_id="xau.registry.catalog", busy_timeout_ms=100, authorities=REGISTRARS,
            digest_registry=structured_profile_registry(), limits=LIMITS, max_payload_bytes=100_000)
        try:
            try:
                return register(cat, "schema", "candle", 1, {"fields": [field]}, previous=0)
            except RegistryConflict:
                return False
        finally:
            cat.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("open", "close")))
    with SyntheticRegistry(path, registry_id="xau.registry.catalog", busy_timeout_ms=100, authorities=REGISTRARS,
         digest_registry=structured_profile_registry(), limits=LIMITS, max_payload_bytes=100_000) as first:
        assert sum(results) == 1
        assert first.connection.execute("SELECT count(*) FROM registry_entries").fetchone()[0] == 1
        first.verify_integrity()


def test_immutable_release_bundle_verifies_and_reconstructs_registry(tmp_path):
    source_path = tmp_path / "source.synthetic.sqlite3"
    with catalog(source_path) as source:
        register(source, "schema", "candle", 1, {"fields": ["open", "close"]}, previous=0)
        register(source, "profile", "candle-json", 1, {"domain": "candle"}, previous=0,
                 refs=("schema/candle@1",))
        source.event("deprecate-1", "schema", "candle", 1, "deprecated", "replaced",
                     registrar_id="fixture-owner", created_at=NOW)
        release = source.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner",
                                        change_reference="synthetic://change-approved")
        replay = source.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner",
                                       change_reference="synthetic://change-approved")
        changed_review = source.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner",
                                               change_reference="synthetic://different-change")
        assert replay.release_id == release.release_id
        assert changed_review.release_id != release.release_id
        assert source.verify_release(release)["registry_schema_version"] == "1"
        with pytest.raises(ValueError, match="change reference"):
            source.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner", change_reference="")

    target_path = tmp_path / "restore.synthetic.sqlite3"
    with catalog(target_path) as restored:
        restored.reconstruct_release(release)
        assert restored.resolve("schema", "candle", 1, historical=True)[1] == "deprecated"
        assert restored.resolve("profile", "candle-json", 1)[0]["digest"] == source_digest(release, "profile")
        replay = restored.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner",
                                         change_reference="synthetic://recovery-change",
                                         previous_release_id=release.release_id, previous_release_digest=release.digest)
        assert replay.previous_release_id == release.release_id
        with pytest.raises(ValueError, match="empty catalog"):
            restored.reconstruct_release(release)


def source_digest(release, registry_id):
    import json
    from app.canonical import parse_json
    value = parse_json(release.payload, LIMITS)
    rows = [json.loads(item) for item in value["entries"]]
    return next(row["digest"] for row in rows if row["registry_id"] == registry_id)


def test_registry_release_digest_tampering_and_missing_release_scope_fail(tmp_path):
    from dataclasses import replace

    with catalog(tmp_path / "release.synthetic.sqlite3") as cat:
        with pytest.raises(PermissionError):
            cat.export_release(created_at=NOW, prepared_by_registrar_id="unlisted", change_reference="fixture")
        release = cat.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner",
                                     change_reference="synthetic://change")
        tampered = replace(release, payload=release.payload.replace(b'"registry_schema_version":"1"',
                                                                    b'"registry_schema_version":"2"'))
        with pytest.raises(ValueError, match="digest"):
            cat.verify_release(tampered)


def test_release_v2_binds_registry_and_legacy_v1_is_historical_only(tmp_path):
    from dataclasses import replace
    from app.canonical import canonical_json
    from app.canonical_digest import digest_structured
    from app.data.evidence_contracts import REGISTRY_RELEASE_SCHEMA
    from app.data.registry_prototype import RegistryRelease

    with catalog(tmp_path / "identity.synthetic.sqlite3") as cat:
        release = cat.export_release(created_at=NOW, prepared_by_registrar_id="fixture-owner",
                                     change_reference="synthetic://identity")
        assert cat.verify_release(release, target_registry_id="xau.registry.catalog")["registry_id"] == "xau.registry.catalog"
        with pytest.raises(ValueError, match="(?i)registry identity"):
            cat.verify_release(release, target_registry_id="xau.other.registry")
        with pytest.raises(ValueError, match="(?i)registry identity"):
            cat.verify_release(replace(release, registry_id=None))
        substitution = replace(release, registry_id="xau.other.registry")
        with pytest.raises(ValueError, match="(?i)registry identity"):
            cat.verify_release(substitution)
        changed_bytes = replace(release, payload=release.payload.replace(
            b"synthetic://identity", b"synthetic://changed"))
        with pytest.raises(ValueError, match="digest"):
            cat.verify_release(changed_bytes)

        legacy_value = {"change_reference": "historical-reference", "created_at": "2026-11-18T00:00:00Z",
            "entries": [], "previous_release_id": None, "prepared_by_registrar_id": "fixture-owner",
            "registry_schema_version": "1", "events": []}
        old_profile = cat.release_profile
        old_digest = digest_structured(legacy_value, REGISTRY_RELEASE_SCHEMA, old_profile,
            cat.digest_registry, LIMITS, 100_000).digest
        legacy = RegistryRelease("sha256:" + old_digest, old_digest,
            canonical_json(legacy_value, REGISTRY_RELEASE_SCHEMA, LIMITS), None)
        with pytest.raises(ValueError, match="historical-only"):
            cat.verify_release(legacy)
        assert cat.verify_release(legacy, allow_unbound_historical=True)[
            "_historical_registry_identity_unbound"] is True
