# Milestone 4 — offline XAU/USD data foundation

This is a local, offline library under `backend/app/data/`. FastAPI still exposes only the existing health contract. Importing or starting the health service neither creates a database nor fetches market data. The frontend, settings, dependency locks, installed skills and hooks are unchanged.

## Authorization and provider evidence

The user explicitly authorized Milestone 4 and supplied the support requirements summarized below. This overrides earlier milestone stopping points for this implementation only. Work stops after Milestone 4; Milestone 5 and live integration require explicit approval.

Intended provider: Twelve Data, native `XAU/USD`, Gold Spot / US Dollar, for personal use, subject to the user's written support confirmation. The user reports an existing Basic 8 account; Twelve Data Support identified Grow as the minimum subscription for ongoing production access. No subscription was bought or upgraded. No entitlement or live provider response was verified.

User-supplied support requirements: `1day`, `4h`, `1h`, `15min`, `5min`; at most 5,000 points per request; historical `start_date`/`end_date`; default UTC timestamps representing candle opening; newest candle may be forming; finalization after the interval closes; retroactive historical corrections permitted; local SQLite for personal research, derived indicators/personal reports, and private AI processing permitted under the stated conditions. These permissions are context, not implementations of indicators or AI.

No original support email or attachment was supplied or explicitly authorized for saving. **No original email was archived.** This document records the user's specifications, not a fabricated provider email or independently authenticated confirmation.

## Versioned contracts

`contracts.py` uses installed Pydantic with forbidden extra fields and frozen models. Every normalized contract has `schema_version: "1.0"`. Serialization schema is [data-foundation.schema.json](data-foundation.schema.json), tested against the models; it does not extend the health OpenAPI schema. SQLite `user_version` is independently `1`.

| Contract | Contents |
| --- | --- |
| `Instrument` | Gold/USD market kind and canonical qualified identity, name, quote and price unit |
| `ProviderSeries` | Twelve Data, explicit native `XAU/USD`, spot identity, interval and `td-xau-utc-v1` policy |
| `Provenance` | Provider, native symbol, endpoint, input kind, aware UTC retrieval instant, original supported public metadata, SHA-256 and declared hash basis |
| `SourceRow` | Source row index and original supported scalar datetime/OHLC/volume fields; invalid rows remain evidence |
| `Candle` | Exact decimal OHLC, optional volume and semantics, source timestamp string/meaning/timezone, UTC open/end, end basis, status, provenance and quality flags |
| `ValidationReport` | `quality-v1` rules, issues with row/instant references, unverified cadence gaps and historical revision links |
| `HistoricalRevision` | Previous/new observation IDs, source opening, detection instant and changed fields |
| `IngestionRecord` | Request range/limit, series, retrieval provenance, source rows, validation report and structured error |
| `Coverage` | Current closed/forming/unverified counts, first/last closed openings, ingestion link; calendar/completeness explicitly unverified |
| `HistoricalRequest` / `PaginationDecision` | Validated range/limit, public request parameters and conservative continuation decision |
| `TimeframePolicy` | Versioned mappings, nominal durations and unverified calendar/daily rules |

Prices and volume use `Decimal`. Decimal text and integers are accepted; binary floats and booleans are rejected for normalized prices/volume. Prices must be finite and positive; volume, when provided, finite and nonnegative. Source strings and trailing decimal precision remain available; no quantization or silent rounding is performed. Normalized values must equal retained source values. The evidence fingerprint covers only declared public metadata and retained source rows, not arbitrary response bytes or error messages.

All normalized instants must be aware and are converted to UTC; JSON emits `Z`. Provider naive full timestamps are interpreted as UTC under the supplied default contract. Explicit offsets are respected and normalized; the original timestamp spelling remains intact. Full seconds and up to six fractional digits are supported; excessive timestamp precision is rejected without truncation. A date-only daily label cannot establish an opening instant without a daily rollover rule, so it is retained with `invalid_timestamp`. Retrieval time never replaces missing source time.

## Distinct instrument identities

