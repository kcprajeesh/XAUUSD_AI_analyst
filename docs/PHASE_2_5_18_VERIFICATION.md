# Phase 2.5.18 — implementation and verification evidence

Date: 2026-11-18. This is a partial implementation checkpoint, not architecture-wide closure, working-ready acceptance or production activation. Latest isolated-contract/archive results below supersede older backend totals in the historical sections.

## Changes and their purpose

- Refined the existing graphite/gold terminal rather than replacing its architecture. Added economic calendar and settings/provider navigation, shared validated IANA timezone controls, explicit evidence requirements, unavailable bias/levels/timestamps and clearer provider/source states. No invented prices, candles, news, confidence or conclusions are supplied. TradingView Lightweight Charts stays lazy and empty with attribution.
- Connected the frontend to the unchanged `/health` contract through loopback Vite development/preview proxies. The health request omits browser credentials, disables caching and has a ten-second UI deadline with retry. It rejects invalid MIME types, impossible dates, year zero, non-UTC timestamps and unexpected response fields. The deadline is ordinary health-request behavior, not a DEC-04 production resource setting or numerical AI safeguard.
- Added separate, explicit-schema canonical primitives with lossless JSON numeric lexemes, exact decimals, UTC6 timestamps, selective NFC, ordered/set array rules, sanitized typed errors and five required caller limits. No old serializer/hash/ID was replaced.
- Added separate domain/profile registered SHA-256 v1 framing and structured/raw verification. Tests use newly named synthetic profiles and byte references only. Raw malformed bytes remain unchanged; profile/representation mismatch, unresolved bytes, tamper and length mismatch fail.
- Added explicit immutable namespace registration/ownership/scope and independently allocated UUIDv4 IDs. Reservation callbacks must reserve IDs atomically; collisions fail without retries or digest reuse. No production namespace registry or original-occurrence persistence exists in this module.
- Corrected configured AI daily USD reservations to sum the same daily estimates used at admission. Validate estimates before arithmetic so negative/nonfinite values cannot alter reservations. No numerical defaults, monthly cap, top-up, provider or paid fallback was added.
- Exercised SQLite's online backup API using disposable synthetic v1 databases. Restoring the checkpoint preserves complete logical contents, original ingestion provenance, legacy hash values/IDs, revisions, current candles, schema version and integrity even after the original is changed.

## Executed checks

| Check | Exact result / evidence |
|---|---|
| Backend baseline before changes | 196 passed in 5.41s; dependency consistency passed |
| Canonical primitive focused suite | 97 passed; covers strict input, numeric lexemes, all five bounds, normalization, Unicode, timestamps/overflow and schema rules |
| Digest focused suite | 48 passed; includes independently constructed frame bytes, metadata/registry failures and raw tamper/reference verification |
| AI infrastructure focused suite | 42 passed in 0.50s, including 14 new regression cases; six regressions failed before the safeguard fix |
| Synthetic backup/restore focused test | 1 passed, 75 deselected in 1.04s |
| Identity allocation focused suite | 9 passed in 0.06s; reservation, immutable ownership/scope, unknown categories, independent IDs and forced collision checks |
| Final backend `.venv/bin/python -m pytest` | **365 passed in 5.93s** on Python 3.13.13 / pytest 9.2.0, Android |
| Backend `.venv/bin/python -m pip check` | **No broken requirements found** |
| Frontend `npm run typecheck` | Passed |
| Frontend `npm test` | **15 passed, 0 failed**; SSR section/navigation/control tests, timeframe/IANA/DST, chart lifecycle and health transport/validation/deadline/cancellation |
| Frontend `npm run build` | Passed; 2133 modules; main JS 242.45 kB, lazy chart 194.80 kB, CSS 15.56 kB before gzip |
| Real independent startup | Backend `127.0.0.1:8000`; frontend development `127.0.0.1:5173`; built preview `127.0.0.1:4173` started successfully |
| Real HTTP / integration | Direct backend health, development HTML, development health proxy and built preview/health proxy passed; OpenAPI application paths remain exactly `/health` |
| Failure / recovery | Terminated only the backend process started by this run; actual frontend health client rejected the outage while frontend HTML stayed available; restarted backend and verified development/preview health recovery |
| Source protection / dependency versions | Original external backup hashes verified; all preserved files remain present; frontend package/lock hashes unchanged; no installs or dependency changes |
| Graph maintenance | `graphify update .` passed after final source changes, AST only, no LLM: 1083 nodes / 2993 edges / 67 communities |

