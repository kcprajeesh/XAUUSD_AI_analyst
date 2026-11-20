"""M1-B uses only disposable synthetic databases and in-process fixtures."""
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from app.canonical import CanonicalLimits
from app.data.archive_prototype import SyntheticArchive
from app.data.evidence_contracts import MVP_TIMEFRAMES, structured_profile_registry
from app.data.storage import CandleStore

NOW = datetime(2026, 11, 20, tzinfo=UTC)
LIMITS = CanonicalLimits(8_000_000, 1000, 1000, 1000, 8_000_000)
REGISTRY = structured_profile_registry()


def test_three_timeframe_archive_is_separate_and_policy_survives_reopen(tmp_path):
    candle_path = tmp_path / 'candles.synthetic.sqlite3'
    with CandleStore(candle_path) as candles:
        tables = tuple(candles.connection.execute('SELECT sql FROM sqlite_master ORDER BY name'))
        assert candles.connection.execute('PRAGMA user_version').fetchone()[0] == 1
        path = tmp_path / 'analysis.synthetic.sqlite3'
        with SyntheticArchive(path, create=True, busy_timeout_ms=25, required_timeframes=MVP_TIMEFRAMES) as archive:
            assert archive.connection.execute('SELECT count(*) FROM analysis_outputs').fetchone()[0] == 0
            with pytest.raises(AttributeError):
                archive.required_timeframes = ('1h',)
            archive.store_evidence('fixture', 'synthetic', 'raw_provider_body', NOW, b'synthetic fixture',
                payload_retention_permitted=True, metadata_retention_permitted=True, credential_free=True)
            for tf in MVP_TIMEFRAMES:
                archive.begin_retrieval(tf, tf, 'synthetic:XAUUSD', 'synthetic', tf, NOW-timedelta(days=1), NOW, NOW)
                archive.add_revision('rev-'+tf, 'logical-'+tf, tf, 0)
                archive.finish_retrieval(tf, 'verified', NOW+timedelta(seconds=1), 'fixture')
                archive.promote_retrieval(tf)
            archive.create_manifest('three', {tf:(NOW-timedelta(days=1),NOW) for tf in MVP_TIMEFRAMES},
                NOW+timedelta(seconds=1), limits=LIMITS, registry=REGISTRY, max_payload_bytes=8_000_000)
            assert {row[0] for row in archive.connection.execute('SELECT timeframe FROM manifest_items')} == set(MVP_TIMEFRAMES)
            archive.verify_integrity()
        with SyntheticArchive(path, busy_timeout_ms=25) as reopened:
            assert reopened.required_timeframes == MVP_TIMEFRAMES
        assert tuple(candles.connection.execute('SELECT sql FROM sqlite_master ORDER BY name')) == tables
        assert candles.connection.execute('PRAGMA user_version').fetchone()[0] == 1
    before = candle_path.read_bytes()
    # Existing databases are inspected only through a read-only connection.
    with sqlite3.connect(candle_path.as_uri()+'?mode=ro', uri=True) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
    assert candle_path.read_bytes() == before
    with pytest.raises(FileExistsError):
        SyntheticArchive(path, create=True, busy_timeout_ms=25, required_timeframes=MVP_TIMEFRAMES)


def test_default_archive_still_rejects_three_timeframes_and_invalid_policy(tmp_path):
    with SyntheticArchive(tmp_path/'default.synthetic.sqlite3', create=True, busy_timeout_ms=25) as archive:
        with pytest.raises(ValueError, match='all five'):
            archive.create_manifest('bad', {tf:(NOW-timedelta(days=1),NOW) for tf in MVP_TIMEFRAMES},
                NOW, limits=LIMITS, registry=REGISTRY, max_payload_bytes=8_000_000)
    with pytest.raises(ValueError, match='policy'):
        SyntheticArchive(tmp_path/'bad.synthetic.sqlite3', create=True, busy_timeout_ms=25, required_timeframes=('1h',))


