# Read-only dashboard analysis projection

Status: **VERIFIED for isolated synthetic archive-to-HTTP-to-frontend integration, including immutable AI report retrieval. Production archive connection and live AI response are NOT IMPLEMENTED.**

## Contract

`GET /api/v1/analysis/{analysis_id}` returns `xau.dashboard-analysis.v1` for one immutable `analysis_outputs.output_id`. There is no `latest`, current-head, promotion, or analysis-generation route. The API projection returns the exact decoded `EvidencePacket` preserved in the existing `xau.analysis-output.v1` wrapper; it does not rerun calculations or write archive rows.

Before responding, `backend/app/analysis/projection.py` recalculates and checks the existing canonical framed digests for the input manifest, analysis output, and derived manifest. It verifies their IDs, linkage, selected retrieval/revision sets, selected retrieval existence/completeness, and the persisted XAUUSD packet. It reports invalidated revisions as historical warnings rather than hiding or rewriting old output. A missing or mismatched record fails closed.

The projection exposes only analysis/provenance fields, deterministic evidence, source attribution, timeframe availability, missing-input reasons, and freshness/eligibility state. Source eligibility is `unverified`; freshness is `unassessed` because no approved/evidenced freshness policy is bound to these persisted rows. It never exposes database paths, credentials or raw evidence. `1M` is explicitly unsupported; H4 is reported from the packet and remains unavailable under H4-03.

The versioned projection includes nullable `ai_report` data from immutable archive tables. It verifies request, response and report canonical digests, prompt digest, analysis/input/derived/output links and provider/model/prompt references before returning the stored `AnalystRun`. `analyst_outcome` is populated only for persisted `complete` or `insufficient_evidence` reports; failed or rejected requests remain explicit statuses without a report. Historical evidence invalidation is a warning and does not rewrite the stored report. Missing macro/news context remains explicit.

## Service boundary and UI

The production application has no archive configuration. The endpoint returns `503 analysis_projection_unavailable` unless an internal projection function is explicitly supplied. Synthetic integration tests inject a connection opened with SQLite `mode=ro`; attempts to write through it fail. The endpoint accepts an exact output identity only and maps missing identity to 404 and invalid provenance to 409.

The Vite development/preview proxy forwards `/api/v1/analysis/{id}` to the loopback backend. The dashboard requires a user-supplied immutable analysis ID, validates the response, and renders those same ID and digests. It shows a permanent `SYNTHETIC ARCHIVE · READ ONLY · NOT LIVE MARKET DATA` banner, persisted AI report identity/status, scenarios, provider/model and prompt version, historical invalidation warnings, unsupported timeframe states, source eligibility, freshness status, missing context and persisted evidence. API errors, malformed payloads, missing results and unconfigured backend remain unavailable states. The local synthetic preview remains a separate opt-in test view.

## Verification boundary

Tests use only disposable `.synthetic.sqlite3` archives and deterministic fixtures. The HTTP route was exercised on loopback with Uvicorn and a read-only SQLite connection. This verifies the synthetic projection, AI persistence and UI contract only; it does not establish a production schema, production database connection, provider eligibility, freshness, or live AI analysis. No production database, provider, AI service or migration is configured or accessed.
