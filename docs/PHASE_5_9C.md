# Phase 5.9C — personal research reproducibility

Status: IMPLEMENTED; VERIFIED BY SYNTHETIC TESTS on the local Termux environment.
This is a prospective, single-owner, offline record library. It has no runner,
network client, database, service integration or automatic execution wrapper.
No existing historical report or canonical utility is modified.

## Artifacts and use

The public Python utilities live in `app.research_repro`. From `backend/`, use
`schema.manifest(value)` to validate a proposed manifest, `schema.digest(value,
MANIFEST)` to identify it, `store.source_inventory(...)` to identify an explicitly
bounded source selection, `store.allocate(...)` to create an authorized attempt,
and `store.append(...)` to record observations. These calls never execute the
invocation described in a manifest. The synthetic test fixture demonstrates all
required fields and a complete attempt without importing the historical runner.

Prepare the inventory first; put its digest in the manifest; obtain a separate
owner record binding the resulting manifest digest; then allocate. Allocation
requires an existing local attempts base and refuses an existing attempt name.
Its layout is:

```text
<attempt_id>/
  manifest.json
  authorization.json
  inventory.json
  snapshot/<project-relative selected sources>
  datasets/<declared dataset paths>
  records/00000000.json, 00000001.json, ...
  outputs/<expected artifacts>
  logs/<explicit diagnostic artifacts>
```

Dataset bytes are separately retained for self-contained offline verification;
allocation is never performed on real data during Phase 5.9C. Snapshot source
paths are a bounded allowlist, not an automatic copy of the project. The caller
must include material transitive local imports and configuration, alongside the
mandatory entry point, specification and declared lockfiles. Arbitrary Python
imports cannot be proven complete through a file inventory; reviewing this bounded
selection is an owner preflight responsibility. Exclusions must explicitly list
separately identified datasets. Hidden paths, common caches, tooling, credential
files and all symlinks are conservatively refused for source selection. Never
select source containing embedded secrets. No credentials or host identifiers
are automatically collected.

## Closed schema

`schema.py` is the executable v1 schema. All declared fields are mandatory unless
explicitly marked optional. No field defaults are applied to submitted manifests.
Empty arrays explicitly declare no applicable items; empty strings are only
appropriate for inapplicable inline-script digest and unavailable Git HEAD.
`schema_version` is `research.v1` for manifests, authorization, inventories and
records. Mandatory manifest groups are:

| Group | Content |
| --- | --- |
| Identity | experiment and attempt IDs; optional retry parent |
| Authorization | reserved reference, operation and scope |
| Strategy/configuration | specification hash/revision, explicit A/B/C variants, values and decimal settings, session/gap/ambiguity/cutoff policies |
| Datasets | path, role, timeframe, size/hash, provider, symbol, inclusion classification |
| Source | snapshot ID, inventory path/hash, entry point |
| Git | usable HEAD or explicit absence, relevant modified/untracked paths |
| Runtime/dependencies | Python implementation/version/build, executable path/size/hash, OS/architecture, numeric/timezone information, installed versions, lockfiles, material non-pip components |
| Time/window | fixed broker conversion, IANA session zones, warmup/input/evaluation/cutoff and close eligibility |
| Invocation | interpreter, ordered argument array, working directory, allowlisted environment, optional-use inline-script identity |
| Determinism | randomness, ordering, decimal precision/settings/rounding, concurrency |
| Preflight | procedure version, named checks and fail conditions |
| Outputs | paths, serializer/schema versions, required stages |
| Conditional plans | explicit inferential/cost-adjusted booleans; required plans when true; random generator/seed list when randomness is true |

Optional fields must be omitted when their condition is false. Null is never an
implicit omission. Other caller-specific executable settings use named string or
decimal entries, not undeclared schema fields. All schema keys are ASCII.
Runtime metadata is supplied explicitly, avoiding indiscriminate host/environment
capture. The executable path may be absolute; source and artifact paths may not.