from hashlib import sha256
from app.analysis.offline import FRAME_INTERVALS, stage_synthetic_pages, prepare_synthetic_evidence
from app.ai.evidence import Timeframe, assess_sufficiency
from app.data.refresh_protocol import RefreshSpec
from app.data.siftingio import INTERVALS, NormalizedCandle, Page, SiftingError

FRESHNESS = {tf:3600 for tf in FRAME_INTERVALS}


def fixture_page(interval, count, *, gap=False, forming=False):
    step = INTERVALS[interval][0]
    start = NOW-step*count
    candles = [NormalizedCandle(interval=interval, opened_at=start+step*i, closes_at=start+step*(i+1),
        open='2000', high='2002', low='1999', close='2001', state='closed', retrieved_at=NOW,
        source_record_hash=sha256(f'synthetic:{interval}:{i}'.encode()).hexdigest()) for i in range(count)]
    if gap:
        del candles[50]
    if forming:
        candles.append(NormalizedCandle(interval=interval, opened_at=NOW, closes_at=NOW+step,
            open='2000', high='2002', low='1999', close='2001', state='forming', retrieved_at=NOW,
            source_record_hash=sha256(b'synthetic-forming').hexdigest()))
    page = Page(candles=tuple(candles), next_cursor=None, raw_count=len(candles), retrieved_at=NOW,
        payload_hash=sha256(b'explicitly synthetic fixture').hexdigest())
    spec = RefreshSpec(interval=interval, start=start, end=NOW if forming else NOW-step, limit=1000, max_pages=2)
    return spec, page


def seed_candles(store, *, gap=False, forming=False):
    for tf, interval in FRAME_INTERVALS.items():
        count = 201 if tf == Timeframe.D1 and gap else 200 if tf == Timeframe.D1 else 300
        spec, page = fixture_page(interval, count, gap=gap and tf == Timeframe.D1,
                                  forming=forming and tf == Timeframe.H1)
        stage_synthetic_pages(store, spec, [page.model_dump(mode='json')], now=NOW)


def test_gate_builds_closed_fresh_three_timeframe_deterministic_evidence(tmp_path):
    with CandleStore(tmp_path/'fixture.synthetic.sqlite3') as store:
        seed_candles(store)
        packet = prepare_synthetic_evidence(store, now=NOW, freshness_seconds=FRESHNESS)
        assert assess_sufficiency(packet).sufficient
        assert set(packet.requested_timeframes) == set(FRAME_INTERVALS)
        assert {s.provider_id for s in packet.sources} == {'synthetic-fixture'}
        assert packet.evidence and all(c.status.value == 'closed' for frame in packet.timeframes for c in frame.candles)
        eligible = {c.candle_id for frame in packet.timeframes for c in frame.candles}
        assert all(set(e.candle_refs) <= eligible for e in packet.evidence)


@pytest.mark.parametrize('case,category', [('stale','stale_data'), ('forming','forming_or_future_candle'),
    ('gap','candle_gap'), ('policy','freshness'), ('cleanup','cleanup_unresolved')])
def test_gate_blocks_invalid_inputs_before_engine(tmp_path, monkeypatch, case, category):
    from app.data import ingestion, refresh
    with CandleStore(tmp_path/'gate.synthetic.sqlite3') as store:
        seed_candles(store, gap=case=='gap', forming=case=='forming')
        def forbidden(*args, **kwargs):
            pytest.fail('Invalid input reached deterministic engine')
        monkeypatch.setattr(ingestion, 'analyze_packet', forbidden)
        if case == 'cleanup':
            monkeypatch.setattr(refresh, '_unresolved', [(None,None)])
        with pytest.raises((ValueError,SiftingError), match=category):
            prepare_synthetic_evidence(store, now=NOW+timedelta(seconds=3601) if case=='stale' else NOW,
                freshness_seconds={} if case=='policy' else FRESHNESS)


