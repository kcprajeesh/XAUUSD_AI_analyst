# Zero-Cost Project Policy

**Status:** Policy established as Stage 2 documentation. This document does not authorize provider integration, AI processing, or any other implementation stage.

## Purpose and budget

The project targets recurring operating costs of **$0/month** for personal use. Every proposed feature must work within that limit or remain unavailable. No feature may initiate a purchase, subscribe to a paid service, upgrade a plan, or incur an overage without a separate explicit user approval. Paid API subscriptions, paid AI API calls, paid hosting, and managed databases are outside the project scope.

Free plans may change, impose hard quotas, or be withdrawn. A zero-cost target is not a guarantee that a third-party free service will remain available. If a free service becomes unavailable or its terms no longer permit the intended use, stop using it and show an unavailable state; do not switch to a paid tier or a different provider automatically.

## Approved architectural direction

The intended operating architecture is a local React frontend, a local FastAPI backend, and a local SQLite database. Backend and frontend development services remain bound to loopback. Market data may come only from a provider tier that costs nothing and whose terms permit the intended use. Technical analysis must be deterministic and evidence-based. AI interpretation is optional and may be performed manually in ChatGPT; the application must remain useful when AI is unavailable.

The project has no broker integration, order submission, execution endpoint, automated trading, or command/tool execution capability. No stage in the roadmap authorizes these capabilities.

This direction preserves the existing project boundaries: FastAPI currently exposes its health service only; the Milestone 4 data foundation is an offline library; SQLite is explicit and local; and the React shell makes no market-data requests. Historical milestone records remain authoritative for what has been implemented and verified. This policy does not revise or replace them.

## Provider classifications

These classifications reflect the Stage 1 repository audit and public documentation reviewed for it. They are planning labels, not proof of account entitlement, response compatibility, or licensing permission. No provider is authorized for integration by this policy.

| Provider | Classification | Limits and unresolved points |
| --- | --- | --- |
| SiftingIO | Candidate primary source | Public documentation lists free commodity access and historical XAUUSD bars at 5m, 15m, 1h, and 1d. It does not document native 4h bars. Written confirmation is still required for local SQLite historical retention and private third-party AI inference. Forming-candle and historical-correction behavior are also unresolved. |
| Twelve Data Basic 8 | Independent comparison candidate | Basic lists 8 API credits/minute and 800 requests/day. Do not assume it includes XAU/USD commodity access: current plan information lists commodities among paid features. No Basic entitlement for this project has been verified. |
| Gold-API.com | Optional snapshot comparison | The free live price endpoint is a possible spot snapshot cross-check. Free historical/OHLC endpoints have a shared published limit of 10 requests/hour, but free intraday XAUUSD candle support has not been verified. It is not an approved intraday history source. |
| GoldAPI.io | Optional alternative | Free quota figures conflict across public pages, and the available public material describes historical daily prices rather than verified free intraday bars. Confirm current quota, endpoint access, and use rights before considering it. |
| API Ninjas | Unsuitable for this workflow on Free | The documented historical gold OHLCV endpoint is Premium-only and describes gold futures; free terms also prohibit caching/storing. It does not fit a spot-history workflow that persists candles in local SQLite. |
| GoldPrice.dev | Optional daily comparison only | Free access is documented for daily XAU/USD history with a limited recent window and delayed spot prices. Free intraday bars are not documented. Do not use it to supply intraday timeframes. |

Provider-specific plans and terms must be rechecked at the approval-gated permissions stage. No undocumented endpoint, interval, entitlement, quota, retention right, or data-use right may be assumed.

## Data integrity rules

