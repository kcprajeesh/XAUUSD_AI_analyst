"""Exclusive local allocation and records; never invokes an experiment."""
from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path
import tempfile

from .schema import (AUTHORIZATION, INVENTORY, MANIFEST, RECORD, authorize, canonical,
                     digest, lifecycle, load, manifest, output_valid, relative_path, require,
                     unique_paths, validate)


def file_identity(path, relative):
    data = Path(path).read_bytes()
    return dict(path=relative, size=len(data), sha256=sha256(data).hexdigest())


def safe_file(root, relative):
    relative_path(relative)
    root = Path(root).resolve(strict=True)
    path = root / relative
    # Conservative policy: reject every symlink, including internal links.
    current = root
    for component in relative.split("/"):
        current = current / component
        require(not current.is_symlink(), "symlink")
    require(path.resolve(strict=True).is_relative_to(root) and path.is_file(), "not_regular_file")
    return path


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, data):
    """Reserve with O_EXCL, then atomically replace only our empty reservation."""
    path = Path(path)
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for folder in reversed(missing):
        sync_directory(folder.parent)
        sync_directory(folder)
    require(not any(p.is_symlink() for p in (path.parent, *path.absolute().parents)), "symlink")
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Android's Python omits os.link. The exclusive empty reservation is
        # deliberately invalid evidence if interrupted before atomic publication.
        reservation = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(reservation)
        sync_directory(path.parent)
        os.replace(temp, path)
        sync_directory(path.parent)
        require(path.read_bytes() == data, "postwrite_mismatch")
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
        sync_directory(path.parent)


def source_inventory(root, paths, exclusions, snapshot_id):
    unique_paths(paths)
    unique_paths(exclusions)
    require(paths and snapshot_id and not (set(paths) & set(exclusions)), "snapshot_selection")
    # Explicit bounded allowlist; datasets must be separately excluded by allocation.
    for p in paths:
        require(not any(c.startswith('.') or c in {"__pycache__", "node_modules", "graphify-out"}
                        or c.endswith((".pem", ".key", ".pyc"))
                        or c.lower() in {"secrets", "credentials", "cache"} for c in p.split('/')),
                "excluded_source_class")
    entries = [file_identity(safe_file(root, p), p) for p in sorted(paths)]
    return validate(dict(schema_version="research.v1", snapshot_id=snapshot_id,
                         entries=entries, exclusions=sorted(exclusions)), INVENTORY)


def check_files(root, identities):
    for expected in identities:
        require(file_identity(safe_file(root, expected["path"]), expected["path"]) == expected,
                "file_identity_mismatch")


def read_records(attempt):
    folder = Path(attempt) / "records"
    names = sorted(p.name for p in folder.iterdir())
    require(names == [f"{i:08d}.json" for i in range(len(names))], "record_filenames_or_pending_write")
    records = []
    for name in names:
        data = safe_file(folder, name).read_bytes()
        value = load(data)
        require(canonical(value, RECORD) == data, "noncanonical_record")
        records.append(value)
    return records


def allocate(base, m, authorization, source_root, source_paths, exclusions, dataset_root):
    m = manifest(m)
    a = authorize(m, authorization)
    base = Path(base)
    require(base.is_dir() and not base.is_symlink(), "attempt_base")
    if "retry_parent" in m:
        from .verify import verify_attempt
        parent = base / m["retry_parent"]
        evidence = verify_attempt(parent)
        require(evidence["state"] in {"FAILED", "INTERRUPTED"}, "retry_parent_not_terminal")
        pm = manifest(load(safe_file(parent, "manifest.json").read_bytes()))
        require(pm["experiment_id"] == m["experiment_id"]
                and pm["authorization"]["reference"] != m["authorization"]["reference"], "retry_linkage")
    inventory = source_inventory(source_root, source_paths, exclusions, m["source"]["snapshot_id"])
    require(digest(inventory, INVENTORY) == m["source"]["inventory_sha256"], "inventory_digest")
    entries = {e["path"]: e for e in inventory["entries"]}
    required = [m["strategy"]["path"], m["source"]["entry_point"],
                *[e["path"] for e in m["dependencies"]["lockfiles"]]]
    require(set(required) <= entries.keys(), "missing_material_source")
    require(entries[m["strategy"]["path"]]["sha256"] == m["strategy"]["sha256"], "strategy_identity")
    for lock in m["dependencies"]["lockfiles"]:
        require(entries[lock["path"]] == lock, "lockfile_identity")
    dataset_paths = {d["path"] for d in m["datasets"]}
    require(not dataset_paths & entries.keys() and dataset_paths <= set(exclusions), "dataset_exclusion")
    datasets = [{k: d[k] for k in ("path", "size", "sha256")} for d in m["datasets"]]
    check_files(dataset_root, datasets)
    attempt = base / m["attempt_id"]
    attempt.mkdir(mode=0o700)  # Exclusive: incomplete allocations are retained, never recycled.
    sync_directory(base)
    for folder in ("snapshot", "datasets", "records"):
        (attempt / folder).mkdir()
    sync_directory(attempt)
    write_new(attempt / "manifest.json", canonical(m, MANIFEST))
    write_new(attempt / "authorization.json", canonical(a, AUTHORIZATION))
    write_new(attempt / "inventory.json", canonical(inventory, INVENTORY))
    for destination, root, identities in (("snapshot", source_root, inventory["entries"]),
                                          ("datasets", dataset_root, datasets)):
        for identity in identities:
            data = safe_file(root, identity["path"]).read_bytes()
            require(len(data) == identity["size"] and sha256(data).hexdigest() == identity["sha256"],
                    "input_changed_during_copy")
            write_new(attempt / destination / identity["path"], data)
    append(attempt, "NOT_STARTED", [], [], [], [], source_root=source_root, dataset_root=dataset_root)
    return attempt


def append(attempt, state, stages, diagnostics, outputs, deviations, *, source_root, dataset_root, preflight=None):
    from .verify import verify_attempt
    attempt = Path(attempt)
    require(not attempt.is_symlink(), "symlink")
    m = manifest(load(safe_file(attempt, "manifest.json").read_bytes()))
    records = read_records(attempt)
    if records:
        verify_attempt(attempt)
    inventory = validate(load(safe_file(attempt, "inventory.json").read_bytes()), INVENTORY)
    check_files(attempt, outputs)
    source_ok = data_ok = output_ok = False
    if state == "COMPLETED":
        check_files(source_root, inventory["entries"])
        check_files(dataset_root, [{k: d[k] for k in ("path", "size", "sha256")} for d in m["datasets"]])
        for identity in outputs:
            output_valid(safe_file(attempt, identity["path"]).read_bytes(), m)
        source_ok = data_ok = output_ok = True
    check_files(attempt, diagnostics)
    r = dict(schema_version="research.v1", experiment_id=m["experiment_id"], attempt_id=m["attempt_id"],
             manifest_sha256=digest(m, MANIFEST), state=state, sequence=len(records),
             previous_sha256=digest(records[-1], RECORD) if records else "",
             observed_at=datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
             stages=stages, preflight=[] if preflight is None else preflight,
             diagnostics=diagnostics, outputs=outputs, deviations=deviations,
             output_validation=output_ok, source_postcheck=source_ok, dataset_postcheck=data_ok)
    lifecycle(m, records + [r])
    write_new(attempt / "records" / f"{len(records):08d}.json", canonical(r, RECORD))
    verify_attempt(attempt)
    return r
