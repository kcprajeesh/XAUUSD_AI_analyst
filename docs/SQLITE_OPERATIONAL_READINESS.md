# SQLite operational readiness proposal

Status: synthetic failure/recovery and workload checks are implemented. The proposed settings below are candidates for review, not production selections. No production or existing database was accessed.

## Implemented prototype behavior

- One SQLite connection belongs to one archive object/owner. Compound writes use `BEGIN IMMEDIATE`; errors roll back if SQLite has not already ended the transaction. An error is returned; there is no application retry loop.
- WAL mode and `synchronous=FULL` are explicit in the disposable archive. Busy timeout is mandatory caller input. Test calls use explicit values such as zero or 100 ms only as fixture settings.
- Readers use separate connections and WAL snapshots; a long reader sees its original snapshot and can delay checkpoint completion. A post-reader `wal_checkpoint(TRUNCATE)` can complete.
- Writes persist exact BLOBs in the same row/transaction as permission and expiry metadata. Manifest and derived-output pairs use foreign keys and one transaction. Immutable records have update/delete triggers.
- A caller may retry an idempotent operation only after rereading state. The derived output/manifest pair supports exact replay. Evidence/retrieval allocation is not generally idempotent; duplicate identities fail rather than overwrite.

## Synthetic workload and observed measurements

Command: `backend/.venv/bin/python -m app.data.sqlite_workload` from `backend/`. It creates and deletes its own temporary `.synthetic.sqlite3` databases. Each run writes 201 synthetic 4 KiB evidence bodies, 125 revisions across the five archive timeframe labels, five retrievals, five promotions and one five-timeframe manifest: 342 explicit write transactions. It validates SQLite integrity before reporting. Five sequential runs on 2026-11-18 yielded:

- Elapsed time: minimum **0.377 s**, median **1.166 s**, maximum **1.630 s**.
- Main database file **1,060,864 bytes**; page accounting **1,085,440 bytes**; active WAL file **4,128,272 bytes** for these runs.
- The workload reports WAL mode, synchronous value `2` (`FULL`) and its explicit test busy timeout of 100 ms.

Environment: Termux/Android 17 aarch64, Python 3.13.13, SQLite 3.53.2. Exact SoC, storage medium, Android device load and filesystem durability properties were not measured. Run-to-run time varied substantially. These measurements are a local test baseline, not capacity, throughput or production storage claims.

## Failure and recovery evidence

`tests/test_sqlite_operational.py` and existing archive/provenance tests exercise: WAL reader/writer snapshot behavior; passive/truncate checkpoint calls; writer contention at a zero-millisecond fixture timeout followed by explicit caller retry; process exit before commit during evidence, manifest and invalidation writes; `SQLITE_FULL` induced with `max_page_count` in a temporary database; online backup and restore; rollback of a failed derived pair; process crash between output and derived-manifest insertion; post-reopen SQLite integrity and foreign-key checks. SQLite automatically rolled back the disk-full transaction; `_transaction` was corrected not to mask the original error with a second rollback attempt.

Demonstrated guarantee: for these local synthetic transactions, committed rows survive process restart and uncommitted transactions leave no partial rows; enforced foreign keys and integrity checks pass after reopen. This is not evidence for power loss, storage-controller failure, filesystem corruption, network filesystems, device reboot durability, backup retention, or a recovery point/time objective. Disk-full was simulated, not produced by exhausting the device filesystem.

## Operational requirements and response procedure

Before any SQLite-backed production archive is considered, the target must provide: a documented supported local filesystem and SQLite build; a single explicit write/transaction owner per connection; observed writer queue and lock/error metrics; WAL byte/frame growth and checkpoint-result monitoring; a maximum transaction duration derived from workload; atomic online backup to a separately protected destination; periodic restore drills; startup/recovery `integrity_check` and `foreign_key_check`; disk-space and write-failure alerts; and an operator-visible unavailable state that preserves the last committed generation. No WAL size, free-space reserve, transaction-time bound, timeout, backup frequency, or recovery target is selected here.

On `SQLITE_BUSY`/locked, `SQLITE_FULL`, I/O or integrity failure: abort the owning transaction, return a typed unavailable/error result, do not promote a retrieval or publish a manifest/report, and do not retry invisibly. After a process restart, reopen the same authorized store, run integrity and foreign-key checks, compare the persisted generation/manifest links, and reconcile the operation by immutable identity. Retry only an exact idempotent operation after reading state. Restore only from a verified online backup into a new destination, then verify integrity and expected immutable identities before read access. Preserve the failed database and WAL for investigation; do not delete sidecars as a recovery shortcut.

Monitoring required for a future operational runbook: SQLite/library version and PRAGMA settings at open; transaction start/end and failure class without payload/secrets; lock wait/failed acquisition; WAL size and checkpoint busy/log/checkpointed counts; DB and free-space measurements; integrity/foreign-key result; backup age/result and restore-drill duration; recovery generation and unavailable-state duration. Retention, access control, encryption/key custody, alert thresholds, ownership and escalation remain target-specific decisions.

## Candidate operational policy (not approved for production)

| Setting/behavior | Candidate | Trade-off / decision still needed |
|---|---|---|
| Journal | WAL | Supports reader/writer overlap; requires checkpoint monitoring and sidecar-aware backup/restore. Validate target filesystem. |
| Synchronous | FULL | Stronger commit durability request at a write-cost; hardware/filesystem guarantees remain external. Current setting is prototype-only. |
| Writer ownership | One connection per owner; `BEGIN IMMEDIATE` for compound writes | Serializes writers and avoids lost updates; writer queueing and request behavior need target-load evidence. |
| Busy timeout | Must be explicitly selected at construction; no chosen production number | Larger values wait longer, smaller values fail sooner. Select only from measured service latency/queue requirements. |
| Retry | No hidden retry. Return lock/IO errors. Retry only after state reread and only for an operation with proven idempotency. | Avoids duplicate/partial publications; evidence/retrieval APIs need explicit idempotency keys before automatic retry is considered. |
| Checkpoint | Measure passive/truncate behavior; no schedule selected | Long readers can prevent truncation. Cadence, WAL size alert and maintenance ownership need operations evidence. |
| Backup | SQLite online backup API; synthetic restore verified | Cadence, destination, retention, encryption, off-device copy and restore drills remain unset. |
| Bounds/recovery | None selected | Database size, disk reserve, backup RPO/RTO and target filesystem need user/operations evidence; DEC-04 remains deferred. |

Failure behavior should be fail-closed: preserve the last committed state, return busy/full/I/O errors without promoting partial retrievals or manifests, run integrity checks after recovery, and require explicit state reconciliation before retry. The present measurements recommend retaining WAL plus `synchronous=FULL` as a prototype candidate only, using whole-transaction `BEGIN IMMEDIATE`, no hidden retries, observed WAL/checkpoint behavior, and SQLite's online backup API. This is not a production setting selection. Production activation requires a separate target-device workload/recovery rehearsal and authorization; these results do not grant it. DEC-04 remains deferred.