Dataset identities enforce Alpari MT5 Demo / XAUUSD_i. Only H1 and M15 may be
included. Daily stays excluded with UNKNOWN_BOUNDARY; H4 stays disabled/excluded.
No candle processing or stream combination occurs. Broker UTC+02:00 has no DST:
subtract two hours for UTC, add one for Qatar; UTC to Qatar adds three hours.
Qatar is Asia/Qatar; actual session IANA zones preserve their DST rules.

The statistical-plan schema explicitly covers chronological splits, untouched
holdout availability, repeated inspection, dependence/clustering, month and
multi-month blocks, A/B/C multiplicity, shared trades, ambiguity, censoring, gaps,
annual/session stability and largest-winner sensitivity. A plan is not evidence
that untouched holdout data exists. Cost-model fields cover spread, commission,
slippage, swap, stop gaps, partial/rejected fills, liquidity, contract details and
reliability/coverage; missing-cost policy must reject net claims. No plan executes
statistics, costs, optimization or parameter selection.

The sole supported output contract is a closed synthetic receipt:
`{"schema_version":"research.receipt.v1","result":"..."}`, with serializer
`research.canonical.v1`. Real historical report serializers require a separately
approved adapter. This deliberately prevents accidental claims that arbitrary
real research outputs have been schema validated.

## Canonical identity and authorization

Canonical JSON uses UTF-8, no BOM, whitespace or newline; recursive lexical object
key ordering; semantic array order; and inventory entry ordering by unique relative
path. Duplicate JSON keys, fractional/exponent JSON number tokens, Python floats,
non-NFC strings, surrogates and invalid schema fields/types are rejected. Plain
string decimals are normalized to remove redundant zeros and negative zero.
Timestamps require a known offset, reject naive and -00:00 input, and normalize to
UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Quotes/backslashes are escaped; every U+0000–001F
uses lowercase `\u00xx`; Unicode and slash remain unescaped. Integers are base 10.
Paths reject traversal, backslashes, control characters, case-fold collisions,
duplicates and file/directory collisions. These are conservative portable checks,
not a claim of support for every filesystem's filename rules.

Manifest identity is direct standard-library SHA-256 of every canonical byte,
64 lowercase hexadecimal digits; no self digest and no excluded manifest fields.
`canonical_digest.py` framing is intentionally unused. Existing canonical parsing,
schema/serializer and decimal/time primitives are reused without behavior changes.
Research-specific rejection happens before their normalizations.

Authorization is a separate local owner permission record, with date, exact
manifest digest, reference, operation, variants, ordered dataset hashes, evaluation
window and restrictions. All bindings must match exactly; required restrictions
are offline-only, no execution/live integration/optimization, and separate owner
execution authorization. A changed manifest needs a new permission record. This
framework authorization is not permission to run the declared invocation and is
not cryptographic proof of authorship.

## Lifecycle and failure

Every append contains experiment/attempt identity, manifest hash, sequence,
previous-record digest (empty only initially), UTC observation, state, named
stage/preflight results, diagnostic and output identities, postcheck results and
deviations. Transitions are:

```text
NOT_STARTED -> RUNNING -> COMPLETED | FAILED | INTERRUPTED
NOT_STARTED -> FAILED | INTERRUPTED
```

Terminal states cannot be resumed or appended to. COMPLETED requires every
required preflight and processing stage successful, valid expected receipt outputs
with sizes/hashes, live source and dataset byte comparisons against the declared
inputs, and no deviation. Offline verification also checks retained inputs and
outputs. Stage/preflight results are explicit owner-supplied attestations; this
library does not run validation commands. Exit success alone is never completion.

FAILED and INTERRUPTED require retained hashed diagnostics; partial artifacts
remain retained. INTERRUPTED records an observation time only, never inventing
exit code or termination instant. A stale RUNNING attempt remains RUNNING until
an explicit interruption observation is appended. Retries require a new ID,
manifest digest and authorization reference and a same-experiment FAILED or
INTERRUPTED parent retained next to the child. Missing parents fail verification.
No silent resume or recovery/reuse of failed allocation directories is supported.

## Offline verification and independence

From `backend/`:

```sh
.venv/bin/python -m app.research_repro.verify /absolute/path/to/attempt
```