One initial canonical test asserted a fixed JSON nesting rejection depth. Python 3.13's C decoder did not reject that depth. The test assumption was removed; no new production nesting limit was selected. The parser still translates actual recursion failures into its typed error. The final combined suite passed after that correction.

Graphify reported missing `tree_sitter_sql`, skipped unsupported extensions including CSS, and no symbols for the frontend SSR test file. No dependency was installed. SQL/CSS/test behavior was inspected directly where relevant. The AST update does not semantically index the newly written documentation; direct documents remain the normative source.

## Verification limits and release gates

- No browser executable/tool was available. SSR/control callbacks, chart mocks, CSS review and HTTP startup do not verify real canvas, touch interactions, viewport rendering, keyboard focus/zoom or screen-reader behavior. Actual Android/mobile and desktop responsiveness remains to be exercised.
- No production or existing local market database, WAL/journal, credentials, provider logs or captured provider evidence was opened. The backup regression uses exclusively synthetic temporary databases; it does not prove deployed data recovery or authorize a migration.
- No live market, macro/news/calendar or AI endpoint was called. Provider entitlement, TLS/provider behavior, AgentRouter/model support and evidence permissions remain unverified. Mock/synthetic success is not end-to-end provider acceptance.
- No target production archive schema/migration, production load, Android background persistence or operational deployment was tested. Synthetic SQLite writer contention and crash/recovery were tested only in temporary databases. Existing v1 persistence is not a canonical immutable archive.
- The configured AI safeguards remain in memory and depend on estimates/provider-reported usage; the fix does not create a durable daily ledger or guarantee actual billed cost.
- Provider-specific eligibility evidence, raw capture-profile boundaries, production registry ownership, freshness/lookback, operational recovery settings and cutover remain open. DEC-04 and H4-03 remain deferred. No production digests, historical provenance upgrades, trading endpoints, commits, push or publication occurred.

## Protection and rollback

The preserved original source/docs/graph files and SHA-256 manifest are outside the workspace at `/data/data/com.termux/files/home/project-backups/XAUUSD_AI_analyst/20261118T142244Z-je7xyryp`. Git is still an untracked baseline; do not use reset/checkout/clean or indiscriminate staging to roll back.

For a deliberate source rollback, first preserve the current changed files separately, then restore only explicitly chosen files from that backup. Archive the new canonical/health source and tests and three new documentation records separately. No database rollback is required for this checkpoint because no existing database or schema was changed. Rebuild the frontend and rerun required backend/frontend checks after any rollback; regenerate the graph from the retained source.

The master tracker records verified work, remaining dependencies and activation gates. Complete application acceptance remains outstanding.

## 2026-11-18 isolated contract and archive follow-up

`backend/app/data/evidence_contracts.py` defines 14 versioned canonical object schemas, 12 structured profile/domain registrations and 13 identity namespaces for isolated use. A deterministic five-timeframe manifest vector pins canonical bytes and its framed SHA-256 digest. Negative tests cover missing/unknown fields, duplicate or incomplete timeframe membership, reused retrievals, invalid generations/ranges and duplicate revisions. These registrations are not imported into the service or archive.

`backend/tests/test_archive_prototype.py` now contains 13 disposable SQLite cases. Added coverage proves two partial retrievals cannot be stitched or used as fallback, delayed older retrievals cannot roll back a generation, manifests keep exact immutable generation snapshots after later promotion, and a second writer respects the transaction lock with an explicit test-only busy timeout.

Exact checks run: `backend/.venv/bin/python -m pytest tests/test_evidence_contracts.py tests/test_archive_prototype.py -q` — **24 passed**; `backend/.venv/bin/python -m pytest` — **443 passed in 6.97s**; `backend/.venv/bin/python -m pip check` — **No broken requirements found**. Provider terms/attribution/freshness/completeness gates are documented in the architecture closure. No provider is certified eligible and no live service/database was used.

## Approved policy response and isolated archive prototype

