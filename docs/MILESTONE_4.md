# Milestone 4 completion — XAU/USD data foundation

Milestone 4 is complete as an offline backend library. User authorization supersedes the historical Milestone 1 boundary for this work. No live market observations, provider requests, subscription operations, credentials, AI integration, frontend changes, new dependencies, execution capabilities or broker connectivity were introduced. Stop here and wait for explicit Milestone 5 approval.

## Architecture, contracts and persistence

The updated [ARCHITECTURE.md](ARCHITECTURE.md) adds an isolated offline normalization → validation → SQLite flow; FastAPI retains its original health-only route/schema. [DATA_FOUNDATION.md](DATA_FOUNDATION.md) defines the typed v1.0 models, `td-xau-utc-v1` timeframe policy, `quality-v1` validation rules, decimal strings, source opening/retrieval provenance, qualified market identities and conservative pagination.

The serialization contract is [data-foundation.schema.json](data-foundation.schema.json). [schema.sql](../backend/app/data/schema.sql) initializes SQLite user_version 1 with eight tables: instruments, provider_series, ingestions, candle_records, current_candles, historical_revisions, quality_reports and coverage. Transactions, identity foreign keys and indexed UTC keys preserve observations and corrections. Synthetic/provider evidence cannot share a database. No database is opened during backend startup.

## Validation and adapter

Positive finite exact OHLC prices and low/open/close/high ordering are enforced. Missing/invalid/future/out-of-range timestamps and invalid/partial prices/volume are reported with retained supported source fields. Identical duplicates collapse with flags; conflicting duplicates are quarantined. Forming and unverified-boundary candles are excluded from default reads. Unverified cadence-gap candidates are reported without filling. Exact-rational 20% outlier heuristics flag and retain observations. Closed-candle numerical corrections link old/new history; older/equal retrievals cannot overwrite newer heads. Source values, timestamp representation/meaning and evidence fingerprints are validated before persistence.

`ProviderAdapter` / `TwelveDataAdapter` plan symbol/interval/range/limit parameters, interpret UTC source openings, normalize supplied public response objects, represent provider/shape errors and decide overlapping pagination. There is no HTTP transport. Short or empty pages do not prove complete history. Native payload details/range inclusivity still need verification during an explicitly authorized live milestone.

## Tests and results

| Check | Result / evidence |
| --- | --- |
| Full backend tests | **87 passed**, 3.51 seconds; `.milestone-4/backend-checks.log` |
| New offline tests | **75 passed**, 0.82 seconds; `.milestone-4/offline-tests.log` |
| Existing API/health regression | All 12 existing tests pass unchanged, including real loopback `/health`, `/openapi.json`, committed schema, route set, execution-endpoint absence, settings and native dependencies |
| Python dependencies | `pip check`: no broken requirements; `.milestone-4/dependency-check.log`; installed validated versions unchanged, `.milestone-4/installed-versions.json` |
| Python syntax | `compileall -q app tests`: passed; `.milestone-4/python-syntax-check.log` |
| Versioned data schema | Serialization snapshot matches models; decimal/UTC/identity/provenance corruption rejected by tests |
| SQLite | Reopened file round trips, preserved history/corrections, injected full-transaction rollback and unknown-schema preservation pass |
| Retained synthetic SQLite example | `integrity_check = ok`, no foreign-key violations; 2 ingestions, 6 observations, 3 current candles, 1 historical revision; `.milestone-4/sqlite-verification.json` |
| Frontend TypeScript | `npm run typecheck` passed; `.milestone-4/frontend-typecheck.log` |
| Frontend tests | All 9 unchanged tests passed; `.milestone-4/frontend-tests.log` |
| Frontend build | Passed; 2,131 modules, 732 ms; `.milestone-4/frontend-build.log`; output isolated in `.milestone-4/build/dist/` |
| Graph and preservation | AST refresh passed; 529 of 538 original files unchanged, 9 intentional architecture/graph changes, no missing or unexpected changes; `.milestone-4/graphify-update.log` and `preservation-and-security.json` |

