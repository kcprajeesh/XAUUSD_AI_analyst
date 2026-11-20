"""Provider-agnostic analyst orchestration; all model I/O is injected by its caller."""

from enum import StrEnum
import json
import re
from typing import Callable, Literal
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.contracts import AnalysisResponse, deterministic_no_trade, validate_response
from app.ai.evidence import EvidencePacket, SufficiencyStatus, Timeframe, TimeframeState, assess_sufficiency
from app.data.context import ContextSnapshot, FeedStatus, context_record_reference
from app.data.contracts import UTCInstant


class AnalystModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalystProvenance(AnalystModel):
    schema_version: Literal["1.0"] = "1.0"
    input_manifest_id: str = Field(min_length=1)
    input_manifest_digest: str = Field(min_length=1)
    derived_manifest_id: str = Field(min_length=1)
    derived_manifest_digest: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    analysis_request_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    configuration_metadata: tuple[tuple[str, str | int | bool | None], ...]
    created_at: UTCInstant

    @model_validator(mode="after")
    def unique_configuration_keys(self):
        keys = tuple(key for key, _ in self.configuration_metadata)
        if len(keys) != len(set(keys)):
            raise ValueError("Analyst configuration metadata keys must be unique")
        return self


class AnalystStatus(StrEnum):
    COMPLETE = "complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"


class AnalystInterpretation(AnalystModel):
    text: str = Field(min_length=1)
    market_evidence_ids: tuple[str, ...] = ()
    context_record_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def grounded(self):
        if not self.market_evidence_ids and not self.context_record_ids:
            raise ValueError("Analyst interpretations must cite market or context evidence")
        return self


class AnalystResponseV1(AnalystModel):
    schema_version: Literal["xau.analyst-response.v1"] = "xau.analyst-response.v1"
    analysis: AnalysisResponse
    bullish_scenario: AnalystInterpretation
    bearish_scenario: AnalystInterpretation
    neutral_conditions: AnalystInterpretation
    context_interpretations: tuple[AnalystInterpretation, ...] = ()


class AnalystRun(AnalystModel):
    provenance: AnalystProvenance
    status: AnalystStatus
    market_data_status: Literal["available", "incomplete", "stale", "unsupported", "unavailable"]
    market_data_retrieved_at: UTCInstant
    analysis: AnalysisResponse | None = None
    report: AnalystResponseV1 | None = None
    context: ContextSnapshot
    unavailable_inputs: tuple[str, ...] = ()
    failure_reason: str | None = None
    context_status: dict[str, FeedStatus] = Field(default_factory=dict)
    response_validation: tuple[str, ...] = ()


Completion = Callable[[str], str]


def _market_data_status(packet: EvidencePacket) -> str:
    statuses = set(assess_sufficiency(packet).statuses)
    if SufficiencyStatus.STALE in statuses:
        return "stale"
    if SufficiencyStatus.UNSUPPORTED_DERIVATION in statuses:
        return "unsupported"
    if SufficiencyStatus.INVALID_CANDLES in statuses:
        return "unavailable"
    if statuses != {SufficiencyStatus.SUFFICIENT}:
        return "incomplete"
    return "available"