The user's 2026-11-18 decision response approved P-01 through P-07. Exact retention classes are raw provider body 30 days, rejected/malformed row 90 days, duplicate occurrence 90 days, and AI prompt/response 30 days. Payload retention requires provider permission and a credential-free capture assertion; denied or unclear permission stores no payload and retains only allowed audit metadata. DEC-04 resource-limit values and H4-03 production policy remain deferred. P-06 authorizes design and disposable synthetic rehearsal only; the v1 database was not opened or migrated.

`backend/app/data/archive_prototype.py` is explicitly isolated and is not imported by the service. It creates only a new `.synthetic.sqlite3` file with a schema marker, SQLite WAL and FULL synchronous mode. BLOB bytes and retention metadata share a row and transaction. Each instance owns one connection and writes under `BEGIN IMMEDIATE`; the disposable harness requires an explicit busy-timeout setting. Retrievals require verified completeness evidence before generation promotion. Manifests require all five timeframes and bind exactly one current whole retrieval per timeframe to exact ranges and revisions. Append-only invalidation blocks new analysis inputs and flags historical analyses without rewriting them.

The isolated `evidence_contracts.py` defines 14 schemas, 12 structured profile/domain registrations and 13 identity namespaces. Its deterministic manifest test vector pins canonical bytes and framed SHA-256; negative cases reject incomplete or reused lineage and invalid fields/ranges. Fourteen archive tests cover retention, provider-bound completeness evidence, no partial stitching/fallback, generation fencing/snapshots, invalidation, transaction recovery, two-connection writer contention and overwrite protection. The full backend suite passed **443 tests** in 6.97 seconds; `pip check` found no broken requirements.

Provider-specific terms, attribution, freshness and completeness evidence, raw capture boundaries, production registry ownership, operational recovery choices, deterministic replay parameters and separate authorization for live providers/spending/production services/real database migration remain outstanding. DEC-04 and H4-03 remain deferred. No production database was accessed and no production profile was activated.

## 2026-11-18 synthetic provider contract follow-up

Added `backend/app/data/provider_contracts.py` with isolated `xau.provider-eligibility.v1` and `xau.retrieval-completeness.v1` contracts. Eligibility requires affirmative evidence with authoritative reference and review time for every gate. Completeness validates supported intervals, freshness, requested range, provider/instrument identity, ordered cursor chain, timestamp validity, and duplicate/conflicting observations. It is explicitly not connected to any provider or runtime intake and cannot prove upstream omissions absent or account permission.

`backend/tests/test_provider_contracts.py` covers fully evidenced/unknown/denied eligibility, valid and broken pagination, duplicate/conflicting records, invalid timestamps, stale retrieval, provider mismatch and unsupported intervals. The positive retrieval state is named `page_chain_complete` to avoid implying source-range completeness. Existing synthetic archive tests cover permission denial, expiry, revisions/invalidation, database recovery and concurrency. Exact results: focused provider/archive/ingestion checks — **69 passed in 2.41s**; latest full backend — **451 passed in 10.52s**; backend `pip check` — **No broken requirements found**; frontend `npm run typecheck` — passed; `npm test` — **15 passed, 0 failed**; `npm run build` — passed. `graphify update .` refreshed the AST graph (1,214 nodes, 3,384 edges).

Twelve Data and SiftingIO remain **UNVERIFIED** because account/order-form and upstream rights, retention and external-inference scope are not established. No live provider request, external AI request, existing database access, production activation, browser/device check or production-load test occurred. Synthetic correctness does not establish production readiness.

## 2026-11-18 Stages B-D synthetic implementation

Stage B adds an explicit canonical raw-digest-metadata schema (byte reference/length, profile, representation and digest), expanding the isolated schema/profile/namespace catalogs to 15/13/13. A frozen `DerivedManifest` now validates algorithm/version, policy, parameter digest, input manifest identity/digest and output schema, with canonical serialization and registered framed hashing. Existing synthetic SQLite tests continue to cover input manifest immutability, whole-retrieval generation fencing/promotion, invalidation propagation, rollback/reopen, abrupt process recovery and two-connection writer contention. Derived manifests are not yet durably persisted or wired to analysis output. Provider-specific raw capture profiles and production registry ownership remain open.

