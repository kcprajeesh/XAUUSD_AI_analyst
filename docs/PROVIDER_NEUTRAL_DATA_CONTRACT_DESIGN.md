# Provider-Neutral Data Contract Design

**Status:** Design only. This document does not authorize provider transport, schema changes, migrations, analysis, or Milestone 5. No application code or existing architecture document is changed by this design.

## Purpose and evidence labels

This proposal retains the Milestone 4 offline foundation while allowing independently identified provider feeds. It targets **$0/month**. A provider that is unavailable, over quota, or no longer permitted remains unavailable; there is no paid fallback or automatic upgrade.

The following labels keep evidence distinct:

- **Repository fact** describes current committed source and tests.
- **SiftingIO test observation** is limited to the results supplied for this design; no request was made during this work.
- **Support statement** reports the user's written support confirmation, not independently authenticated vendor material.
- **Design rule** is proposed behavior, not a statement that a provider supports it.

## Current architecture assessment

Milestone 4 is an offline library, not a live integration. `TwelveDataAdapter` plans requests, normalizes supplied payloads and chooses a conservative continuation; it has no HTTP transport or credentials. `CandleStore` is explicitly constructed and uses standard-library SQLite. FastAPI remains health-only and the frontend has no market-data calls.

Existing strengths to retain include frozen Pydantic contracts, `Decimal` prices/volume, UTC-aware instants, source rows and hashes, strict OHLC ordering, explicit instrument identity, forming/closed/unverified status, quality reports, append-only candle records, current heads, correction links, atomic ingestion, bounded 5,000-row pages, no silent gap filling, and preserved unknown databases. Tests in `backend/tests/test_data_foundation.py` exercise these behaviors, identity separation, pagination, schema snapshots, errors, rollback, precision and source evidence.

The current contract is Twelve Data-specific in places: `ProviderSeries`, `Provenance`, interval policy and SQL constrain provider/symbol/endpoints; all volume has only `provider_reported_unverified`; pagination is a date-range overlap decision; and current `Candle` has no explicit aggregation origin or revision identifier. Existing tests snapshot those assumptions and must remain valid or be deliberately versioned during a separately approved implementation.

## Proposed provider-neutral model

Keep provider normalization behind adapters and use a common validated observation model. Provider-specific response details remain in a provider evidence envelope; normalized fields are portable but never erase their source identity.

### Instrument identity

Represent an instrument using a canonical `instrument_id`, `asset_class=precious_metal`, `instrument_type`, base `XAU`, quote `USD`, quote/price unit, plus provider and feed identity on the series. Types are `otc_spot`, `broker_cfd`, `exchange_futures`, and `benchmark`. Provider symbol is distinct from canonical identity. A feed identity distinguishes provider product/venue/aggregation when the vendor has multiple feeds.

Examples: `xau-usd:spot-aggregate`, `xau-usd:cfd:<broker>`, `comex:gc:<contract-month>`, and `lbma:gold:usd:<AM|PM>`. Never join, substitute, revise, or aggregate across instrument types, brokers, futures expiries, benchmark fixes, providers, or feeds just because symbols or prices look similar. The current `spot_aggregate` identity remains a valid spot identity; it is not proof that two providers' spot feeds are interchangeable.

### Candle record

Proposed logical record fields:

| Field | Meaning |
| --- | --- |
| `contract_version` | Version of the neutral model, separate from provider policy version. |
| `instrument_id`, `provider_id`, `feed_id`, `provider_symbol` | Qualified source identity. |
| `interval` | Requested/display interval and unit, such as 5m, 1h, 4h or 1d. |
| `boundary_policy_id`, `boundary_semantics` | Provider-defined UTC boundary rule or explicitly defined UTC aggregation rule; never inferred from display timezone. |
| `opened_at` | Aware UTC opening instant. |
| `closes_at` | Known end instant, otherwise null with an explicit unverified boundary reason. |
| `open`, `high`, `low`, `close` | Finite positive `Decimal`; exact value after documented source normalization. Validate `low <= open/close <= high`. |
| `volume_value`, `volume_type` | Optional nonnegative exact decimal and an enum: `tick_count`, `exchange_traded`, `contract_volume`, `unknown`, or `unspecified`. Null remains distinct from zero. |
| `status` | `forming`, `closed`, or `unverified`; closure requires a verified boundary and evidence at/after it, not merely a later application clock. |
| `provenance` | Provider/feed, provider symbol, endpoint/resource, request/page reference, retrieved-at UTC, source timestamp text/meaning, source precision evidence, normalization method/version and permitted source evidence hash. |
| `observation_id` | Unique immutable ingestion observation identity. |
| `revision_of` / revision event | Link to prior observation(s), changed fields, detection time and reason; retain every observation. |
| `origin` | `native` or `aggregated`, with source interval and contributing observation IDs for aggregation. |
| `quality_flags` | Typed validation, gap, stale, duplicate, outlier, boundary and conflict findings. |

