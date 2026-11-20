# Stage 5E.1 — Ingestion Integrity & Failure Safety

## 1. Executive summary

Historical SiftingIO pages are now staged under an explicit retrieval ID. A retrieval is promoted to current candle observations only after all pages pass validation and pagination reaches a verified terminal state. Failed, incomplete, pending, and unknown retrieval states fail closed in evidence construction and produce `NO TRADE — DATA NOT VERIFIED`.

Request attempts retain a hashed request identity and a terminal outcome. Provider tick-count semantics and the unverified-range warning survive into Stage 5C/5D evidence. Persistence independently validates the page and candle identity, interval, range, timestamps, and OHLC.

No database migration was needed. Existing SQLite tables store retrieval metadata in ingestion JSON and quality reports; candle history remains append-only. No live request, external service call, or AI inference was made in this phase.

## 2. Original Stage 5E audit findings addressed

- Later-page failures can no longer promote earlier pages to `current_candles`.
- Rejected pagination is not persisted as current data; staged pages from failed batches remain historical diagnostics only.
- Evidence construction checks the latest retrieval status for each requested interval. Missing status is treated as unknown and fails closed.
- Request ledger entries now move from `started` to a recorded success/failure outcome.
- `unusual_tick_count_range_unverified` is retained on evidence candles and in sufficiency warnings. Tick-count observations are not used as traded volume or spike signals.
- SiftingIO persistence revalidates incoming pages independently of the HTTP adapter.
- The default HTTPS transport’s redirect behavior is documented accurately and covered with a mocked 302 response.

## 3. Files modified

- `backend/app/data/ingestion.py`
- `backend/app/data/siftingio.py`
- `backend/app/data/quota.py`
- `backend/app/data/storage.py`
- `backend/app/data/contracts.py`
- `backend/app/ai/evidence.py`
- `backend/app/analysis/engine.py`
- `backend/tests/test_siftingio_ingestion.py`
- `docs/MILESTONE_5E.md`
- `docs/MILESTONE_5E_1.md`
- `graphify-out/graph.json`, `graphify-out/graph.html`, and `graphify-out/GRAPH_REPORT.md` were refreshed because `AGENTS.md` requires `graphify update .` after code changes.

## 4. Retrieval-completion model

`RetrievalStatus` defines `pending`, `complete`, `incomplete`, and `failed`; a missing or invalid stored value resolves to unknown. A retrieval ledger entry records its ID, interval, range, start time, and final status. Each page ingestion carries the retrieval ID and its own pagination metadata.

Each candle observation is validated and appended to `candle_records`, but it does not become current while its batch is pending. Finalization rechecks that pages belong to the same interval and requested range, all page pagination states are verified, cursors do not repeat, page order is monotonic, openings do not overlap, and the final page has no cursor. Only then does one SQLite transaction mark the retrieval complete and promote newer observations. Existing current observations are not replaced by an incomplete or failed batch.

No page or candle validity is used as a substitute for retrieval completion. Legacy observations with no completion ledger status remain readable in history but are not considered verified analysis input until a successful retrieval status exists.

## 5. Pagination failure behavior

Each page is checked before staging. Repeated cursors, loops, overlaps, out-of-order data, an empty page with a cursor, an unverified page, and a page limit reached with a remaining cursor terminate the operation as incomplete. Provider, timeout, network, persistence, and unexpected exceptions mark the retrieval failed when the store is available. The client does not retry.

If a later request fails, earlier staged candles remain append-only diagnostic observations, while the previous completed current dataset remains unchanged. The latest retrieval status is failed/incomplete, so evidence is insufficient even when older complete candles remain available.

The adapter retains the existing short-page terminal policy: a short page without a cursor is accepted as terminal; a full page without a cursor is unverified. This policy is tested offline and remains dependent on the provider’s pagination contract.

## 6. Persistence isolation behavior

`persist_sifting_page` revalidates the `Page` and each `NormalizedCandle`, checks SiftingIO/commodities/XAUUSD identity, expected interval, requested UTC range, page size, duplicate openings, UTC timestamps, candle boundaries, and OHLC. Page insertion and its quality report are transactional. Promotion, correction-history writes, and coverage refresh are transactional during retrieval finalization; incomplete batches leave prior current data and coverage intact.

Rejected pages are not promoted. Stale observations and revisions retain the existing append-only semantics. A database insertion failure leaves the prior current dataset intact; an associated pipeline retrieval is marked failed, or remains pending if the database itself prevents status recording. Pending status fails closed.

## 7. Request outcome tracking