Stage C now selects only candle rows belonging to the latest whole completed retrieval attempt. A newer pending, failed or incomplete retrieval yields no usable candles; older records cannot be silently stitched or used as fallback. Expected openings are enumerated inside the selected requested range without fabricating bars. Candle evidence carries retrieval and content-revision lineage. UTC alignment and exact duration are validated for each declared timeframe. H4 is now explicitly unsupported in the ingestion/evidence path; the prior H1-to-H4 production-capable aggregation implementation was removed while H4-03 remains deferred. 1M is unsupported by the current packet/store timeframe contract.

Stage D documents algorithm v1 parameters, method IDs, input gates and unavailable conditions in `docs/DETERMINISTIC_ANALYSIS_CONTRACT.md`. It adds swing-cluster support/resistance, VWAP only for complete exchange-traded/contract volume, ATR-relative volatility, ten-interval close momentum and partial-aware multi-timeframe EMA alignment. Strictly out-of-order inputs are invalidated and excluded. Synthetic fixtures cover edge cases and provenance.

Exact verification after these changes: focused AI/analysis/ingestion/evidence-contract tests — **115 passed in 2.63s**; full backend `backend/.venv/bin/python -m pytest` — **459 passed in 9.87s**; `backend/.venv/bin/python -m pip check` — **No broken requirements found**; frontend `npm run typecheck` — passed, `npm test` — **15 passed, 0 failed**, `npm run build` — passed. `graphify update .` completed with 1,237 nodes and 3,424 edges. Browser/device rendering and production-load/recovery acceptance remain unverified.

## 2026-11-18 synthetic derived-manifest persistence follow-up

Added `backend/app/analysis/provenance.py`, extending the existing isolated canonical evidence contracts and `SyntheticArchive`. Input manifests are persisted as canonical payloads with framed digests. Analysis output uses `xau.analysis-output.v1`; the existing derived-manifest contract is extended as `xau.derived-manifest.v2`, while v1 remains available for historical verification. The derived record binds input/output IDs and digests, selected retrieval/revision IDs, algorithm/version, parameter context, policy, timeframe/window, creation time, schema IDs, canonicalization profile/framing, and unavailable timeframe states.

`SyntheticArchive.persist_provenance` re-parses and verifies both canonical payloads, checks cross-record links and the input-manifest digest, rejects invalidated inputs, then stores the immutable output/manifest pair in one transaction. Exact pair replays are idempotent; identity reuse with changed content fails. Synthetic tests cover repeatable digests, changed revisions and algorithm versions, lineage mismatch rejection, invalidation warnings for historical outputs, explicit unavailable H4 state, transaction rollback and process-crash recovery without orphaned records.

Exact verification from this repository:

- `backend/.venv/bin/python -m pytest` (in `backend/`) — final run after naming the extension as derived-manifest v2 **464 passed in 41.39s**.
- `backend/.venv/bin/python -m pip check` (in `backend/`) — **No broken requirements found**.
- `npm run typecheck` (in `frontend/`) — **passed**.
- `npm test` (in `frontend/`) — one parallel run hit a Node spawn timeout under resource contention; serial rerun **15 passed, 0 failed**.
- `npm run build` (in `frontend/`) — **passed**, Vite transformed 2,133 modules.

This verifies synthetic provenance only. The archive remains disconnected from the application; no existing/production database was accessed or migrated, and no provider or AI call was made. Provider account/upstream permissions, production registry ownership, raw capture profiles, freshness/lookback policy, SQLite operating limits/recovery targets and migration/cutover remain open. DEC-04 and H4-03 remain deferred.

## 2026-11-18 registry, SQLite, capture and freshness follow-up

Implemented an isolated append-only registry prototype with scoped registrar authorities, compare-and-swap version allocation, canonical framed entry digests, cross-registry reference checks, historical lookup, deprecation and terminal invalidation. The synthetic registry is not connected to the application and is not the production registry source. `docs/REGISTRY_OWNERSHIP_AND_VERSIONING.md` inventories current registries and proposes a versioned reviewed source bundle plus rebuildable index. Production trust-anchor and accountable release authority remain undecided; no human owner is inferred.

