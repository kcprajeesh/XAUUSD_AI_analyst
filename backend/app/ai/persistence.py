"""Synthetic-only immutable persistence for injected analyst completions."""

import json
import re

from app.ai.analyst import AnalystProvenance, AnalystRun, AnalystStatus, build_prompt, run_analyst
from app.canonical import CanonicalLimits
from app.canonical_digest import DigestRegistry, digest_structured
from app.data.archive_prototype import SyntheticArchive, _utc
from app.data.evidence_contracts import (AI_PROMPT_SCHEMA, AI_REQUEST_SCHEMA, AI_RESPONSE_SCHEMA,
    AI_REPORT_SCHEMA)


def _encoded(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(domain, schema_id, schema, value, registry, limits, max_payload_bytes):
    profile = next((p for p in registry.entries if p.domain == domain and p.schema_version == schema_id), None)
    if profile is None:
        raise ValueError("AI schema profile is not registered")
    return digest_structured(value, schema, profile, registry, limits, max_payload_bytes).digest


def _assert_credential_free(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if any(word in key.lower() for word in ("secret", "password", "credential", "api_key", "token", "authorization")):
                raise ValueError("AI persistence metadata cannot contain credential fields")
            _assert_credential_free(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _assert_credential_free(item)


def _contains_secret_text(value: str) -> bool:
    return re.search(r"(?i)(api[_-]?key|secret|password|credential|authorization|bearer)\s*[\"']?\s*[:=]\s*[\"']?[^\s,}\"]+", value) is not None


def run_and_persist_analyst(archive: SyntheticArchive, packet, context, provenance: AnalystProvenance,
                            completion, *, response_id: str, report_id: str,
                            registry: DigestRegistry, limits: CanonicalLimits, max_payload_bytes: int) -> AnalystRun:
    """Run only an explicitly injected completion and atomically persist its immutable records."""
    _assert_credential_free(dict(provenance.configuration_metadata))
    prompt = build_prompt(packet, context, provenance)
    if _contains_secret_text(prompt):
        raise ValueError("credential_like_prompt_rejected")
    captured = []
    raw_responses = []

    def capture(value):
        captured.append(value)
        raw = completion(value)
        raw_responses.append(raw)
        return raw

    result = run_analyst(packet, context, provenance, capture if completion is not None else None,
        verify_binding=lambda p: archive.verify_analyst_binding(p.input_manifest_id, p.input_manifest_digest,
            p.derived_manifest_id, p.derived_manifest_digest))
    result_json = _encoded(result.model_dump(mode="json"))
    credential_like = (_contains_secret_text(result_json)
                       or any(_contains_secret_text(raw) for raw in raw_responses))
    if credential_like:
        result = result.model_copy(update={"status": AnalystStatus.INVALID_RESPONSE, "analysis": None, "report": None,
            "failure_reason": "credential_like_content_rejected", "response_validation": ("credential_like_content_rejected",)})
    # The prompt itself is retained as synthetic request content; no transport or provider is created here.
    created = _utc(provenance.created_at)
    prompt_digest = _digest("ai.prompt", "xau.ai-prompt.v1", AI_PROMPT_SCHEMA,
        {"prompt": prompt}, registry, limits, max_payload_bytes)
    # Request IDs are not derivable identities. Resolve the analysis output from the linked derived manifest.
    derived = archive.connection.execute("SELECT output_id FROM derived_manifests WHERE derived_id=?",
                                         (provenance.derived_manifest_id,)).fetchone()
    if derived is None:
        raise ValueError("Analyst derived manifest is missing")
    output = archive.connection.execute("SELECT output_id,digest FROM analysis_outputs WHERE output_id=?",
                                        (derived[0],)).fetchone()
    if output is None:
        raise ValueError("Analyst deterministic output is missing")
    request = {"analysis_id": output[0], "created_at": created,
        "derived_manifest_digest": provenance.derived_manifest_digest, "derived_manifest_id": provenance.derived_manifest_id,
        "input_manifest_digest": provenance.input_manifest_digest, "input_manifest_id": provenance.input_manifest_id,
        "model_id": provenance.model_id, "output_digest": output[1], "output_id": output[0],
        "payload_json": _encoded({"prompt": prompt, "configuration_metadata": list(provenance.configuration_metadata),
                                   "exact_completion_invoked": bool(captured)}),
        "prompt_digest": prompt_digest, "prompt_version": provenance.prompt_version,
        "provider_id": provenance.provider_id, "request_id": provenance.analysis_request_id,
        "schema_id": "xau.ai-request.v1"}
    request_digest = _digest("ai.request", "xau.ai-request.v1", AI_REQUEST_SCHEMA, request,
                             registry, limits, max_payload_bytes)
    result_json = _encoded(result.model_dump(mode="json"))
    response = {"created_at": created, "payload_json": _encoded({"analyst_run": json.loads(result_json),
        "raw_response": raw_responses[0] if raw_responses and not credential_like else None}),
        "request_id": provenance.analysis_request_id,
        "response_id": response_id, "schema_id": "xau.ai-response.v1", "status": result.status.value}
    response_digest = _digest("ai.response", "xau.ai-response.v1", AI_RESPONSE_SCHEMA, response,
                              registry, limits, max_payload_bytes)
    report = None
    report_digest = None
    if result.status in {AnalystStatus.COMPLETE, AnalystStatus.INSUFFICIENT_EVIDENCE}:
        report = {"analysis_id": output[0], "created_at": created,
            "canonicalization_profile": "xau.canon.json-utf8-nfc-decimal-utc6.v1", "framing_version": 1,
            "derived_manifest_digest": provenance.derived_manifest_digest, "derived_manifest_id": provenance.derived_manifest_id,
            "input_manifest_digest": provenance.input_manifest_digest, "input_manifest_id": provenance.input_manifest_id,
            "output_digest": output[1], "output_id": output[0], "payload_json": result_json,
            "provider_id": provenance.provider_id, "model_id": provenance.model_id,
            "prompt_version": provenance.prompt_version, "request_id": provenance.analysis_request_id,
            "response_id": response_id, "report_id": report_id, "schema_id": "xau.ai-report.v1"}
        report_digest = _digest("ai.report", "xau.ai-report.v1", AI_REPORT_SCHEMA, report,
                                registry, limits, max_payload_bytes)
    archive.persist_ai_records(provenance.analysis_request_id, request, request_digest, response_id,
        response, response_digest, report_id if report else None, report, report_digest,
        registry=registry, limits=limits, max_payload_bytes=max_payload_bytes)
    return result