def build_prompt(packet: EvidencePacket, context: ContextSnapshot,
                 provenance: AnalystProvenance) -> str:
    """Build a bounded-to-evidence request; actual token limits belong to configured providers."""
    payload = {
        "prompt_version": provenance.prompt_version,
        "task": "Assess XAUUSD research evidence; return only the versioned analyst response JSON schema.",
        "response_schema": AnalystResponseV1.model_json_schema(),
        "requirements": [
            "Distinguish cited market facts, deterministic calculations, interpretations and uncertainty.",
            "Never add unsupported prices, events, news, sentiment or indicators.",
            "Use NO TRADE and insufficient evidence when deterministic gates fail.",
            "Explain conflicting timeframes; H4 is unsupported unless its policy is approved.",
            "Cite evidence IDs for each market claim and state missing or stale inputs.",
        ],
        "provenance": provenance.model_dump(mode="json"),
        "evidence_packet": packet.model_dump(mode="json"),
        "context_snapshot": context.model_dump(mode="json"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_analyst(packet: EvidencePacket, context: ContextSnapshot, provenance: AnalystProvenance,
                completion: Completion | None, *, verify_binding: Callable[[AnalystProvenance], bool]) -> AnalystRun:
    """Execute an injected completion function, validate grounding, and fail closed.

    This function has no provider client or network access. A real caller must separately
    establish source/model permission, safeguards and activation authorization.
    """
    try:
        binding_is_valid = verify_binding(provenance)
    except Exception:
        binding_is_valid = False
    if not binding_is_valid:
        return AnalystRun(provenance=provenance, status=AnalystStatus.UNAVAILABLE,
                          market_data_status="unavailable", market_data_retrieved_at=packet.retrieved_at,
                          failure_reason="immutable_manifest_binding_not_verified", context=context,
                          context_status=context.feed_status)
    if any(item.timeframe == Timeframe.H4 and item.state == TimeframeState.AVAILABLE
           for item in packet.timeframes):
        return AnalystRun(provenance=provenance, status=AnalystStatus.UNAVAILABLE, context=context,
                          market_data_status="unsupported", market_data_retrieved_at=packet.retrieved_at,
                          failure_reason="h4_policy_deferred", context_status=context.feed_status)
    sufficiency = assess_sufficiency(packet)
    market_status = _market_data_status(packet)
    unavailable = list(sufficiency.warnings)
    unavailable.extend(context.unavailable_reasons)
    unavailable.extend(f"{name}:{status.value}" for name, status in context.feed_status.items()
                       if status != FeedStatus.AVAILABLE)
    if not sufficiency.sufficient:
        return AnalystRun(provenance=provenance, status=AnalystStatus.INSUFFICIENT_EVIDENCE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          analysis=deterministic_no_trade(packet), context=context,
                          unavailable_inputs=tuple(dict.fromkeys(unavailable)), context_status=context.feed_status)
    if completion is None:
        return AnalystRun(provenance=provenance, status=AnalystStatus.UNAVAILABLE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          context=context, unavailable_inputs=tuple(dict.fromkeys(unavailable)), failure_reason="completion_not_configured",
                          context_status=context.feed_status)
    try:
        raw = completion(build_prompt(packet, context, provenance))
    except Exception as error:
        return AnalystRun(provenance=provenance, status=AnalystStatus.UNAVAILABLE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          unavailable_inputs=tuple(dict.fromkeys(unavailable)),
                          failure_reason=f"completion_failed:{type(error).__name__}", context=context,
                          context_status=context.feed_status)
    try:
        report = AnalystResponseV1.model_validate_json(raw)
    except (ValidationError, ValueError):
        return AnalystRun(provenance=provenance, status=AnalystStatus.INVALID_RESPONSE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          unavailable_inputs=tuple(dict.fromkeys(unavailable)),
                          failure_reason="response_schema_invalid", context=context, context_status=context.feed_status)
    response = report.analysis
    validation = validate_response(packet, response)
    if (response.provider_metadata is None or response.provider_metadata.provider_id != provenance.provider_id
            or response.provider_metadata.model_id != provenance.model_id
            or response.provider_metadata.analysis_request_id != provenance.analysis_request_id):
        return AnalystRun(provenance=provenance, status=AnalystStatus.INVALID_RESPONSE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          unavailable_inputs=tuple(dict.fromkeys(unavailable)),
                          failure_reason="provider_model_provenance_mismatch", context=context,
                          context_status=context.feed_status)
    if not validation.valid:
        return AnalystRun(provenance=provenance, status=AnalystStatus.INVALID_RESPONSE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          unavailable_inputs=tuple(dict.fromkeys(unavailable)),
                          failure_reason="response_evidence_validation_failed", context=context,
                          context_status=context.feed_status,
                          response_validation=validation.errors)
    context_records = {context_record_reference(name, record.source_id, record.revision_id
            if hasattr(record, "revision_id") else record.sentiment_id): (name, record.source_id)
        for name, collection in (
        ("calendar", context.events), ("macro", context.macro), ("news", context.news),
        ("sentiment", context.sentiment)) for record in collection}
    market_ids = {record.evidence_id for record in packet.evidence}
    invalid_citations = False
    for claim in (report.bullish_scenario, report.bearish_scenario, report.neutral_conditions,
                  *report.context_interpretations):
        if not set(claim.market_evidence_ids) <= market_ids:
            unavailable.append("analyst_scenario_unknown_market_evidence")
            invalid_citations = True
            break
        for record_id in claim.context_record_ids:
            record = context_records.get(record_id)
            if (record is None or context.feed_status[record[0]] != FeedStatus.AVAILABLE):
                unavailable.append("analyst_scenario_context_evidence_unavailable")
                invalid_citations = True
                break
        if "analyst_scenario_context_evidence_unavailable" in unavailable:
            break
        allowed_values = {item.value for item in packet.evidence
                          if item.evidence_id in claim.market_evidence_ids and item.value is not None}
        for record_id in claim.context_record_ids:
            name, _source_id = context_records[record_id]
            collection = {"calendar": context.events, "macro": context.macro, "news": context.news,
                          "sentiment": context.sentiment}[name]
            item = next(record for record in collection if record_id == context_record_reference(
                name, record.source_id, record.revision_id if hasattr(record, "revision_id") else record.sentiment_id))
            for field in ("actual", "forecast", "previous", "value"):
                raw_value = getattr(item, field, None)
                if raw_value is not None:
                    try:
                        allowed_values.add(Decimal(raw_value))
                    except (InvalidOperation, TypeError):
                        pass
        for literal in re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?", claim.text):
            try:
                value = Decimal(literal.rstrip("%").replace(",", ""))
            except InvalidOperation:
                continue
            if value not in allowed_values:
                unavailable.append("analyst_scenario_unsupported_numeric_claim")
                invalid_citations = True
                break
        if invalid_citations:
            break
    if invalid_citations:
        return AnalystRun(provenance=provenance, status=AnalystStatus.INVALID_RESPONSE,
                          market_data_status=market_status, market_data_retrieved_at=packet.retrieved_at,
                          unavailable_inputs=tuple(dict.fromkeys(unavailable)),
                          failure_reason="response_evidence_validation_failed", context=context,
                          context_status=context.feed_status)
    return AnalystRun(provenance=provenance, status=AnalystStatus.COMPLETE, market_data_status=market_status,
                      market_data_retrieved_at=packet.retrieved_at, analysis=response, report=report,
                      context=context,
                      unavailable_inputs=tuple(dict.fromkeys(unavailable)), context_status=context.feed_status)