`tick_count` is never treated as traded volume. Unknown, unspecified and not-provided are distinct states. SiftingIO's `v` is currently described by that provider as tick count, so a normalized observation would be typed `tick_count` only if the provider's field definition is confirmed applicable to this endpoint. Its unusually large observed variation remains flagged for clarification. Do not enable volume-spike analysis on this field until units/semantics and anomalous variation are resolved.

## Adapter boundary

A future structural adapter should expose only the smallest common operations:

- `capabilities()` returns verified native intervals, symbol/feed identity, boundary/timestamp semantics, supported pagination mode and page cap, quota metadata if known, and permission/use constraints with verification status.
- `build_request(range, interval, continuation)` returns a provider-specific bounded request plan without performing I/O.
- `normalize(response, request_context, retrieved_at)` returns normalized observations plus original supported public evidence, typed provider error, quality report and pagination continuation.

Transport, secrets and retry scheduling belong outside normalization. The adapter must not claim an unverified capability. A capability may be `verified`, `claimed`, or `unsupported/unverified`; only verified support is selectable for trusted data. Preserve Twelve Data's current offline `series/normalize/next_page` behavior behind a compatibility adapter until a separately authorized migration. Do not add a generic base class or dependency unless implementation proves it necessary; Python protocols, enums, dataclasses/Pydantic, `Decimal`, `datetime`, `zoneinfo`, `sqlite3`, `hashlib` and `json` suffice.

## Timestamp and decimal policy

All canonical instants are aware UTC. Preserve original timestamp representation and meaning separately. SiftingIO test results say `t` is Unix milliseconds and documented as the UTC bucket opening. Convert integer milliseconds exactly to UTC; do not route through local time or floating-point seconds. Retrieval time is not a substitute for missing source time. Use IANA zones only for display.

The current implementation rejects Python floats for normalized prices because binary floats lose source precision. SiftingIO OHLC arrives as JSON floats. A normal JSON decoder may discard the original number token spelling. Safest future intake is a JSON decoder configured to parse floating tokens as `Decimal` (standard-library `json.loads(parse_float=Decimal)`), retaining the received decimal token where the transport provides raw JSON text. If only an already-created Python float is available, `Decimal(str(value))` provides the language's shortest round-trippable decimal representation, **not** source precision or a promise about the provider's original decimal token; label that normalization method and source precision `unknown`. Never use `Decimal(float)` or binary float arithmetic for stored financial values. Do not round or quantize absent a declared precision rule. Store normalized decimals as text in SQLite. This design does not change Milestone 4's exact-decimal validator.

## Pagination and safe resumption

Treat each adapter's pagination as provider-specific. Normalize provider pagination into a typed continuation envelope containing mode (`offset`, `page`, `cursor`, or range), opaque continuation token, request identity/range, provider page limit, last accepted source key, and contract version. Keep tokens opaque and avoid logging secrets embedded in URLs/tokens.

For either range or token pagination:

1. Validate requested inclusive/exclusive start/end semantics in adapter capabilities; preserve the exact requested bounds in ingestion provenance.
2. Enforce provider page cap before sending; a caller cannot raise it past provider or application limits.
3. Persist page observations and the continuation checkpoint atomically. Resume from the last committed continuation after interruption; if the provider's cursor expires or is invalid, mark the run `resume_required`/`indeterminate` and require a fresh bounded request rather than guessing.
4. A short page does not mean completion unless the verified provider contract says so. Empty page, missing cursor, repeated cursor, invalid cursor, impossible progression, or page limit exhaustion ends safely with an explicit incomplete state.
5. Deduplicate by full series identity plus UTC opening instant. Identical overlaps are retained as evidence/duplicate findings without duplicate current candles; differing same-key rows are conflicts/revisions, never a last-row-wins choice.
6. Do not claim completion from cursor absence unless provider semantics verify it. Record completion reason and page counts.

