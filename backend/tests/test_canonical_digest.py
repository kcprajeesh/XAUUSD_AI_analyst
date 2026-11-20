"""New synthetic HASH-01 fixtures; not the six historical illustrative vectors."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import struct

import pytest

from app.canonical import CanonicalError, CanonicalLimits, Field, ObjectSchema, Scalar
import app.canonical_digest as codec
from app.canonical_digest import (
    DigestError, DigestMetadata, DigestRegistry, RawDigestMetadata, RawProfile, StructuredProfile,
    digest_raw, digest_structured, frame_payload, verify_raw, verify_structured,
)


SCHEMA = ObjectSchema({"label": Field(Scalar("string", semantic_text=True), True, False)})
LIMITS = CanonicalLimits(512, 32, 20, 10, 256)
RAW = RawProfile(
    "evidence.raw", "synthetic.raw.retained.v1", 1, "synthetic_raw", "synthetic.v1",
    "synthetic.representation.retained.v1", "Synthetic immutable byte buffer after capture",
    ("all buffer bytes",), ("separately stored metadata",), (),
)
OTHER_RAW = replace(RAW, profile_id="synthetic.raw.other.v1",
                    representation_id="synthetic.representation.other.v1")
STRUCTURED = StructuredProfile("synthetic.object", "synthetic.canonical.v1", 1,
                               "synthetic_object", "synthetic.v1", SCHEMA)
REGISTRY = DigestRegistry((RAW, OTHER_RAW, STRUCTURED))
PAYLOAD = b'\xff\x00 { "label": "e\xcc\x81" }\r\n'


def independent_frame(payload, profile):
    domain = profile.domain.encode("ascii")
    profile_id = profile.profile_id.encode("ascii")
    return (bytes.fromhex("58 41 55 2d 43 41 4e 4f 4e 00") + struct.pack(">H", 1)
            + struct.pack(">H", len(domain)) + domain
            + struct.pack(">H", len(profile_id)) + profile_id
            + struct.pack(">Q", len(payload)) + payload)


def test_exact_independent_frame_and_raw_digest_preserve_all_bytes():
    expected = independent_frame(PAYLOAD, RAW)
    assert frame_payload(PAYLOAD, RAW, REGISTRY, len(PAYLOAD)) == expected
    metadata = digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, len(PAYLOAD))
    assert metadata == RawDigestMetadata(
        "sha256", sha256(expected).hexdigest(), "evidence.raw", RAW.profile_id, 1,
        "synthetic_raw", "synthetic.v1", "synthetic:bytes:1", len(PAYLOAD), RAW.representation_id,
    )
    calls = []

    def resolve(reference):
        calls.append(reference)
        return PAYLOAD

    assert verify_raw(metadata, REGISTRY, resolve, len(PAYLOAD)) is True
    assert calls == ["synthetic:bytes:1"]


def test_empty_bytes_are_retained_and_framed():
    metadata = digest_raw(b"", "synthetic:empty", RAW, REGISTRY, 1)
    assert metadata.byte_length == 0
    assert frame_payload(b"", RAW, REGISTRY, 1) == independent_frame(b"", RAW)
    assert verify_raw(metadata, REGISTRY, lambda _reference: b"", 1)


def test_profiles_separate_identical_raw_bytes():
    first = digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, 128)
    second = digest_raw(PAYLOAD, "synthetic:bytes:1", OTHER_RAW, REGISTRY, 128)
    assert first.digest != second.digest
    assert frame_payload(PAYLOAD, RAW, REGISTRY, 128) != frame_payload(PAYLOAD, OTHER_RAW, REGISTRY, 128)


def test_structured_digest_has_canonical_payload_and_external_metadata():
    metadata = digest_structured({"label": "e\u0301"}, SCHEMA, STRUCTURED, REGISTRY, LIMITS, 128)
    canonical_payload = b'{"label":"\xc3\xa9"}'
    assert metadata == DigestMetadata(
        "sha256", sha256(independent_frame(canonical_payload, STRUCTURED)).hexdigest(),
        STRUCTURED.domain, STRUCTURED.profile_id, 1, STRUCTURED.object_category, STRUCTURED.schema_version,
    )
    assert verify_structured({"label": "\u00e9"}, SCHEMA, metadata, REGISTRY, LIMITS, 128)
    with pytest.raises(CanonicalError, match="invalid_object"):
        digest_structured(b'{ "label": "e" }', SCHEMA, STRUCTURED, REGISTRY, LIMITS, 128)
    with pytest.raises(CanonicalError, match="unknown_field"):
        digest_structured({"label": "e", "digest": metadata.digest}, SCHEMA, STRUCTURED, REGISTRY, LIMITS, 128)
    with pytest.raises(DigestError, match="digest_mismatch"):
        verify_structured({"label": "changed"}, SCHEMA, metadata, REGISTRY, LIMITS, 128)


def test_registry_and_capture_definitions_are_immutable_and_required():
    with pytest.raises(FrozenInstanceError):
        RAW.capture_boundary = "changed"
    with pytest.raises(FrozenInstanceError):
        REGISTRY.entries = ()
    with pytest.raises(DigestError, match="invalid_registry"):
        DigestRegistry([RAW])
    with pytest.raises(DigestError, match="invalid_capture_definition"):
        replace(RAW, included_bytes=[])
    with pytest.raises(DigestError, match="invalid_capture_definition"):
        replace(RAW, included_bytes=())
    with pytest.raises(DigestError, match="invalid_capture_boundary"):
        replace(RAW, capture_boundary="")
    with pytest.raises(TypeError):
        RawProfile("evidence.raw", "synthetic.raw.v1", 1, "synthetic", "v1", "synthetic.rep.v1")


def test_registry_one_to_one_mapping_and_distinct_payload_kinds():
    with pytest.raises(DigestError, match="duplicate_registry_entry"):
        DigestRegistry((RAW, RAW))
    with pytest.raises(DigestError, match="non_unique_representation_mapping"):
        DigestRegistry((RAW, replace(OTHER_RAW, representation_id=RAW.representation_id)))
    with pytest.raises(DigestError, match="payload_kind_mismatch"):
        DigestRegistry((RAW, replace(STRUCTURED, profile_id=RAW.profile_id)))
    with pytest.raises(DigestError, match="payload_kind_mismatch"):
        replace(STRUCTURED, domain="evidence.raw")
    with pytest.raises(DigestError, match="payload_kind_mismatch"):
        replace(RAW, domain="synthetic.object")
    with pytest.raises(DigestError, match="payload_kind_mismatch"):
        replace(RAW, profile_id="xau.canon.json-utf8-nfc-decimal-utc6.v1")
    with pytest.raises(DigestError, match="payload_kind_mismatch"):
        digest_structured({"label": "e"}, SCHEMA, RAW, REGISTRY, LIMITS, 128)
    with pytest.raises(DigestError, match="payload_kind_mismatch"):
        digest_raw(PAYLOAD, "synthetic:bytes:1", STRUCTURED, REGISTRY, 128)


@pytest.mark.parametrize("field,value,code", [
    ("algorithm", "SHA256", "unsupported_algorithm"),
    ("digest", "A" * 64, "invalid_digest_text"),
    ("digest", "0" * 63, "invalid_digest_text"),
    ("digest", "0" * 64 + "\n", "invalid_digest_text"),
    ("digest", bytes(32), "invalid_digest_text"),
    ("domain", "synthetic.unknown", "unregistered_profile_or_domain"),
    ("profile_id", "synthetic.unknown.v1", "unregistered_profile_or_domain"),
    ("profile_id", "nonascii.\u00e9", "invalid_identifier"),
    ("framing_version", 2, "unsupported_framing_version"),
    ("framing_version", True, "invalid_framing_version"),
    ("object_category", "synthetic_other", "object_category_mismatch"),
    ("schema_version", "synthetic.v2", "schema_version_mismatch"),
    ("representation_id", OTHER_RAW.representation_id, "representation_mismatch"),
    ("byte_reference", "", "missing_byte_reference"),
    ("byte_reference", None, "missing_byte_reference"),
    ("byte_length", True, "invalid_byte_length"),
    ("byte_length", -1, "invalid_byte_length"),
    ("byte_length", 1 << 64, "invalid_byte_length"),
    ("byte_length", 129, "payload_limit_exceeded"),
])
def test_bad_raw_metadata_fails_before_resolving(field, value, code):
    metadata = digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, 128)

    def never_resolve(_reference):
        pytest.fail("invalid metadata reached resolver")

    with pytest.raises(DigestError) as error:
        verify_raw(replace(metadata, **{field: value}), REGISTRY, never_resolve, 128)
    assert error.value.code == code


@pytest.mark.parametrize("payload,code", [
    (PAYLOAD[:-1], "byte_length_mismatch"),
    (b"X" + PAYLOAD[1:], "digest_mismatch"),
    (bytearray(PAYLOAD), "invalid_resolved_bytes"),
    (None, "invalid_resolved_bytes"),
])
def test_raw_byte_tamper_or_unavailable_bytes_fail(payload, code):
    metadata = digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, 128)
    with pytest.raises(DigestError) as error:
        verify_raw(metadata, REGISTRY, lambda _reference: payload, 128)
    assert error.value.code == code


def test_resolver_failure_is_sanitized_and_profile_switch_is_not_inferred():
    metadata = digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, 128)

    def missing(_reference):
        raise OSError("secret body or backend credential")

    with pytest.raises(DigestError) as error:
        verify_raw(metadata, REGISTRY, missing, 128)
    assert str(error.value) == "unresolvable_byte_reference"
    assert error.value.__cause__ is None
    with pytest.raises(DigestError, match="representation_mismatch"):
        verify_raw(replace(metadata, profile_id=OTHER_RAW.profile_id), REGISTRY, lambda _r: PAYLOAD, 128)
    switched = replace(metadata, profile_id=OTHER_RAW.profile_id, representation_id=OTHER_RAW.representation_id)
    with pytest.raises(DigestError, match="digest_mismatch"):
        verify_raw(switched, REGISTRY, lambda _r: PAYLOAD, 128)


def test_unknown_or_changed_registry_and_structured_schema_fail():
    with pytest.raises(DigestError, match="unregistered_profile_or_domain"):
        frame_payload(PAYLOAD, RAW, DigestRegistry(()), 128)
    with pytest.raises(DigestError, match="registry_definition_mismatch"):
        frame_payload(PAYLOAD, replace(RAW, capture_boundary="another capture step"), REGISTRY, 128)
    metadata = digest_structured({"label": "e"}, SCHEMA, STRUCTURED, REGISTRY, LIMITS, 128)
    other_schema = ObjectSchema({"other": Field(Scalar("string"), True, False)})
    with pytest.raises(DigestError, match="schema_mismatch"):
        verify_structured({"label": "e"}, other_schema, metadata, REGISTRY, LIMITS, 128)
    with pytest.raises(DigestError, match="object_category_mismatch"):
        verify_structured({"label": "e"}, SCHEMA, replace(metadata, object_category="other"),
                          REGISTRY, LIMITS, 128)
    with pytest.raises(DigestError, match="schema_version_mismatch"):
        verify_structured({"label": "e"}, SCHEMA, replace(metadata, schema_version="v2"),
                          REGISTRY, LIMITS, 128)


@pytest.mark.parametrize("field,value,code", [
    ("domain", "", "invalid_identifier"),
    ("domain", "\u00e9", "invalid_identifier"),
    ("profile_id", b"ascii", "invalid_identifier"),
    ("profile_id", "x" * 65536, "identifier_too_long"),
    ("framing_version", 0, "unsupported_framing_version"),
    ("framing_version", -1, "invalid_framing_version"),
    ("framing_version", 65536, "invalid_framing_version"),
    ("framing_version", "1", "invalid_framing_version"),
])
def test_ascii_lengths_and_unsigned_version_validation(field, value, code):
    with pytest.raises(DigestError) as error:
        replace(RAW, **{field: value})
    assert error.value.code == code


def test_identifier_uint16_boundary_is_exact():
    profile = replace(RAW, profile_id="x" * 65535)
    registry = DigestRegistry((profile,))
    assert frame_payload(b"", profile, registry, 1) == independent_frame(b"", profile)


@pytest.mark.parametrize("limit", [None, True, 0, -1, 1.0, 1 << 64])
def test_payload_limit_is_required_typed_and_has_no_default(limit):
    with pytest.raises(DigestError, match="invalid_payload_limit"):
        digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, limit)


def test_validation_and_limits_fail_before_hashing(monkeypatch):
    def no_hash(_frame):
        pytest.fail("invalid input reached SHA-256")

    monkeypatch.setattr(codec, "sha256", no_hash)
    with pytest.raises(DigestError, match="payload_limit_exceeded"):
        digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, len(PAYLOAD) - 1)
    with pytest.raises(DigestError, match="invalid_payload_type"):
        digest_raw(bytearray(PAYLOAD), "synthetic:bytes:1", RAW, REGISTRY, 128)
    with pytest.raises(DigestError, match="unregistered_profile_or_domain"):
        digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, DigestRegistry(()), 128)
    with pytest.raises(DigestError, match="payload_limit_exceeded"):
        digest_structured({"label": "e"}, SCHEMA, STRUCTURED, REGISTRY, LIMITS, 1)
    with pytest.raises(CanonicalError, match="limit_exceeded:max_canonical_output_bytes"):
        digest_structured({"label": "e"}, SCHEMA, STRUCTURED, REGISTRY,
                          replace(LIMITS, max_canonical_output_bytes=1), 128)


def test_unrelated_metadata_types_and_noncallable_resolver_fail():
    raw = digest_raw(PAYLOAD, "synthetic:bytes:1", RAW, REGISTRY, 128)
    structured = digest_structured({"label": "e"}, SCHEMA, STRUCTURED, REGISTRY, LIMITS, 128)
    with pytest.raises(DigestError, match="invalid_metadata_type"):
        verify_raw(structured, REGISTRY, lambda _r: PAYLOAD, 128)
    with pytest.raises(DigestError, match="invalid_metadata_type"):
        verify_structured({"label": "e"}, SCHEMA, raw, REGISTRY, LIMITS, 128)
    with pytest.raises(DigestError, match="invalid_byte_resolver"):
        verify_raw(raw, REGISTRY, None, 128)
