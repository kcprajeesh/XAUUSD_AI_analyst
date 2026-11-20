# Milestone 5E — Live Market Data Integration

## Status

The offline SiftingIO ingestion pipeline was implemented without a live request at that time. A later user-confirmed single-request verification is recorded in the Stage 5E.1 report. No credentials were inspected and no AI inference was performed.

## Provider and source identity

`backend/app/data/siftingio.py` is a standard-library HTTPS adapter. It is separate from the Twelve Data adapter and emits an XAUUSD spot aggregate identity (`xau-usd:spot-siftingio`, provider `siftingio`, feed `commodities`). It only accepts the configured SiftingIO HTTPS host, rejects URL credentials, keeps `X-API-Key` in a header, uses TLS verification, and separates connection/read timeouts. The default `http.client` transport does not follow redirects. Compressed and decompressed response sizes are bounded. Errors omit provider bodies, sensitive headers, and credentials. Automatic retries are not performed.

The key is resolved from the environment variable named by `api_key_env` at request time; the default name is `SIFTING_API_KEY`. The name can be configured without putting a value in source, SQLite, or frontend configuration. The app does not load `.env` files. A missing variable yields `not_configured`.

Historical requests use `GET /v1/hist/commodities/XAUUSD/bars`, UTC RFC 3339 inclusive `start` and `end`, supported intervals 5m/15m/1h/1d, order, limit (at most 2,000), and opaque cursor. Returned `t` millisecond timestamps are converted with integer arithmetic. OHLC JSON numeric tokens are decoded to `Decimal`; the JSON token is preserved as the available precision, without claiming greater source precision. Tick counts retain `VolumeType.TICK_COUNT`.

The snapshot adapter follows the previously user-verified `GET /v1/snapshot/commodities?symbols=XAUUSD` shape and maps the reported price/bid/ask/timestamp fields (compact and descriptive field aliases), sizes when supplied, source timestamp, and retrieval timestamp. It is never converted into or used to overwrite a candle. Current public SiftingIO pages also document `/v1/last/quote/commodities/XAUUSD` and quote/trade endpoints. The snapshot route/shape discrepancy must be rechecked against the user’s actual account before production; no assumption is made that the currently documented last-quote endpoint contains a reference price.

