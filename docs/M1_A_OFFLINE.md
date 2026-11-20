# M1-A / M1-A2 offline implementation

These changes establish offline behavior, not live provider readiness. No refresh
route, scheduler or startup ingestion is registered. Health remains independent
of market availability. Status retains A0's in-memory unavailable state and does
not open a database. Live requests require separate owner authorization.

## Evidence and immutable readiness

SiftingIO analysis selects only closed candles from the latest whole complete
retrieval. Forming candles remain in stored/provenance records. Coverage excludes
buckets that have not closed at analysis time. Failed or incomplete attempts
cannot be mixed with earlier attempts or silently fall back to old evidence.

`freshness_max_age_seconds`, `minimum_closed_candles` and
`FreshnessPolicy.max_age_seconds` are validated copies exposed through immutable
mapping proxies. Their JSON representation remains an object with timeframe keys.
Values are strictly positive integers: booleans, numeric strings and fractions
are rejected. Empty or incomplete configuration fails closed.

Bind a separately supplied policy before assessment and analyst dispatch:

```python
bound = packet.with_readiness(freshness=supplied_policy.max_age_seconds,
                             minimum_candles=required_depths)
sufficiency = assess_sufficiency(bound)
# Only pass bound, including its serialized policy, to downstream analysis.
```

`with_readiness` returns a new validated packet. Existing freshness limits can
only decrease and depth requirements can only increase. Passing a stricter,
unbound policy directly to `assess_sufficiency(packet, policy)` raises an error;
it cannot produce a transient assessment whose stronger policy is then lost.
Looser reassessment never overrides a bound limit. Explicit reconstruction of a
different packet or Pydantic's unvalidated construction/copy APIs is not an
authorization mechanism; trusted callers must preserve packet identity and its
manifest binding.

Freshness uses closed market-event time, never retrieval time alone. Default
personal depths remain Daily 200, H1 300 and M15 300. No production freshness
thresholds are invented. The richer calendar/publication-delay policy remains
separate and provider semantics remain unverified. External-AI/source/model
permission remains a separate caller obligation; market readiness grants none.

## Dormant explicit refresh interface

`MarketDataPipeline.refresh(request, budget=budget, authorized=True)` is explicit.
The caller supplies the existing store and client; the worker receives neither a
database path nor a store. Arbitrary client transports are rejected. No endpoint
calls this method. Daily, H1 and M15 are supported; H4 and M5 are rejected.

`RefreshRequest` bounds page size to 1–2000 and pages/requests to 1–100.
`RefreshBudget` requires explicit retrieval, cleanup and persistence allowances.
Local ceilings are 3600 seconds for retrieval/persistence and 30 seconds for
cleanup. Result bytes default to 16 MB and cannot exceed 64 MB. Frames cannot
exceed 4 MB. Socket connect/read timeouts must each be finite and at most 60
seconds. These are local safety ceilings, not provider quota claims.

## Worker, admission and IPC

The parent launches the existing backend interpreter with `-B -m
app.data.refresh_worker`, without a shell, in a new session, with unrelated file
descriptors closed and a minimal credential-free environment. The dedicated CLI
accepts no arguments, database paths or injected code. In-process transport
injection in the private worker function is used only by the synthetic test
executable; no callable can be selected over the production protocol.

Private stdin/stdout pipes carry versioned JSON with a four-byte network-order
length prefix. The parent drains the pipe while the child runs, bounds cumulative
bytes, rejects duplicate keys and validates exact message shapes, attempt IDs,
page indices, identities, ranges, ordering and terminal pagination. Every page is
provisional. Complete messages without a complete page sequence are rejected.
Abnormal exit, missing EOF, trailing data, malformed/truncated/oversized results,
repeated cursors, overlaps and late output never authorize persistence.

The parent resolves credentials explicitly using the existing loader, or an
explicit client credential. The worker receives the credential in the private
start frame and keeps it in memory, not argv or its environment. Stderr is
discarded; worker failures return only allowlisted categories. This is trusted
same-UID process isolation, not an OS security sandbox or guaranteed memory
zeroization. The worker necessarily sees the authentication material.

Before each request the child asks the parent for admission. A process-wide gate
shares quotas/concurrency across refresh workers. A conflicting policy fails
closed instead of silently replacing the shared policy. Persisted request history
is merged without double charging already observed events. The parent records
admission durably before granting it; uncertain requests remain charged. Quota
values are still caller-configured. The parent deadline monitor can terminate the
child even while parent SQLite admission is blocked.

Continuation is authorized only through an operation-owned admission object and
the next cursor from a validated page. A public historical call with a supplied
cursor has no polling exemption. Continuations retain pause, quota, duplicate and
concurrency checks. The shared gate covers workers within one parent process;
multiple independent service parents are not a supported admission topology.