Offline test cases cover every required interval, UTC/default-naive/offset timestamps, timestamp/domain precision, OHLC/volume constraints, forming/exact-close behavior, unresolved daily boundaries, identical/conflicting duplicates, unfilled missing-cadence candidates, outliers, historical corrections, source provenance/decimal scale, partial/invalid/empty data, response/page limits, stalled pagination, SQLite history/reopening/coverage, rollback, unknown schemas and public-field secret omission. Socket connection functions are blocked in the offline test module. Fixtures and the retained example are explicitly synthetic, not observations or captured Twelve Data responses.

Graphify emitted an SQL extraction warning because its existing `tree_sitter_sql` parser is not installed. No dependency was added. The SQLite DDL is exercised by the offline tests and integrity checks; SQL graph extraction and document semantic refresh were not performed. The required AST refresh produced 316 nodes and 765 edges without an API or LLM.

No Python static type checker is configured/installed for this project; syntax compilation and runtime Pydantic contract checks were exercised, and the frontend's configured TypeScript check passed. No compatible browser/canvas, production load/concurrency, Android background persistence, live provider compatibility/access or subscription entitlement was tested. Entry points were unchanged; existing regression tests start and stop the backend on a real loopback port.

## Files changed and preservation

Application files created:

- `backend/app/data/__init__.py`
- `backend/app/data/contracts.py`
- `backend/app/data/policy.py`
- `backend/app/data/validation.py`
- `backend/app/data/twelve_data.py`
- `backend/app/data/storage.py`
- `backend/app/data/schema.sql`

Tests/fixture created: `backend/tests/test_data_foundation.py`, `backend/tests/fixtures/synthetic_twelve_data.json`.

Documentation created: `docs/DATA_FOUNDATION.md`, `docs/data-foundation.schema.json`, `docs/MILESTONE_4.md`, `docs/MILESTONE_4_ROLLBACK.md`. Modified: `docs/ARCHITECTURE.md` by appending the current milestone section. The graph's existing public/hidden outputs are regenerated by the required installed tool. New verification, preservation and rollback evidence lives in `.milestone-4/`, including the pre-change architecture and graph copies. No existing application caller, export, settings, fixture, dependency lock or API schema needed changes.

All pre-existing milestone evidence and rollback documents are preserved by hashes. No separate 2.5 document was located in `docs/`; the preservation manifest covers every existing record regardless of name. No original support email was supplied or archived; only user-provided requirements and account/support context are recorded in DATA_FOUNDATION.md. Git remains uncommitted and no push/deployment occurred.

## Security review

The offline module imports no network client/transport, exposes no API endpoints, takes no API key and runs no AI/tools/trading/broker functionality. Existing backend startup validation still rejects undocumented key variables and loopback binding remains intact. SQLite schemas have no credential fields. Arbitrary extra envelope/row fields and provider error messages are omitted; tests prove a synthetic key sentinel cannot reach the database. Values remain public supported candle fields, with provenance/identity checks at the normalization/storage boundaries.

SQLite writes use bound values; internal SQL identifiers come from fixed implementation calls. Foreign keys, JSON validity, typed validation, schema-version rejection and atomic writes guard against accidental mixing or loss. Existing Git rules already ignore database files and sidecars. Synthetic fixtures are explicit, and mixed synthetic/provider ingestions fail. No dependency, lock, skills, hooks or preparation assets changed. These checks do not establish a production security/load review or validate the user's provider license independently.

## Rollback and remaining live integration

Follow [MILESTONE_4_ROLLBACK.md](MILESTONE_4_ROLLBACK.md): archive new files/databases, move the offline modules/tests/docs out, restore the saved architecture/graph, retain all earlier evidence and rerun the 12-test health baseline. No credentials, subscriptions or deployed service state need reversal; no schema downgrade or data deletion is performed.

Milestone 5 needs explicit approval. Remaining work includes verifying the original support/access conditions and usable subscription without automatic purchase; confirming real response shape, symbols/interval availability, decimal/timestamp/volume semantics, UTC daily rollover and any shortened intraday/calendar rules; verifying inclusive pagination/limits/empty-page behavior; and implementing approved backend-only secret configuration, HTTP transport, rate limits, timeouts/retries, controlled historical backfill, refresh/revision overlap and operational checks. First-class verified calendar/daily policies require a deliberate new policy version. Freshness/coverage expectations require verified trading rules. AI and frontend data integration remain separate scope; no execution or broker capabilities are permitted.
