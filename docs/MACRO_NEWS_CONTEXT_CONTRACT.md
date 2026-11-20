# Macro, calendar, news and sentiment context contract

Status: **IMPLEMENTED; synthetic processing VERIFIED; production source integrations BLOCKED by source eligibility evidence.** Contract v1 is provider-agnostic and is not wired to a live feed.

## Contract and processing

`backend/app/data/context.py` defines immutable Pydantic records for scheduled economic events, published event values, macro observations, news reports, sentiment observations and source attribution. Every record separates event/publication time from retrieval time and has a revision identity. Scheduled events may have no `actual`; actual/forecast/previous values are not inferred from schedules. Actual macro values require an explicit publication time and decimal text.

Source eligibility is an input reference/state, not something this module adjudicates or grants. A source can be treated as usable only when its existing reviewed eligibility record says `eligible`, attribution is present, and permission evidence references are supplied. `process_context` also requires an explicit feed-level completeness decision and evidence reference, then applies caller-supplied, versioned per-feed retrieval-age and publication-delay limits. Per-row validity alone cannot prove whole-feed completeness. Missing limits, permissions, completeness, or source records produce explicit `unavailable`, `unverified`, `incomplete`, or `stale` state. Exact same-source news duplicates collapse by source/topic/publication/headline identity; opposing directional claims for one topic make the news feed `conflicting` rather than preferring one report.

`ContextPolicy` has no default age or delay thresholds. Thresholds and completeness references in tests are synthetic-only and do not represent a real feed. Calendar closure/holiday interpretation is not inferred from a missing event. The context layer supports CPI/inflation, Fed decisions and publications, Treasury yields, employment, DXY context, gold/dollar/central-bank/geopolitical news, and sentiment without assigning real provider eligibility.

## Current source eligibility

No provider status is changed by this implementation. Twelve Data, SiftingIO bars/calendar, Treasury and DXY remain **UNVERIFIED**; BLS CPI and Board-authored Fed material remain **CONDITIONALLY ELIGIBLE**, not activated. No news or sentiment source has been established. Account rights, applicable upstream terms, exact attribution, retention, AI-processing rights, completeness/correction semantics and entitlement evidence remain required as recorded in `AUTHORITATIVE_MARKET_DATA_SOURCE_ELIGIBILITY.md`. All external feeds therefore remain unavailable to the application.

## Verification

`backend/tests/test_macro_context.py` verifies scheduled versus published values, publication-time requirements, unverified and incomplete inputs, missing policy, stale publication, exact duplicate collapse and conflicting reports. The end-to-end provenance test passes an empty/unavailable context snapshot and verifies the analyst returns NO TRADE without invoking a completion provider.

These tests establish synthetic contract behavior only. They do not validate source rights, macro correctness, calendar completeness, news credibility or live freshness.
