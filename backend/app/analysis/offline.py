"""Explicit synthetic-only handoff; no provider, worker, scheduler or startup work."""
from datetime import datetime
from pathlib import Path
import uuid

from pydantic import ValidationError

from app.ai.evidence import EvidencePacket, FreshnessPolicy, Timeframe
from app.data import refresh
from app.data.contracts import utc_instant
from app.data.ingestion import build_evidence, MINIMUM_CLOSED_CANDLES, PERSONAL_ANALYSIS_TIMEFRAMES
from app.data.refresh_protocol import PageSequence, RefreshSpec
from app.data.siftingio import INTERVALS, NormalizedCandle, SiftingError


FRAME_INTERVALS = {Timeframe.D1: '1d', Timeframe.H1: '1h', Timeframe.M15: '15m'}


def require_resolved_cleanup():
    with refresh._registry_lock:
        if refresh._unresolved:
            raise SiftingError('cleanup_unresolved')


def stage_synthetic_pages(store, spec: RefreshSpec, pages, *, now: datetime):
    """Validate supplied fixture pages through the production page protocol, never HTTP."""
    require_resolved_cleanup()
    spec = RefreshSpec.model_validate(spec.model_dump())
    now = utc_instant(now)
    attempt = 'synthetic-' + uuid.uuid4().hex
    store.begin_sifting_retrieval(attempt, spec.interval, spec.start, spec.end, now)
    try:
        sequence = PageSequence(spec)
        for value in pages:
            try:
                page = sequence.add(value)
            except ValidationError as error:
                if 'Invalid page cursor' in str(error):
                    raise SiftingError('invalid_cursor') from None
                raise
            if page.retrieved_at > now:
                raise ValueError('Fixture retrieval is in the future')
        if not sequence.complete:
            raise SiftingError('pagination_indeterminate')
        for page in sequence.pages:
            store.persist_sifting_page(spec.interval, spec.start, spec.end, page,
                retrieval_id=attempt, limit=spec.limit, synthetic=True)
        store.finish_sifting_retrieval(attempt, 'complete', now)
        return attempt
    except BaseException:
        store.finish_sifting_retrieval(attempt, 'failed', now)
        raise