Added permission-gated capture profiles for raw bytes, parsed rows, normalized observations, rejected rows, duplicate occurrences, derived inputs and AI prompts/responses. Provider rights and provider-defined retention terms gate enabled status; Twelve Data and SiftingIO remain UNVERIFIED. Added a versioned fail-closed freshness evaluator which independently considers event age, publication delay and retrieval delay, plus completeness, permission, conflict, calendar evidence, timeframe and explicit fallback policy. Missing numerical policy evidence yields unavailable; H4 remains deferred by H4-03.

SQLite operational tests cover WAL/FULL settings, concurrent reader snapshot with writer/checkpoint, lock timeout with explicit caller retry, abrupt termination before compound writes to evidence/manifests/invalidation, simulated SQLITE_FULL, integrity and foreign-key checks, and online backup/restore. A five-run disposable workload executed 342 transactions per run: median 1.166083 seconds, minimum 0.376725 seconds, maximum 1.629566 seconds; median database size 1,060,864 bytes, page allocation 1,085,440 bytes, and active WAL 4,128,272 bytes. Environment: Python 3.13.13, Termux/Android 17 aarch64, SQLite 3.53.2. Exact device, storage medium, device load and power-loss characteristics are unknown; these are reproducibility observations, not production capacity evidence.

Exact verification commands and results:

- From `backend/`: `.venv/bin/python -m pytest tests/test_registry_prototype.py tests/test_capture_contracts.py tests/test_freshness_policy.py tests/test_sqlite_operational.py tests/test_analysis_provenance.py tests/test_archive_prototype.py tests/test_evidence_contracts.py -q` — **51 passed in 3.62s**.
- From `backend/`: `.venv/bin/python -m pytest` — **484 passed in 11.49s**.
- From `backend/`: `.venv/bin/python -m pip check` — **No broken requirements found**.
- From `frontend/`: `npm run typecheck` — **passed**; `npm test` — **15 passed, 0 failed in 7.31s**; `npm run build` — **passed** (Vite 8.3.8, 2,133 modules; Vite build phase 2.04s). `npm run typecheck` passed (about 6s wall time from the command session; TypeScript does not report its own duration).
- From repository root: `backend/.venv/bin/python -m app.data.sqlite_workload` (working directory `backend/`) — five runs above.

Synthetic registry invariants and recovery tests pass. Production registry release, provider capture eligibility, numeric freshness thresholds, SQLite timeout/checkpoint/size/backup targets and power-loss acceptance remain unresolved. No provider/AI calls or production database operations occurred. DEC-04 and H4-03 remain deferred.

## 2026-11-18 synthetic macro, analyst and dashboard follow-up

Stage E adds `backend/app/data/context.py`: immutable versioned event, macro observation, news and sentiment contracts; separate scheduled and published event values; per-record revisions; attributed source states; explicit whole-feed completeness evidence; caller-supplied retrieval-age/publication-delay limits; exact duplicate collapse; conflicting-news state; and fail-closed unavailable/unverified/incomplete/stale states. No live source is connected and source statuses remain unchanged. BLS CPI and Board-authored Fed content remain conditionally eligible only; other proposed feeds remain unverified as documented in the source eligibility assessment.

Stage F adds `backend/app/ai/analyst.py`. It requires a caller-supplied immutable manifest-pair verifier, consumes deterministic analysis and the context snapshot, binds input/derived manifest digests and provider/model/request/prompt/config metadata, and accepts completion only through an injected function. It does not instantiate a transport or make network requests. Its versioned response envelope contains bullish/bearish scenarios, neutral conditions and context-cited interpretations. Technical output uses the existing response validator; context citations must resolve to available feeds; scenario numeric values must match referenced records. Insufficient market evidence returns deterministic NO TRADE without invoking completion. Invalidations block new manifest verification while historical provenance warnings remain available.

Stage G adds a validated, opt-in frontend `DashboardAnalysis` fixture view. The regular dashboard remains unavailable and has no analysis endpoint; the fixture is never inserted into the market chart or shown as live. It displays manifest IDs, missing market price, all five supported contract timeframes, explicit H4-03 and 1M warnings, scenarios, evidence quality and unavailable context. This is a presentation-contract preview only, not backend API integration.

Exact latest verification:

- From `backend/`: `.venv/bin/python -m pytest tests/test_macro_context.py tests/test_ai_evidence.py tests/test_analysis_provenance.py -q` — **42 passed in 1.33s**.
- From `backend/`: `.venv/bin/python -m pytest` — **499 passed in 8.94s**.
- From `backend/`: `.venv/bin/python -m pip check` — **No broken requirements found**.
- From `frontend/`: `npm run typecheck` — **passed**; `npm test` — **16 passed, 0 failed in 3.93s**; `npm run build` — **passed**, Vite 8.3.8 transformed 2,136 modules and built in **1.22s**.

At the Stage E-G follow-up recorded above, the complete synthetic backend archive-to-analyst workflow was verified for an insufficient-evidence path, including unavailable macro/news and post-generation invalidation; dashboard projection was not yet connected at that point. The subsequent immutable projection integration is recorded below. No external market-data/AI requests, production database access, migration, activation or spending occurred. Production source permissions and feed completeness, live model authorization, registry authority, SQLite deployment targets and production recovery remain unresolved. DEC-04 and H4-03 remain deferred.

## 2026-11-18 immutable analysis projection integration

Added `backend/app/analysis/projection.py`, a read-only, transaction-scoped projection that verifies the existing canonical input-manifest, analysis-output and derived-manifest digests and identity links, selected retrieval/revision sets, XAUUSD packet and invalidation history. It projects only display-required deterministic evidence and provenance fields; provider/source details and candles are omitted. The projection issues only SELECTs within its own SQLite read snapshot and always rolls it back. Synthetic tests prove row snapshots are unchanged, active caller transactions are rejected, read-only SQLite writes fail, and missing records, malformed payloads, digest mismatches and linkage mismatches fail closed.

Added `GET /api/v1/analysis/{analysis_id}` with version `xau.dashboard-analysis.v1`. The route only accepts an immutable output ID; there is no `latest`, promotion, analysis execution or write path. The service has no archive configured and defaults to 503. Tests inject a read-only disposable synthetic archive and exercise the real route over loopback Uvicorn; unknown IDs return 404 and provenance errors return 409. API responses explicitly identify `synthetic_archive`, source eligibility as unverified and freshness as unassessed. H4/1M support state, macro/news absence and historical invalidation are carried explicitly.

The React workspace now offers immutable-ID lookup through the Vite loopback proxy and renders the API response identity and provenance. Malformed payloads, 404/503/backend errors and historical invalidation are visible. The persisted deterministic evidence is rendered as archived evidence; no price chart or bias is derived. The existing local fixture remains a separate opt-in development view. The archive still does not persist an AI analyst report, so the API truthfully reports `analyst_outcome: unavailable`.

Exact verification:

- From `backend/`: `.venv/bin/python -m pytest tests/test_analysis_projection.py -q` — **11 passed in 2.02s**.
- From `backend/`: `.venv/bin/python -m pytest` — **510 passed in 13.54s**.
- From `backend/`: `.venv/bin/python -m pip check` — **No broken requirements found**.
- From `frontend/`: `npm run typecheck` — **passed**.
- From `frontend/`: `npm test` — **18 passed, 0 failed in 6.51s**.
- From `frontend/`: `npm run build` — **passed**, Vite 8.3.8 transformed 2,138 modules and built in **0.79s**.

This verifies the isolated synthetic archive → real local HTTP endpoint → frontend contract/rendering path, not production readiness. No production database, live provider, external AI, migration, service activation or spending was used. Production archive access/ownership, source permissions and freshness policy remain unresolved; immutable AI response persistence remains the next implementation milestone. DEC-04 and H4-03 remain deferred. No browser/device verification was performed.

## 2026-11-18 immutable synthetic AI report persistence (Stage F.2)

Extended the isolated evidence schema/profile/namespace catalog with versioned AI prompt, request, response and report schemas. Synthetic archive schema v3 adds immutable AI request/response/report tables with foreign keys and append-only triggers; creation remains new-file-only and performs no migration. `backend/app/ai/persistence.py` runs only the existing injected completion boundary, binds the exact prompt and provenance, records failed/rejected states without successful reports, and atomically stores complete or insufficient-evidence results. Prompt and records use the existing canonical JSON profile and framed digest codec. Metadata and persisted prompt/result text reject credential-like content. Exact replays are idempotent; identity/content conflicts are rejected.