SiftingIO test observation: limit 3 returned three rows and a cursor; the next page returned three additional rows with no timestamp overlap; repeating the first request yielded identical first-page records. This supports observed repeatability in that test only. It does not establish cursor lifetime, all boundary behavior, or universal snapshot consistency. Twelve Data's existing latest-opening overlap rule remains provider-specific and is not generalized.

## Finalization, revisions, quality and freshness

A provider can return a currently forming bar; user support confirmation also says historical revisions may occur. Store each retrieval as an immutable observation. `closed` requires a verified interval boundary and a provider or deterministic rule supporting finalization. At an unverified boundary, status is `unverified`; later passage of time must not silently rewrite a stored status. A subsequent observation may establish finalization, linked to the earlier record.

Validate each row independently but quarantine invalid OHLC. Detect missing cadence candidates, duplicates, outliers and source conflicts as quality findings; do not fill, interpolate, silently discard evidence, or assert full calendar coverage without a verified calendar. Keep provider outage, invalid response, stale observation and conflicting sources separate. Staleness thresholds must be configured from verified source behavior; absent such a rule, show source and retrieval timestamps and mark freshness unverified. A conflicting provider remains a separate series; comparison may produce a conflict state, not merge records.

Revisions create a new immutable observation and typed link to the superseded observation, including source identity, retrieved-at, changed fields and detection method. Never overwrite old price history or hide a provider correction. A correction does not itself prove that the provider's prior candle was closed or that a related analysis remains valid.

## Native, aggregated and unsupported timeframes

Every selectable interval has exactly one explicit mode: `native`, `aggregated`, or `unsupported`. Never relabel aggregation as native.

| Display interval | SiftingIO evidence and design state |
| --- | --- |
| 5M | Historical endpoint HTTP 200 observed; native candidate, subject to access/use rights and complete contract validation. |
| 15M | HTTP 200 observed; native candidate. Cursor pagination and repeatability observed in the limited test described above. |
| 1H | HTTP 200 observed; native candidate. |
| Daily | `1d` HTTP 200 observed; native candidate. Boundary/calendar details still require validation. |
| 4H | Native request `4h` returned HTTP 400 listing allowed intervals without 4h. Native support is **not verified**. Support statement claims 4h and suggested aggregation from 1H; discrepancy remains unresolved. |

Design an optional deterministic 4H aggregation mode, **not activated**. If later explicitly approved, define UTC epoch-aligned half-open buckets `[00:00,04:00)`, `[04:00,08:00)`, etc., unless a verified provider/calendar contract justifies a different named policy. Do not use Qatar display time or implicit market sessions for boundaries. Require exactly four distinct, valid, consecutive, closed 1H source candles whose openings match the four expected UTC slots. If any source is missing, duplicate-conflicting, forming, unverified, outlier-quarantined or stale under an approved rule, emit no trusted aggregate and report the missing/invalid evidence. Aggregation: open from first open; high=max highs; low=min lows; close=last close. Volume can be summed only if all four have the same verified additive volume type; tick count remains tick count, never traded volume. Otherwise aggregate volume is unknown/omitted. Provenance records policy version and all four source observation IDs. Native and aggregated 4H must have distinct series identities and cannot overwrite each other.

Unsupported intervals produce `unsupported_timeframe` and `insufficient_evidence`; no silent fallback to another timeframe/provider.

## Quota and cost protection

Track provider/account/feed usage conservatively by request, endpoint, units/credits, observed rate-limit headers, configured daily/minute budget, reset time and certainty. Where provider quota is unknown, apply a conservative local request budget and bounded on-demand/manual refresh; do not poll continuously. Reserve budget for required work, serialize calls by default, and avoid redundant requests through a permission-compliant local cache.

Use bounded retries only for transient transport/server failures, honoring `Retry-After` and documented provider guidance with capped exponential backoff and jitter. Do not retry invalid requests, invalid cursors, permission errors, or quota exhaustion. On quota exhaustion or uncertain remaining quota, hard-stop that provider until a verified reset or explicit user action within the free limit. No parallel-account use, paid fallback, auto-upgrade, auto-billing, or overage. Cache and retain only within provider permissions; delete/expire when required. Keep the operational target at $0/month even if that means unavailable data.

## Errors and evidence states