def test_invalid_cursor_fails_latest_attempt_without_promoting_or_reusing_old_data(tmp_path):
    with CandleStore(tmp_path/'cursor.synthetic.sqlite3') as store:
        seed_candles(store)
        spec, page = fixture_page('1h',300)
        bad = page.model_dump(mode='json') | {'next_cursor':'invalid\ncursor'}
        with pytest.raises(SiftingError, match='invalid_cursor'):
            stage_synthetic_pages(store,spec,[bad],now=NOW)
        assert store.sifting_retrieval('1h')['status'] == 'failed'
        with pytest.raises(ValueError, match='complete_retrieval'):
            prepare_synthetic_evidence(store,now=NOW,freshness_seconds=FRESHNESS)


def test_mock_analyst_and_immutable_archive_are_linked_without_extra_timeframes(tmp_path, monkeypatch):
    import socket
    from app.analysis.offline import persist_synthetic_analysis
    from app.analysis.projection import project_analysis
    from app.ai import offline_mock
    calls = []
    completion = offline_mock.mock_completion
    def stub(prompt):
        calls.append(prompt)
        return completion(prompt)
    def forbidden(*args, **kwargs):
        pytest.fail('External network attempted')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket.socket,'connect_ex',forbidden)
    monkeypatch.setattr(offline_mock,'mock_completion',stub)
    with CandleStore(tmp_path/'mock-candles.synthetic.sqlite3') as store, SyntheticArchive(
            tmp_path/'mock-analysis.synthetic.sqlite3',create=True,busy_timeout_ms=25,required_timeframes=MVP_TIMEFRAMES) as archive:
        seed_candles(store)
        identity, run = persist_synthetic_analysis(store,archive,now=NOW+timedelta(seconds=1),freshness_seconds=FRESHNESS)
        assert len(calls) == 1
        assert run.status.value == 'complete'
        view = project_analysis(archive.connection,identity,limits=LIMITS,max_payload_bytes=8_000_000)
        assert view.analyst_outcome == 'complete'
        assert view.ai_report.provider_id == 'offline-mock'
        assert view.ai_report.report['analysis']['trade_stance'] == 'WAIT'
        assert view.timeframe_availability['4H'] == 'unsupported'
        assert {row[0] for row in archive.connection.execute('SELECT timeframe FROM retrievals')} == set(MVP_TIMEFRAMES)
        archive.verify_integrity()


import asyncio
import json
from app.api.offline import create_app, OfflineProjectionSource
from app.analysis.offline import persist_synthetic_analysis


def api_get(app, path):
    async def request():
        sent = []
        async def receive():
            return {'type':'http.request','body':b'','more_body':False}
        async def send(message):
            sent.append(message)
        await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET',
            'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'',
            'headers':[],'client':('127.0.0.1',1),'server':('127.0.0.1',8000)},receive,send)
        status = next(m['status'] for m in sent if m['type']=='http.response.start')
        body = b''.join(m.get('body',b'') for m in sent if m['type']=='http.response.body')
        return status,json.loads(body)
    return asyncio.run(request())


def seed_analysis(tmp_path):
    path = tmp_path/'api.synthetic.sqlite3'
    with CandleStore(tmp_path/'api-candles.synthetic.sqlite3') as store, SyntheticArchive(
            path,create=True,busy_timeout_ms=25,required_timeframes=MVP_TIMEFRAMES) as archive:
        seed_candles(store)
        identity, _ = persist_synthetic_analysis(store,archive,now=NOW+timedelta(seconds=1),freshness_seconds=FRESHNESS)
    return path,identity


def test_offline_api_reads_fresh_local_projection_and_never_writes_archive(tmp_path):
    path,identity = seed_analysis(tmp_path)
    before = path.read_bytes()
    app = create_app(path,clock=lambda:NOW+timedelta(seconds=2))
    status,market = api_get(app,'/api/v1/market-data/status')
    assert status == 200 and market['analysis_available']
    assert market['analysis_id'] == identity and market['freshness_status'] == 'fresh'
    status,view = api_get(app,'/api/v1/analysis/'+identity)
    assert status == 200 and view['freshness_status'] == 'fresh'
    assert view['valid_until'] == (NOW+timedelta(hours=1)).isoformat().replace('+00:00','Z')
    assert len(view['candles']) == 800
    assert view['ai_report']['provider_id'] == 'offline-mock'
    assert {c['timeframe'] for c in view['candles']} == {'1D','1H','15M'}
    assert all(c['opened_at'].endswith('Z') for c in view['candles'])
    assert api_get(app,'/api/v1/analysis/missing')[0] == 404
    assert path.read_bytes() == before


