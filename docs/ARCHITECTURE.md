# Architecture

## Current execution status — Phase 2.5.18

The sections below preserve historical milestone architecture. Current implementation and authorization are tracked in [MASTER_PROJECT_TRACKER.md](MASTER_PROJECT_TRACKER.md) and [PHASE_2_5_18_ARCHITECTURE_CLOSURE.md](PHASE_2_5_18_ARCHITECTURE_CLOSURE.md). The user's master directive authorizes approved implementation beyond the historical stop boundaries, while preserving deferred policy and production permissions.

The frontend now includes economic calendar and provider/settings sections, shared IANA timezone controls, expandable evidence requirements and a local backend health indicator. Vite development/preview proxies only `/api/health` to loopback port 8000. Health availability is independent of market/AI availability; no credential input or direct provider request exists in the browser.

Backend deterministic, provider and AI foundations from later milestones remain isolated from FastAPI startup. New canonical primitives are separately schema-directed and require explicit limits; they do not replace legacy serializers/hashes or activate production profiles. The application routes are `/health`, `/api/v1/analysis/{analysis_id}` and `/api/v1/market-data/status`. Under A0, ordinary import/startup/shutdown do not discover provider credentials, construct provider clients/pipelines, make provider/AI requests, or construct/open market storage. There is no startup ingestion or activation switch. Market status retains its schema and provider label but reports `startup_ingestion_disabled`, zero candles and unavailable analysis; the analysis projection defaults to 503 without an explicitly supplied internal source. Health remains independent of market availability.

## Milestone 1 implementation

`frontend/` is a React 19 / TypeScript 6 / Vite 8 application with Tailwind CSS 4, Lucide React, and the validated Lightweight Charts dependency. It shows empty market and analyst states; it makes no API calls. The only interactions select a display timezone and one of Daily, 4H, 1H, 15M, or 5M. A workspace-opened timestamp is clearly labeled as application time, not market freshness.

`backend/app/` contains FastAPI, the Pydantic health model, validated process settings, and a loopback Uvicorn entry point. `GET /health` reports service availability only. NumPy and pandas are installed and smoke-tested; SQLite is the Python standard-library driver, tested with an in-memory connection. No database or persistence schema is created. Frontend and backend have their own commands, configurations, dependency locks and checks.

## Approved future analysis boundary

One central AI Analyst Engine will own the final Gold-only assessment. Internal specialist modules will provide evidence for that engine, not competing independent analyst agents. The intended flow is verified market evidence → internal specialist observations → central assessment → presentation. Module names, algorithms and provider choice await evaluation and approval; no placeholder engine or module implementations exist in Milestone 1.

Conclusions must identify their evidence and its provenance, timestamps and limitations. Missing, stale, contradictory or inadequate evidence must produce an explicit `insufficient_evidence` state. Do not invent market observations, signals, confidence percentages or price targets. The current shell communicates this state without generating any conclusion.

The analyst is read-only: no broker integration, order submission, automatic trading, shell/tool execution capability, or execution API is permitted. Future provider credentials belong in backend-only configuration, never frontend code or browser bundles.

## Time policy

Store, exchange and compute timestamps in UTC, using timezone-aware instants. API timestamps serialize as ISO 8601 ending in `Z`. Display defaults to `Asia/Qatar`; India uses `Asia/Kolkata`. Optional UTC, London and New York preferences use their IANA names. Browser `Intl.DateTimeFormat` applies daylight saving rules without fixed-offset arithmetic. Backend conversions, if later needed, must use standard-library `zoneinfo` or pandas named zones.

Daily and intraday bar boundaries will be defined with the selected provider's session/calendar contract during market integration. A display timezone must not change a candle's underlying UTC instant. No candle generation or resampling is implemented yet.

## Development security

Default frontend and backend bindings are `127.0.0.1`. Backend settings validate at import/startup; only the documented prefixed variables are accepted. Frontend public environment values validate during Vite startup/build. No API keys are needed or supported. Cross-origin middleware, authentication, persistence, queues, external providers and deployment infrastructure are deferred until a concrete approved need exists.

## Current Milestone 4 — offline data foundation

Milestone 4 is explicitly authorized and complete. Earlier sections describe the historical Milestone 1 state. The health API, entry point and frontend remain unchanged. `backend/app/data/` now provides versioned Gold/USD identities, decimal-safe candle/provenance/quality contracts, UTC timeframe policies, a Twelve Data request-planning and normalization interface, and explicit local SQLite persistence with append-only observations and historical revision links. No data module is wired into FastAPI startup or the browser.

The implemented flow is supplied offline payload → public source evidence and normalized validation → transactional SQLite observations/reports/current heads/coverage. Invalid/conflicting data is quarantined with evidence; forming and unverified-boundary records remain stored but closed-only reads exclude them. Synthetic and provider observations require separate databases. The default development services still bind to loopback.

Twelve Data `XAU/USD` is the intended personal-use primary spot series under the user-supplied support conditions. No live requests, credentials, purchase, AI processing or broker/trade integration were implemented. All calendar rules remain unverified; intraday ends use elapsed intervals from source openings, while Daily ends remain unresolved. No holidays, session boundaries, daily rollover, filled candles or completeness claims are invented. The original support email was not supplied or archived.

Contracts/schema, identity separation, validation, SQL tables and adapter semantics are documented in [DATA_FOUNDATION.md](DATA_FOUNDATION.md). [MILESTONE_4.md](MILESTONE_4.md) records verification and remaining work; [MILESTONE_4_ROLLBACK.md](MILESTONE_4_ROLLBACK.md) preserves a rollback path. Stop after Milestone 4 and wait for explicit Milestone 5 approval.