- Keep each provider's series distinct, with provider, native symbol, instrument identity, interval, retrieval time, and source provenance attached to observations.
- Never combine or silently substitute spot, broker CFD, COMEX futures, or LBMA benchmark observations. They are different instruments and require different identities.
- Store and compute timestamps as aware UTC instants. Display Qatar time (`Asia/Qatar`) by default, using named IANA time zones for any other display preference.
- Preserve the supported public source evidence and retrieval provenance needed to explain a result. Never store credentials in provenance, logs, API payload records, or SQLite.
- Identify tick-count volume as tick count. Never present it as exchange-traded volume or futures-contract volume. If volume meaning is unknown, label it unknown or omit it.
- Never invent, fill, interpolate, or forward-fill missing candles. Represent gaps as missing or unverified evidence.
- Never switch providers silently. Any comparison source must remain separately identified and cannot repair another source's gaps without an explicit, visible comparison policy.
- Never silently resample 1H or smaller bars into 4H. A 4H view requires a verified native 4H source and policy; otherwise show **unsupported timeframe**.
- Show stale data and unavailable data clearly, including the source timestamp when one exists. Do not let application-open time stand in for market freshness.
- Keep the existing UTC, timeframe, candle-status, revision, and instrument-identity validations. Any future provider-specific differences require deliberate contract and policy versioning.

## Quota and charge protection

- Respect documented per-minute, daily, and monthly provider quotas. Track usage conservatively when a provider exposes limits or rate-limit headers.
- Cache only when that provider's current terms permit it, and retain data only within the provider's permitted scope and period.
- Stop requests when a quota is exhausted or the provider returns a quota/rate-limit response. Show **quota exhausted** and wait for the documented reset or explicit user action.
- Do not use aggressive retry loops, concurrent polling bursts, or multiple accounts to evade limits. Honor `Retry-After` and provider-specific backoff instructions.
- Do not configure paid fallback, automatic plan upgrades, automatic billing, or overage usage. Provider failure must never trigger a paid request path.
- Before adding any service or feature, document its recurring cost and confirm it remains $0/month under the chosen plan. If that cannot be established, the feature remains disabled.

## AI privacy and credentials

- Do not add a paid AI API integration. Manual ChatGPT interpretation is optional and outside the application's runtime data pipeline.
- Do not send provider data to any third-party AI service unless the provider's applicable terms, including upstream pass-through terms, permit that use. SiftingIO private inference permission is unresolved and must be confirmed before sending its data.
- Do not use provider market data to train, fine-tune, evaluate, or augment AI models. Do not create a training corpus from provider data.
- Keep API keys backend-only, out of frontend `VITE_` values, source control, browser bundles, request URLs, logs, SQLite, test fixtures, and error details. Never print or expose credentials.
- Manual interpretation must not make the application dependent on an AI service or turn AI output into unverified market evidence. The user must be able to review the source data and analysis without AI.

## Required failure states

Future integrations must distinguish these states instead of treating them as valid data:

| State | Required behavior |
| --- | --- |
| `provider_unavailable` | Stop or defer requests according to provider guidance; retain the last permitted observation with its timestamp and mark it unavailable/stale as appropriate. |
| `invalid_response` | Reject the response from trusted analysis, preserve only permitted diagnostic evidence, and show that the source response could not be validated. |
| `quota_exhausted` | Stop calls to that provider until its quota resets or the user explicitly requests a permitted next action. Never upgrade or use a paid fallback. |
| `stale_data` | Show the observation's source time and stale status; do not label it current or advance its timestamp. Freshness thresholds require verified source behavior. |
| `insufficient_evidence` | Withhold a directional conclusion when evidence is missing, stale, contradictory, unsupported, or insufficient. Never invent prices, candles, confidence percentages, or price targets. |
| `unsupported_timeframe` | Show that the selected interval is unavailable for the selected source. Do not substitute another interval or resample into 4H. |
| `permission_not_confirmed` | Do not fetch, persist, or send the affected provider data for the unconfirmed use. Keep the corresponding feature disabled. |

## Unresolved issues

The following remain open and cannot be inferred from this policy:

- Whether SiftingIO permits personal historical data to be retained in local SQLite, and under what retention/deletion conditions.
- Whether SiftingIO permits private inference through a third-party AI service for this use case.
- Whether SiftingIO historical responses include a forming candle or how candle finalization is indicated.
- Whether SiftingIO can revise historical bars and how such corrections are communicated.
- Whether any free provider offers native XAUUSD 4H spot candles suitable for this project.
- Whether any currently free provider plan will remain available long term.

These questions must be resolved or explicitly left unsupported before the dependent feature is enabled.