@pytest.mark.parametrize('case', ['stale','cleanup','corrupt','missing_file','wrong_schema'])
def test_api_fails_closed_and_status_does_not_create_storage(tmp_path,monkeypatch,case):
    from app.data import refresh
    path,identity = seed_analysis(tmp_path)
    now = NOW+timedelta(hours=2) if case=='stale' else NOW+timedelta(seconds=2)
    if case=='cleanup':
        monkeypatch.setattr(refresh,'_unresolved',[(None,None)])
    elif case=='corrupt':
        with sqlite3.connect(path) as connection:
            connection.execute('DROP TRIGGER analysis_outputs_no_update')
            connection.execute("UPDATE analysis_outputs SET digest=?",('0'*64,))
    elif case=='missing_file':
        path = tmp_path/'absent.synthetic.sqlite3'
    elif case=='wrong_schema':
        path = tmp_path/'v1.synthetic.sqlite3'
        with CandleStore(path): pass
    app = create_app(path,clock=lambda:now)
    status,market = api_get(app,'/api/v1/market-data/status')
    assert status == 200 and not market['analysis_available']
    assert market['analysis_id'] is None and market['freshness_status'] == 'unavailable'
    status,body = api_get(app,'/api/v1/analysis/'+identity)
    assert status == (503 if case=='cleanup' else 409)
    assert 'candles' not in body and 'ai_report' not in body
    if case=='missing_file': assert not path.exists()


def test_offline_factory_and_unconfigured_status_are_dormant(tmp_path,monkeypatch):
    import socket
    import subprocess
    def forbidden(*args,**kwargs):
        pytest.fail('Dormant startup touched storage, process or provider')
    monkeypatch.delenv('XAU_OFFLINE_ARCHIVE',raising=False)
    monkeypatch.setattr(sqlite3,'connect',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    app = create_app()
    assert api_get(app,'/health')[0] == 200
    assert not api_get(app,'/api/v1/market-data/status')[1]['analysis_available']
    assert api_get(app,'/api/v1/analysis/missing')[0] == 503
    configured = create_app(tmp_path/'absent.synthetic.sqlite3')
    assert api_get(configured,'/health')[0] == 200


@pytest.mark.parametrize('case', ['stale','forming','gap','invalid_cursor','cleanup'])
def test_end_to_end_invalid_input_never_reaches_mock_archive_or_projection(tmp_path,monkeypatch,case):
    from app.ai import offline_mock
    from app.data import refresh
    path = tmp_path/'rejected.synthetic.sqlite3'
    def forbidden(*args,**kwargs):
        pytest.fail('Rejected input reached mock Analyst')
    monkeypatch.setattr(offline_mock,'mock_completion',forbidden)
    with CandleStore(tmp_path/'rejected-candles.synthetic.sqlite3') as store, SyntheticArchive(
            path,create=True,busy_timeout_ms=25,required_timeframes=MVP_TIMEFRAMES) as archive:
        seed_candles(store,gap=case=='gap',forming=case=='forming')
        if case=='invalid_cursor':
            spec,page = fixture_page('1h',300)
            with pytest.raises(SiftingError,match='invalid_cursor'):
                stage_synthetic_pages(store,spec,[page.model_dump(mode='json')|{'next_cursor':'bad\ncursor'}],now=NOW)
        if case=='cleanup': monkeypatch.setattr(refresh,'_unresolved',[(None,None)])
        with pytest.raises((ValueError,SiftingError)):
            persist_synthetic_analysis(store,archive,now=NOW+timedelta(hours=2) if case=='stale' else NOW+timedelta(seconds=1),freshness_seconds=FRESHNESS)
        for table in ('analysis_outputs','ai_requests','ai_responses','ai_reports'):
            assert archive.connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
    app = create_app(path,clock=lambda:NOW+timedelta(seconds=2))
    assert not api_get(app,'/api/v1/market-data/status')[1]['analysis_available']
    assert api_get(app,'/api/v1/analysis/rejected')[0] == (503 if case=='cleanup' else 404)


def test_real_offline_factory_startup_is_loopback_and_does_not_create_database(tmp_path):
    import os
    import socket
    import subprocess
    import sys
    import time
    from urllib.request import urlopen
    from urllib.error import URLError
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port = probe.getsockname()[1]
    env = {k:v for k,v in os.environ.items() if not k.startswith('XAUUSD_') and k!='SIFTING_API_KEY'}
    env['XAU_OFFLINE_ARCHIVE'] = str(tmp_path/'never-created.synthetic.sqlite3')
    process = subprocess.Popen([sys.executable,'-m','uvicorn','app.api.offline:create_app','--factory',
        '--host','127.0.0.1','--port',str(port),'--log-level','error'],env=env)
    try:
        deadline = time.monotonic()+15
        while True:
            assert process.poll() is None
            try:
                with urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as response:
                    assert json.load(response)['status']=='ok'
                break
            except URLError:
                if time.monotonic()>=deadline: pytest.fail('Offline factory failed startup')
                time.sleep(.05)
        with urlopen(f'http://127.0.0.1:{port}/api/v1/market-data/status',timeout=2) as response:
            assert not json.load(response)['analysis_available']
        assert not (tmp_path/'never-created.synthetic.sqlite3').exists()
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)