The read-only projection now verifies AI request, response, report and prompt digests; all links to the input manifest, deterministic output and derived manifest; provider/model/prompt references; AI status; and, for complete reports, deterministic evidence and scenario citations. It preserves a historical report with invalidation warnings. The real local `GET /api/v1/analysis/{analysis_id}` path was exercised with read-only SQLite storage and returned the exact persisted insufficient-evidence report. The frontend validates and renders that stored identity, status, NO TRADE conclusion, provenance and synthetic-only warning.

Exact verification:

- From `backend/`: `.venv/bin/python -m pytest tests/test_ai_report_persistence.py tests/test_analysis_projection.py tests/test_ai_evidence.py -q` — **53 passed in 10.73s**.
- From `backend/`: `.venv/bin/python -m pytest -q` — **521 passed in 17.36s**.
- From `backend/`: `.venv/bin/python -m pip check` — **No broken requirements found**.
- From `frontend/`: `npm run typecheck` — **passed**.
- From `frontend/`: `npm test` — **20 passed, 0 failed in 6.88s**.
- From `frontend/`: `npm run build` — **passed**, Vite 8.3.8 transformed 2,138 modules; build completed in **0.91s**.
- From repository root: `. .venv-graphify/bin/activate && graphify update .` — **completed**, 1,551 nodes and 4,628 edges.

This verifies the synthetic persisted-input → deterministic-analysis → AI request/response/report → read-only HTTP → frontend path for both a complete synthetic response and an insufficient-evidence outcome, plus failure/rejection, rollback, process termination recovery, exact replay, changed-content collision and invalidation handling. It does not verify an actual external model response, live provider eligibility, production service/storage, target hardware recovery, or browser/device rendering. No production database, provider, AI API, migration, activation or spending was used. Twelve Data/SiftingIO and other providers remain unverified; production registry authority and SQLite targets remain unresolved. DEC-04 and H4-03 remain deferred.

## 2026-11-18 Stage B release readiness update

Added `REGISTRY_RELEASE_SCHEMA` and a `registry.release` digest registration. The synthetic registry exports a transactionally consistent immutable bundle with a content-derived release identity, exact entries and lifecycle history, previous-release reference, registrar and approval-reference metadata. Verification checks canonical schema/profile/framing and identity. Reconstruction is restricted to an empty isolated catalog and transactionally validates entry digests, version chains, registry references and lifecycle foreign keys. This tests recovery mechanics only; the release approval reference is not an organizational/human authorization, and no production signature/trust anchor exists. No production registry release is enabled.

Freshness inputs now carry explicit invalidation state, which yields `evidence_invalidated`. Synthetic policy tests also cover closure/holiday evidence and absent timeframe thresholds; none add a production numerical default. `SQLITE_OPERATIONAL_READINESS.md` now documents monitoring, typed failure behavior, backup/restore and recovery requirements. Candidate WAL/FULL policy remains unselected for production; prior local workload measurements are not extrapolated.

The real loopback development workflow was started: frontend shell and app module returned 200, Vite's backend health proxy returned 200, and the analysis endpoint returned 503 as designed without an injected archive. Browser automation was unavailable; no visual browser/mobile/device verification was performed.

Exact verification for this update:

- From `backend/`: `.venv/bin/python -m pytest tests/test_registry_prototype.py tests/test_freshness_policy.py tests/test_sqlite_operational.py -q` — **20 passed in 1.23s**.
- From `backend/`: `.venv/bin/python -m pytest -q` — **524 passed in 18.30s** (final run after release replay coverage).
- From `backend/`: `.venv/bin/python -m pip check` — **No broken requirements found**.
- From `frontend/`: `npm run typecheck` — **passed**.
- From `frontend/`: `npm test` — **20 passed, 0 failed in 7.76s**. Nonfatal Vite HMR WebSocket port 24678 warning; no test failures.
- From `frontend/`: `npm run build` — **passed**, 2,138 modules transformed; 1.41s Vite build.
- Loopback HTTP smoke: frontend shell 200; app module 200; backend health 200; unavailable projection 503 — **all assertions passed**.
- `. .venv-graphify/bin/activate && graphify update .` — completed, **1,573 nodes and 4,684 edges**.

Current release-readiness classification and required owner decision are consolidated in `docs/RELEASE_READINESS_ASSESSMENT.md`. No live provider/AI calls, production database/migration, production activation/deployment, spending or trading occurred. Provider statuses are unchanged, no provider is ELIGIBLE, DEC-04 and H4-03 remain deferred.