def prepare_synthetic_evidence(store, *, now: datetime, freshness_seconds):
    """Gate the latest whole three-timeframe fixture before invoking the evidence/engine path."""
    require_resolved_cleanup()
    connection = store.connection
    if connection.in_transaction:
        raise ValueError('Evidence gate requires its own read snapshot')
    connection.execute('BEGIN')
    try:
        now = utc_instant(now)
        policy = FreshnessPolicy(max_age_seconds=freshness_seconds)
        if set(policy.max_age_seconds) != set(PERSONAL_ANALYSIS_TIMEFRAMES):
            raise ValueError('Explicit freshness is required for D1/H1/M15')
        retrieval_times = []
        for tf, interval in FRAME_INTERVALS.items():
            retrieval = store.sifting_retrieval(interval)
            if not retrieval or retrieval['status'] != 'complete' or not retrieval.get('synthetic'):
                raise ValueError('synthetic_complete_retrieval_required')
            candles = tuple(NormalizedCandle.model_validate({key:value for key,value in row.items() if key not in {"retrieval_id", "revision_id"}})
                            for row in retrieval['candles'])
            if any(c.state.value != 'closed' or c.closes_at > now or c.retrieved_at > now for c in candles):
                raise ValueError('forming_or_future_candle')
            retrieval_times.extend(c.retrieved_at for c in candles)
            if len(candles) < MINIMUM_CLOSED_CANDLES[tf]:
                raise ValueError('insufficient_closed_depth')
            step = INTERVALS[interval][0]
            start = datetime.fromisoformat(retrieval['start'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(retrieval['end'].replace('Z', '+00:00'))
            openings = [c.opened_at for c in candles]
            expected_count = int((min(end, now-step)-start) // step) + 1
            if (not openings or openings[0] != start or openings[-1] != end or len(openings) != expected_count
                    or any(b-a != step for a,b in zip(openings, openings[1:]))):
                raise ValueError('candle_gap')
            if (now-candles[-1].closes_at).total_seconds() > policy.max_age_seconds[tf]:
                raise ValueError('stale_data')
        packet, sufficiency = build_evidence(store, retrieved_at=max(retrieval_times), analysis_at=now, requested=PERSONAL_ANALYSIS_TIMEFRAMES,
            freshness_seconds=dict(policy.max_age_seconds))
        if not sufficiency.sufficient:
            raise ValueError('insufficient_evidence')
        values = packet.model_dump(mode='json')
        values['analysis_id'] = 'synthetic-' + packet.analysis_id.removeprefix('siftingio-')
        values['instrument']['instrument_id'] = 'xau-usd:spot-synthetic'
        for source in values['sources']:
            source['instrument'] = values['instrument']
            source['provider_id'] = 'synthetic-fixture'
            source['feed_id'] = 'offline-fixture'
        return EvidencePacket.model_validate(values)
    finally:
        connection.execute('ROLLBACK')


def persist_synthetic_analysis(store, archive, *, now: datetime, freshness_seconds):
    """Archive one gated fixture and its mock Analyst result, with no external completion hook."""
    from app.ai.analyst import AnalystProvenance
    from app.ai.persistence import run_and_persist_analyst
    from app.ai.offline_mock import mock_completion
    from app.analysis.engine import AnalysisParameters
    from app.analysis.provenance import persist_analysis
    from app.canonical import CanonicalLimits
    from app.data.context import process_context
    from app.data.evidence_contracts import MVP_TIMEFRAMES, structured_profile_registry

    if archive.required_timeframes != MVP_TIMEFRAMES:
        raise ValueError('Offline MVP requires its explicit three-timeframe archive')
    packet = prepare_synthetic_evidence(store, now=now, freshness_seconds=freshness_seconds)
    candle_path = store.connection.execute('PRAGMA database_list').fetchone()[2]
    if Path(candle_path).suffixes[-2:] != ['.synthetic','.sqlite3']:
        raise ValueError('Offline projection requires a separate synthetic candle file')
    # shortcut: paired files use a local path; add portable source identities when archives must move.
    previous = archive.connection.execute("SELECT value FROM archive_metadata WHERE key='candle_store_path'").fetchone()
    if previous is not None and previous[0] != candle_path:
        raise ValueError('Archive is already bound to another candle store')
    if previous is None:
        archive.connection.execute("INSERT INTO archive_metadata VALUES ('candle_store_path',?)",(candle_path,))
    identity = packet.analysis_id
    limits = CanonicalLimits(8_000_000, 1000, 1000, 1000, 8_000_000)
    registry = structured_profile_registry()
    options = dict(limits=limits, registry=registry, max_payload_bytes=8_000_000)
    ranges = {}
    for frame in packet.timeframes:
        source = next(s for s in packet.sources if s.source_id == frame.source_ids[0])
        interval = FRAME_INTERVALS[frame.timeframe]
        start, end = frame.candles[0].opened_at, frame.candles[-1].opened_at
        ranges[interval] = (start,end)
        evidence_id = 'fixture-' + source.retrieval_id
        archive.store_evidence(evidence_id, 'synthetic-fixture', 'raw_provider_body', source.retrieved_at,
            packet.model_dump_json().encode(), payload_retention_permitted=True,
            metadata_retention_permitted=True, credential_free=True)
        archive.begin_retrieval(source.retrieval_id, source.series_id, packet.instrument.instrument_id,
            'synthetic-fixture', interval, start, end, source.retrieved_at)
        for index, candle in enumerate(frame.candles):
            archive.add_revision(candle.revision_id, candle.candle_id, source.retrieval_id, index)
        archive.finish_retrieval(source.retrieval_id, 'verified', utc_instant(now), evidence_id)
        archive.promote_retrieval(source.retrieval_id)
    manifest_id, derived_id = 'input-'+identity, 'derived-'+identity
    archive.create_manifest(manifest_id, ranges, now, **options)
    # Existing persistence owns calculation; remove derived IDs before its deterministic replay.
    raw = packet.model_dump(mode='json')
    raw['evidence'] = []
    for frame in raw['timeframes']:
        frame['evidence_ids'] = []
    _, derived, analyzed = persist_analysis(archive, manifest_id, EvidencePacket.model_validate(raw),
        output_id=identity, derived_id=derived_id, timeframe='1h', window_start=ranges['1h'][0],
        window_end=ranges['1h'][1], created_at=now, parameters=AnalysisParameters(),
        policy_id='synthetic-mvp-v1', **options)
    digest = archive.connection.execute('SELECT digest FROM manifests WHERE manifest_id=?',(manifest_id,)).fetchone()[0]
    provenance = AnalystProvenance(input_manifest_id=manifest_id, input_manifest_digest=digest,
        derived_manifest_id=derived_id, derived_manifest_digest=derived.digest,
        provider_id='offline-mock', model_id='deterministic-stub', analysis_request_id='request-'+identity,
        prompt_version='offline-mvp-v1', configuration_metadata=(('external_calls_enabled',False),), created_at=now)
    result = run_and_persist_analyst(archive, analyzed, process_context(retrieved_at=now,
        source_registry_version='synthetic-mvp-v1'), provenance, mock_completion,
        response_id='response-'+identity, report_id='report-'+identity, **options)
    return identity, result