Use explicit machine-readable outcomes: `provider_unavailable`, `invalid_response`, `quota_exhausted`, `stale_data`, `unsupported_timeframe`, `permission_not_confirmed`, `pagination_indeterminate`, `resume_required`, `data_conflict`, and `insufficient_evidence`. A request outcome may coexist with last known permitted data, but that data retains its original timestamp and is marked stale/unavailable as appropriate. No failure becomes a fabricated candle or silent provider substitution. Insufficient or contradictory evidence blocks directional assessment.

## Security and permissions

Credentials remain backend-only, excluded from request logs, page tokens, provenance, source hashes, SQLite and error details. Requests remain loopback-mediated; no browser provider calls. Retain only fields allowed by provider terms. Local SQLite retention and private AI inference permissions reported in support correspondence are user-supplied support statements; they do not extend to other providers and do not establish every retention period or data class. The supplied support confirmation permits private local SQLite, personal backtesting/research, and private AI inference with third-party retention/training disabled; do not infer broader redistribution/training rights. No provider data is sent to a third party unless applicable terms and permissions explicitly allow the exact use.

## Compatibility matrix: current foundation vs proposed design

| Area | Milestone 4 actual behavior | Proposed compatibility / gap |
| --- | --- | --- |
| Provider and symbol | `ProviderSeries` literals pin Twelve Data, `XAU/USD`, `time_series`; series ID includes policy. | Preserve IDs for existing rows; neutral provider/feed fields require a new versioned contract. |
| Instrument | Existing qualified spot/CFD/futures/benchmark identities already prevent type aliasing. | Extend with explicit asset class and provider feed; retain existing canonical spot identity. |
| Interval | Five enum values and SQL check, including 4h. | SiftingIO native 4h must not be advertised; represent capability per provider. Existing Twelve Data 4h policy is a proposed mapping, not verified live support. |
| Decimal | Exact `Decimal`; strings/integers accepted; floats rejected; source rows preserve scalar values including float. | JSON token-preserving Decimal parse is needed for SiftingIO. Already-decoded floats require labeled `Decimal(str(...))` normalization and unknown source precision. |
| Volume | Optional Decimal, semantics only `not_provided` or `provider_reported_unverified`. | Incompatible: typed tick/traded/contract/unknown/unspecified semantics and behavior need versioning; block spike analysis for SiftingIO. |
| Candle status | `forming`, `closed`, `boundary_unverified`; status derived from current retrieval and elapsed interval; daily close unresolved. | Reuse categories, add explicit finalization evidence and avoid reclassifying historical records from wall time alone. |
| Provenance | Twelve Data-only provider/endpoint/symbol and public metadata hash. | Generalize provider/feed/endpoint, timestamp units, source precision and normalization provenance without storing secrets. |
| Pagination | UTC range + outputsize up to 5000; overlap latest opening; short page not completion. | Incompatible with opaque SiftingIO cursor and provider-specific page limits. Add a separate cursor checkpoint model; do not alter current logic in this stage. |
| Revisions/storage | Append-only observations, current heads, revision links, explicit SQLite schema v1. | Strong fit conceptually; new identity/volume/pagination/origin fields need a deliberate schema migration and preserved history. |
| 4H | Policy currently includes native label and elapsed close for 4h. | Must not imply SiftingIO native support. Any 1H aggregate gets separate identity and provenance; inactive until approval. |
| Gaps/outliers | Typed quality reports, no fill, heuristic outlier flags. | Retain and version rules; thresholds are not provider facts or trading signals. |
| Quotas/cost | No request transport or quota ledger exists. | New bounded request budget and persistent usage state would be implementation work; stop by default on exhaustion/uncertainty. |

### Incompatible existing assumptions to address before any implementation