## 2026-11-19 synthetic registry approval and governance verification

The isolated registry now has versioned approval/signing schemas registered in the existing evidence contract catalog. Approval signing binds the exact release ID/digest, registry/version/predecessor, preparation registrar, approver/key identity/version, timestamp, decision, compatibility metadata, canonicalization profile and framing version. The signature excludes itself; a separate full-record digest includes it. An injected verifier is used, with HMAC-SHA256 fixtures exclusively in tests. `SyntheticRegistry` schema v3 stores approval and revocation history append-only and checks replay identity, approved-version progression, predecessor/head, registrar scope, self-approval, release/key revocation and record integrity. This is not production signing or activation; synthetic revocation actor authorization is injected and not cryptographically authenticated.

Tests cover valid and invalid signatures, digest tampering/mismatch, unknown key/registrar, self-approval, revoked/expired/superseded key behavior, rotation, rollback/version mismatch, exact replay, revocation history and process termination before transaction commit. Production Ed25519 support, key enrollment, signed revocations, transparency/checkpoint storage and release publication are not implemented. The proposed Ed25519 profile and custody plan are marked **PROPOSED — AWAITING PROJECT OWNER REVIEW** in `REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md`.

Exact verification:

- From `backend/`: `.venv/bin/python -m pytest tests/test_registry_approval.py tests/test_registry_prototype.py tests/test_evidence_contracts.py -q` — **26 passed in 0.74s**.
- From `backend/`: `.venv/bin/python -m pytest -q` — **532 passed in 24.56s**.
- From `backend/`: `.venv/bin/python -m pip check` — **No broken requirements found**.
- From `frontend/`: `npm run typecheck` — **passed**.
- From `frontend/`: `npm test` — **20 passed, 0 failed in 7.96s**; nonfatal HMR WebSocket port 24678 conflict warning.
- From `frontend/`: `npm run build` — **passed**, 2,138 modules; 1.54s.

No production trust-anchor was generated or activated, no registry released, no production database accessed, and no provider/AI call, migration, deployment or spending occurred. DEC-04 and H4-03 remain deferred.

## 2026-11-20 B1 personal market-data pipeline follow-up

The existing `MarketDataPipeline` and deterministic `analyze_packet` path were reused. Its convenience `analyze()` call now requests Daily, 1H and 15M by default—the user's priority set—rather than requiring unsupported H4 and lower-priority 5M as part of that default. Callers may request another supported analysis set explicitly. The shared builder still labels H4 unsupported; no H4 aggregation or production rule was added. Existing SiftingIO interval support remains 5M, 15M, 1H and 1D only; 1M is unsupported. Internal candle instants remain UTC; the existing frontend's display default is `Asia/Qatar`.

No source or account was activated. The 2026-11-20 official documentation recheck is recorded as a status-preserving addendum in `AUTHORITATIVE_MARKET_DATA_SOURCE_ELIGIBILITY.md`: Twelve Data's documented plan gates and SiftingIO's current product/terms evidence still do not establish this account's entitlement, raw/normalized retention or external-AI processing rights. Both remain **UNVERIFIED**. BLS, Federal Reserve, Treasury, DXY, calendar, news and sentiment eligibility remains as recorded in the source assessment. There is consequently no verified current price or directional conclusion; the existing pipeline returns unavailable/NO TRADE on missing, incomplete, stale or otherwise insufficient evidence. Complete synthetic evidence can exercise deterministic calculations, but is not market analysis and is not presented as live.

Verification from `backend/`:

- `.venv/bin/python -m pytest tests/test_siftingio_ingestion.py tests/test_analysis_engine.py -q` — **82 passed in 2.45s**.
- `.venv/bin/python -m pytest -q` — **547 passed in 20.37s**.
- `.venv/bin/python -m pip check` — **No broken requirements found**.
- From repository root, `. .venv-graphify/bin/activate && graphify update .` — completed, **1,743 nodes / 5,298 edges**.

No frontend files or shared frontend contracts changed; frontend suites were not rerun. No provider/AI calls, production database access, migration, activation, spending, trading, commit or push occurred. H4-03 and DEC-04 remain deferred.
