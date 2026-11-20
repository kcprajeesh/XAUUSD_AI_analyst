"""Offline reader. Independent encoder and file hashing; shared declarative schema checks.

Usage: python -m app.research_repro.verify /path/to/attempt
"""
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

from app.canonical import ArraySchema, ObjectSchema, Scalar
from .schema import (AUTHORIZATION, INVENTORY, LIMITS, MANIFEST, OUTPUT, RECORD, authorize,
                     lifecycle, load, manifest, relative_path, require, unique_paths, validate)


def independent_bytes(value, schema):
    """Reconstruct bytes without canonical_json, canonical_decimal or canonical_timestamp."""
    def quote(text):
        parts = ['"']
        for c in text:
            n = ord(c)
            parts.append('\\' + c if c in {'"', '\\'} else f'\\u{n:04x}' if n < 32 else c)
        return ''.join(parts) + '"'

    def encode(v, s):
        if v is None:
            return 'null'
        if isinstance(s, ObjectSchema):
            return '{' + ','.join(quote(k) + ':' + encode(v[k], s.fields[k].schema) for k in sorted(v)) + '}'
        if isinstance(s, ArraySchema):
            return '[' + ','.join(encode(item, s.element) for item in v) + ']'
        require(isinstance(s, Scalar), "verifier_schema")
        if s.kind == 'integer':
            return str(v)
        if s.kind == 'boolean':
            return 'true' if v else 'false'
        if s.kind == 'decimal':
            d = Decimal(v)
            text = format(d, 'f')
            if '.' in text:
                text = text.rstrip('0').rstrip('.')
            return quote('0' if d == 0 else text)
        if s.kind == 'timestamp':
            stamp = datetime.fromisoformat(v.replace('Z', '+00:00')).astimezone(UTC)
            return quote(stamp.isoformat(timespec='microseconds').replace('+00:00', 'Z'))
        return quote(v)

    # Input validity is checked by the closed schema separately, before this encoder.
    if schema == INVENTORY:
        value = dict(value, entries=sorted(value['entries'], key=lambda e: e['path']))
    result = encode(value, schema).encode('utf-8')
    require(len(result) <= LIMITS.max_canonical_output_bytes, "verifier_size")
    return result


def independent_digest(value, schema):
    return hashlib.sha256(independent_bytes(value, schema)).hexdigest()


def retained(root, name):
    relative_path(name)
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "verifier_root")
    path = root
    for component in name.split('/'):
        path = path / component
        require(not path.is_symlink(), "verifier_symlink")
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()), "missing_file")
    return path.read_bytes()


def document(root, name, schema):
    data = retained(root, name)
    value = load(data)
    manifest(value) if schema == MANIFEST else validate(value, schema)
    # Reconstruct from the original parsed values, never writer-normalized output.
    require(independent_bytes(value, schema) == data, "noncanonical_document")
    return value


def identities(root, entries, *, exact=False):
    names = [e['path'] for e in entries]
    unique_paths(names)
    for entry in entries:
        payload = retained(root, entry['path'])
        require(len(payload) == entry['size'] and hashlib.sha256(payload).hexdigest() == entry['sha256'],
                "retained_hash_mismatch")
    if exact:
        files = []
        for p in Path(root).rglob('*'):
            require(not p.is_symlink(), "verifier_symlink")
            if p.is_file():
                files.append(p.relative_to(root).as_posix())
        require(set(files) == set(names), "unexpected_snapshot_file")


