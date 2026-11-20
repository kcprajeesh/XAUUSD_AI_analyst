"""Synthetic-only analysis-to-archive provenance workflow."""

from datetime import datetime
import json

from app.analysis.engine import ANALYSIS_ALGORITHM_ID, ANALYSIS_ALGORITHM_VERSION, AnalysisParameters, analyze_packet
from app.canonical import CanonicalLimits, canonical_json
from app.canonical_digest import DigestRegistry
from app.data.archive_prototype import SyntheticArchive, _utc
from app.data.evidence_contracts import (ANALYSIS_OUTPUT_SCHEMA, DERIVED_MANIFEST_V2_SCHEMA,
    AnalysisOutput, DerivedManifestV2, digest_analysis_output, digest_derived_manifest_v2)


def persist_analysis(archive: SyntheticArchive, manifest_id: str, packet, *, output_id: str,
                     derived_id: str, timeframe: str, window_start: datetime, window_end: datetime,
                     created_at: datetime, parameters: AnalysisParameters, registry: DigestRegistry,
                     limits: CanonicalLimits, max_payload_bytes: int, policy_id: str,
                     unavailable_inputs: tuple[str, ...] = ()):
    """Analyze one immutable packet and atomically persist its canonical output/provenance pair."""
    archive.assert_manifest_eligible(manifest_id)
    manifest = archive.connection.execute("SELECT digest FROM manifests WHERE manifest_id=?", (manifest_id,)).fetchone()
    if manifest is None:
        raise ValueError("Unknown input manifest")
    selected = archive.connection.execute(
        "SELECT mi.retrieval_id,mr.revision_id FROM manifest_items mi JOIN manifest_revisions mr "
        "USING(manifest_id,timeframe) WHERE mi.manifest_id=? ORDER BY mi.timeframe,mr.revision_id", (manifest_id,)).fetchall()
    retrieval_ids = tuple(sorted({row[0] for row in selected}))
    revision_ids = tuple(row[1] for row in selected)
    selected_retrievals, selected_revisions = set(retrieval_ids), set(revision_ids)
    packet_retrievals = {source.retrieval_id for source in packet.sources if source.retrieval_id is not None}
    packet_revisions = {c.revision_id for item in packet.timeframes for c in item.candles if c.revision_id is not None}
    if packet_retrievals - selected_retrievals or packet_revisions - selected_revisions:
        raise ValueError("Analysis packet contains lineage outside the immutable input manifest")
    used_candles = tuple(c for item in packet.timeframes if item.state.value == "available" for c in item.candles)
    if any(c.retrieval_id is None or c.revision_id is None for c in used_candles):
        raise ValueError("Analyzed candles require immutable retrieval and revision lineage")
    selected_window = archive.connection.execute(
        "SELECT requested_start,requested_end FROM manifest_items WHERE manifest_id=? AND timeframe=?",
        (manifest_id, timeframe)).fetchone()
    if selected_window is None or tuple(selected_window) != (_utc(window_start), _utc(window_end)):
        raise ValueError("Analysis window must match its selected immutable input range")
    analyzed = analyze_packet(packet, parameters)
    output_json = json.dumps(analyzed.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    output = AnalysisOutput(output_id, manifest_id, output_json)
    output_metadata = digest_analysis_output(output, registry, limits, max_payload_bytes)
    output_payload = canonical_json(output.payload(limits), ANALYSIS_OUTPUT_SCHEMA, limits)
    parameter_context = json.dumps({"swing_left": parameters.swing_left, "swing_right": parameters.swing_right,
        "equal_level_tolerance": str(parameters.equal_level_tolerance),
        "order_block_displacement_atr": str(parameters.order_block_displacement_atr),
        "session_definitions": [str(item) for item in parameters.session_definitions]},
        sort_keys=True, separators=(",", ":"))
    unavailable = tuple(sorted(set(unavailable_inputs) | {
        f"{item.timeframe.value}:{item.state.value}" for item in packet.timeframes
        if item.state.value != "available"}))
    provenance = DerivedManifestV2(derived_id, manifest_id, manifest[0], retrieval_ids, revision_ids,
        output_id, output_metadata.digest, ANALYSIS_ALGORITHM_ID, ANALYSIS_ALGORITHM_VERSION,
        parameter_context, policy_id, timeframe, _utc(window_start), _utc(window_end),
        unavailable, _utc(created_at))
    derived_metadata = digest_derived_manifest_v2(provenance, registry, limits, max_payload_bytes)
    derived_payload = canonical_json(provenance.payload(limits), DERIVED_MANIFEST_V2_SCHEMA, limits)
    archive.persist_provenance(manifest_id, output_id, output_payload, output_metadata.digest,
                                derived_id, derived_payload, derived_metadata.digest,
                                registry=registry, limits=limits, max_payload_bytes=max_payload_bytes)
    return output_metadata, derived_metadata, analyzed