Each HTTP attempt stores a hash of the request path/query and a request timestamp, never the API key, authorization header, full URL, or response body. The initial outcome is `started`; it is updated to `succeeded`, `provider_error`, `authentication_failure`, `quota_exhausted`, `rate_limited`, `timeout`, `network_error`, `invalid_response`, or `unexpected_error` as applicable. The request gate releases the active signature on all transport paths and no automatic retry is made.

## 8. Quality-warning propagation

The provider warning `unusual_tick_count_range_unverified` maps to `DataQualityFlag.UNVERIFIED_TICK_COUNT_RANGE`, remains attached to the Stage 5C evidence candle, and appears in sufficiency warnings. Volume evidence remains `tick_count` and receives insufficient quality for this field; price evidence is not downgraded solely because tick-count range is uncertain. No traded-volume spike is calculated from tick counts.

## 9. Database schema/migration impact

No schema or migration change was made. The repository has a version-1 schema guard and no separate migration framework. Retrieval IDs/statuses and request outcomes use existing `ingestions.request_json`, `ingestions.provenance_json`, and `quality_reports.report_json` fields. `schema.sql` and `PRAGMA user_version` remain unchanged. Tests used temporary SQLite databases only; no existing or production database was opened.

## 10. Backward compatibility

The Twelve Data adapter and its storage path were not changed. SiftingIO identity, Decimal normalization, UTC semantics, candle states, append-only observations, correction history, and 1H-to-4H aggregation rules remain in place. `DataQualityFlag` and `RetrievalStatus` gain values without removing existing contract values. The Stage 5D engine remains deterministic and does not call AI providers.

SiftingIO persistence now stages observations before current-pointer promotion. Callers that invoke `persist_sifting_page` directly get one-page completion only when the page is verified and terminal; a page containing a cursor remains ineligible for current observations.

## 11. Tests executed and exact results

- Focused SiftingIO, storage, and evidence test run: **154 passed** before final focused-only additions.
- Final focused SiftingIO ingestion run: **41 passed in 1.70s**.
- Full backend suite after final implementation changes: **196 passed in 5.16s**.
- Python compilation (`compileall` over `backend/app` and `backend/tests`): **passed**.
- Backend dependency consistency (`pip check`): **No broken requirements found**.
- Frontend TypeScript check (`npm run typecheck`): **passed**.
- Frontend tests (`npm test`): **9 passed, 0 failed**.
- Frontend production build (`npm run build`): **passed**.
- `git diff --check`: **no whitespace errors reported**. Project files are untracked in this workspace, so ordinary Git diff does not provide a tracked baseline.
- `graphify update .`: **completed**. Its SQL extraction warning reports that `tree_sitter_sql` is unavailable; no dependency was installed and schema inspection was done directly.

The tests use mocked transports and temporary SQLite files. No network-facing test or production database test was run.

## 12. Remaining limitations

- Request status is stored in JSON fields without database-level enum constraints. Application code validates statuses, but an out-of-band database writer could insert malformed values; unknown values fail closed.
- A process or storage failure that prevents final status persistence can leave a batch pending. Pending is deliberately treated as incomplete for evidence.
- Short-page termination remains based on the existing provider pagination assumption; provider contract changes would require revalidation.
- Mocked tests do not establish provider behavior, TLS operation against the live endpoint, production SQLite contention, Android/browser behavior, or production load safety.
- Historical data outside the requested interval is retained; this change does not add a market calendar or session completeness model.

## 13. Security and credential handling

No credentials were inspected or printed. Request ledger entries contain only a SHA-256 request identity and timestamps/outcome. Raw response bodies and auth headers are not persisted. Only local mocked transports were used; no SiftingIO, Twelve Data, AgentRouter, broker, or AI endpoint was contacted.

The default `http.client.HTTPSConnection` transport does not follow redirects. A mocked 302 test verifies the response is rejected without issuing a second request. The injected transport remains a test seam and is not used by the default live transport.

## 14. Rollback procedure

No database rollback or migration is needed. The application rollback is to restore the pre-Stage-5E.1 versions of the listed source and test files, and restore the prior `docs/MILESTONE_5E.md`; existing append-only SQLite rows can remain untouched. The Graphify outputs can be regenerated from whichever source state is retained.

The initial Git status showed the project tree as untracked, so `git checkout` or `git revert` cannot safely restore a tracked baseline in this workspace. Preserve the current files before any manual rollback.

## 15. Final readiness assessment

Stage 5E.1 meets its offline failure-safety criteria: incomplete or failed pagination cannot replace a completed current dataset or produce verified evidence; request outcomes are auditable; provider tick-count warnings remain explicit; and persistence checks its trust boundary. Backend and frontend verification passed.

This is **not a production-readiness claim**. No live provider behavior, production database, external service, credential, browser runtime, or production load was tested. Do not start Stage 5F or scheduled ingestion as part of this milestone.
