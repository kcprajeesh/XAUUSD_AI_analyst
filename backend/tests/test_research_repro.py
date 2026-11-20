"""Prospective framework tests: synthetic bytes only, never import a research runner."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.canonical import CanonicalError, Field, ObjectSchema
from app.research_repro import schema as s
from app.research_repro import store as w
from app.research_repro.verify import independent_bytes, independent_digest, verify_attempt


STAMP = '2026-01-01T00:00:00.000000Z'


@pytest.fixture
def setup(tmp_path):
    src, data, attempts = [tmp_path / p for p in ('source', 'data', 'attempts')]
    for folder in (src, data, attempts):
        folder.mkdir()
    (src / 'runner.py').write_bytes(b'# inert synthetic source\n')
    (src / 'strategy.md').write_bytes(b'Synthetic specification\n')
    (src / 'lock.txt').write_bytes(b'no dependencies\n')
    (data / 'h1.txt').write_bytes(b'synthetic non-market input\n')
    paths = ['strategy.md', 'runner.py', 'lock.txt']
    inv = w.source_inventory(src, paths, ['h1.txt'], 'snapshot-1')
    identity = w.file_identity(src / 'strategy.md', 'strategy.md')
    m = dict(
        schema_version='research.v1', experiment_id='synthetic', attempt_id='attempt-1',
        authorization=dict(reference='owner-1', operation='synthetic_receipt', scope=['synthetic_only']),
        strategy=dict(path='strategy.md', sha256=identity['sha256'], revision='synthetic'),
        configuration=dict(variants=['A', 'B', 'C'], values=[], decimals=[dict(name='threshold', value='-0.00')],
                           session_policy='IANA sessions', gap_policy='reject', ambiguity_policy='flag', cutoff_policy='closed'),
        datasets=[dict(w.file_identity(data / 'h1.txt', 'h1.txt'), role='synthetic_input', timeframe='H1',
                       provider='Alpari MT5 Demo', symbol='XAUUSD_i', classification='included')],
        source=dict(snapshot_id='snapshot-1', inventory_path='inventory.json',
                    inventory_sha256=s.digest(inv, s.INVENTORY), entry_point='runner.py'),
        git=dict(head_available=False, head='', no_usable_baseline=True,
                 tracked_modifications=[], untracked_files=paths),
        runtime=dict(implementation='CPython', version='synthetic', build='synthetic',
                     executable=dict(path='/synthetic/python', size=1, sha256='0'*64), os='synthetic',
                     architecture='synthetic', numeric='decimal', timezone_database='synthetic'),
        dependencies=dict(installed=[], lockfiles=[w.file_identity(src / 'lock.txt', 'lock.txt')], non_pip=[]),
        time_policy=dict(s.FIXED_TIME_POLICY, session_zones=['Europe/London', 'America/New_York']),
        window=dict(input_start=STAMP, warmup_end=STAMP, evaluation_start=STAMP,
                    cutoff='2026-02-01T00:00:00.000000Z', boundary_inclusion='[start,cutoff)',
                    candle_close_eligibility='close <= cutoff'),
        invocation=dict(interpreter='/synthetic/python', arguments=['runner.py'], working_directory='.',
                        environment=[dict(name='PYTHONHASHSEED', value='0')], inline_script_sha256=''),
        determinism=dict(randomness=False, ordering='path', decimals=[], decimal_precision=28, rounding='ROUND_HALF_EVEN', concurrency='1'),
        preflight=dict(procedure_version='synthetic.v1', required_checks=['inputs'], fail_conditions=['mismatch']),
        outputs=dict(paths=['outputs/receipt.json'], serializer='research.canonical.v1',
                     schema_version='research.receipt.v1', required_stages=['synthetic_stage']),
        inferential=False, cost_adjusted=False,
    )
    m = s.manifest(m)

    def auth(value):
        return dict(schema_version='research.v1', reference=value['authorization']['reference'], date=STAMP,
                    manifest_sha256=s.digest(value, s.MANIFEST), operation=value['authorization']['operation'],
                    variants=value['configuration']['variants'], dataset_hashes=[d['sha256'] for d in value['datasets']],
                    window=deepcopy(value['window']), restrictions=list(s.RESTRICTIONS))

    def allocate(value=None):
        value = m if value is None else value
        return w.allocate(attempts, value, auth(value), src, paths, ['h1.txt'], data)

    return dict(m=m, auth=auth, allocate=allocate, src=src, data=data, attempts=attempts, inv=inv, paths=paths)


def record(attempt, fixture, state, *, stages=None, diagnostics=None, outputs=None, deviations=None):
    return w.append(attempt, state, stages or [], diagnostics or [], outputs or [], deviations or [],
                    source_root=fixture['src'], dataset_root=fixture['data'],
                    preflight=[dict(name='inputs', succeeded=True)] if state == 'COMPLETED' else [])


def receipt(attempt):
    path = 'outputs/receipt.json'
    w.write_new(attempt / path, s.canonical(dict(schema_version='research.receipt.v1', result='synthetic'), s.OUTPUT))
    return w.file_identity(attempt / path, path)


def diagnostic(attempt):
    w.write_new(attempt / 'logs/failure.txt', b'synthetic diagnostic; no exit status inferred')
    return w.file_identity(attempt / 'logs/failure.txt', 'logs/failure.txt')


def test_vectors():
    schema = s.obj(z=s.TEXT, a=s.obj(n=s.INT, ordered=s.array(s.TEXT)), decimal=s.DECIMAL, time=s.TIME)
    value = dict(z='é/"\\\x00\n\x1f', a=dict(n=0, ordered=['b', 'a']), decimal='-0.000',
                 time='2026-01-01T03:00:00+03:00')
    expected = '{"a":{"n":0,"ordered":["b","a"]},"decimal":"0","time":"2026-01-01T00:00:00.000000Z","z":"é/\\"\\\\\\u0000\\u000a\\u001f"}'.encode()
    assert s.canonical(value, schema) == expected
    assert independent_bytes(value, schema) == expected
    assert s.digest(value, schema) == sha256(expected).hexdigest() == independent_digest(value, schema)
    assert s.canonical(dict(value, decimal='12.3400'), schema).find(b'"12.34"') > 0
    optional = ObjectSchema({'v': Field(s.TEXT, False, True)})
    assert s.canonical({}, optional) == b'{}'
    assert s.canonical({'v': None}, optional) == b'{"v":null}'
    assert s.digest({}, optional) != s.digest({'v': None}, optional)
    assert sha256(b'{}').hexdigest() == '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'


@pytest.mark.parametrize('value', ['e\u0301', '\ud800', 1.25, float('inf')])
def test_reject_python_values(value):
    with pytest.raises((ValueError, CanonicalError)):
        s.canonical({'v': value}, s.obj(v=s.TEXT))


@pytest.mark.parametrize('data', [b'{"v":1,"v":2}', b'{"v":1.0}', b'{"v":1e0}', b'{"v":NaN}',
                                       b'\xef\xbb\xbf{}', b'{"v":"\\udfff"}', b'\xff'])
def test_reject_json(data):
    with pytest.raises((ValueError, CanonicalError)):
        s.load(data)


@pytest.mark.parametrize('value', ['2026-01-01T00:00:00', '2026-01-01T00:00:00-00:00', 'invalid'])
def test_reject_timestamp(value):
    with pytest.raises(ValueError):
        s.canonical({'v': value}, s.obj(v=s.TIME))


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '00.1', '1e2', ''])
def test_reject_decimal(value):
    with pytest.raises(ValueError):
        s.canonical({'v': value}, s.obj(v=s.DECIMAL))


def test_inventory_order(setup):
    inv = deepcopy(setup['inv'])
    inv['entries'].reverse()
    assert s.canonical(inv, s.INVENTORY) == s.canonical(setup['inv'], s.INVENTORY)
    assert independent_bytes(inv, s.INVENTORY) == s.canonical(inv, s.INVENTORY)
    inv['entries'].append(inv['entries'][0])
    with pytest.raises(ValueError):
        s.canonical(inv, s.INVENTORY)


@pytest.mark.parametrize('field', ['manifest_sha256', 'operation', 'variants', 'dataset_hashes', 'window', 'restrictions', 'reference'])
def test_authorization_mismatch(setup, field):
    a = setup['auth'](setup['m'])
    if field in {'variants', 'dataset_hashes', 'restrictions'}:
        a[field] = []
    elif field == 'window':
        a[field]['cutoff'] = '2027-01-01T00:00:00Z'
    else:
        a[field] = 'wrong'
    with pytest.raises(ValueError):
        s.authorize(setup['m'], a)


@pytest.mark.parametrize('change', ['unknown', 'missing', 'float', 'nfc', 'conditional', 'timeframe', 'environment', 'window', 'head'])
def test_manifest_rejections(setup, change):
    m = deepcopy(setup['m'])
    if change == 'unknown': m['extra'] = 1
    if change == 'missing': del m['runtime']
    if change == 'float': m['configuration']['decimals'][0]['value'] = 1.0
    if change == 'nfc': m['strategy']['revision'] = 'e\u0301'
    if change == 'conditional': m['inferential'] = True
    if change == 'timeframe': m['datasets'][0]['timeframe'] = 'Daily'
    if change == 'environment': m['invocation']['environment'][0]['name'] = 'API_KEY'
    if change == 'window': m['window']['cutoff'] = STAMP
    if change == 'head': m['git']['head_available'] = True
    with pytest.raises(ValueError):
        s.manifest(m)


def test_valid_attempt_and_offline_cli(setup):
    attempt = setup['allocate']()
    assert verify_attempt(attempt)['state'] == 'NOT_STARTED'
    record(attempt, setup, 'RUNNING')
    out = receipt(attempt)
    record(attempt, setup, 'COMPLETED', stages=[dict(name='synthetic_stage', succeeded=True)], outputs=[out])
    assert verify_attempt(attempt)['state'] == 'COMPLETED'
    result = subprocess.run([sys.executable, '-m', 'app.research_repro.verify', str(attempt)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['manifest_sha256'] == s.digest(setup['m'], s.MANIFEST)
    with pytest.raises(FileExistsError):
        setup['allocate']()
    with pytest.raises(FileExistsError):
        w.write_new(attempt / 'manifest.json', b'overwrite')
    assert verify_attempt(attempt)['state'] == 'COMPLETED'


@pytest.mark.parametrize('kind', ['modified', 'missing', 'extra', 'symlink', 'dataset'])
def test_snapshot_tampering(setup, kind):
    attempt = setup['allocate']()
    target = attempt / 'snapshot/runner.py'
    if kind == 'modified': target.write_bytes(b'tamper')
    if kind == 'missing': target.unlink()
    if kind == 'extra': (attempt / 'snapshot/extra.py').write_bytes(b'extra')
    if kind == 'symlink':
        target.unlink()
        target.symlink_to(setup['src'] / 'runner.py')
    if kind == 'dataset': (attempt / 'datasets/h1.txt').write_bytes(b'tamper')
    with pytest.raises((ValueError, OSError)):
        verify_attempt(attempt)


@pytest.mark.parametrize('paths', [['../escape'], ['/absolute'], ['a/../b'], ['a//b'], ['a\\b'],
                                  ['runner.py', 'runner.py'], ['A', 'a'], ['a', 'a/b']])
def test_unsafe_source_paths(setup, paths):
    with pytest.raises(ValueError):
        w.source_inventory(setup['src'], paths, [], 's')


def test_source_symlink_escape(setup):
    (setup['src'] / 'escape.py').symlink_to(setup['data'] / 'h1.txt')
    with pytest.raises(ValueError):
        w.source_inventory(setup['src'], ['escape.py'], [], 's')


@pytest.mark.parametrize('kind', ['sequence', 'previous', 'corrupt', 'manifest', 'authorization', 'pending'])
def test_record_tampering(setup, kind):
    attempt = setup['allocate']()
    record(attempt, setup, 'RUNNING')
    path = attempt / 'records/00000001.json'
    r = s.load(path.read_bytes())
    if kind == 'sequence':
        r['sequence'] = 4
        path.write_bytes(s.canonical(r, s.RECORD))
    if kind == 'previous':
        r['previous_sha256'] = 'f'*64
        path.write_bytes(s.canonical(r, s.RECORD))
    if kind == 'corrupt': path.write_bytes(b'{')
    if kind == 'manifest': (attempt / 'manifest.json').write_bytes(b'{}')
    if kind == 'authorization': (attempt / 'authorization.json').unlink()
    if kind == 'pending': (attempt / 'records/.pending-test').write_bytes(b'{')
    with pytest.raises((ValueError, OSError)):
        verify_attempt(attempt)


@pytest.mark.parametrize('kind', ['source', 'dataset', 'missing_output', 'invalid_output', 'stage', 'deviation'])
def test_completion_requires_evidence(setup, kind):
    attempt = setup['allocate']()
    record(attempt, setup, 'RUNNING')
    out = receipt(attempt)
    stages = [dict(name='synthetic_stage', succeeded=True)]
    deviations = []
    if kind == 'source': (setup['src'] / 'runner.py').write_bytes(b'changed')
    if kind == 'dataset': (setup['data'] / 'h1.txt').write_bytes(b'changed')
    if kind == 'missing_output': (attempt / out['path']).unlink()
    if kind == 'invalid_output':
        (attempt / out['path']).write_bytes(b'{}')
        out = w.file_identity(attempt / out['path'], out['path'])
    if kind == 'stage': stages = []
    if kind == 'deviation': deviations = ['disqualifying']
    with pytest.raises((ValueError, OSError)):
        record(attempt, setup, 'COMPLETED', stages=stages, outputs=[out], deviations=deviations)
    assert len(w.read_records(attempt)) == 2


@pytest.mark.parametrize('kind', ['tamper', 'missing'])
def test_completed_output_tampering(setup, kind):
    attempt = setup['allocate']()
    record(attempt, setup, 'RUNNING')
    out = receipt(attempt)
    record(attempt, setup, 'COMPLETED', stages=[dict(name='synthetic_stage', succeeded=True)], outputs=[out])
    path = attempt / out['path']
    if kind == 'tamper': path.write_bytes(b'changed')
    else: path.unlink()
    with pytest.raises(ValueError):
        verify_attempt(attempt)


@pytest.mark.parametrize('state', ['FAILED', 'INTERRUPTED'])
def test_terminal_and_retry(setup, state):
    attempt = setup['allocate']()
    record(attempt, setup, 'RUNNING')
    partial = receipt(attempt)
    diag = diagnostic(attempt)
    record(attempt, setup, state, diagnostics=[diag], outputs=[partial])
    assert verify_attempt(attempt)['state'] == state
    with pytest.raises(ValueError):
        record(attempt, setup, 'RUNNING')
    m = deepcopy(setup['m'])
    m.update(attempt_id='attempt-2', retry_parent='attempt-1')
    m['authorization']['reference'] = 'owner-2'
    retry = setup['allocate'](m)
    assert verify_attempt(retry)['state'] == 'NOT_STARTED'
    assert s.digest(m, s.MANIFEST) != s.digest(setup['m'], s.MANIFEST)
    assert (attempt / partial['path']).exists()


def test_no_completion_from_not_started(setup):
    attempt = setup['allocate']()
    with pytest.raises(ValueError):
        record(attempt, setup, 'COMPLETED')
    with pytest.raises(ValueError):
        record(attempt, setup, 'FAILED')


def test_writer_encoder_not_used_to_reconstruct_bytes(setup, monkeypatch):
    attempt = setup['allocate']()
    import app.research_repro.verify as verifier
    seen = []
    original = verifier.independent_bytes
    def independent(value, schema):
        seen.append(schema)
        return original(value, schema)
    monkeypatch.setattr(verifier, 'independent_bytes', independent)
    assert verifier.verify_attempt(attempt)['state'] == 'NOT_STARTED'
    assert s.MANIFEST in seen and s.INVENTORY in seen and s.RECORD in seen
    # Exact vectors separately establish equivalence; schema semantics remain shared by design.


def test_interrupted_atomic_publication_is_not_evidence(setup, monkeypatch):
    attempt = setup['allocate']()
    def interrupted(*args):
        raise OSError('synthetic interruption before replace')
    monkeypatch.setattr(w.os, 'replace', interrupted)
    with pytest.raises(OSError):
        record(attempt, setup, 'RUNNING')
    assert (attempt / 'records/00000001.json').read_bytes() == b''
    with pytest.raises(ValueError):
        verify_attempt(attempt)
    # Reservation is never silently replaced on retry.
    with pytest.raises(FileExistsError):
        w.write_new(attempt / 'records/00000001.json', b'replacement')


def test_concurrent_publication_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    target = tmp_path / 'record.json'
    def publish(payload):
        try:
            w.write_new(target, payload)
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [b'first', b'second']))
    assert sum(results) == 1
    assert target.read_bytes() in {b'first', b'second'}


def test_independent_encoder_ignores_writer_functions(monkeypatch):
    def broken(*args):
        raise AssertionError('writer must not encode independent bytes')
    monkeypatch.setattr(s, 'canonical_json', broken)
    value = dict(d='10.000', t='2026-01-01T03:00:00+03:00')
    assert independent_bytes(value, s.obj(d=s.DECIMAL, t=s.TIME)) == (
        b'{"d":"10","t":"2026-01-01T00:00:00.000000Z"}')


def test_missing_parent_and_running_parent_reject_retry(setup):
    m = deepcopy(setup['m'])
    m.update(attempt_id='attempt-2', retry_parent='absent')
    m['authorization']['reference'] = 'owner-2'
    with pytest.raises(ValueError):
        setup['allocate'](m)
    setup['allocate']()
    m['retry_parent'] = 'attempt-1'
    with pytest.raises(ValueError):
        setup['allocate'](m)


def test_inventory_changed_before_allocation(setup):
    (setup['src'] / 'runner.py').write_bytes(b'changed after manifest')
    with pytest.raises(ValueError):
        setup['allocate']()
    assert not list(setup['attempts'].iterdir())


def test_independent_verifier_rejects_noncanonical_manifest(setup):
    attempt = setup['allocate']()
    path = attempt / 'manifest.json'
    path.write_bytes(json.dumps(setup['m'], ensure_ascii=False, indent=2).encode())
    with pytest.raises(ValueError, match='noncanonical_document'):
        verify_attempt(attempt)


def test_conditional_plans(setup):
    m = deepcopy(setup['m'])
    m['inferential'] = m['cost_adjusted'] = m['determinism']['randomness'] = True
    m['random_generators'] = [dict(generator='synthetic', seed=1)]
    m['statistical_plan'] = {key: 'synthetic evidence plan' for key in s.STATISTICS.fields}
    m['cost_model'] = {key: 'synthetic evidence plan' for key in s.COSTS.fields}
    m['cost_model']['missing_cost_policy'] = 'reject_net_claim'
    assert s.manifest(m)['inferential']
    m['cost_model']['missing_cost_policy'] = 'assume_zero'
    with pytest.raises(ValueError):
        s.manifest(m)


def test_no_real_runner_imports():
    import ast
    package = Path(__file__).parents[1] / 'app/research_repro'
    forbidden = ('historical_mt5', 'subprocess', 'socket', 'requests', 'urllib', 'sqlite')
    for source in package.glob('*.py'):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                assert not any(any(part in alias.name for part in forbidden) for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not any(part in (node.module or '') for part in forbidden)


def test_completion_requires_preflight(setup):
    attempt = setup['allocate']()
    record(attempt, setup, 'RUNNING')
    out = receipt(attempt)
    with pytest.raises(ValueError, match='incomplete_preflight'):
        w.append(attempt, 'COMPLETED', [dict(name='synthetic_stage', succeeded=True)], [], [out], [],
                 source_root=setup['src'], dataset_root=setup['data'], preflight=[])

# Phase 5.9E corrective regressions; all artifacts are inert synthetic bytes.
@pytest.mark.parametrize('deviations', [['disqualifying'], ['first', 'second'], ['informational: still untyped']])
def test_historical_deviations_writer_and_forged_verifier(setup, deviations, monkeypatch):
    attempt = setup['allocate']()
    record(attempt, setup, 'RUNNING', deviations=deviations)
    out = receipt(attempt)
    before = [p.read_bytes() for p in sorted((attempt / 'records').iterdir())]
    with pytest.raises(ValueError, match='completion_evidence'):
        record(attempt, setup, 'COMPLETED', stages=[dict(name='synthetic_stage', succeeded=True)], outputs=[out])
    assert before == [p.read_bytes() for p in sorted((attempt / 'records').iterdir())]
    # Construct an otherwise valid, canonical, digest-linked completion, bypassing the writer.
    r = deepcopy(w.read_records(attempt)[-1])
    r.update(sequence=2, previous_sha256=s.digest(r, s.RECORD), state='COMPLETED', deviations=[],
             stages=[dict(name='synthetic_stage', succeeded=True)], preflight=[dict(name='inputs', succeeded=True)],
             outputs=[out], output_validation=True, source_postcheck=True, dataset_postcheck=True)
    w.write_new(attempt / 'records/00000002.json', s.canonical(r, s.RECORD))
    import app.research_repro.verify as verifier
    monkeypatch.setattr(verifier, 'lifecycle', lambda *args: 'COMPLETED')
    with pytest.raises(ValueError, match='independent_historical_deviations'):
        verifier.verify_attempt(attempt)


def test_missing_deviation_metadata(setup):
    attempt = setup['allocate']()
    r = w.read_records(attempt)[0]
    del r['deviations']
    with pytest.raises(ValueError):
        s.lifecycle(setup['m'], [r])
    # Raw JSON with a missing mandatory field must fail the full verifier too.
    (attempt / 'records/00000000.json').write_text(json.dumps(r))
    with pytest.raises(ValueError):
        verify_attempt(attempt)


@pytest.mark.parametrize('state', ['RUNNING', 'FAILED', 'INTERRUPTED', 'COMPLETED'])
@pytest.mark.parametrize('bad', ['missing', 'hash', 'size', 'directory', 'traversal', 'symlink'])
def test_invalid_output_never_published(setup, state, bad):
    attempt = setup['allocate']()
    if state == 'COMPLETED':
        record(attempt, setup, 'RUNNING')
    out = receipt(attempt)
    diag = diagnostic(attempt)
    invalid = dict(out)
    if bad == 'missing': invalid['path'] = 'outputs/absent'
    if bad == 'hash': invalid['sha256'] = 'f' * 64
    if bad == 'size': invalid['size'] += 1
    if bad == 'directory': invalid['path'] = 'outputs'
    if bad == 'traversal': invalid['path'] = '../outside'
    if bad == 'symlink':
        (attempt / 'outputs/link').symlink_to(setup['data'] / 'h1.txt')
        invalid['path'] = 'outputs/link'
    before = {p.name: p.read_bytes() for p in (attempt / 'records').iterdir()}
    with pytest.raises((ValueError, OSError)):
        record(attempt, setup, state, outputs=[invalid], diagnostics=[diag],
               stages=[dict(name='synthetic_stage', succeeded=True)] if state == 'COMPLETED' else [])
    assert before == {p.name: p.read_bytes() for p in (attempt / 'records').iterdir()}
    if bad == 'symlink':
        (attempt / 'outputs/link').unlink()
    record(attempt, setup, state, outputs=[out], diagnostics=[diag],
           stages=[dict(name='synthetic_stage', succeeded=True)] if state == 'COMPLETED' else [])
    assert verify_attempt(attempt)['state'] == state
    (attempt / out['path']).write_bytes(b'changed after publication')
    with pytest.raises(ValueError):
        verify_attempt(attempt)


@pytest.mark.parametrize('state', ['FAILED', 'INTERRUPTED'])
def test_invalid_diagnostic_never_published(setup, state):
    attempt = setup['allocate']()
    invalid = dict(path='logs/missing', size=1, sha256='0' * 64)
    with pytest.raises((ValueError, OSError)):
        record(attempt, setup, state, diagnostics=[invalid])
    assert len(w.read_records(attempt)) == 1
    record(attempt, setup, state, diagnostics=[diagnostic(attempt)])
    assert verify_attempt(attempt)['state'] == state


@pytest.mark.parametrize('kind', ['supported', 'unsupported', 'variant', 'dataset', 'window', 'operation', 'advisory'])
def test_restriction_semantics(setup, kind):
    m = setup['m']
    a = setup['auth'](m)
    a['restrictions'] += ['synthetic_receipt_only', 'exact_scope']
    a['restriction_scope'] = {k: deepcopy(a[k]) for k in ('operation', 'variants', 'dataset_hashes', 'window')}
    if kind == 'unsupported': a['restrictions'].append('please enforce arbitrary prose')
    if kind == 'variant': a['restrictions'].append('variant_a_only')
    if kind == 'dataset': a['restriction_scope']['dataset_hashes'] = ['f' * 64]
    if kind == 'window': a['restriction_scope']['window']['cutoff'] = '2027-01-01T00:00:00.000000Z'
    if kind == 'operation': a['restriction_scope']['operation'] = 'other'
    if kind == 'advisory': a['advisory_notes'] = ['Only variant A please (advisory, not enforcement)']
    if kind in {'supported', 'advisory'}:
        validated = s.authorize(m, a)
        if kind == 'advisory': assert validated['advisory_notes'] == a['advisory_notes']
        attempt = w.allocate(setup['attempts'], m, a, setup['src'], setup['paths'], ['h1.txt'], setup['data'])
        assert verify_attempt(attempt)['state'] == 'NOT_STARTED'
        changed = deepcopy(m)
        changed['strategy']['revision'] = 'changed'
        with pytest.raises(ValueError, match='authorization_mismatch:manifest_sha256'):
            s.authorize(changed, a)
    else:
        with pytest.raises(ValueError):
            s.authorize(m, a)


@pytest.mark.parametrize('namespace', ['values', 'decimals', 'cross_settings', 'determinism', 'installed', 'non_pip', 'cross_dependencies', 'lockfiles'])
@pytest.mark.parametrize('conflict', [False, True])
def test_named_collection_duplicates(setup, namespace, conflict):
    m = deepcopy(setup['m'])
    entry = dict(name='duplicate', value='1')
    other = dict(entry, value='2' if conflict else '1')
    if namespace in {'values', 'decimals'}: m['configuration'][namespace] = [entry, other]
    if namespace == 'cross_settings':
        m['configuration'].update(values=[entry], decimals=[other])
    if namespace == 'determinism': m['determinism']['decimals'] = [entry, other]
    if namespace in {'installed', 'non_pip'}: m['dependencies'][namespace] = [entry, other]
    if namespace == 'cross_dependencies': m['dependencies'].update(installed=[entry], non_pip=[other])
    if namespace == 'lockfiles':
        entry = m['dependencies']['lockfiles'][0]
        m['dependencies']['lockfiles'].append(dict(entry, sha256='f'*64 if conflict else entry['sha256']))
    with pytest.raises(ValueError):
        s.manifest(m)


@pytest.mark.parametrize('field', ['serializer', 'schema_version'])
def test_unsupported_contract_rejected_before_allocation(setup, field):
    m = deepcopy(setup['m'])
    m['outputs'][field] = 'unsupported.future.v99'
    with pytest.raises(ValueError, match='unsupported_output_contract'):
        setup['allocate'](m)
    assert not list(setup['attempts'].iterdir())


def test_unreferenced_inventory_and_classification(setup):
    attempt = setup['allocate']()
    out = receipt(attempt)
    diag = diagnostic(attempt)
    w.write_new(attempt / 'unexpected.tmp', b'not a research output')
    evidence = verify_attempt(attempt)
    assert evidence['unreferenced_artifacts'] == ['logs/failure.txt', 'outputs/receipt.json', 'unexpected.tmp']
    record(attempt, setup, 'FAILED', outputs=[out], diagnostics=[diag])
    evidence = verify_attempt(attempt)
    assert evidence['unreferenced_artifacts'] == ['unexpected.tmp']
    assert evidence['artifacts'] == dict(final_outputs=[], partial_outputs=[out['path']], diagnostics=[diag['path']])


def test_full_manifest_fixed_vector_and_verifier(setup):
    expected = b'{"attempt_id":"attempt-1","authorization":{"operation":"synthetic_receipt","reference":"owner-1","scope":["synthetic_only"]},"configuration":{"ambiguity_policy":"flag","cutoff_policy":"closed","decimals":[{"name":"threshold","value":"0"}],"gap_policy":"reject","session_policy":"IANA sessions","values":[],"variants":["A","B","C"]},"cost_adjusted":false,"datasets":[{"classification":"included","path":"h1.txt","provider":"Alpari MT5 Demo","role":"synthetic_input","sha256":"15b479071eb04d9dd380e801cc1e0c7449c2b16866195c0ba7da3534ef90b48f","size":27,"symbol":"XAUUSD_i","timeframe":"H1"}],"dependencies":{"installed":[],"lockfiles":[{"path":"lock.txt","sha256":"d77f09158c22a98cb680228ca7bd58f5aa2ea7bf011eaff59b6afbb6b17cb4d2","size":16}],"non_pip":[]},"determinism":{"concurrency":"1","decimal_precision":28,"decimals":[],"ordering":"path","randomness":false,"rounding":"ROUND_HALF_EVEN"},"experiment_id":"synthetic","git":{"head":"","head_available":false,"no_usable_baseline":true,"tracked_modifications":[],"untracked_files":["strategy.md","runner.py","lock.txt"]},"inferential":false,"invocation":{"arguments":["runner.py"],"environment":[{"name":"PYTHONHASHSEED","value":"0"}],"inline_script_sha256":"","interpreter":"/synthetic/python","working_directory":"."},"outputs":{"paths":["outputs/receipt.json"],"required_stages":["synthetic_stage"],"schema_version":"research.receipt.v1","serializer":"research.canonical.v1"},"preflight":{"fail_conditions":["mismatch"],"procedure_version":"synthetic.v1","required_checks":["inputs"]},"runtime":{"architecture":"synthetic","build":"synthetic","executable":{"path":"/synthetic/python","sha256":"0000000000000000000000000000000000000000000000000000000000000000","size":1},"implementation":"CPython","numeric":"decimal","os":"synthetic","timezone_database":"synthetic","version":"synthetic"},"schema_version":"research.v1","source":{"entry_point":"runner.py","inventory_path":"inventory.json","inventory_sha256":"593c839f9838e4dc358c430afc691e086f99d16f9c712b6c13e8ed44241b5af2","snapshot_id":"snapshot-1"},"strategy":{"path":"strategy.md","revision":"synthetic","sha256":"7a504fb6c5467eff6c5cade933fd81771384966271abb5b0302f1bf1f66fb775"},"time_policy":{"broker":"UTC+02:00_FIXED_NO_DST","broker_to_qatar":"add_one_hour","broker_to_utc":"subtract_two_hours","qatar":"Asia/Qatar","session_zones":["Europe/London","America/New_York"],"utc_to_qatar":"add_three_hours"},"window":{"boundary_inclusion":"[start,cutoff)","candle_close_eligibility":"close <= cutoff","cutoff":"2026-02-01T00:00:00.000000Z","evaluation_start":"2026-01-01T00:00:00.000000Z","input_start":"2026-01-01T00:00:00.000000Z","warmup_end":"2026-01-01T00:00:00.000000Z"}}'
    expected_digest = '59d7836e4b1b1af731d397be020481c2e6a38c5e606448d0af1bd988420c3b55'
    assert s.canonical(setup['m'], s.MANIFEST) == expected
    assert independent_bytes(setup['m'], s.MANIFEST) == expected
    assert sha256(expected).hexdigest() == expected_digest
    attempt = setup['allocate']()
    assert (attempt / 'manifest.json').read_bytes() == expected
    assert verify_attempt(attempt)['manifest_sha256'] == expected_digest


def test_concurrent_process_lifecycle_append(setup, tmp_path):
    attempt = setup['allocate']()
    # Synchronize after both processes validated the same chain, before exclusive publication.
    script = '''
import sys, time
from pathlib import Path
from app.research_repro import store as w
attempt, source, data, barrier, identity = map(Path, sys.argv[1:])
original = w.write_new
def synchronized(path, payload):
    (barrier / str(identity)).write_text('ready')
    deadline = time.monotonic() + 10
    while len(list(barrier.iterdir())) != 2:
        if time.monotonic() > deadline:
            raise RuntimeError('barrier timeout')
        time.sleep(0.01)
    original(path, payload)
w.write_new = synchronized
try:
    w.append(attempt, 'RUNNING', [], [], [], [], source_root=source, dataset_root=data)
except (ValueError, OSError):
    sys.exit(2)
'''
    barrier = tmp_path / 'barrier'
    barrier.mkdir()
    processes = [subprocess.Popen([sys.executable, '-c', script, str(attempt), str(setup['src']),
                                  str(setup['data']), str(barrier), str(i)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
    results = [p.communicate(timeout=20) for p in processes]
    assert all(p.returncode in {0, 2} for p in processes), results
    # A reader may fail closed while another writer still has a pending file.
    assert sum(p.returncode == 0 for p in processes) <= 1
    assert verify_attempt(attempt)['state'] == 'RUNNING'
    assert len(w.read_records(attempt)) == 2


@pytest.mark.parametrize('bad', ['hash', 'size', 'traversal', 'symlink'])
def test_interrupted_invalid_diagnostic_identity(setup, bad):
    attempt = setup['allocate']()
    diag = diagnostic(attempt)
    if bad == 'hash': diag['sha256'] = 'f'*64
    if bad == 'size': diag['size'] += 1
    if bad == 'traversal': diag['path'] = '../outside'
    if bad == 'symlink':
        (attempt / 'logs/link').symlink_to(setup['data'] / 'h1.txt')
        diag['path'] = 'logs/link'
    with pytest.raises((ValueError, OSError)):
        record(attempt, setup, 'INTERRUPTED', diagnostics=[diag])
    assert len(w.read_records(attempt)) == 1


def test_new_directory_hierarchy_is_synchronized(tmp_path, monkeypatch):
    calls = []
    original = w.sync_directory
    def observed(path):
        calls.append(Path(path))
        original(path)
    monkeypatch.setattr(w, 'sync_directory', observed)
    w.write_new(tmp_path / 'first/second/artifact', b'synthetic')
    assert tmp_path in calls
    assert tmp_path / 'first' in calls
    assert tmp_path / 'first/second' in calls
    assert (tmp_path / 'first/second/artifact').read_bytes() == b'synthetic'


def test_supported_variant_restriction_and_informational_date(setup):
    m = deepcopy(setup['m'])
    m['configuration']['variants'] = ['A']
    a = setup['auth'](m)
    a['restrictions'].append('variant_a_only')
    a['date'] = '2099-01-01T00:00:00.000000Z'
    assert s.authorize(m, a)['date'] == a['date']


def test_full_verifier_rejects_unsupported_enforceable_restriction(setup):
    attempt = setup['allocate']()
    a = setup['auth'](setup['m'])
    a['restrictions'].append('arbitrary prose')
    (attempt / 'authorization.json').write_bytes(s.canonical(a, s.AUTHORIZATION))
    with pytest.raises(ValueError, match='unsupported_restriction'):
        verify_attempt(attempt)
