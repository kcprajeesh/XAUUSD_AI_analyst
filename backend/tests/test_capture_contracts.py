"""Synthetic provider capture permission and byte-boundary checks."""
from app.canonical_digest import RawProfile
from app.data.capture_contracts import CaptureProfile, CaptureStage, Permission, PermissionEvidence
import pytest


def raw_profile(provider):
    return RawProfile("evidence.raw", f"raw.{provider}.synthetic.v1", 1, "raw_evidence", "1",
        f"representation.{provider}.synthetic.v1", "body after transport decompression before decoding",
        ("response-body-octets",), ("headers", "transport-framing", "credentials"),
        ("content-decompression-v1",))


def test_account_rights_unknown_keeps_proposed_providers_disabled():
    for provider in ("twelve-data", "siftingio"):
        profile = CaptureProfile(provider, "candidate-v1", CaptureStage.RAW_RESPONSE_BYTES,
            "body after transport decompression before decoding", ("response-body-octets",),
            ("headers", "transport-framing", "credentials"), "raw_provider_body_30d",
            (PermissionEvidence(Permission.RETRIEVE, None, None),
             PermissionEvidence(Permission.RETAIN_RAW, None, None)), raw_profile=raw_profile(provider))
        assert not profile.enabled
        assert {"permission_unknown:retrieve", "permission_unknown:retain_raw"} <= set(profile.unavailable_reasons)


def test_exact_capture_boundary_and_authorized_synthetic_profile():
    p = raw_profile("fixture")
    profile = CaptureProfile("synthetic-fixture", "v1", CaptureStage.RAW_RESPONSE_BYTES,
        p.capture_boundary, p.included_bytes, p.excluded_bytes, "raw_provider_body_30d",
        (PermissionEvidence(Permission.RETRIEVE, True, "fixture://permission/retrieve"),
         PermissionEvidence(Permission.RETAIN_RAW, True, "fixture://permission/retention"),
         PermissionEvidence(Permission.ATTRIBUTION, True, "fixture://permission/attribution")),
        attribution_text="Synthetic fixture attribution", raw_profile=p,
        registration_reference="fixture://registry/raw/fixture@1")
    assert profile.enabled
    try:
        CaptureProfile("synthetic-fixture", "v1", CaptureStage.RAW_RESPONSE_BYTES,
            p.capture_boundary, p.included_bytes, (), "raw_provider_body_30d", profile.permissions, raw_profile=p)
    except ValueError as error:
        assert "inclusion/exclusion" in str(error)
    else:
        raise AssertionError("Raw capture boundary mismatch must fail closed")


def test_normalized_and_ai_boundaries_require_distinct_rights_and_retention_terms():
    permissions = (PermissionEvidence(Permission.RETRIEVE, True, "fixture://retrieval"),
        PermissionEvidence(Permission.RETAIN_NORMALIZED, True, "fixture://normalized"),
        PermissionEvidence(Permission.INTERNAL_ANALYSIS, True, "fixture://analysis"))
    with pytest.raises(ValueError, match="retention duration reference"):
        CaptureProfile("fixture", "v1", CaptureStage.NORMALIZED_OBSERVATION,
            "normalized Decimal OHLC observation after validation", ("normalized fields",), ("raw tokens",),
            "provider_permission_terms", permissions +
            (PermissionEvidence(Permission.ATTRIBUTION, True, "fixture://attribution"),),
            attribution_text="Synthetic fixture attribution")
    normalized = CaptureProfile("fixture", "v1", CaptureStage.NORMALIZED_OBSERVATION,
        "normalized Decimal OHLC observation after validation", ("normalized fields",), ("raw tokens",),
        "provider_permission_terms", permissions +
        (PermissionEvidence(Permission.ATTRIBUTION, True, "fixture://attribution"),),
        attribution_text="Synthetic fixture attribution", retention_limit_reference="fixture://duration",
        registration_reference="fixture://registry/normalized/fixture@1")
    assert normalized.enabled
    ai = CaptureProfile("fixture", "v1", CaptureStage.AI_PROMPT,
        "exact prompt bytes sent to configured model", ("prompt body",), ("provider credentials",),
        "ai_prompt_response_30d", (PermissionEvidence(Permission.RETAIN_AI, True, "fixture://ai-retention"),
            PermissionEvidence(Permission.ATTRIBUTION, True, "fixture://attribution")),
        attribution_text="Synthetic fixture attribution", registration_reference="fixture://registry/ai/fixture@1")
    assert not ai.enabled
    assert "permission_missing:external_ai" in ai.unavailable_reasons