| Market | Canonical identity | Required qualifier |
| --- | --- | --- |
| Spot aggregate | `xau-usd:spot-aggregate` | None |
| Broker gold CFD | `xau-usd:cfd:<broker>` | Broker identity |
| COMEX GC future | `comex:gc:<YYYY-MM>` | Contract month |
| LBMA gold USD benchmark | `lbma:gold:usd:<AM or PM>` | Benchmark fixing |

These identities cannot alias each other; contradictory/missing qualifiers fail validation. They define identities only and do not claim broker, futures or benchmark data access. The initial adapter accepts only the spot aggregate. Its series ID is `twelve_data:XAU/USD:<interval>:td-xau-utc-v1`.

## Timeframe and calendar policy

| Display | Native interval | Nominal seconds | End/status policy |
| --- | --- | --- | --- |
| Daily | `1day` | 86,400, cadence diagnostic only | Daily end unknown, `boundary_unverified` |
| 4H | `4h` | 14,400 | Source open plus elapsed interval |
| 1H | `1h` | 3,600 | Source open plus elapsed interval |
| 15M | `15min` | 900 | Source open plus elapsed interval |
| 5M | `5min` | 300 | Source open plus elapsed interval |

Intraday `closed` means the retrieval instant is at or after the nominal end; before that end it is `forming`. This says nothing about subsequent historical corrections. No candle grid is aligned to midnight or any display timezone. Qatar/India display preferences cannot alter these policies. Holidays, sessions, closures, daily rollover, shortened bars and first/last expected trading candles remain unverified. No calendar, resampling, interpolation or forward fill is invented.

Daily full opening timestamps can be persisted but are excluded from closed-only reads while daily ends are unknown. Changes to these observations remain in history; they cannot be classified as corrections of finalized daily bars until closure is verified. A future confirmed boundary/calendar contract needs a deliberate new policy/series version.

## Deterministic validation

- Reject missing, malformed, ambiguous date-only, future, out-of-request-range or overflowing source timestamps; retain supported source fields and issues.
- Reject missing/nonfinite/nonpositive prices, binary float prices, and any ordering that violates `low <= open <= high` and `low <= close <= high` (therefore also `high >= low`). Reject invalid volume without pretending volume is unavailable.
- Sort valid observations by source opening. Collapse identical same-opening rows, retaining all originals and duplicate flags. Quarantine every conflicting valid duplicate; a valid row conflicting with an invalid OHLC/volume observation at that opening is also quarantined. No arbitrary last-row winner.
- Retain forming and unresolved-boundary candles as evidence; default storage queries return closed candles only. Closure classification is an observation at retrieval, never automatically advanced merely because wall time passes.
- Report missing nominal cadence slots between observed openings as **unverified candidates**, with a count and bounding source instants. Irregular spacing is separately flagged. Empty responses are explicit; no empty page or coverage report asserts calendar completeness. These checks cannot prove outages or missing first/last trading candles without a verified calendar.
- Flag a candle range exceeding 20% of its low or an adjacent close move exceeding 20% of the previous close. Exact rational comparisons avoid decimal-context rounding. This versioned heuristic is not confidence or a signal; outliers are retained, including in closed reads. Recalibrate against verified history later.
- Compare numerically changed OHLC/volume of closed observations at the same provider/series/opening. Preserve old and new records, link the correction and flag `historical_revision`. Decimal formatting/timezone-spelling changes alone are not price revisions. Forming-to-closed changes are observations, not historical corrections.
- Preserve older/equal retrieval observations but flag them and keep the newer current head. Preserve the previous usable current candle when a newer response contains quarantined/invalid rows; the latest ingestion report exposes that failure.

Unsupported non-scalar candle fields are rejected; arbitrary extra envelope/row fields and source error messages are omitted. Public scalar fields from rejected rows are retained. Responses above 5,000 rows are rejected without storing an oversized row set. The declared fingerprint reflects retained supported evidence, not omitted fields.

## SQLite schema and behavior

The authoritative DDL is [backend/app/data/schema.sql](../backend/app/data/schema.sql).