## Deadline and cleanup contract

A monotonic retrieval deadline is established before process launch. Creation,
worker execution, pipe handling, parent validation and confirmed direct-child
exit all consume that budget. Results are accepted only before expiry, after a
terminal sequence, EOF and zero exit status. Retrieval cancellation is permanently
fatal to acceptance. No partial pages are persisted on retrieval failure.

The parent uses a separate deadline-monitor thread so blocking parent admission
I/O does not prevent signaling the worker. Timeout/cancellation starts bounded
process-group SIGTERM, SIGKILL escalation and direct-child reaping using the
separate cleanup allowance. Descriptors are closed on all paths. If exit/reaping
cannot be confirmed, `cleanup_unresolved` retains the process handle and admission
state and blocks further workers. There is no automatic resume or replacement.

This is not hard real time: Python process creation may block before returning a
handle, and OS scheduling, GIL-held native code, suspension or kernel waits may
delay supervision/termination. A slow creation that returns late is rejected and
cleaned up. Launch ownership is retained in thread-local state as soon as the
constructor returns. If launch is interrupted before a handle can be recovered,
the child state is unknown, not confirmed absent: `cleanup_unresolved` latches
and blocks subsequent workers. Cancellation before launch remains distinguishable
and needs no child cleanup. Unknown ownership has no automatic recovery; it
requires separately authorized reconciliation. A cleanup failure is never success. The worker creates no descendant
processes; a daemon watchdog exits it when its parent PID changes. Actual Android
reparenting/background behavior is unverified. Process groups do not contain
hostile descendants that create new sessions; arbitrary worker code is unsupported.

## Parent-only persistence and failure contract

Only after worker exit and retrieval acceptance does the parent stage returned
pages and promote the complete retrieval using the existing schema-v1 methods.
Pending attempts and request-admission records are also written only by the
parent. No schema migration is introduced. Page-stage or promotion failure before
commit leaves the previous current generation intact; the failed latest attempt
is not eligible as evidence. No attempt reuses pages from another attempt.

The separate persistence budget covers post-retrieval outcome recording, page
staging and promotion. SQLite busy timeout is bounded to that allowance and an SQL
progress handler checks expiry/cancellation. The busy timeout is restored and the
private progress handler is cleared afterward.
There are no automatic retries. SQLite fsync/commit and failure bookkeeping are
not hard-interruptible. A commit that finishes over budget produces
`persistence_commit_budget_exceeded`; it may already have committed and requires
state reconciliation, never a blind retry. Cancellation is checked before promotion,
by SQL progress handling and immediately before the transaction's commit boundary.
Cancellation or interruption observed after commit returns
`persistence_committed_reconciliation_required`, with `committed=True` and
`reconciliation_required=True`, preserving the committed generation. Exceptions
at the commit boundary are reconciled against that exact attempt's persisted
status; failure to establish the status returns `persistence_reconciliation_required`
with `committed=None` and does not mark the attempt failed or claim rollback. A late completed commit
also carries both flags. Cancellation arriving after the final acceptance check
cannot retroactively cancel a completed operation. Failure to record a retrieval failure
sets `RefreshFailure.persistence_failure` without hiding cleanup status. Parent
SQLite thread/connection ownership must be preserved by the caller.

## Offline verification and separate authorization

Synthetic tests exercise private-pipe workers, simulated blocked DNS/slow
responses, deadlines across pages, late exit, malformed IPC, oversized output,
full pipes, crash/kill/cancel paths, shared admission and disposable SQLite
persistence. The synthetic executable forbids real socket connections and SQLite
access. Parent-death watchdog branching is unit-tested; actual Android parent
death, device suspend, background restrictions and kernel-level uninterruptible
waits require separately authorized device experiments. No real provider or DNS
verification is implied by synthetic subprocess tests.

M1-B still requires owner approval of freshness thresholds and live verification
of authentication, pagination, timestamps, calendar/publication semantics, quota
values and data quality. Existing user-database access, device lifecycle
experiments and external-AI use each require their own authorization. The earlier
M1-A report's statement that refresh was never invoked applies to that pass only;
M1-A2 invokes refresh exclusively against synthetic workers and disposable stores.
Graphify execution/update is explicitly excluded from M1-A2.


## M1-A3 offline corrections

Interrupted launches with unknown child ownership fail closed and block further
workers; retained handles still use bounded termination/reaping. Promotion has an
explicit pre-commit cancellation guard and post-commit reconciliation contract.
`invalid_cursor` and the safe `worker_failed` fallback share the worker/parent
error allowlist. Synthetic regressions cover interrupted creation, unresolved
latching, cancellation before/during/after promotion, missing terminal messages,
trailing frames and invalid-cursor propagation. No device or provider verification
is implied, and no automatic reconciliation or retry is implemented.
