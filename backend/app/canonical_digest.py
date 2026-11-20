"""Isolated HASH-01 codec; caller registries do not activate production profiles."""

from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
import re
from typing import Callable

from app.canonical import ArraySchema, CanonicalLimits, ObjectSchema, Scalar, canonical_json


class DigestError(ValueError):
    """A typed failure that never echoes payloads, metadata or resolver errors."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


Schema = Scalar | ObjectSchema | ArraySchema
_MAGIC = b"XAU-CANON\x00"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MAX_LENGTH = (1 << 64) - 1


def _identifier(value):
    if type(value) is not str or not value or not value.isascii():
        raise DigestError("invalid_identifier")
    if len(value) > 65535:
        raise DigestError("identifier_too_long")
    return value.encode("ascii")


def _version(value):
    if type(value) is not int or not 0 <= value <= 65535:
        raise DigestError("invalid_framing_version")
    if value != 1:
        raise DigestError("unsupported_framing_version")


def _payload_limit(value):
    if type(value) is not int or not 0 < value <= _MAX_LENGTH:
        raise DigestError("invalid_payload_limit")


def _byte_length(value, maximum):
    if type(value) is not int or not 0 <= value <= _MAX_LENGTH:
        raise DigestError("invalid_byte_length")
    if value > maximum:
        raise DigestError("payload_limit_exceeded")


def _profile_fields(profile):
    for value in (profile.domain, profile.profile_id, profile.object_category, profile.schema_version):
        _identifier(value)
    _version(profile.framing_version)


@dataclass(frozen=True, slots=True)
class StructuredProfile:
    domain: str
    profile_id: str
    framing_version: int
    object_category: str
    schema_version: str
    schema: Schema

    def __post_init__(self):
        _profile_fields(self)
        if self.domain == "evidence.raw":
            raise DigestError("payload_kind_mismatch")
        if type(self.schema) not in (Scalar, ObjectSchema, ArraySchema):
            raise DigestError("invalid_schema")


@dataclass(frozen=True, slots=True)
class RawProfile:
    domain: str
    profile_id: str
    framing_version: int
    object_category: str
    schema_version: str
    representation_id: str
    capture_boundary: str
    included_bytes: tuple[str, ...]
    excluded_bytes: tuple[str, ...]
    prior_transformations: tuple[str, ...]

    def __post_init__(self):
        _profile_fields(self)
        _identifier(self.representation_id)
        if self.domain != "evidence.raw" or self.profile_id == "xau.canon.json-utf8-nfc-decimal-utc6.v1":
            raise DigestError("payload_kind_mismatch")
        if type(self.capture_boundary) is not str or not self.capture_boundary.strip():
            raise DigestError("invalid_capture_boundary")
        for values in (self.included_bytes, self.excluded_bytes, self.prior_transformations):
            if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
                raise DigestError("invalid_capture_definition")
        if not self.included_bytes:
            raise DigestError("invalid_capture_definition")


Profile = RawProfile | StructuredProfile


@dataclass(frozen=True, slots=True)
class DigestRegistry:
    entries: tuple[Profile, ...]

    def __post_init__(self):
        if type(self.entries) is not tuple:
            raise DigestError("invalid_registry")
        keys = set()
        raw_profiles = set()
        representations = set()
        structured_profiles = set()
        for entry in self.entries:
            if type(entry) not in (RawProfile, StructuredProfile):
                raise DigestError("invalid_registry_entry")
            key = (entry.domain, entry.profile_id, entry.framing_version)
            if key in keys:
                raise DigestError("duplicate_registry_entry")
            keys.add(key)
            if type(entry) is RawProfile:
                if entry.profile_id in raw_profiles or entry.representation_id in representations:
                    raise DigestError("non_unique_representation_mapping")
                raw_profiles.add(entry.profile_id)
                representations.add(entry.representation_id)
            else:
                structured_profiles.add(entry.profile_id)
        if raw_profiles & structured_profiles:
            raise DigestError("payload_kind_mismatch")


@dataclass(frozen=True, slots=True)
class DigestMetadata:
    algorithm: str
    digest: str
    domain: str
    profile_id: str
    framing_version: int
    object_category: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class RawDigestMetadata(DigestMetadata):
    byte_reference: str
    byte_length: int
    representation_id: str


def _lookup(domain, profile_id, version, registry):
    _identifier(domain)
    _identifier(profile_id)
    _version(version)
    if type(registry) is not DigestRegistry:
        raise DigestError("invalid_registry")
    for entry in registry.entries:
        if (entry.domain, entry.profile_id, entry.framing_version) == (domain, profile_id, version):
            return entry
    raise DigestError("unregistered_profile_or_domain")


def _registered(profile, registry):
    if type(profile) not in (RawProfile, StructuredProfile):
        raise DigestError("invalid_registry_entry")
    entry = _lookup(profile.domain, profile.profile_id, profile.framing_version, registry)
    if entry != profile:
        raise DigestError("registry_definition_mismatch")
    return entry


def frame_payload(payload: bytes, profile: Profile, registry: DigestRegistry, max_payload_bytes: int) -> bytes:
    """Return the exact v1 message; validation completes before any hash is made."""
    _payload_limit(max_payload_bytes)
    _registered(profile, registry)
    if type(payload) is not bytes:
        raise DigestError("invalid_payload_type")
    _byte_length(len(payload), max_payload_bytes)
    domain = _identifier(profile.domain)
    profile_id = _identifier(profile.profile_id)
    return (_MAGIC + profile.framing_version.to_bytes(2, "big")
            + len(domain).to_bytes(2, "big") + domain
            + len(profile_id).to_bytes(2, "big") + profile_id
            + len(payload).to_bytes(8, "big") + payload)


def _digest(payload, profile, registry, maximum):
    return sha256(frame_payload(payload, profile, registry, maximum)).hexdigest()


def _reference(value):
    if type(value) is not str or not value:
        raise DigestError("missing_byte_reference")


def digest_raw(payload: bytes, byte_reference: str, profile: RawProfile,
               registry: DigestRegistry, max_payload_bytes: int) -> RawDigestMetadata:
    if type(profile) is not RawProfile:
        raise DigestError("payload_kind_mismatch")
    _reference(byte_reference)
    digest = _digest(payload, profile, registry, max_payload_bytes)
    return RawDigestMetadata("sha256", digest, profile.domain, profile.profile_id,
                             profile.framing_version, profile.object_category, profile.schema_version,
                             byte_reference, len(payload), profile.representation_id)


def _structured(value, schema, profile, registry, limits, maximum):
    _payload_limit(maximum)
    if type(profile) is not StructuredProfile:
        raise DigestError("payload_kind_mismatch")
    _registered(profile, registry)
    if type(schema) not in (Scalar, ObjectSchema, ArraySchema) or schema != profile.schema:
        raise DigestError("schema_mismatch")
    return canonical_json(value, schema, limits)


def digest_structured(value, schema: Schema, profile: StructuredProfile, registry: DigestRegistry,
                      limits: CanonicalLimits, max_payload_bytes: int) -> DigestMetadata:
    payload = _structured(value, schema, profile, registry, limits, max_payload_bytes)
    return DigestMetadata("sha256", _digest(payload, profile, registry, max_payload_bytes),
                          profile.domain, profile.profile_id, profile.framing_version,
                          profile.object_category, profile.schema_version)


def _metadata(metadata, registry, raw, maximum):
    _payload_limit(maximum)
    if type(metadata) is not (RawDigestMetadata if raw else DigestMetadata):
        raise DigestError("invalid_metadata_type")
    if type(metadata.algorithm) is not str or metadata.algorithm != "sha256":
        raise DigestError("unsupported_algorithm")
    if type(metadata.digest) is not str or _DIGEST.fullmatch(metadata.digest) is None:
        raise DigestError("invalid_digest_text")
    _identifier(metadata.object_category)
    _identifier(metadata.schema_version)
    profile = _lookup(metadata.domain, metadata.profile_id, metadata.framing_version, registry)
    if type(profile) is not (RawProfile if raw else StructuredProfile):
        raise DigestError("payload_kind_mismatch")
    if metadata.object_category != profile.object_category:
        raise DigestError("object_category_mismatch")
    if metadata.schema_version != profile.schema_version:
        raise DigestError("schema_version_mismatch")
    if raw:
        _reference(metadata.byte_reference)
        _byte_length(metadata.byte_length, maximum)
        _identifier(metadata.representation_id)
        if metadata.representation_id != profile.representation_id:
            raise DigestError("representation_mismatch")
    return profile


def verify_raw(metadata: RawDigestMetadata, registry: DigestRegistry,
               resolve_bytes: Callable[[str], bytes], max_payload_bytes: int) -> bool:
    """Resolve the declared immutable reference and hash unchanged retained bytes."""
    profile = _metadata(metadata, registry, True, max_payload_bytes)
    if not callable(resolve_bytes):
        raise DigestError("invalid_byte_resolver")
    try:
        payload = resolve_bytes(metadata.byte_reference)
    except Exception:
        raise DigestError("unresolvable_byte_reference") from None
    if type(payload) is not bytes:
        raise DigestError("invalid_resolved_bytes")
    if len(payload) != metadata.byte_length:
        raise DigestError("byte_length_mismatch")
    actual = _digest(payload, profile, registry, max_payload_bytes)
    if not compare_digest(actual, metadata.digest):
        raise DigestError("digest_mismatch")
    return True


def verify_structured(value, schema: Schema, metadata: DigestMetadata, registry: DigestRegistry,
                      limits: CanonicalLimits, max_payload_bytes: int) -> bool:
    profile = _metadata(metadata, registry, False, max_payload_bytes)
    payload = _structured(value, schema, profile, registry, limits, max_payload_bytes)
    actual = _digest(payload, profile, registry, max_payload_bytes)
    if not compare_digest(actual, metadata.digest):
        raise DigestError("digest_mismatch")
    return True