1. Provider-specific `Literal` fields and series IDs cannot identify SiftingIO without a versioned generalized contract.
2. `Candle.volume_semantics` cannot express tick count or distinguish all requested volume classes.
3. The adapter protocol expects only range-style `HistoricalRequest`; it cannot retain/resume an opaque cursor or model short-page/cursor errors.
4. Existing source rows accept floats as raw evidence, but exact price validation rejects floats. SiftingIO normalization needs raw JSON token handling or explicitly lossy-to-source (but decimal-safe) conversion provenance.
5. Candle provenance is one shared retrieval record and source row index; revision links exist at storage level but there is no portable observation ID in the contract or aggregate lineage.
6. Current status validation ties closure to `retrieved_at >= closes_at` and policy duration. Provider-finalization evidence and unverified interval boundaries need explicit representation.
7. Existing 4H interval enum/policy does not encode native vs aggregate vs unsupported capability.
8. SQLite `provider_series` uniqueness/check constraints and JSON snapshots are schema v1 and Twelve Data-specific; neutral fields, continuation checkpoints, quota ledger and volume enums require a deliberate migration/version. No existing database may be rewritten in place without backup, migration validation and rollback plan.
9. Existing tests assert Twelve Data contract and schema behavior. Compatibility must preserve old stored v1 records and tests, or introduce a separately reviewed v2 with explicit conversion semantics; never reinterpret existing `provider_reported_unverified` as tick volume.

## Migration implications for Milestone 4

No migration is performed here. Any implementation proposal should first freeze representative v1 fixtures and preserve the v1 reader. Prefer additive v2 tables/contract types or a carefully transactional migration that retains every original JSON record and maps old volume semantics to `unknown`/`unspecified`, never to traded volume. Existing series IDs and Twelve Data records remain stable. Include rollback by keeping a copy and refusing unknown/future schema versions as current code does. New per-provider capabilities, page checkpoints and quota usage should be separate persisted records with explicit retention; do not mix synthetic and provider-response databases. Do not create a production database at startup.

## Risks and unresolved questions

- **4H discrepancy:** endpoint rejection conflicts with support's claim and 1H aggregation suggestion. Neither native nor aggregate mode is verified/activated.
- **Volume:** provider describes `v` as tick count; observed 15m examples vary from 6,540 to 622,513,355. This design does not decide whether those values reflect a unit, encoding, aggregate or anomaly. Ask provider for field semantics, scale, reset/rollover, and explanation; disable volume-spike analysis meanwhile.
- **Float source precision:** JSON float results can lose the original lexical decimal when decoded normally. Exact source precision cannot be recovered from an already-decoded float.
- **Finalization and revisions:** forming-bar and correction behavior is stated by support only; exact signals, timing and correction delivery are unknown.
- **Pagination:** one successful cursor sequence does not establish token expiration, snapshot consistency, boundary inclusivity, invalid-cursor behavior, or completeness semantics.
- **Permissions and quotas:** support statements cover specified uses, but current free-tier entitlement, quota/reset behavior, retention limits and service continuity remain implementation-time checks. $0 cannot be guaranteed if free access is withdrawn; the feature must stop.
- **Daily boundaries, missing-candle calendar, freshness thresholds:** not established by supplied tests. Keep daily closure and stale classification unverified until defined.
- **Cross-provider conflicts:** different spot feeds may disagree without either being erroneous. Keep them separate and surface conflict rather than choosing silently.

## Implementation sequence and acceptance criteria (future approval required)

1. **Contract v2 proposal:** define instrument/feed, typed volume, source precision, status evidence, native/aggregate origin and observation/revision IDs. Acceptance: all v1 fixtures remain readable and no old volume meaning is upgraded by assumption.
2. **Pagination and quota records:** model cursor/range checkpoints, request budgets, stop states and restart behavior. Acceptance: interruption resumes only from a committed valid cursor; repeated/missing/invalid cursor and quota exhaustion make no further request.
3. **SiftingIO normalization:** only after permissions/entitlement are confirmed; parse raw JSON floats as `Decimal` tokens, map epoch milliseconds exactly, preserve provider evidence and validate OHLC. Acceptance: synthetic cases cover all verified intervals, errors, duplicate/conflict, pagination and source-precision limitations; `v` cannot reach volume-spike analysis.
4. **4H capability decision:** wait for written/API resolution; keep native unsupported while API rejects it. Optional aggregate requires separate approval and tests for UTC alignment, four complete closed source bars, missing inputs and lineage.
5. **Storage migration:** transactional, backup/rollback, append-only retention; acceptance includes v1 read compatibility, integrity and foreign-key checks, preservation of current/history/revisions and refusal to alter unrelated databases.
6. **Operational gate:** bounded no-cost requests, documented cache permission, freshness and failure states; acceptance proves hard stop on quota/permission/unavailable conditions, no paid path or uncontrolled polling, and backend-only secrets.

This design does not authorize any of these steps. Stop at this document until explicit approval.
