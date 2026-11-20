# Milestone 5C — Evidence-First AI Analysis Contracts

**Status:** Backend contracts and offline validation only. No AI provider, market-data provider, scheduled task, analysis engine, database, or frontend integration is active. Stage 5B provider configuration, selection, secret resolution, mocked adapter, and usage safeguards remain unchanged.

## Contract architecture

`backend/app/ai/evidence.py` defines the versioned `EvidencePacket` and its contents. `backend/app/ai/contracts.py` defines the provider-independent `AnalysisResponse`, deterministic sufficiency assessment, deterministic data-gate `NO TRADE`, and `validate_response()`. `backend/app/ai/__init__.py` exposes these as package-level contracts. Pydantic models are frozen and reject undeclared fields. Packet and response schema versions are `1.0`.

### Evidence packet

An `EvidencePacket` carries an analysis ID, aware UTC analysis/retrieval instants, `Asia/Qatar` display zone, canonical XAUUSD instrument, source identities, requested timeframes, timeframe records, evidence records, and quality flags. Each source records its own retrieval time, price normalization method, and source precision (which can remain explicitly unknown). Timeframes are `1D`, `4H`, `1H`, `15M`, and `5M`; every requested timeframe has exactly one record. Unavailable and unsupported timeframes have explicit states and contain no trusted candles.

An instrument identity binds canonical `XAUUSD` to a qualified `instrument_id` and type: OTC spot, broker CFD, COMEX GC contract month, or LBMA AM/PM benchmark. Each source keeps its own provider ID, feed ID, series ID, provider symbol, retrieval time, and decimal-normalization provenance. An available timeframe selects exactly one source series, so candle rows from different feeds cannot be blended. Instrument type qualifiers are validated in the canonical ID. If any source identity conflicts with the packet instrument, the packet remains representable for audit, but sufficiency fails and its evidence cannot support a response. A source conflict flag also fails the gate.

Each candle contains its source ID, timeframe, UTC opening and optional closing instants, forming/closed/unverified state consistent with retrieval time, exact-decimal OHLC, explicit optional volume value/type, quality flags, and origin (`native` or `aggregated`). A missing close boundary requires `unverified` state. OHLC ordering and volume semantics are checked. Tick count is a distinct type and is never recast as traded volume. Volume evidence records also require an explicit volume type (`tick_count`, exchange-traded, contract, unknown, or unspecified). Binary floats are rejected at this contract boundary; normalize source numbers to decimal text/`Decimal` with provenance before constructing the packet.

Aggregated candles cannot be mislabeled native. The current contract accepts only explicit 4H aggregation from four present, consecutive, closed, native, UTC-aligned 1H candles, and checks the 4H open/high/low/close and boundaries against those inputs. An included aggregate volume must equal all four present source values of the same explicit type. No aggregation function or native 4H provider capability is implemented. This check validates a supplied aggregate's traceability; it does not create or authorize one.

Evidence records have packet-unique caller-supplied IDs, type, description, optional exact numeric value and unit, timeframe, UTC observation time, source IDs, candle references, quality status, and a calculation-method reference. Timeframe sections list their evidence IDs, and packet validation resolves every reference. All observation types except directly observed volume require a method reference. Supported interface categories include trend/directional structure, swing highs/lows, BOS/CHoCH, liquidity levels/sweeps, FVG, order blocks, EMA/RSI/ATR, explicit volume, sessions/kill zones, support, and resistance. The contracts do not implement calculations or claim that a method is correct. Invalid OHLC is rejected; a quarantined packet can report invalid-candle quality flags without carrying invalid candles as trusted evidence.

Evidence IDs must be supplied by the deterministic producer and remain stable for equivalent source observations/calculations. Uniqueness and reference resolution are validated within a packet; cross-packet ID persistence is a producer responsibility. Packet timestamps do not invent source freshness. `FreshnessPolicy` is optional and unset by default because no universal age limit has been approved.

### Deterministic evidence sufficiency

`assess_sufficiency()` produces explicit statuses for sufficient, partial, stale, missing timeframes, conflicting instrument identity/feed, invalid candles, unsupported derivations, forming/unverified candles, and incomplete multi-timeframe context. Missing candle candidates, duplicates, and outliers produce a partial gate. Explicit stale quality or a configured per-timeframe age limit produces a stale gate. No AI request is needed to evaluate these conditions.

`deterministic_no_trade()` returns neutral bias and `NO TRADE`, with the fixed rationale `NO TRADE — DATA NOT VERIFIED`. It requires an insufficient packet, carries the gate reasons in `missing_information`, and has no provider metadata. It does not calculate an entry, stop, target, or signal.

### Response contract and validation