def test_evidence_gate_uses_one_snapshot_during_concurrent_latest_attempt(tmp_path,monkeypatch):
    from app.analysis import offline
    path = tmp_path/'snapshot-candles.synthetic.sqlite3'
    with CandleStore(path) as store:
        store.connection.execute('PRAGMA journal_mode=WAL')
        seed_candles(store)
        original = offline.build_evidence
        def concurrent_write_then_build(*args,**kwargs):
            with CandleStore(path) as writer:
                writer.begin_sifting_retrieval('concurrent','1h',NOW-timedelta(hours=300),NOW-timedelta(hours=1),NOW)
                writer.finish_sifting_retrieval('concurrent','failed',NOW)
            return original(*args,**kwargs)
        monkeypatch.setattr(offline,'build_evidence',concurrent_write_then_build)
        packet = prepare_synthetic_evidence(store,now=NOW,freshness_seconds=FRESHNESS)
        assert assess_sufficiency(packet).sufficient
        assert not store.connection.in_transaction
        assert store.sifting_retrieval('1h')['status'] == 'failed'


def test_synthetic_and_provider_observations_cannot_mix(tmp_path):
    with CandleStore(tmp_path/'separated.synthetic.sqlite3') as store:
        seed_candles(store)
        spec,page = fixture_page('1h',300)
        with pytest.raises(ValueError,match='separate databases'):
            store.persist_sifting_page('1h',spec.start,spec.end,page)



def test_failed_cursor_after_archived_analysis_closes_current_api_availability(tmp_path):
    path,identity = seed_analysis(tmp_path)
    app = create_app(path,clock=lambda:NOW+timedelta(seconds=2))
    assert api_get(app,'/api/v1/market-data/status')[1]['analysis_available']
    with CandleStore(tmp_path/'api-candles.synthetic.sqlite3') as store:
        spec,page = fixture_page('1h',300)
        with pytest.raises(SiftingError,match='invalid_cursor'):
            stage_synthetic_pages(store,spec,[page.model_dump(mode='json')|{'next_cursor':'bad\ncursor'}],now=NOW)
    assert not api_get(app,'/api/v1/market-data/status')[1]['analysis_available']
    status,body = api_get(app,'/api/v1/analysis/'+identity)
    assert status == 409 and body['detail'] == 'current_retrieval_not_eligible'
