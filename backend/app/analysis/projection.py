"""Read-only projection of an immutable archived deterministic analysis output."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.ai.analyst import AnalystRun, AnalystStatus
from app.ai.contracts import validate_response
from app.data.context import FeedStatus, context_record_reference
from app.ai.evidence import EvidencePacket, EvidenceType, QualityStatus, Timeframe, TimeframeState
from app.canonical import CanonicalLimits, JSONNumber, canonical_json, parse_json
from app.canonical_digest import DigestRegistry, digest_structured
from app.data.evidence_contracts import (ANALYSIS_OUTPUT_SCHEMA, DERIVED_MANIFEST_V2_SCHEMA,
    MANIFEST_SCHEMA, AI_REQUEST_SCHEMA, AI_RESPONSE_SCHEMA, AI_REPORT_SCHEMA, AI_PROMPT_SCHEMA,
    structured_profile_registry)


class ProjectionError(ValueError):
    pass


class ProjectionNotFound(ProjectionError):
    pass


class ProjectedTimeframe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timeframe: Timeframe
    state: Literal["available", "unavailable", "unsupported"]


class ProjectedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    evidence_type: EvidenceType
    description: str
    value: str | None
    units: str | None
    timeframe: Timeframe | None
    observed_at: AwareDatetime
    source_ids: tuple[str, ...]
    calculation_method: str | None
    quality: QualityStatus
    candle_refs: tuple[str, ...]


class ProjectedDeterministicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    analysis_id: str
    analysis_at: AwareDatetime
    retrieved_at: AwareDatetime
    requested_timeframes: tuple[Timeframe, ...]
    timeframes: tuple[ProjectedTimeframe, ...]
    evidence: tuple[ProjectedEvidence, ...]


class ProjectedAIReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "insufficient_evidence", "unavailable", "invalid_response"]
    report_id: str | None = None
    report_digest: str | None = None
    response_id: str
    response_digest: str
    request_id: str
    request_digest: str
    provider_id: str
    model_id: str
    prompt_version: str
    report: dict | None = None


class ProjectedCandle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timeframe: Timeframe
    opened_at: AwareDatetime
    closed_at: AwareDatetime
    open: str
    high: str
    low: str
    close: str


class AnalysisProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["xau.dashboard-analysis.v1"] = "xau.dashboard-analysis.v1"
    environment: Literal["synthetic_archive"] = "synthetic_archive"
    analysis_id: str
    status: Literal["available", "historical_invalidated"]
    analysis_timestamp: AwareDatetime
    market_data_status: Literal["available", "incomplete", "unavailable"]
    market_data_timestamp: AwareDatetime
    freshness_status: Literal["unassessed", "fresh"] = "unassessed"
    valid_until: AwareDatetime | None = None
    candles: tuple[ProjectedCandle, ...] = ()
    source_eligibility_status: Literal["unverified"] = "unverified"
    source_attribution: tuple[str, ...]
    retrieval_completeness: dict[str, Literal["verified", "incomplete", "unsupported", "collecting"]]
    timeframe_availability: dict[str, Literal["available", "unavailable", "unsupported"]]
    analyst_outcome: Literal["unavailable", "complete", "insufficient_evidence"] = "unavailable"
    analyst_unavailable_reason: str = "no_persisted_analyst_report"
    ai_report: ProjectedAIReport | None = None
    evidence_quality: str
    unavailable_inputs: tuple[str, ...]
    invalidation_warnings: tuple[str, ...]
    input_manifest_id: str
    input_manifest_digest: str
    derived_manifest_id: str
    derived_manifest_digest: str
    analysis_output_digest: str
    algorithm_id: str
    algorithm_version: str
    analysis_output: ProjectedDeterministicOutput


def _digest(payload: bytes, schema, domain: str, schema_id: str, registry: DigestRegistry,
            limits: CanonicalLimits, max_payload_bytes: int) -> tuple[dict, str]:
    value = parse_json(payload, limits)
    profile = next((item for item in registry.entries
                    if item.domain == domain and item.schema_version == schema_id), None)
    if profile is None:
        raise ProjectionError("registered_digest_profile_unavailable")
    calculated = digest_structured(value, schema, profile, registry, limits, max_payload_bytes).digest
    return value, calculated


def _record_digest(payload: bytes, schema, domain: str, schema_id: str, registry: DigestRegistry,
                   limits: CanonicalLimits, max_payload_bytes: int):
    return _digest(payload, schema, domain, schema_id, registry, limits, max_payload_bytes)


def _project_in_snapshot(connection, analysis_id: str, *, limits: CanonicalLimits,
                         max_payload_bytes: int, registry: DigestRegistry, freshness_at=None) -> AnalysisProjection:
    output = connection.execute(
        "SELECT output_id,manifest_id,digest,schema_id,payload FROM analysis_outputs WHERE output_id=?",
        (analysis_id,)).fetchone()
    if output is None:
        raise ProjectionNotFound("analysis_not_found")
    derived = connection.execute(
        "SELECT derived_id,manifest_id,output_id,digest,schema_id,payload FROM derived_manifests WHERE output_id=?",
        (output[0],)).fetchone()
    manifest = connection.execute("SELECT manifest_id,created_at,instrument_id,payload,digest FROM manifests WHERE manifest_id=?",
                                  (output[1],)).fetchone()
    if derived is None or manifest is None:
        raise ProjectionError("analysis_provenance_missing")
    input_payload, input_digest = _digest(bytes(manifest[3]), MANIFEST_SCHEMA, "evidence.input-manifest",
                                          "xau.input-manifest.v1", registry, limits, max_payload_bytes)
    output_record, output_digest = _digest(bytes(output[4]), ANALYSIS_OUTPUT_SCHEMA, "evidence.analysis-output",
                                          output[3], registry, limits, max_payload_bytes)
    derived_record, derived_digest = _digest(bytes(derived[5]), DERIVED_MANIFEST_V2_SCHEMA,
                                            "evidence.derived-manifest.v2", derived[4], registry, limits,
                                            max_payload_bytes)
    if (input_digest != manifest[4] or output_digest != output[2] or derived_digest != derived[3]
            or output[3] != "xau.analysis-output.v1" or derived[4] != "xau.derived-manifest.v2"
            or output_record.get("analysis_output_id") != output[0]
            or output_record.get("input_manifest_id") != manifest[0]
            or derived[0] != derived_record.get("derived_manifest_id")
            or derived[1] != manifest[0] or derived[2] != output[0]
            or derived_record.get("input_manifest_id") != manifest[0]
            or derived_record.get("input_manifest_digest") != input_digest
            or derived_record.get("analysis_output_id") != output[0]
            or derived_record.get("analysis_output_digest") != output_digest):
        raise ProjectionError("analysis_provenance_digest_or_linkage_mismatch")
    try:
        packet = EvidencePacket.model_validate_json(output_record["output_json"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ProjectionError("persisted_analysis_output_malformed") from exc
    if packet.instrument.canonical_symbol != "XAUUSD":
        raise ProjectionError("persisted_instrument_mismatch")
    selected_revisions = {revision for item in input_payload["items"] for revision in item["revisions"]}
    selected_retrievals = {item["retrieval_id"] for item in input_payload["items"]}
    if (set(derived_record.get("selected_revision_ids", ())) != selected_revisions
            or set(derived_record.get("selected_retrieval_ids", ())) != selected_retrievals):
        raise ProjectionError("analysis_selected_lineage_mismatch")
    retrieval_rows = connection.execute(
        "SELECT retrieval_id,provider_id,completeness FROM retrievals WHERE retrieval_id IN ("
        + ",".join("?" for _ in selected_retrievals) + ") ORDER BY retrieval_id",
        tuple(sorted(selected_retrievals))).fetchall()
    if {row[0] for row in retrieval_rows} != selected_retrievals:
        raise ProjectionError("selected_retrieval_missing")
    invalidated = tuple(row[0] for row in connection.execute(
        "SELECT DISTINCT i.revision_id FROM invalidations i JOIN manifest_revisions mr USING(revision_id) "
        "WHERE mr.manifest_id=? ORDER BY i.revision_id", (manifest[0],)))
    states = {item.timeframe.value: ("available" if item.state == TimeframeState.AVAILABLE
              else "unsupported" if item.state == TimeframeState.UNSUPPORTED else "unavailable")
              for item in packet.timeframes}
    states.setdefault("4H", "unsupported")
    states["1M"] = "unsupported"
    available = sum(value == "available" for value in states.values())
    unavailable_values = [*derived_record.get("unavailable_inputs", ()),
                          "analyst:no_persisted_analyst_report", "macro:no_persisted_context",
                          "news:no_persisted_context"]
    unavailable_values.extend(f"retrieval:{row[0]}:{row[2]}" for row in retrieval_rows if row[2] != "verified")
    providers = tuple(sorted({row[1] for row in retrieval_rows if row[1]}))
    if not providers:
        unavailable_values.append("market_data:source_attribution_unavailable")
    unavailable = tuple(dict.fromkeys(unavailable_values))
    evidence_quality = ("incomplete" if available < len(packet.requested_timeframes)
                        or any(row[2] != "verified" for row in retrieval_rows) else "unassessed")
    ai_projection = None
    ai_request = connection.execute("SELECT request_id,digest,schema_id,payload FROM ai_requests WHERE output_id=?",
                                    (output[0],)).fetchone()
    if ai_request is not None:
        request_record, request_digest = _record_digest(bytes(ai_request[3]), AI_REQUEST_SCHEMA, "ai.request",
            ai_request[2], registry, limits, max_payload_bytes)
        response_row = connection.execute("SELECT response_id,digest,schema_id,payload FROM ai_responses WHERE request_id=?",
                                          (ai_request[0],)).fetchone()
        if response_row is None:
            raise ProjectionError("AI response record missing")
        response_record, response_digest = _record_digest(bytes(response_row[3]), AI_RESPONSE_SCHEMA, "ai.response",
            response_row[2], registry, limits, max_payload_bytes)
        if (request_digest != ai_request[1] or response_digest != response_row[1]
                or request_record.get("request_id") != ai_request[0]
                or response_record.get("request_id") != ai_request[0]
                or request_record.get("analysis_id") != output[0]
                or request_record.get("input_manifest_digest") != input_digest
                or request_record.get("derived_manifest_digest") != derived_digest
                or request_record.get("output_digest") != output_digest):
            raise ProjectionError("AI request or response provenance mismatch")
        try:
            request_content = parse_json(request_record["payload_json"].encode(), limits)
            prompt = request_content["prompt"]
            prompt_digest = _record_digest(canonical_json({"prompt": prompt}, AI_PROMPT_SCHEMA, limits),
                AI_PROMPT_SCHEMA, "ai.prompt", "xau.ai-prompt.v1", registry, limits, max_payload_bytes)[1]
        except (KeyError, ValueError, TypeError) as exc:
            raise ProjectionError("persisted AI request malformed") from exc
        if prompt_digest != request_record.get("prompt_digest"):
            raise ProjectionError("AI prompt digest mismatch")
        report_row = connection.execute("SELECT report_id,digest,schema_id,payload FROM ai_reports WHERE request_id=?",
                                        (ai_request[0],)).fetchone()
        report_payload = None
        report_digest = None
        report_id = None
        if report_row is not None:
            report_value, report_digest = _record_digest(bytes(report_row[3]), AI_REPORT_SCHEMA, "ai.report",
                report_row[2], registry, limits, max_payload_bytes)
            report_id = report_row[0]
            if (report_digest != report_row[1] or report_value.get("report_id") != report_id
                    or report_value.get("canonicalization_profile") != "xau.canon.json-utf8-nfc-decimal-utc6.v1"
                    or report_value.get("framing_version") != JSONNumber("1")
                    or report_value.get("request_id") != ai_request[0]
                    or report_value.get("response_id") != response_row[0]
                    or report_value.get("analysis_id") != output[0]
                    or report_value.get("input_manifest_digest") != input_digest
                    or report_value.get("derived_manifest_digest") != derived_digest
                    or report_value.get("output_digest") != output_digest
                    or report_value.get("provider_id") != request_record.get("provider_id")
                    or report_value.get("model_id") != request_record.get("model_id")
                    or report_value.get("prompt_version") != request_record.get("prompt_version")):
                raise ProjectionError("AI report provenance mismatch")
            try:
                report_payload = parse_json(report_value["payload_json"].encode(), limits)
                persisted_run = AnalystRun.model_validate(report_payload)
            except (KeyError, ValueError, TypeError) as exc:
                raise ProjectionError("persisted AI report malformed") from exc
            provenance = persisted_run.provenance
            if (persisted_run.status.value != response_record["status"]
                    or provenance.input_manifest_id != manifest[0]
                    or provenance.input_manifest_digest != input_digest
                    or provenance.derived_manifest_id != derived[0]
                    or provenance.derived_manifest_digest != derived_digest
                    or provenance.provider_id != request_record["provider_id"]
                    or provenance.model_id != request_record["model_id"]
                    or provenance.prompt_version != request_record["prompt_version"]
                    or provenance.analysis_request_id != ai_request[0]):
                raise ProjectionError("persisted AI report output binding mismatch")
            if persisted_run.analysis is not None and persisted_run.analysis.analysis_id != packet.analysis_id:
                raise ProjectionError("persisted AI analysis identity mismatch")
            if persisted_run.status == AnalystStatus.INSUFFICIENT_EVIDENCE:
                if (persisted_run.analysis is None or not validate_response(packet, persisted_run.analysis).valid
                        or persisted_run.analysis.trade_stance.value != "NO TRADE"):
                    raise ProjectionError("insufficient-evidence report is not a validated NO TRADE outcome")
            if persisted_run.status == AnalystStatus.COMPLETE:
                if persisted_run.analysis is None or not validate_response(packet, persisted_run.analysis).valid:
                    raise ProjectionError("persisted AI analysis failed evidence validation")
                if any(item.timeframe == Timeframe.H4 and item.state == TimeframeState.AVAILABLE
                       for item in packet.timeframes):
                    raise ProjectionError("persisted AI analysis claims deferred H4 evidence")
                context_refs = {}
                for name, records in (("calendar", persisted_run.context.events), ("macro", persisted_run.context.macro),
                                      ("news", persisted_run.context.news), ("sentiment", persisted_run.context.sentiment)):
                    for record in records:
                        revision = record.revision_id if hasattr(record, "revision_id") else record.sentiment_id
                        context_refs[context_record_reference(name, record.source_id, revision)] = name
                for claim in (persisted_run.report.bullish_scenario, persisted_run.report.bearish_scenario,
                              persisted_run.report.neutral_conditions, *persisted_run.report.context_interpretations):
                    if (not set(claim.market_evidence_ids) <= {item.evidence_id for item in packet.evidence}
                            or any(ref not in context_refs or persisted_run.context_status[context_refs[ref]] != FeedStatus.AVAILABLE
                                   for ref in claim.context_record_ids)):
                        raise ProjectionError("persisted AI scenario citation is unavailable")
        ai_projection = ProjectedAIReport(status=response_record["status"], report_id=report_id,
            report_digest=report_digest, response_id=response_row[0], response_digest=response_digest,
            request_id=ai_request[0], request_digest=request_digest, provider_id=request_record["provider_id"],
            model_id=request_record["model_id"], prompt_version=request_record["prompt_version"], report=report_payload)
    # Select display fields verbatim from the persisted packet; omit source/candle internals.
    exact_output = ProjectedDeterministicOutput.model_validate({
        "analysis_id": packet.analysis_id,
        "analysis_at": packet.analysis_at.isoformat().replace("+00:00", "Z"),
        "retrieved_at": packet.retrieved_at.isoformat().replace("+00:00", "Z"),
        "requested_timeframes": [item.value for item in packet.requested_timeframes],
        "timeframes": [{"timeframe": item.timeframe.value, "state": item.state.value}
                       for item in packet.timeframes],
        "evidence": [{"evidence_id": item.evidence_id, "evidence_type": item.evidence_type.value,
                      "description": item.description, "value": str(item.value) if item.value is not None else None,
                      "units": item.units, "timeframe": item.timeframe.value if item.timeframe else None,
                      "observed_at": item.observed_at.isoformat().replace("+00:00", "Z"),
                      "source_ids": list(item.source_ids), "calculation_method": item.calculation_method,
                      "quality": item.quality.value, "candle_refs": list(item.candle_refs)}
                     for item in packet.evidence],
    })
    view = AnalysisProjection(
        analysis_id=output[0], status="historical_invalidated" if invalidated else "available",
        analysis_timestamp=datetime.fromisoformat(derived_record["created_at"].replace("Z", "+00:00")),
        market_data_status=("available" if available == len(packet.requested_timeframes)
                            and all(row[2] == "verified" for row in retrieval_rows) and providers
                            else "incomplete" if available or providers else "unavailable"),
        market_data_timestamp=packet.retrieved_at, source_attribution=providers,
        retrieval_completeness={row[0]: row[2] for row in retrieval_rows},
        timeframe_availability=states, evidence_quality=evidence_quality,
        unavailable_inputs=unavailable, invalidation_warnings=tuple(f"invalidated_revision:{item}" for item in invalidated),
        input_manifest_id=manifest[0], input_manifest_digest=input_digest, derived_manifest_id=derived[0],
        derived_manifest_digest=derived_digest, analysis_output_digest=output_digest,
        algorithm_id=derived_record["algorithm_id"], algorithm_version=derived_record["algorithm_version"],
        analysis_output=exact_output, ai_report=ai_projection,
        analyst_outcome=(ai_projection.status if ai_projection and ai_projection.status in {"complete", "insufficient_evidence"}
                         else "unavailable"),
        analyst_unavailable_reason=("no_persisted_analyst_report" if ai_projection is None else ai_projection.status))
    return view if freshness_at is None else _fresh_offline_projection(view, packet, freshness_at)


def _fresh_offline_projection(view, packet, now):
    from app.ai.evidence import assess_sufficiency, CandleState
    from app.data.contracts import utc_instant
    from app.data.siftingio import INTERVALS
    from app.analysis.offline import FRAME_INTERVALS
    from app.data.ingestion import MINIMUM_CLOSED_CANDLES
    now = utc_instant(now)
    if (set(packet.requested_timeframes) != set(FRAME_INTERVALS) or now < packet.analysis_at
            or view.status != "available" or view.analyst_outcome != "complete"
            or view.ai_report is None or view.ai_report.report is None or view.ai_report.report_id is None
            or view.ai_report.provider_id != "offline-mock"
            or view.ai_report.model_id != "deterministic-stub"
            or any(source.provider_id != "synthetic-fixture" for source in packet.sources)):
        raise ProjectionError("offline_analysis_not_eligible")
    current = EvidencePacket.model_validate(packet.model_dump(mode="python") | {"analysis_at": now})
    if not assess_sufficiency(current).sufficient:
        raise ProjectionError("stale_or_invalid_evidence")
    expirations, candles = [], []
    for frame in current.timeframes:
        step = INTERVALS[FRAME_INTERVALS[frame.timeframe]][0]
        if (len(frame.candles) < MINIMUM_CLOSED_CANDLES[frame.timeframe]
                or current.minimum_closed_candles.get(frame.timeframe, 0) < MINIMUM_CLOSED_CANDLES[frame.timeframe]
                or any(c.status != CandleState.CLOSED or c.closed_at-c.opened_at != step for c in frame.candles)
                or any(b.opened_at-a.opened_at != step for a,b in zip(frame.candles, frame.candles[1:]))):
            raise ProjectionError("forming_or_gapped_evidence")
        expirations.append(frame.candles[-1].closed_at + timedelta(seconds=current.freshness_max_age_seconds[frame.timeframe]))
        candles.extend(ProjectedCandle(timeframe=frame.timeframe, opened_at=c.opened_at,closed_at=c.closed_at,
            open=str(c.open),high=str(c.high),low=str(c.low),close=str(c.close)) for c in frame.candles)
    valid_until = min(expirations)
    if now >= valid_until:
        raise ProjectionError("stale_or_invalid_evidence")
    return AnalysisProjection.model_validate(view.model_dump(mode="python") | {
        "freshness_status":"fresh", "valid_until":valid_until,"candles":tuple(candles),
        "evidence_quality":"verified", "market_data_status":"available"})


def project_analysis(connection, analysis_id: str | None, *, limits: CanonicalLimits,
                     max_payload_bytes: int, registry: DigestRegistry | None = None,
                     freshness_at: datetime | None = None) -> AnalysisProjection:
    """Project one consistent SQLite read snapshot; never writes or owns production storage."""
    if connection.in_transaction:
        raise ProjectionError("projection_requires_its_own_read_snapshot")
    connection.execute("BEGIN")
    try:
        if analysis_id is None:
            latest = connection.execute("SELECT output_id FROM analysis_outputs ORDER BY rowid DESC LIMIT 1").fetchone()
            if latest is None:
                raise ProjectionNotFound("analysis_not_found")
            analysis_id = latest[0]
        return _project_in_snapshot(connection, analysis_id, limits=limits,
                                    max_payload_bytes=max_payload_bytes,
                                    registry=registry or structured_profile_registry(), freshness_at=freshness_at)
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