`AnalysisResponse` holds overall bias (`BULLISH`, `BEARISH`, `NEUTRAL`), stance (`BUY SETUP`, `SELL SETUP`, `WAIT`, `NO TRADE`), evidence-cited rationale, per-requested-timeframe direction/structure/support/conflict/warnings, setup conditions and optional evidence-backed price levels, qualitative confidence, conflicts, missing information, avoid-trading reasons, provider metadata, and schema/validation statuses. Numeric claim references must resolve to the exact value on their cited evidence record. Every market statement is represented as a `Claim` with evidence IDs. Claims have a purpose: ordinary market facts require verified evidence; data-quality warnings and conflict descriptions may cite non-verified evidence only in their designated sections and cannot then be used as market support. Confidence explanations reject percentages. Unsupported news/headline/sentiment statements are rejected because this evidence schema has no such source contract.

Provider metadata is a separate field: provider/model/protocol/request ID, generated UTC instant, optional reported token counts/cost, and metadata validation state. No metadata is inferred from a model answer. A model-origin report requires it; the deterministic gate omits it. Provider-reported usage/cost is only represented when supplied and is not independently verified here.

`validate_response(packet, response)` returns a separate `ResponseValidation`; callers must treat this result as authoritative and reject invalid results. It checks schema/analysis identity, timeframe coverage, evidence references and scope, instrument identity, evidence quality, numeric values and price-level support, directional level ordering, risk/reward, evidence sufficiency warnings, and separation of provider metadata. Entry zones must cite exact verified price records. Long levels must satisfy stop < entry zone < target, with inverse ordering for short. When entry, stop, and target are all present, risk/reward is required and calculated from the entry-zone midpoint; the reported ratio must match reward/risk rounded to four decimal places using `ROUND_HALF_UP`. A ratio without all three supported levels is invalid.

Validation is deterministic and conservative, but cannot prove that a natural-language interpretation is semantically correct simply because it cites a valid record. The AI response remains an interpretation, not a verified market fact. Numeric values placed in prose require a matching structured numeric evidence reference or supported price level. No independent live-data fact checking is available.

## Synthetic test coverage

`backend/tests/test_ai_evidence.py` uses only synthetic values and verifies accepted bullish, bearish, neutral/range, and NO TRADE responses; deterministic insufficient evidence; missing 4H; forming and stale evidence; configured freshness; conflicting instrument identities; unknown evidence IDs; unsupported levels and prose prices; wrong timeframe references; inconsistent entry/stop/target; incorrect/missing risk/reward; unsupported news/sentiment; missing provider metadata; duplicate evidence IDs; float price and invalid OHLC rejection; explicitly typed tick count; and valid UTC-aligned aggregated 4H provenance. Existing provider infrastructure and market-data tests remain separate.

## Limits and unresolved decisions

- No AI response is created from a provider call, and no raw model JSON parser or live inference route is connected.
- No universal candle freshness thresholds, session calendars, market-news source, or indicator parameters are defined.
- Deterministic calculations and stable evidence-ID generation remain future work; method strings alone do not prove a calculation.
- Evidence producer policy must decide when a source/feed conflict is meaningful and set the explicit quality flag.
- Cost and token metadata are declarative provider fields; account billing is not audited.
- The four-decimal risk/reward display precision and entry-zone midpoint convention are this schema's deterministic calculation policy, not a trading recommendation.
- A verified NO TRADE gate means required evidence checks failed; it is not a statement about future price direction.

## Verification and files changed

Focused evidence-contract tests: **18 passed**. Full backend suite: **133 passed**. `.venv/bin/python -m pip check`: no broken requirements. Frontend `npm run typecheck`, `npm test` (**9 passed**), and `npm run build`: passed. Graphify refreshed the code graph; SQL extraction remains unavailable because its optional parser is not installed. Tests are synthetic and no external calls were made; no credentials were read. No package/dependency or lock file changed.

Changed files:

- `backend/app/ai/evidence.py`
- `backend/app/ai/contracts.py`
- `backend/app/ai/__init__.py` (exports only; Stage 5B provider behavior unchanged)
- `backend/tests/test_ai_evidence.py`
- `docs/MILESTONE_5C.md`
- `graphify-out/.graphify_build_state.json`
- `graphify-out/.graphify_labels.json`
- `graphify-out/.graphify_labels.json.sig`
- `graphify-out/.graphify_labels.pending.json`
- `graphify-out/.graphify_root`
- `graphify-out/GRAPH_REPORT.md`
- `graphify-out/cache/stat-index.json`
- `graphify-out/graph.html`
- `graphify-out/graph.json`
- `graphify-out/manifest.json`

No frontend source, data provider, SQLite schema, migration, API route, credential/config value, or existing milestone document was changed.

## Rollback

Remove the two new modules and `backend/tests/test_ai_evidence.py`, remove the new exports from `backend/app/ai/__init__.py`, and remove this milestone record. Regenerate the derived graph from the rolled-back repository with `. .venv-graphify/bin/activate && graphify . --force --no-viz`. Stage 5B provider modules, `backend/app/config.py`, provider configuration, market-data code/schema, and existing milestone records require no rollback. Run the backend tests and dependency check after rollback. No database or external state was created.

## Stop boundary

No live inference, market-data request, external network request, credential access, scheduled analysis, dashboard work, or trading functionality occurred. AgentRouter / GPT-6.1 Sol remains unverified and disabled. Stage 5D requires separate explicit authorization.