Public reference pages consulted: [Commodities bars](https://sifting.io/docs/historical/commodities), [snapshot reference](https://sifting.io/docs/live/snapshot), [commodities product/API examples](https://sifting.io/product/commodities), and [SiftingIO limits](https://sifting.io/docs/errors). Current documentation describes RFC 3339/date start/end values, cursor pagination, gzip, and a `v` tick count. The support confirmation and prior endpoint tests remain user-supplied evidence. The current docs’ snapshot route differs from that prior observed route; it is unresolved.

## Normalization, lifecycle, and persistence

`NormalizedCandle` validates positive, ordered OHLC, exact UTC bucket boundaries for intraday bars, volume semantics, timestamps, and forming/closed status at retrieval time. The daily boundary is a UTC day; daily candles are not confirmed until its elapsed boundary. An unusual-range candidate is retained with a quality flag and never silently corrected. Conflicting same-page duplicate openings are rejected. Rows are sorted by opening time. No gap is filled.

`fetch_pages` follows cursors, caps page count, detects repeated cursors, overlaps and out-of-order pages. Pages are staged under a retrieval ID and become current observations only after a successful terminal page. A failed or incomplete retrieval remains in the ingestion ledger and cannot replace the prior current observations. Evidence construction fails closed when the latest status for a requested series is pending, failed, incomplete, or unknown. A full page with no cursor field is unverified; a short page without a cursor follows the adapter's short-page terminal rule. `MarketDataPipeline.incremental` rechecks a caller-selected number of candles before the latest stored opening, so provider corrections are discoverable without a broad backfill.

`CandleStore.persist_sifting_page` writes to the existing Milestone 4 tables. Original observations are append-only; completed newer changed closed candles create revision records and retain both JSON records. Retrieval IDs and lifecycle states use existing ingestion request/provenance JSON fields; incomplete observations remain staged outside `current_candles`. Request events record hashed request identity and outcome, without credentials or response bodies. Transaction boundaries are used. This implementation does not alter `schema.sql` or `user_version`.

## 4H and evidence handoff

Native 4H is never requested. `aggregate_4h` only emits four consecutive, aligned, closed native 1H candles from the same source. OHLC uses first open, maximum high, minimum low, and final close. Tick-count values are summed only when all four source candles have tick-count values, and the output remains labeled tick count. Aggregated records preserve all four candle IDs and are marked `CandleOrigin.AGGREGATED`. Any gap or forming input leaves that 4H interval unavailable.

`build_evidence` creates a versioned Stage 5C packet for requested timeframes, leaves absent series unavailable, invokes `analyze_packet`, and returns `assess_sufficiency`. Only the deterministic Stage 5D engine is called. Forming candles remain explicitly marked and are excluded from confirmed calculations by that engine. No AI response is created. Freshness limits are caller-configurable; with no configured limit, the packet carries source/retrieval timestamps but does not assert a universal stale threshold.

Outlier candidates and cadence gaps are flagged; they are not filled or treated as verified. The Stage 5D engine records source tick observations but does not turn tick counts into exchange-volume spikes. The unusually variable tick-count values previously observed are retained, but volume-spike analysis remains disabled pending provider clarification. Snapshot staleness is not classified without a configured freshness threshold.

## Quota and cost protection

`RequestPolicy` has optional per-minute, per-day, calendar-month, minimum-poll, concurrency, and pause controls. No numeric quota defaults are invented. `MarketDataPipeline` connects the gate to the existing SQLite ingestion ledger, recording each attempted request before transport and updating it with its outcome. The app’s configured monthly request window uses calendar UTC months; this is an application safeguard and does not claim to match the provider’s quota reset. The gate supports pause/resume and suppresses concurrent duplicate request signatures. No retry, fallback, upgrade, purchase, or top-up exists. Provider plan limits supplied by the user (10,000 REST calls/month and 60/minute) must be rechecked before live use.

## Offline verification

Synthetic-only tests cover gzip, exact decimals, missing credentials, endpoint security, authentication/quota/service errors, malformed data, OHLC rejection, snapshot normalization, cursor paging, duplicate suppression, configured limits, SQLite persistence/revisions/integrity, tick semantics, four-hour aggregation, evidence packet construction, and incomplete aggregation. All test values are synthetic and are not market observations.

Verification on Android/Termux: backend `pytest` — 165 passed; backend `pip check` — clean; frontend `npm run typecheck` — passed; `npm test` — 9 passed; `npm run build` — passed; `git diff --check` — clean. No startup behavior changed, so no new service-startup check was needed.

## Changed files

- `backend/app/data/siftingio.py` — HTTP transport, normalization, snapshot and history contracts.
- `backend/app/data/ingestion.py` — pagination, incremental fetch, 4H aggregation, evidence builder and pipeline.
- `backend/app/data/quota.py` — configurable request gate.
- `backend/app/data/storage.py` — shared-table SiftingIO persistence and request ledger.
- `backend/tests/test_siftingio_ingestion.py` — offline synthetic tests.
- `docs/MILESTONE_5E.md` — this record.

No frontend, schema, dependency, Twelve Data adapter, or application startup files are changed. The pipeline is a backend service interface; this milestone does not expose new browser/API routes, schedule polling, or open a public listener.

## Limitations and unresolved items

- Snapshot route and payload are supported from the prior user test, but current public docs describe a different last-quote route. Reconcile this before live verification.
- The account’s current key presence, endpoint access, subscription quota, and exact range/timeframes have not been checked. No key was read.
- The request gate and SQLite ledger record attempted request outcomes, but rate-limit response headers are not used to alter pacing; the client never retries.
- There is no configured universal freshness cutoff, market calendar, or session-gap schedule. Calendar gaps remain quality candidates.
- SiftingIO sends JSON numbers as floating-point values. Decimal parsing preserves the JSON token, not precision beyond what the provider emitted.
- No scheduled ingestion, health endpoint, dashboard, Twelve Data comparison call, or AI execution is included.

## Rollback

Stop using `MarketDataPipeline` and remove the new SiftingIO modules/test/documentation. Existing SQLite rows can remain as audit history. Do not delete the database or alter its schema as part of rollback. Existing Twelve Data reads and Stage 5B–5D code are independent.

## Live verification gate

Before a future real request, confirm without displaying the secret that `SIFTING_API_KEY` is present; confirm the endpoint, requested timeframe(s), exact historical range, maximum request count, and remaining quota budget. The user has separately confirmed one historical sample request; Stage 5E.1 made no live requests.
