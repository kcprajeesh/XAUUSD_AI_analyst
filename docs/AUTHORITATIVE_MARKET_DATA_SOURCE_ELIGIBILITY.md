# Authoritative market data source eligibility assessment

**Assessment date:** 2026-11-18
**Status:** Research and documentation complete; no provider is ELIGIBLE for application use.
**Scope:** Public official documentation and terms only. No live API calls, credentials, subscriptions, configuration changes, provider activation, or database access were used.

This assessment applies the gates in [Phase 2.5.18 architecture closure](PHASE_2_5_18_ARCHITECTURE_CLOSURE.md#provider-eligibility-gates) and the approved P-01/P-02 retention rules. It does not grant a license, establish account entitlements, or amend deferred DEC-04/H4-03. Provider terms, plan limits, and availability can change; recheck the linked sources and applicable account/order documents before any activation.

## Repository inventory

Repository inspection found:

| Source or integration | Present use / proposal | Assessment treatment |
|---|---|---|
| Twelve Data | Offline XAU/USD normalizer and documented intended source; no HTTP implementation in that adapter | Assess as proposed XAU/USD OHLCV source |
| SiftingIO | XAU/USD request transport, synthetic/local staging, persistence and historical retrieval code; no production service wiring | Assess bars and snapshot independently; technical code is not eligibility evidence |
| SiftingIO economic calendar | Endpoint exists in vendor documentation, but no configured application feed was found | Assess as a documented candidate, not integrated |
| BLS | No repository provider/configuration | Assess as a possible primary CPI data source only |
| U.S. Treasury | No repository provider/configuration | Assess as a possible primary Treasury-yield source only |
| Federal Reserve | No repository provider/configuration | Assess as a possible primary Fed release source only |
| ICE U.S. Dollar Index | No repository provider/configuration | Assess as a possible proprietary DXY source only |

No dedicated gold-news/headline or market-sentiment provider is configured or proposed in the inspected source/docs. The UI panels and research requirements are placeholders, not sources. Lightweight Charts/TradingView is a charting library, not a market-data entitlement. OpenAI-compatible/AgentRouter references concern AI transport, not market, macro, news, or sentiment sources, and are outside this provider assessment.

## Decision summary

| Provider / dataset | Classification | Basis and remaining condition |
|---|---|---|
| Twelve Data XAU/USD OHLCV | **UNVERIFIED** | Official documentation supports the requested timeframe shapes, but access tier/category entitlement, applicable upstream terms, the approved 30-day raw-body retention, local normalized-history retention, and internal AI-processing scope are not established for this account/product. |
| SiftingIO XAUUSD historical bars | **UNVERIFIED** | Technical shape and cursor semantics are documented, but active plan/order-form and upstream rights must authorize the exact retention, internal AI processing, and use class. Current documented interval list omits 4H; no H4-03 policy may be inferred. |
| SiftingIO XAUUSD live quote/snapshot | **UNVERIFIED** | Product docs describe aggregate reference snapshots and timestamps, but account/upstream rights and durable retention/AI scope remain unconfirmed. It cannot replace verified whole OHLCV retrievals. |
| SiftingIO U.S. economic calendar | **UNVERIFIED** | Documented U.S. schedule API may provide event times, but vendor plan and upstream rights for storing/forwarding event data to AI are unresolved; its schedule is not a source for actual macro values or a complete news feed. |
| BLS public API — CPI candidate | **CONDITIONALLY ELIGIBLE** | Its own API terms support public data reuse subject to attribution/date/access caveats and API limits. Before integration, pin exact CPI series and API version, honor current limits, preserve the required caveat/access date, and verify series revision/observation semantics. No data have been retrieved. |
| U.S. Treasury Daily Treasury Par Yield Curve — yields candidate | **UNVERIFIED** | Official publication, feed pagination, and history are documented, but this review did not establish explicit reuse/retention rights under Treasury terms. It is a daily indicative par curve, not an intraday Treasury-yield feed. |
| Federal Reserve FOMC publications — Fed catalyst candidate | **CONDITIONALLY ELIGIBLE** | The Board states its website information is public domain unless otherwise indicated and requests source citation. Conditions remain to filter out separately copyrighted material and establish canonical publication retrieval, completeness/update semantics, and application evidence handling. |
| ICE U.S. Dollar Index (USDX/DXY) | **UNVERIFIED** | ICE’s official FAQ establishes proprietary administration and indicative real-time cadence, not a license to retrieve, retain, or analyze the index. A suitable ICE/vendor license and technical feed contract are needed. |

**ELIGIBLE:** none. **INELIGIBLE:** none established from reviewed evidence. UNVERIFIED means insufficient documentary support; it is not a finding that a provider refuses permission. CONDITIONAL eligibility is limited to BLS source content under its published API terms, and does not mean the application integration is implemented or operationally verified.

## Gate findings by provider

### Twelve Data — XAU/USD market data

**Classification: UNVERIFIED.** The offline adapter’s existence and historical user-supplied account/support note do not prove current subscription rights. No account was inspected and no endpoint was called.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw response | Terms §2.2 allow access, processing, and storage for internal use subject to subscription/add-on scope; §§2.3(g), 16 cap storage by documented/subscription and upstream restrictions. This does not prove the 30-day raw-body retention class is permitted for XAU/USD. |
| Store normalized data | §2.2 permits internal processing/storage and derived data that cannot reconstruct source data; third-party market data may have separate licensing terms and fees under §§3.1–3.3. Specific XAU/USD rights remain unresolved. |
| Attribution | The attribution guide says internal/private analytics and dashboards do not require Twelve Data attribution; public display/research/report distribution can require visible attribution and exchange-specific rules. Preserve source attribution in evidence regardless. |
| Internal/AI analysis | Individual plan guidance says Pro permits programmatic API use for internal AI assistants; plan entitlement is not evidenced. This is not a blanket right to send data to an arbitrary external model or retain prompt/response bodies for 30 days. That exact processing/data-flow scope requires confirmation. |
| Freshness/history | Historical support says depth varies by instrument/interval; use `/earliest_timestamp` to discover it. Intraday data are generally multiple years for most symbols, but XAU-specific depth has not been verified. Terms disclaim accuracy, completeness, and timeliness; no SLA for this proposed dataset is established here. |
| Pagination/completeness | Historical price guidance lists `outputsize` up to 5,000 and supports date-range retrieval, but does not prove that a series response covers every expected bar. Project completeness still requires source-specific terminal/range evidence and correction/finality handling. |
| Shape/timeframes | Official interval guidance lists 5min, 15min, 1h, 4h and 1day, matching the desired labels. Timestamp/daily boundary, OHLCV token fidelity, XAU-specific category and entitlement require confirmation before production use. |

Official evidence, accessed 2026-11-18: [Terms of Use §§2.2–3.3, 8.3 and 16](https://twelvedata.com/terms) (updated 2026-01-01); [commercial and personal usage — Individual plans](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage); [attribution guidelines — internal/private and public display](https://support.twelvedata.com/en/articles/12647398-attribution-guidelines-for-using-twelve-data); [historical prices — intervals, historical-depth caveat, `/earliest_timestamp`, and outputsize](https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices); [getting historical data — date-range behavior](https://support.twelvedata.com/en/articles/5214728-getting-historical-data); [XAU/USD market page](https://twelvedata.com/markets/300755/commodity/xau-usd/historical-data).

**Required to clear:** provider/account confirmation of the XAU/USD product and plan, including upstream restrictions; written confirmation that 30-day raw body storage and normalized local history fit the plan; confirmation of internal inference to the configured external AI provider and 30-day AI evidence retention; verify XAU-specific earliest date, timestamp/volume semantics, full-range pagination, updates/corrections and attribution rules. No upgrade or purchase is implied.

### SiftingIO — XAUUSD bars and quote

**Classification: UNVERIFIED** for both endpoints. The vendor’s technical documentation is useful evidence of interface behavior, but a free API key or API availability does not establish the required license.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw response | Terms §§4–5 make use subject to active plan/order form and upstream pass-through terms; §12 requires deletion after termination. They do not establish permission for the approved 30-day raw-body retention for this account. |
| Store normalized data | §9 forbids standalone historical-data redistribution/publication absent written authorization. Internal analysis may be within the plan scope, but exact local archive/derived output rights and upstream restrictions must be confirmed. |
| Attribution | Terms §9 require retaining any attribution/source identifier/disclaimer required by service/agreement; product docs describe aggregation, but no exact required app attribution text/placement was found. |
| Internal/AI analysis | Internal-business license is plan-bound. Terms §9 restrict training/fine-tuning/evaluating/augmenting third-party AI models or substantially data-derived outputs; they do not clearly settle ordinary inference through the configured external AI provider. Obtain a written determination; no external model training is allowed by project policy. |
| Freshness/history | Commodity product says aggregated spot/reference values, not a particular venue quote; quote docs expose source time. Product page advertises history depth but actual per-series completeness is not established by a live retrieval. Quote freshness must be judged from the returned source timestamp; no product-level stale threshold is adopted here. |
| Pagination/completeness | Historical bars use inclusive start/end bounds, opaque cursor pagination, limit up to 2,000 and `next_cursor` continuation; documented absence at tail/short terminal response is necessary but does not alone prove no missing source buckets or correction finality. Reconcile returned range and per-page evidence. |
| Shape/timeframes | Bars expose UTC bucket-open timestamp and OHLC fields; `v` is tick-count volume, not exchange-traded quantity. Documented commodity intervals include 1m, 5m, 15m, 30m, 1h, 1d, 1w and 1mo; 4h is not listed. Thus native evidence does not cover the project’s H4 requirement. Do not derive production H4 while H4-03 is deferred. |

Official evidence, accessed 2026-11-18: [Terms of Use §§4–5 and 9–12](https://sifting.io/legal/terms-of-use) (effective 2026-04-26, updated 2026-05-09); [XAUUSD product and coverage description](https://sifting.io/symbols/commodities/XAUUSD); [commodities historical bars API](https://sifting.io/docs/historical/commodities) (request bounds, `limit`, cursor, response fields and interval list); [quote API](https://sifting.io/docs/live/quote); [commodity product](https://sifting.io/product/commodities); [error and entitlement behavior](https://sifting.io/docs/errors). The bar endpoint docs were not directly rendered by the research browser on this access; the linked official page is cited as the source to recheck before implementation. The provider’s official product page describes this price as a single aggregate, with tier-dependent update/history characteristics.

**Required to clear:** applicable active plan/order form and all upstream pass-through terms must affirmatively permit XAUUSD retrieval, the 30-day raw / normalized retention, and intended internal AI inference; obtain exact attribution rules; confirm rate/usage entitlement without add-ons; document source timestamp and correction semantics; prove pagination/range completeness in a future authorized integration; keep 4H unavailable unless a separate H4-03 decision authorizes a policy.

### SiftingIO — U.S. economic calendar

**Classification: UNVERIFIED.** This is a documented candidate only; no application configuration or live request was found.

The official endpoint is described as upcoming U.S. CPI, NFP, FOMC, GDP and other scheduled releases, sourced from official agency calendars. Documentation describes UTC RFC3339 `scheduled_at`, filtering by date, limits/pagination, and a bounded date range; examples may have null actual/consensus values, so the schedule cannot be represented as actual release data. A vendor “impact” value is a vendor classification, not an official agency assessment. The terms, upstream pass-through, retention, attribution, AI-inference scope, active entitlement, correction behavior and completeness all remain unresolved under the same SiftingIO terms above.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw and normalized data | Same plan/order-form and upstream pass-through limits apply as SiftingIO bars; permission for 30-day body retention and local normalized event history is unconfirmed. |
| Attribution | Preserve source and vendor IDs; no endpoint-specific exact displayed attribution requirement has been established. |
| Internal/AI analysis | Internal plan use may apply, but external AI inference remains ambiguous under the vendor’s AI restrictions; no third-party training. |
| Freshness/history | Upcoming U.S. scheduled events only, default next 30 days (documentation); not a historical macro series and not a freshness guarantee for released actuals. |
| Pagination/completeness | Endpoint documents bounded date filters and paged responses; exact eligibility still requires following terminal pagination and recording range/page evidence. Revisions/reschedules need explicit correction handling. |
| Data shape | Scheduled time is documented as UTC RFC3339. Actual/consensus may be null; vendor impact is not an official agency label. No gold headlines or sentiment shape is provided. |

Official evidence, accessed 2026-11-18: [Economic Calendar overview](https://sifting.io/docs/economic-calendar); [List economic-calendar endpoint](https://sifting.io/docs/economic-calendar/list); [SiftingIO Terms of Use §§4–5 and 9–12](https://sifting.io/legal/terms-of-use). Calendar evidence could eventually support event risk timing only. It does not provide a confirmed full economic dataset, earnings/news headlines, market sentiment, or gold news.

### BLS public API — CPI research candidate

**Classification: CONDITIONALLY ELIGIBLE** as an authoritative source of published BLS data under the public API terms; not integrated or activated.

BLS states that public API users should cite the retrieval date and include the statement that BLS cannot vouch for data or analyses after retrieval; users may not modify or falsely represent content while citing BLS; API limits may apply. Separately, the BLS copyright notice states its published content is public domain, except previously copyrighted photographs/illustrations, and asks users to cite BLS. This supports retaining public BLS CPI observations and internally analyzing them, including AI-assisted inference, while preserving the required caveat and source attribution. The API’s official guide says v1 is public without registration while v2 requires registration and allows more frequent/data-rich access. These terms do not guarantee continuous service. The assessment covers BLS CPI observations only, not every possible CPI-derived measure or release document.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw and normalized data | BLS-published content is public domain except identified third-party photos/illustrations; API terms say secondary use is not technically controlled. For CPI response data, the approved retention classes are compatible with the published reuse terms, subject to observing terms/caveat. |
| Attribution | Cite BLS and retrieval date; include BLS’s exact post-retrieval quality/timeliness caveat. Do not use the BLS logo. |
| Internal/AI analysis | No API end-use restriction is stated for public series data; public-domain text can be internally analyzed. Exclude non-BLS copyrighted assets. |
| Freshness/history | Public API returns published historical time series; it is not a real-time feed. API version/series update and revision semantics must be pinned and retained. |
| Pagination/completeness | API limits apply; request-size/period limits and result completeness need to be enforced for the exact series/version. |
| Data shape | API guide documents JSON/XLSX and series requests. Exact CPI series ID, units, adjustment, period labels and release/vintage fields remain to be specified. |

Official evidence, accessed 2026-11-18: [BLS API Terms — Secondary Use, Citing Data, Modification, Right to Limit](https://www.bls.gov/developers/termsOfService.htm); [BLS Public Data API guide — versions and returned formats](https://www.bls.gov/developers/); [BLS public-domain notice and exceptions](https://www.bls.gov/bls/linksite.htm).

**Conditions before integration:** identify exact CPI series, seasonal adjustment and units; use allowed API/version and current limits; store retrieval date and the required caveat with the evidence; preserve published revisions/vintages rather than overwrite; establish source release timestamp and full requested-series completeness; ensure only public BLS content enters retention/AI pipelines. BLS provides CPI observations, not a live XAU price, calendar-wide event coverage or gold sentiment.

### U.S. Treasury — daily yield curve research candidate

**Classification: UNVERIFIED.** Official material establishes what the series represents and how pagination is described, but this review did not locate an explicit reuse/retention license applicable to this application.

The Treasury describes its Daily Treasury Par Yield Curve Rates as daily rates and publishes a machine-readable XML feed. Its feed documentation says page numbering is zero-based, the first page defaults to 300 rows, callers can iterate until `<entry>` has no data, and daily par-yield-curve data are available from 1990. The published par curve is an indicative daily observation, not an intraday executable/current market yield; this source cannot satisfy an intraday yield freshness requirement. The feed’s reported range and terminal mechanics are documented but still need response-level integrity and revision checks.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw and normalized data | No explicit applicable reuse/retention term was established in this review; the feed being public does not itself grant storage rights. |
| Attribution | No attribution requirement was confirmed; keep source name/URL and retrieval timestamp in provenance until official reuse terms are reviewed. |
| Internal/AI analysis | No explicit permission for retention or disclosure to an AI service was established. |
| Freshness/history | Official yield series is daily; daily par-yield-curve observations are documented from 1990. Not intraday/current continuously. |
| Pagination/completeness | Official XML feed provides zero-based pages, 300 rows by default on page 0, and an empty `<entry>` terminal signal. Implementations must fetch through terminal, validate date coverage and preserve revisions. |
| Data shape | XML and daily dated maturities/rates; source observation/time meaning and correction policy still require a versioned contract. |

Official evidence, accessed 2026-11-18: [Interest Rate Statistics — rate series](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics); [Daily Interest Rate XML Feed — pagination and data availability](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed).

**Required to clear:** confirm applicable reuse/retention rights and attribution with Treasury’s official terms; define the chosen maturity/curve series, release timestamp and intended freshness semantics; test all-page retrieval and corrections in an authorized integration. This source does not provide CPI, DXY, headlines or current intraday yields.

### Federal Reserve — FOMC publication research candidate

**Classification: CONDITIONALLY ELIGIBLE** for Board-authored public website information, not separately copyrighted third-party material; not integrated or activated. The Board’s disclaimer says, unless otherwise indicated, website information is public domain, may be copied and distributed without permission, and should cite the Board. Materials identified as non-Board still require permission from their source. This supports storing and internally analyzing eligible Board-authored content, subject to the retention policy. The release guide alone does not settle machine-readable retrieval or completeness.

The Fed says policy statements are released after meetings, minutes three weeks after regularly scheduled meetings, and press conferences/quarterly projections accompany applicable meetings. These are publication-cadence facts, not an API freshness guarantee or a license for automated content retention/AI forwarding.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw and normalized data | Board-authored website information may be copied/distributed under the disclaimer, unless otherwise indicated; keep 30-day raw bodies only for clearly Board-authored material, excluding marked third-party content. |
| Attribution | Cite the Board as source; no Board logos/seals. Third-party works carry separate rights. |
| Internal/AI analysis | Public-domain Board text can be retained and internally analyzed; no express AI-specific clause was found. Preserve attribution/context when sending evidence to an approved model; no third-party embedded material. |
| Freshness/history | Post-meeting statements and minutes released three weeks after regular meetings; this is event publication timing, not a continuous freshness SLA. |
| Pagination/completeness | No complete machine-readable FOMC archive/pagination contract was established in this review; full document set and revisions need a defined source traversal. |
| Data shape | Official pages and publications are available, but no selected structured schema or timestamp contract for machine ingestion is established. |

Official evidence, accessed 2026-11-18: [Federal Reserve FAQ — sources and publication timing for FOMC decisions](https://www.federalreserve.gov/faqs/federal-open-market-committee-fomc-not-public.htm); [Federal Reserve Disclaimer — General Disclaimer and Copyright/trademark](https://www.federalreserve.gov/disclaimer.htm).

**Conditions before application eligibility:** select canonical FOMC statements/minutes/pages and a structured retrieval method; exclude or separately license every identified non-Board copyrighted asset; cite the Board; specify revision/update detection and archive completeness; retain publication time separately from event effective time. No separate Fed provider is configured.

### ICE U.S. Dollar Index — DXY candidate

**Classification: UNVERIFIED.** ICE’s official FAQ says ICE Futures U.S. compiles, maintains, determines and weights the U.S. Dollar Index and calculates/disseminates it; the index is calculated approximately every 15 seconds from multi-contributor spot prices. This does not grant a right to use an ICE/vendor feed or retain its data. The FAQ is dated 2015, so confirm current terms and methodology before use.

| Gate | Evidence-backed finding |
|---|---|
| Retrieve/store raw and normalized data | No data license/retention agreement was established; index/feed availability is not permission. |
| Attribution | Not determined; obtain vendor/index-specific required notices and display wording. |
| Internal/AI analysis | Not determined; no evidence supports internal analysis, external inference, or retention. |
| Freshness/history | ICE FAQ describes approximately 15-second calculation from multi-contributor spot prices; historical limits and current entitlement are unknown. |
| Pagination/completeness | No licensed API/feed contract or history pagination documentation was established. |
| Data shape | Official FAQ describes the index calculation, but not a permitted feed schema, exact timestamps, bar intervals or corrections. |

Official evidence, accessed 2026-11-18: [ICE USDX FAQ — index authority and calculation cadence](https://www.ice.com/publicdocs/futures_us/ICE_Dollar_Index_FAQ.pdf), especially “What is the U.S. Dollar Index?” and “How is the U.S. Dollar Index calculated?” A [current ICE data catalog](https://developer.ice.com/fixed-income-data-services/catalog/ice-data-indices-currency-indices) identifies ICE Data Indices’ currency-index product family.

**Required to clear:** licensed source and product, permitted internal display/analysis, retention and AI terms, attribution, exact real-time/delayed entitlement, historical depth and pagination/correction mechanics. Do not silently substitute a different broad-dollar index for DXY.

## Minimum useful research-source set and missing coverage

There is **no verified minimum set available today**: no market feed is classified ELIGIBLE, and no live source integration has been verified. A candidate research basket after rights and engineering gates are cleared would be:

1. One permitted XAUUSD OHLCV source for native Daily, 1H, 15M and 5M (SiftingIO documents these intervals; Twelve Data also documents all requested intervals, subject to the unresolved product/retention terms). Keep 4H unavailable pending H4-03 or a separately evidenced native source policy.
2. BLS CPI for actual inflation observations, with retrieval-date provenance and the required caveat.
3. U.S. Treasury daily par yields for longer-context nominal rates, clearly labeled daily/indicative.
4. Federal Reserve primary releases for policy decisions and statements.
5. A licensed ICE DXY feed if actual DXY is required; no verified substitute is approved.

This basket still does not supply verified gold-related headlines or broad market sentiment. SiftingIO’s calendar could add upcoming U.S. scheduled events only after license, retention, AI and completeness terms are settled; it does not remove the need for BLS actual values or primary Fed/Treasury evidence. Missing coverage must remain explicitly unavailable in the UI and analysis. No provider in this list is activated by this document.

## Next eligibility and engineering gates

- Obtain documentary provider/account/order-form evidence for XAUUSD license scope, local retention, internal AI inference, attribution, plan quotas, and upstream rules, without buying or activating anything. Unclear permission means the feed stays unavailable.
- Before any provider adapter is connected, translate each cleared provider’s official request, timestamp, pagination, range, correction and volume behavior into a versioned provider eligibility record; do not change the current provider configuration as part of this assessment.
- Add source-specific synthetic contract fixtures for exact pages/range boundaries, empty/short/error pages, duplicate/corrected rows, provider timestamp semantics, calendar revisions and metadata. These tests may not claim live/source eligibility.
- Keep DEC-04 resource choices and H4-03 production policy deferred. Production migration, live credentials, subscriptions, provider activation and external AI data flow remain separately gated.

## 2026-11-20 official-source recheck (status-preserving addendum)

This addendum supplements the 2026-11-18 review; it does not replace its evidence history or change any eligibility classification. No account dashboard, order form, API key, provider endpoint, or market-data call was used.

| Candidate | Newly checked official evidence | Personal XAUUSD pipeline consequence | Classification |
|---|---|---|---|
| Twelve Data XAU/USD | Current individual pricing lists commodity market data on Grow and higher plans, not Basic; its personal-use support page says Pro permits programmatic use for internal AI assistants. `/time_series` documentation supports `1day`, `1h`, `15min` and `4h` among its intervals; support documentation says depth varies by symbol and interval and directs users to `earliest_timestamp`. | Potential Daily/1H/15M fit, but the actual account tier, XAU/USD access, applicable upstream rights, caching/retention and whether the intended AI path is covered by the account’s terms are not established. No paid plan is assumed or selected. H4 remains disabled under H4-03. | **UNVERIFIED** |
| SiftingIO XAUUSD | Current product/pricing pages describe XAUUSD historical bars at 1m, 5m, 15m, 30m, 1h and 1d among other intervals, cursor pagination, UTC bucket timestamps, and tick-count (not traded) volume. Pricing/changelog pages state full available history on all tiers, but the XAUUSD product page also describes tier-dependent history/update characteristics. Terms §§4–5 and 9–12 pass upstream rights through, scope use to an active plan and restrict data storage/AI uses unless plan/order terms authorize them; termination requires deletion. | Potential Daily/1H/15M fit, but product wording on depth, plan entitlement, rate limits, personal-use classification, local retention after termination, and ordinary inference by an external AI service are not resolved for this account. The Terms use “internal business purposes” while pricing mentions personal side projects; obtain provider clarification for this personal use. No live quote can substitute for validated OHLC retrieval. H4 is not documented. | **UNVERIFIED** |
| BLS / Federal Reserve / U.S. Treasury / ICE DXY / SiftingIO calendar | No eligibility-changing account, license, or feed evidence was found in this recheck; the existing candidate-by-candidate findings below remain controlling. | Keep their existing source-specific statuses and conditions. Scheduled events remain distinct from published values; no gold-news or sentiment provider is established. | Unchanged |

Official sources accessed 2026-11-20: [Twelve Data individual pricing](https://twelvedata.com/pricing), [Twelve Data personal and commercial usage](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage), [Twelve Data historical prices](https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices), [Twelve Data time-series documentation](https://twelvedata.com/docs/ai/ai-data-assistant), [SiftingIO XAUUSD product](https://sifting.io/symbols/commodities/XAUUSD), [SiftingIO commodity API/product](https://sifting.io/product/commodities), [SiftingIO pricing](https://sifting.io/pricing?market=commodities), [SiftingIO changelog](https://sifting.io/changelog), and [SiftingIO Terms of Use](https://sifting.io/legal/terms-of-use).

**No source is ELIGIBLE.** The recheck establishes published product claims only; it cannot establish this account’s plan, permission, upstream pass-through rights, or exact source response behavior. Do not activate either provider on this evidence.

## Evidence method and limitations

Links in the original assessment were checked 2026-11-18; the supplementary links above were checked 2026-11-20. The reviewed sections/pages are named beside the findings. Evidence establishes only what those pages state, not individual account entitlement, unlinked upstream agreements, jurisdiction-specific legal conclusions, actual response behavior, or current production availability. No provider API request, key, paywall bypass, or commercial plan purchase was used. All technical conclusions remain subject to version/terms recheck before activation.
