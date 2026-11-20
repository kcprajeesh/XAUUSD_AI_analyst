# Health API

`GET http://127.0.0.1:8000/health` returns `200 OK`, content type `application/json`:

```json
{
  "status": "ok",
  "service": "XAUUSD AI Analyst",
  "timestamp": "2026-11-17T12:00:00Z"
}
```

The timestamp above is an illustrative format example, not market data. The actual value is generated in UTC for each response. `status` and `service` are fixed strings; `timestamp` is required and timezone-aware. Health confirms that this process can respond; it does not assert market availability or analyst readiness.

The committed [JSON response schema](health.schema.json) is checked against the running service's OpenAPI schema and real HTTP response. FastAPI exposes `/openapi.json`, `/docs`, `/docs/oauth2-redirect` and `/redoc` for documentation. `/execute` returns 404.

## Fail-closed backend startup (A0)

Ordinary backend import, startup and shutdown do not discover provider credentials, construct a provider client or ingestion pipeline, make provider/AI requests, or construct/open market storage. `SIFTING_API_KEY` in the environment or a private `~/.config/xauusd-ai-analyst/sifting.env` file does not enable ingestion. Startup does not create the market state directory or open `market.sqlite3`. Provider and storage libraries remain available only to explicitly invoked callers outside ordinary service startup; A0 adds no activation option.

`GET /api/v1/market-data/status` retains its existing response schema and SiftingIO source label, which identifies the contract rather than an active connection. It returns `analysis_available=false`, `analysis_status="NO TRADE — INSUFFICIENT EVIDENCE"`, `updated_at=null` and empty `sufficiency_statuses`. Daily/1H/15M targets remain 200/300/300; each frame has zero actual candles, `retrieval_status="not_attempted"`, `error_category="startup_ingestion_disabled"`, null retrieval ID/time bounds and no missing-opening timestamps. This is a fixed, secret-free unavailable state, not a completeness assessment or synthetic market data. H4 remains unsupported. No OHLC values or directional bias are returned.

The frontend uses the same contract through local Vite development/preview `/api/health`, which proxies to `http://127.0.0.1:8000/health`. This is a frontend proxy route, not a new backend API. It omits browser credentials, bypasses cached health responses, rejects invalid JSON/timestamps and expires after ten seconds. A failed check offers retry; a successful check reports backend reachability only. The existing schema is unchanged.

## Research analysis availability

`GET http://127.0.0.1:8000/api/v1/analysis/{analysis_id}` is a read-only, versioned projection route. It addresses an immutable persisted output ID; there is no `latest` or mutable-head route. The response contract is `xau.dashboard-analysis.v1`, documented in [DASHBOARD_ANALYSIS_CONTRACT.md](DASHBOARD_ANALYSIS_CONTRACT.md). It exposes the existing persisted deterministic output and its verified manifest/digest lineage. It does not recalculate analysis or create records.

No archive source is configured in the running service. The route therefore returns `503 analysis_projection_unavailable` unless an internal projection function is explicitly supplied. In disposable synthetic tests it reads a `mode=ro` SQLite connection, returns 404 for an unknown output, and 409 for missing or invalid provenance. The frontend uses the Vite `/api/v1/analysis/` loopback proxy, requires an exact analysis ID, validates the response and visibly marks returned data as synthetic. The local “View synthetic example” preview remains separate.

The optional `ai_report` member projects an already persisted immutable AI request, response and report associated with that exact analysis ID. The projection checks registered canonical digests and input/output/derived/prompt/provider/model links; it never invokes AI or creates records. `analyst_outcome` is populated only for a persisted `complete` or `insufficient_evidence` report. Failed or rejected requests have a response status and no report object. Historical invalidation warnings apply to the stored result without changing it. The archive remains synthetic-only; production archive integration, provider eligibility, verified freshness, and live AI response persistence remain unimplemented. No production database or external service is connected.