Exit 0 reports the observed state, recalculated manifest hash and record count;
it does not imply COMPLETED. Exit 1 reports NOT VERIFIED for missing/corrupt
records. The verifier has its own encoder, decimal/time formatting and filesystem
hashing path. It reconstructs canonical bytes from original parsed documents,
recalculates the inventory/manifest/chain digests with hashlib, checks all retained
hashes, exact snapshot/dataset membership, authorization, transitions and completion
requirements. It rejects pending writes and noncanonical artifact bytes. Retry
parents are independently visited with cycle detection.

Declarative schemas, JSON parser and semantic binding/transition rules are shared;
this is independent byte reconstruction/hashing, not a separately authored audit
implementation. Fixed expected-byte/hash vectors exercise both encoders, including
a test with the writer encoder disabled. An external verifier can implement the
profile above using the closed schema without importing the writer.

## Atomicity and filesystem limits

Files are staged in the destination directory, flushed and fsynced. Each final
name is reserved with O_CREAT|O_EXCL before atomic replacement of that writer's
own empty reservation. This is needed because local Android Python lacks os.link.
Existing names, including empty incomplete reservations, are never reused. Parent
directories are fsynced and bytes are read back after publication. A process
interruption may leave an invalid empty reservation, pending file or incomplete
attempt; verification fails closed and retains that evidence. Publication of an
entire attempt is not one filesystem transaction. Readers during a write can fail
closed and should retry only after the writer has finished.

This relies on a trusted single-owner local filesystem, cooperative writers and
working exclusive creation, atomic replacement and fsync. Unsupported operations
raise errors; no weaker fallback is used. It cannot guarantee power-loss durability
beyond the kernel/filesystem/storage device, prevent a malicious owner rewriting
all evidence, prove an entirely deleted lifecycle tail once existed, or prevent
hostile concurrent path replacement. Postchecks observe bytes at their recorded
time, not continuously. No cross-platform or production-load claim is made.

## Preserved findings and non-goals

Phase 5.4 zero trades came from a defect and are not performance evidence.
Phase 5.5.1 corrected FVG direction case comparison. Phase 5.6 report SHA-256 remains
`29974cb4ba40d08a373093e18f9f0bb3e89623690de1a04700187eb2c5158adc`.
A current source snapshot cannot recover historical executable provenance.
Phase 5.8 remains accounting validated with limitations; STATISTICALLY INCONCLUSIVE;
source provenance NOT VERIFIED; EXECUTION VALIDATION NOT AVAILABLE.

This framework does not prove broker data authenticity, strategy correctness,
statistical or net profitability, or live execution capability. No experiment,
backtest, simulation, holdout study, market-data acquisition, cost modeling,
strategy modification, broker execution, live integration or deployment is included.
Phase 5.9D requires separate owner authorization.

## Implementation verification record

IMPLEMENTED: closed schemas, canonical identity, permission binding, bounded retained
snapshots, exclusive allocation, lifecycle/completion checks and offline verification.
VERIFIED BY SYNTHETIC TESTS: 79 new framework cases and 145 existing canonical cases,
224 passed. No real datasets, experiments or historical runner imports were used.

Commands run from `backend/`:

```sh
.venv/bin/python -m pytest tests/test_research_repro.py tests/test_canonical.py tests/test_canonical_digest.py -q --tb=short
.venv/bin/python -m compileall -q app/research_repro tests/test_research_repro.py
.venv/bin/python -m pip check
```

All passed; pip reported no broken requirements. An AST import-boundary assertion
is included in the synthetic suite, and the verifier CLI was exercised in a child
Python process against a temporary synthetic completed attempt. Atomic interruption
and concurrent publication are covered. An initial test run found Android's absent
os.link; exclusive reservation plus atomic replacement fixed that portability issue.

From the repository root, `. .venv-graphify/bin/activate` then `graphify update .`
updated the AST graph offline: 2245 nodes, 6959 edges. Graphify reported an existing
missing SQL parser and unclassified extensions; no dependency was installed. This
is an AST refresh, not a fresh semantic extraction of documentation.

Created application/test/documentation files:

- `backend/app/research_repro/__init__.py`
- `backend/app/research_repro/schema.py`
- `backend/app/research_repro/store.py`
- `backend/app/research_repro/verify.py`
- `backend/tests/test_research_repro.py`
- `docs/PHASE_5_9C.md`

Existing files modified (generated graph state only):

- `graphify-out/.graphify_build_state.json`
- `graphify-out/.graphify_labels.json.sig`
- `graphify-out/.graphify_labels.pending.json`
- `graphify-out/GRAPH_REPORT.md`
- `graphify-out/cache/stat-index.json`
- `graphify-out/graph.html`
- `graphify-out/graph.json`
- `graphify-out/manifest.json`

Generated graph cache files added:

- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/0f8d9aed2e38efb5a1b1d13329811bb05533eca308701a1bef1c7013bcdd235b.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/370e1556fee81aecb1c015c6342d4a43c65bc11b193553fd7e91fd581059abdc.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/415ca34282e80ff6f07269afac25dd5c5c424506b05a91b85558f5c6012ca66b.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/94c6705354ef66b8f0e340f6913aa42f727bf5ee405f88aa1f4207f2f5f768d2.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/aa3229bbf80e270feea943247956fd466e91ef713da95a675eb14b5fd7009aff.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/ac2d9461511c7412f5a80366cff3103cf2311a20e47635f86b3de8fbe45ca1db.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/d9f1c27c559a89862f7acb505bfc1a5039c646ed279fd9892101da7dc2ad97c3.json`
- `graphify-out/cache/ast/v0.9.112-s48-g0c3eaf764afd/f35275236d36df3a32dd8a8cc354d3556f4235f35393e37c7d23d9480a406550.json`

Normal ignored Python bytecode and pytest cache artifacts were also produced by
verification. No existing application source, configuration, dependency lock or
historical report was modified. No dependencies added; no network activity; no live
pipeline changes. No destructive Git operations or commits.

Git before and after: no usable HEAD; the same root entries remain untracked
(`.agents/`, `.codex/`, `.environment-preparation/`, `.gitignore`, `.graphifyignore`,
`.milestone-1/`, `.milestone-2/`, `.milestone-4/`, `AGENTS.md`, `README.md`, `backend/`,
the three existing codex-session Markdown files, `docs/`, `frontend/`, `graphify-out/`,
`reports/`). Consequently git diff cannot establish a committed baseline; this
report identifies the bounded files written by this task.

Historical JSON report hashes were checked before and after and remain:

- Phase 5.4: `60c1761cb53e0f66db062d34f3ada26ac01445bf781bda96b291c88bb1371102`
- Phase 5.5 diagnostics: `6ab61d40a9fc402c07ae7a9b4ac22ad84d481d1a6a4b69e50af0577e90f2a188`
- Phase 5.6: `29974cb4ba40d08a373093e18f9f0bb3e89623690de1a04700187eb2c5158adc`

NOT VERIFIED: cross-platform behavior, physical power-loss durability, browser/canvas,
production load, and historical executable provenance. Full backend and frontend
suites were not run: this authorization requests focused synthetic tests and safe
static checks only, and no service entry point or UI changed. NOT IMPLEMENTED by
design: real report adapters, real research execution and every Phase 5.9D activity.

## Phase 5.9E corrective engineering (2026-11-20)

This addendum records later corrections to the original Phase 5.9C implementation;
the implementation history above is retained. Status: IMPLEMENTED and VERIFIED BY
TESTS for the bounded synthetic framework changes below. It does not authorize
research execution or supersede the Phase 5.8 conclusions.

### Confirmed defects and corrections

F1: `lifecycle` previously inspected only the COMPLETED record's deviations.
It now accumulates deviations across the entire sequence before accepting
completion. The existing string-array schema has no validated severity or
resolution metadata: every recorded deviation is therefore disqualifying and
unresolved. Text saying “informational” does not change its meaning. Missing
mandatory deviation metadata and empty deviation entries are rejected. Earlier
records remain unchanged; no resolution mechanism has been added. A separate
verifier history check rejects historical deviations even when the shared
lifecycle evaluator is disabled in an adversarial test.

F2: output identities were previously checked before publication only for
COMPLETED. Every proposed record now checks all referenced outputs and diagnostics
before any record publication: safe relative paths, no symlinks, regular files,
existence, exact byte size and recalculated SHA-256. Completion additionally
requires every declared final output in manifest order and valid receipt content.
FAILED/INTERRUPTED still require diagnostics. Partial outputs need byte identity,
not the final receipt schema. Invalid references leave the previous chain unchanged;
a later valid append can succeed. Post-publication independent verification is
retained. Artifact mutation after validation remains a filesystem race, not a
transactional guarantee; it is detected by subsequent verification.

F3: `restrictions` is now a closed, unique list of enforceable identifiers.
Unsupported natural-language entries are rejected. Existing five required
identifiers remain structural boundaries of this offline library: it has no
execution, optimization, broker, network or live integration capability, and its
records grant no execution permission. They cannot constrain an external program
that chooses to ignore this library. Additional supported identifiers are:

| Identifier | Validation |
| --- | --- |
| `synthetic_receipt_only` | Operation must be exactly `synthetic_receipt` |
| `variant_a_only` | Ordered variants must be exactly `["A"]` |
| `exact_scope` | Requires `restriction_scope` with operation, variants, dataset_hashes and window, each exactly matching the authorized manifest |

`restriction_scope` is forbidden without `exact_scope`; its fields use the existing
closed types. Conflicting operation/variant/dataset/window constraints fail closed.
The ordinary authorization bindings still require the exact manifest digest,
operation, variants, ordered dataset hashes and complete window regardless of
additional restrictions. Optional `advisory_notes` retains arbitrary strings as
non-enforceable information: notes do not affect authorization. Authorization
`date` remains a validated timestamp for information only, with no expiry,
not-before or freshness policy. No multi-user or cryptographic authorship claim
is made. Existing valid authorizations without these optional fields remain valid;
previously accepted arbitrary restriction strings must be moved to advisory notes.

### Configuration, contracts and artifact inventory

Configuration string and decimal settings share a unique, nonempty name namespace.
Determinism decimal settings have their own unique namespace. Installed and
non-pip dependency records share a unique name namespace; lockfile paths are
unique under the existing portable path rules. Equal duplicates and conflicting
values are both rejected. Name comparisons are exact, not package-manager alias
resolution. Environment, stages, checks, generator identifiers and other existing
keyed collections retain their uniqueness checks. Semantic array order is preserved.
No canonical utility behavior changed.

Manifest validation now accepts only the explicit serializer/schema pair
`research.canonical.v1` / `research.receipt.v1`, before allocation creates a directory.
Unknown versions fail rather than substituting a serializer. This validates a
manifest contract; it does not implement a real historical report adapter.

Final manifest output paths must be under `outputs/`. Lifecycle output references
must be under `outputs/` or `partial/`; diagnostic references must be under `logs/`.
Output and diagnostic identities cannot overlap within one record. The verifier
returns `artifacts` with `final_outputs`, `partial_outputs` and `diagnostics` lists,
and a sorted `unreferenced_artifacts` list. Classification describes each historical
reference, so an artifact observed while RUNNING and later finalized can appear in
both output lists. Only COMPLETED references classify as final outputs.

The inventory covers regular files recursively visible under the retained attempt:
three metadata documents, exact snapshot/dataset membership, exact contiguous
record filenames and every lifecycle artifact reference. Extra snapshot/dataset
files and invalid record filenames remain fatal. Other extra regular files,
including harmless temporary files, are explicitly reported without being called
verified outputs or deleted. Symlinks, pending publication files and special file
types fail verification. Empty directories are not research artifacts and are not
inventoried. No filesystem inventory proves absence of externally hidden files or
protects against hostile concurrent namespace replacement.

### Independence, durability and concurrency

Independent canonical reconstruction, SHA-256, chain checks, retained file checks
and receipt byte verification remain in the verifier. Its historical-deviation
check runs independently before the shared lifecycle business-rule evaluator.
A fixed full-manifest canonical byte vector (2686 bytes) and digest
`59d7836e4b1b1af731d397be020481c2e6a38c5e606448d0af1bd988420c3b55`
exercise both encoders and the full attempt verifier.

PARTIALLY IMPLEMENTED: validation independence. Declarative schemas remain separate
objects from business-rule functions, but share `schema.py`; parsing, manifest and
authorization semantics, schema validation and the remaining lifecycle rules are
intentionally shared. No wholesale duplicated business-rule engine was introduced.
This is not a fully independent audit implementation.

New directory hierarchies created by publication now synchronize their parents and
the directories themselves; allocation synchronizes the attempt directory after
creating snapshot/dataset/record directories. Existing exclusive creation,
no-overwrite reservations, atomic replacement and final directory synchronization
remain. Tests observe synchronization calls and actual local success; they do not
simulate physical power loss.

A two-process regression forces both appends to reach publication with the same
sequence. Exclusive reservation permits only one record at that sequence; the final
chain verifies. A caller may receive a fail-closed error while a competing writer
still has a pending file, even if its own publication succeeded. Callers must inspect
the retained chain after errors; they must not assume failure implies no publication.
Pre-publication validation failures in a quiescent attempt create no record.
Interrupted filesystem publication may still retain an invalid reservation, as
before. No locking, automatic recovery or transactional whole-attempt publication
was added. Atomic rename, fsync and physical power-loss durability remain dependent
on filesystem, kernel, platform and storage behavior. Hostile path replacement,
malicious owner rewrites and deleted tails remain outside the guarantee.

### Corrective verification evidence and change control

Final commands from `backend/`:

```sh
.venv/bin/python -m pytest tests/test_research_repro.py tests/test_canonical.py tests/test_canonical_digest.py -q --tb=short
.venv/bin/python -m pytest tests/test_research_repro.py --collect-only -q
.venv/bin/python -m compileall -q app/research_repro tests/test_research_repro.py
.venv/bin/python -m pip check
```

Final focused run: 289 collected, 289 passed, 0 failed, 0 skipped (23.09 seconds).
This comprises 144 framework cases (65 added regressions) and 145 existing canonical
cases. Earlier intermediate runs passed 280 and 286 cases before the last tests
were added. Compilation passed; pip reported no broken requirements. The suite
includes AST import-boundary checks, the offline verifier CLI, missing/size/hash/
file-type/traversal/symlink artifact attacks in each state, successful failure and
interruption records, unchanged chains after rejection, subsequent successful
appends, digest-valid forged completion histories, restriction mismatch/advisory
cases, duplicate settings and dependencies, unsupported output contracts,
unreferenced artifact visibility and process concurrency. Synthetic source named
`runner.py` is inert bytes and is never executed.

Modified only:

- `backend/app/research_repro/schema.py`
- `backend/app/research_repro/store.py`
- `backend/app/research_repro/verify.py`
- `backend/tests/test_research_repro.py`
- `docs/PHASE_5_9C.md`

No project files created. A temporary before-state outside the repository supports
source-level comparisons and SHA-256 integrity checks. Git has no usable HEAD;
root entries are untracked, which establishes no ownership or historical attribution.
Existing unrelated contents were preserved. Generated graph artifacts were neither
refreshed nor regenerated, per the explicit Phase 5.9E boundary.

All historical report and graph artifact bytes remain unchanged from this task's
before-state, including the three report hashes listed in the original verification
record. All other pre-existing non-cache project files outside these five paths
remain unchanged: no strategy, raw dataset, historical runner, live pipeline,
frontend/API, dependency or lock changes. No dependencies were installed, and no
network tool or network command was used. No packet-level network monitoring was
performed. Only inert local fixtures were allocated and examined. No backtest,
experiment, simulation, benchmark, optimization, acquisition, activation, deployment,
commit or destructive Git operation occurred.

NOT VERIFIED: cross-platform behavior, physical power-loss durability, production
load, browser/canvas, historical source provenance and real report adapters. Full
application suites were deliberately excluded. Phase 5.8 remains accounting
validated with limitations; statistical evidence INCONCLUSIVE; source provenance
NOT VERIFIED; EXECUTION VALIDATION NOT AVAILABLE. Phase 5.9E ends here; Phase 5.9F
or any research execution requires separate owner authorization.