def verify_attempt(attempt, _seen=None):
    root = Path(attempt)
    seen = set() if _seen is None else _seen
    require(root.resolve() not in seen, "retry_cycle")
    seen.add(root.resolve())
    require(root.is_dir() and not root.is_symlink(), "verifier_root")
    for p in root.rglob('*'):
        require(not p.is_symlink() and not p.name.startswith('.pending-'), "symlink_or_pending_write")
    m = document(root, 'manifest.json', MANIFEST)
    require(root.name == m['attempt_id'], "attempt_directory_identity")
    md = independent_digest(m, MANIFEST)
    a = document(root, 'authorization.json', AUTHORIZATION)
    authorize(m, a)  # Binding semantics are shared; digest is independently checked below.
    require(a['manifest_sha256'] == md, "independent_manifest_digest")
    inv = document(root, 'inventory.json', INVENTORY)
    require(inv['snapshot_id'] == m['source']['snapshot_id']
            and independent_digest(inv, INVENTORY) == m['source']['inventory_sha256'], "inventory_identity")
    unique_paths(inv['exclusions'])
    entries = {e['path']: e for e in inv['entries']}
    require(not set(entries) & set(inv['exclusions']), "inventory_exclusion")
    required = [m['strategy']['path'], m['source']['entry_point'],
                *[e['path'] for e in m['dependencies']['lockfiles']]]
    require(set(required) <= entries.keys(), "missing_material_source")
    require(entries[m['strategy']['path']]['sha256'] == m['strategy']['sha256'], "strategy_identity")
    for lock in m['dependencies']['lockfiles']:
        require(entries[lock['path']] == lock, "lockfile_identity")
    dataset_names = {d['path'] for d in m['datasets']}
    require(not dataset_names & entries.keys() and dataset_names <= set(inv['exclusions']), "dataset_exclusion")
    identities(root / 'snapshot', inv['entries'], exact=True)
    identities(root / 'datasets', m['datasets'], exact=True)
    folder = root / 'records'
    require(folder.is_dir(), "missing_records")
    names = sorted(p.name for p in folder.iterdir())
    require(names and names == [f'{i:08d}.json' for i in range(len(names))], "record_sequence")
    records = [document(folder, name, RECORD) for name in names]
    previous = ''
    historical_deviations = []
    for record in records:
        require(record['manifest_sha256'] == md and record['previous_sha256'] == previous,
                "independent_chain")
        previous = independent_digest(record, RECORD)
        identities(root, record['diagnostics'])
        identities(root, record['outputs'])
        historical_deviations.extend(record['deviations'])
        if record['state'] == 'COMPLETED':
            require(not historical_deviations, 'independent_historical_deviations')
            require(m['outputs']['serializer'] == 'research.canonical.v1'
                    and m['outputs']['schema_version'] == 'research.receipt.v1', "unsupported_output_contract")
            for entry in record['outputs']:
                payload = retained(root, entry['path'])
                value = load(payload)
                # Shared schema validates shape; independent encoding validates bytes.
                from app.canonical import canonical_json
                canonical_json(value, OUTPUT, LIMITS)
                require(value['schema_version'] == 'research.receipt.v1'
                        and independent_bytes(value, OUTPUT) == payload, "output_validation")
    state = lifecycle(m, records)
    if 'retry_parent' in m:
        parent = root.parent / m['retry_parent']
        evidence = verify_attempt(parent, seen)
        pm = document(parent, 'manifest.json', MANIFEST)
        require(evidence['state'] in {'FAILED', 'INTERRUPTED'}
                and pm['experiment_id'] == m['experiment_id']
                and pm['authorization']['reference'] != m['authorization']['reference'], "retry_linkage")
    expected = {'manifest.json', 'authorization.json', 'inventory.json'}
    expected.update('snapshot/' + e['path'] for e in inv['entries'])
    expected.update('datasets/' + d['path'] for d in m['datasets'])
    expected.update('records/' + name for name in names)
    classified = dict(final_outputs=[], partial_outputs=[], diagnostics=[])
    for record in records:
        classified['final_outputs' if record['state'] == 'COMPLETED' else 'partial_outputs'].extend(
            e['path'] for e in record['outputs'])
        classified['diagnostics'].extend(e['path'] for e in record['diagnostics'])
        expected.update(e['path'] for e in record['outputs'] + record['diagnostics'])
    actual = set()
    for path in root.rglob('*'):
        require(path.is_dir() or path.is_file(), 'unsupported_artifact_type')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    return dict(manifest_sha256=md, state=state, records=len(records),
                artifacts=classified, unreferenced_artifacts=sorted(actual - expected),
                limitations=['Local permission record; not proof of authorship.',
                             'Stage results are supplied evidence, not proof of strategy correctness.',
                             'Postchecks compare bytes at observation time; no continuous monitoring.'])


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2, "usage: python -m app.research_repro.verify ATTEMPT")
        print(json.dumps(verify_attempt(sys.argv[1]), sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('NOT VERIFIED: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