| Table | Stored data / keys |
| --- | --- |
| `instruments` | Instrument ID primary key, versioned JSON metadata |
| `provider_series` | Series ID primary key, instrument FK, explicit provider/native symbol/interval/policy and metadata; unique provider/symbol/interval/policy |
| `ingestions` | Ingestion ID, series FK, UTC retrieval key, request/provenance/source rows/error JSON |
| `candle_records` | Append-only observation ID, ingestion/series FK, fixed-width UTC opening key, status, normalized JSON with decimal strings; unique ingestion/opening |
| `current_candles` | Series/opening primary key pointing to the selected observation through a composite identity FK |
| `historical_revisions` | Ingestion, previous/new observation FKs and typed revision JSON |
| `quality_reports` | One typed report per ingestion |
| `coverage` | One aggregate snapshot per series, linked to an ingestion |

UTC index keys always include six microsecond digits, so lexicographic range reads preserve timestamp order. Indexes cover series/opening history and series/retrieval; current-head and identity constraints are indexed primary/unique keys. JSON columns enforce valid JSON; model validation protects decimal, identity, UTC, provenance and boundary semantics before writes. Read models validate persisted contracts again.

`CandleStore(path)` is explicit. An empty database initializes schema v1; unrecognized versions or existing unrelated schemas are rejected without migration or data deletion. Foreign keys are enabled. One `BEGIN IMMEDIATE` transaction covers metadata, ingestion, observations, current heads, corrections, report and coverage; failure rolls the whole ingestion back. Concurrent writers serialize through SQLite; no WAL/concurrency tuning or production-load claim is made.

Every accepted ingestion observation is retained even when unchanged. No API credentials or credential columns exist; the adapter has no key input and stores only supported public response metadata/fields. Synthetic and provider-response ingestions are forbidden from sharing a database. No default production database is created; verification uses clearly named synthetic temporary/local databases ignored by the existing Git rules.

The store exposes `ingest`, `get_ingestion`, `get_instrument`, `candles` (closed-only by default, optional UTC bounds), `history`, `coverage` and `integrity_check`. Metadata cannot be silently overwritten under an existing identity. Gap evidence belongs to per-ingestion reports; coverage counts summarize current records across ingestions and are not a trading-calendar completeness calculation.

## Offline provider adapter interface

`ProviderAdapter` is a structural protocol with `series`, `normalize` and `next_page`; `TwelveDataAdapter` implements it. It contains **no HTTP implementation**, credentials, API endpoint connection, subscription operation or AI integration.

`HistoricalRequest` validates aware UTC `start_date < end_date` and integer output size 1–5,000. Parameters use `symbol=XAU/USD`, the native interval, UTC date-time bounds, `outputsize`, `timezone=UTC`, `order=asc`; fractional request bounds are rejected to avoid truncation. This is an interface proposal to verify against an actual authorized response, not a live-tested transport.

`normalize(payload, request, retrieved_at=..., input_kind=...)` requires an explicit synthetic/provider label. It checks the expected public `meta`/`values` envelope, exact symbol/interval/UTC metadata, optional USD currency, response limit, timestamps, OHLC and volume. A provider error gets a typed error and optional integer code; arbitrary provider messages are not persisted. Invalid envelopes cannot yield trusted candles. Partial row failures remain in a typed report; valid independent rows can be retained.

Pagination overlaps the latest source opening by making it the next `start_date`, with the original end/limit. Deduplication handles inclusive overlap without dropping fractional/adjacent observations. Empty or invalid pages and nonprogressing cursors return `indeterminate`; reaching the supplied end returns `range_boundary_reached`, which does not assert complete coverage. A short page alone never proves the range is complete. Range inclusivity, payload shape, ordering/limits and short-page behavior still require live/provider-contract confirmation. No pagination loop or HTTP calls are implemented.

## Verification, limits and rollback

See [MILESTONE_4.md](MILESTONE_4.md) for results, changed files, security review and remaining integration work. See [MILESTONE_4_ROLLBACK.md](MILESTONE_4_ROLLBACK.md) for rollback using preserved architecture/graph copies. Earlier milestone evidence and rollback records remain intact.
