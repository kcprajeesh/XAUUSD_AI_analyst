# Phase 2.5.18 — architecture contract closure

Date: 2026-11-18. Status: approved policy decisions P-01 through P-07 recorded; isolated synthetic archive/retrieval implementation authorized and in progress. DEC-04 and H4-03 remain deferred. Production migration, live provider activation, external spending and production service activation remain unauthorized.

## Authoritative records and actual state

Read the complete `MILESTONE_5E_3_PHASE_2_5_12_DECISION_RECORD.md`, including Phase 2.5.15. Read the Phase 2.5.17 report preserved in `codex-session-01a1eee8-469a-7bf1-a2cf-9e2e2a8fedf5.md`, lines 10827–11465. The report was not a standalone file and expressly recorded static inspection only. Its unavailable prior reports and six illustrative vectors remain unavailable; no provenance is reconstructed.

The canonical record's headings say 27 decisions and 12 AMEND rows. Its actual enumeration contains 28 distinct IDs: 13 ACCEPT, 13 AMEND and 2 DEFER. This counting inconsistency changes no rule: every enumerated ACCEPT/AMEND is honored, and both DEFER rows remain deferred. The historical record is not rewritten.

Phase 17 correctly identifies the principal implementation gaps: heterogeneous legacy serializers/hashes; transient raw response bytes; mutable cross-retrieval heads; incomplete provider completeness contracts; logical IDs without revision identity; missing manifests/generation fencing/invalidation; SQLite v1 without migrations or database-level immutable history; in-memory AI usage; and no Phase 2.5 conformance suite. Existing health/UI/offline algorithms are useful foundations, not working-ready evidence.

## Decision register

### 1. Already approved requirements

| Contract | Locked requirement | Implementation boundary |
|---|---|---|
| CJ-01–04 | Strict UTF-8 without leading BOM; malformed/trailing/duplicate-key rejection; UTF-8 key ordering; exact escaping and scalar Unicode | New canonical intake/output only; legacy bytes remain unchanged |
| CJ-05–09 | ASCII snake-case known fields; per-field NFC; separate optional/null states; declared ordered/set-like arrays; bounded integers; decimal strings; no floats/coercions | Explicit schemas required; no global text normalization or default materialization |
| DEC-01–03 | Exact source lexemes and grammar; no rounding/quantization; canonical fixed-point decimal strings; five independent typed limits | Every caller supplies limits; no production defaults |
| TS-01–03 | Explicit complete timestamp offsets; UTC six-digit output; reject unknown `-00:00`, leap seconds and overflow; preserve source spelling separately | No global naive-time, Daily or session boundary inference |
| HASH-01–04 | Domain-separated length-framed SHA-256; registered profiles/domains; exact raw representation; external metadata; lowercase digest text | New codec cannot relabel or overwrite historical hash bases |
| ID-01–03 | Independent logical/retrieval/page/occurrence/revision allocation; immutable zero-based received ordinals; collisions fail | Identical content at different occurrences remains distinct |
| H4-01–02 | Four ordered immutable H1 revisions in one series/retrieval/input manifest; bind policy/algorithm and supported snapshot; separate replay and output objects | Does not approve H4-03 production policy |
| VEC-01 / HIST-01 | Original illustrative vectors remain illustrative; historical digest values/metadata retained | New synthetic verification vectors have separate provenance |
| Product/security | Gold only, research only, no execution/tools/broker/top-ups; backend secrets; loopback; aware UTC/Qatar display; central provider-neutral analyst | No monthly AI spending cap; no invented numerical AI safeguards or external spend |

The exact normative spelling and framing remain in the decision record; this table summarizes rather than replaces it.

### 2. Technical specifications that can close without approval

These choices implement approved behavior and create no production policy:

- Separate new canonical primitives from existing serializers, request hashes and legacy IDs. No import into ingestion/storage/analysis publication until the relevant versioned contracts close.
- Represent parsed JSON numeric tokens by their original lexeme, including integer tokens. Convert only under an explicit decimal or bounded-integer schema. Duplicate keys are checked after JSON escape decoding; Unicode surrogates are rejected; NFC belongs only to declared semantic text.
- Errors are typed by failure category and identify fields/limits without echoing supplied document content, provider bodies or secrets. Invalid input returns no partial canonical output.
- A required explicit limit object contains all five DEC-03 positive integer limits; boolean values and omitted limits fail. `max_significand_digits` counts every mantissa digit in the original token/string, excluding sign, decimal point and exponent. Exponent magnitude is the mathematical signed exponent; comparison must precede potentially expensive expansion. Token/document limits count original UTF-8 bytes. `max_canonical_output_bytes` bounds the bytes of each complete returned canonical output, including a decimal string result and the complete serialized JSON result. No market scale is inferred.
- Schemas distinguish required/optional and nullable/non-null; do not synthesize absent fields. Integer bounds, object fields, semantic-text declarations, array element types and any set identity/sort rules must be explicit. Equal normalized set identities fail; ordered arrays retain declared order. Unsupported schema kinds fail rather than coerce.
- Pure frame code requires explicitly supplied immutable registry entries, supports only a declared framing version, validates ASCII identifiers and byte lengths before SHA-256, and keeps digest metadata outside payloads. Synthetic registries do not register production profiles.
- Future identity namespaces are distinct by object category and allocated independently; collision is a typed integrity failure. Choosing an implementation allocator does not upgrade legacy IDs.
- For isolated identity allocation, the backend identity layer accepts an explicit immutable registry declaring each namespace's object category, owner and uniqueness scope. Namespace/category names match ASCII `[a-z][a-z0-9_.-]*`; mappings are one-to-one. The allocated text is the declared namespace followed by `:` and a standard-library UUIDv4's 32 lowercase hexadecimal characters. No production namespace registry is supplied. An injected reservation callback receives the immutable allocated ID and namespace metadata and must atomically reserve that complete ID within the declared archive scope before allocation succeeds. A collision fails without retry or digest reuse; backend persistence must later enforce the reservation. Logical IDs remain stored references across revisions, not values recomputed from content. Ownership/scope strings and IDs are preserved without NFC. This format is new isolated implementation behavior, not a claim about legacy IDs or production allocation activation.
- Preserve deterministic algorithm parameters and existing precision 34 as separately versioned execution inputs. Canonical serialization does not change numeric calculation behavior.
- Develop schema/state-machine prototypes and disposable synthetic tests independently. No synthetic database is described as production evidence. No real migration or profile activation is authorized by a prototype.

These specifications close the boundary for isolated primitive implementation. Full object schemas, manifest relationships and policy-dependent state transitions remain prerequisites before downstream integration.

### 3. Decisions requiring explicit approval

No P-01 through P-07 decisions remain pending. The user approved the following on 2026-11-18; this response is the authority for implementation and does not amend the historical Phase 2.5.12/2.5.15 record.

| ID | Approved rule | Implementation boundary |
|---|---|---|
| P-01/P-02 | Retain permitted raw provider bodies for 30 days; rejected/malformed rows and duplicate occurrences for 90 days; AI prompts/responses for 30 days. Exclude credentials/secrets. Retain only data permitted by the provider's terms; disable payload retention when permission is unclear or prohibited. Preserve permitted audit metadata and deletion status after expiry. No redistribution, resale, or external model training using provider data. | Apply retention class and expiry at capture. Retention denial is an explicit metadata-only state, never a silent partial body. Expiry removes payload bytes and preserves allowed audit metadata/deletion status. |
| P-03 | Require verified provider completeness. Unsupported or incomplete retrievals stay unavailable. | Completion requires provider-specific completeness evidence; page-count or short-page assumptions alone do not qualify. |
| P-04 | Select one qualifying whole retrieval per timeframe; never stitch ranges across retrievals. No older-retrieval fallback until freshness/lookback policies are separately approved. | A manifest binds one complete retrieval for each selected timeframe and its exact revision set. |
| P-05 | Append-only invalidation events target exact immutable revisions. Block affected inputs from new processing; flag dependent historical analyses and keep them visible with a clear warning. Never silently rewrite or delete historical analysis. | New selection/derivation/AI dispatch checks invalidation. Historical result content and provenance remain immutable; presentation adds an invalidation state. |
| P-06 | Design a separate archive using SQLite BLOB storage, one transaction owner, and explicit crash consistency, recovery and orphan handling. Preserve v1. | Authorized for design and disposable synthetic rehearsal only. No existing/production DB access, migration or cutover; those need separate authorization. |
| P-07 | Use documented permitted sources; verify provider terms, attribution and freshness. AI provider/model configuration must be explicit. No purchases, paid fallbacks, top-ups or external spending without approval. Keep any source with unclear permission unavailable. | No live provider activation or external call is authorized by this decision. |

### 3.1 Remaining approval gates

Only DEC-04 and H4-03 remain explicitly deferred policy decisions. Separate authorization is still required for production database access/migration/cutover, live provider activation, external spending and production service activation. These are activation permissions, not unresolved design choices.

### 4. Intentionally deferred policies

| Decision | Exact required approval | Options and tradeoffs | Recommendation now | Delay effect |
|---|---|---|---|---|
| DEC-04 | Select production values for all five resource limits after workload evidence | Recorded A: 1 MiB/64 KiB/1,024/1,024/4 KiB; B: 8 MiB/1 MiB/4,096/4,096/16 KiB; C: 32 MiB/4 MiB/16,384/16,384/64 KiB; or explicit custom values. Larger choices admit more data but expand CPU/memory exposure; smaller choices reject larger legitimate inputs. Candidates remain unvalidated | **Deferred by user.** Synthetic tests may use explicit, documented test-only limits. No production default or profile. | Production canonical intake cannot activate; isolated synthetic boundary tests proceed. |
| H4-03 | Approve production bucket alignment, candle eligibility/finality and volume combination together | Provider-native verified H4; approved derivation from exactly four eligible H1 revisions under a provider calendar/bucket policy; unavailable H4. Native needs source entitlement/contract. Derivation needs explicit alignment and volume semantics. Unavailable avoids unsupported output | **Deferred by user.** Synthetic replay may use a clearly isolated test-only policy. No production H4 policy is activated. | Production H4 remains unavailable; isolated replay/lineage tests proceed. |

### 5. Implementation prerequisites

1. Reviewed versioned shapes exist in the isolated contract catalog; bind them to durable schemas only after registry ownership and compatibility/recovery rules close. Provider raw capture boundaries still need per-source registration.
2. Bind namespace reservation atomically to archive transactions and persist original page/row ordinals, immutable revision relationships and append-only event envelopes.
3. Implement approved permission-gated retention classes with exact permitted bytes, expiry/deletion metadata and atomic publication.
4. Supply authoritative provider-specific completeness/finalization contracts; implement retrieval lifecycle and per-series generation ownership without live activation.
5. Implement immutable one-retrieval-per-timeframe manifests, exact revision membership, append-only invalidation and fenced promotion; do not add fallback.
6. Bound deterministic parameters/numeric policy and derived manifests; H4 adds exactly ordered immutable lineage and an approved production policy before activation.
7. Versioned schema compatibility, migration/recovery rehearsal on synthetic disposable data, approved runtime/cutover settings and separate real-data authorization.
8. Local end-to-end tests followed by separately authorized provider verification, mobile/browser testing, contention/recovery and operational acceptance.

## Safe first implementation and closure limit

Start with the existing terminal UI and local service health integration, which do not depend on market policy. Implement pure canonical primitives only within the closed technical boundary above, with explicit synthetic limits and schemas. Preserve all existing legacy hashes, calculations, raw provenance and historical reports.

P-01–07 are approved as recorded above. Architecture implementation can proceed in an isolated synthetic archive while provider-specific completeness evidence, production registry ownership, raw representation/capture definitions and operational SQLite settings are finalized. DEC-04 and H4-03 remain deferred. Test evidence and next eligible actions are maintained in `MASTER_PROJECT_TRACKER.md`.

## Implemented technical boundary

`backend/app/canonical.py` implements the isolated primitive/schema boundary above. `backend/app/canonical_digest.py` implements v1 frames and external metadata verification with explicit caller-supplied registries. Structured registrations bind an explicit schema, category and schema version; raw registrations declare a representation, capture boundary, included/excluded bytes and prior transformations. An explicit payload-byte ceiling is required for codec calls; no numerical default is supplied or selected for production.

The codec's registry is immutable within a value. Production registration ownership, historical registry lookup and globally preventing reuse of a profile ID with a changed definition remain archive/integration prerequisites; a caller-created synthetic registry is not a production registry. Raw verification requires the resolver to honor an immutable byte reference. It cannot turn a mutable file reference into immutable evidence by hashing it.

Neither module is imported into legacy ingestion, SQLite storage, deterministic analysis or provider dispatch. No existing digest or ID is rewritten. All new conformance fixtures are synthetic and distinct from the unavailable six historical illustrative vectors. See `PHASE_2_5_18_VERIFICATION.md` for exact checks and limitations.

`backend/app/canonical_identity.py` implements the explicit isolated namespace contract. It supplies no production namespace names, stores no IDs itself and has no content/digest argument. UUIDv4 IDs succeed only after the reservation callback returns literal `True`; collisions, invalid return values and sanitized callback failures return no allocated result. Original received ordinals and observation/revision relationships still require archive integration before claiming complete ID-03 provenance.

## Phase 2.5.18 isolated contract closure (2026-11-18)

`backend/app/data/evidence_contracts.py` now defines versioned canonical shapes for OHLCV, raw-evidence audit metadata, observations, revisions, pages, accepted/rejected row occurrences, provider completeness evidence, retrievals, manifest items, whole-input manifests, invalidations, derived manifests, digest metadata and historical analysis references. Decimal values remain exact decimal strings; source timestamps remain separate from normalized UTC instants; unknown fields are rejected. Twelve structured domains/categories/schema IDs are explicitly listed in `_REGISTRATION_ROWS`, bound to the approved `xau.canon.json-utf8-nfc-decimal-utc6.v1` profile, and exposed only through caller-requested immutable registries. Archive-owned namespace names/scopes are explicitly defined for isolated allocation. Nothing imports these registrations into the running service or archive.

The standalone manifest contract requires exactly one item for each of Daily, 4H, 1H, 15M and 5M, distinct retrieval IDs, positive SQLite-representable generations, increasing normalized UTC ranges and nonempty unique revision membership. It serializes each item with exact revision membership and generation; arrays use the approved set sorting where membership is unordered. A fixed canonical byte vector and framed SHA-256 vector guard profile/schema identity. These definitions close the implementation contract for isolated testing. They are not a production profile activation, provider completeness policy, or proof that a source is eligible.

### Provider eligibility gates

No provider is presently declared eligible. A provider/timeframe/source may be marked eligible only after all applicable gates have documentary evidence retained with a review date and source URL/reference:

1. **Permission and retention:** applicable provider terms explicitly permit each requested use (retrieval, persistence, retention class, derived analysis and configured AI disclosure where relevant). Store payload only when permitted; otherwise keep the feed unavailable or retain only metadata explicitly allowed by the terms. No redistribution, resale, external model training or secret capture.
2. **Attribution:** the source's required attribution text/location, licensing notices and update attribution are documented and can be displayed beside derived claims. Missing attribution requirements block eligibility.
3. **Freshness:** authoritative publication/update cadence, timestamp meaning/time zone, delay and correction/finality behavior are known. A product freshness/lookback threshold is still unapproved; until approved, the source may not satisfy production freshness or older-retrieval fallback.
4. **Completeness:** provider documentation/API contract establishes request-range semantics, pagination/cursors, terminal-page evidence, limits, partial/error behavior, revisions/corrections and candle finality. The adapter supplies retained evidence proving the specific retrieval covered its whole requested range. A successful HTTP response, page count, short page or locally assembled set is insufficient by itself.
5. **Data shape and identity:** XAUUSD instrument identity, timeframe, OHLCV units, timestamp boundary/naive-time behavior, decimal token preservation and any volume semantics are documented. H4 policy remains separately blocked by H4-03.
6. **Operational eligibility:** credential storage, allowed request rate/concurrency/timeout, jurisdiction and service availability are verified from the provider contract; no paid plan, purchase, paid fallback or production call occurs without separate authorization.

An eligibility record must name provider, product/endpoint, instrument, timeframe, evidence references, terms/version review date, attribution rendering, freshness rule status and completeness evidence method. Any unknown or contradictory item means unavailable, not eligible. A provider-eligibility object is deliberately not assigned a production schema or digest domain until the evidence and ownership contract exists; a syntactically valid declaration cannot confer eligibility.

### SQLite operational review

The prototype owns one SQLite connection per `SyntheticArchive` instance and serializes writes with `BEGIN IMMEDIATE`; every compound mutation commits or rolls back as one unit. BLOB payload and evidence metadata share the same row, so an accepted payload has no external-file orphan path. WAL and `synchronous=FULL` are set explicitly; the disposable harness requires an explicit busy-timeout value, with test values confined to tests. Integrity and foreign-key checks run after synthetic reopen/crash tests. Checkpoint schedule, maximum DB/BLOB size, disk reserve, backup cadence/retention, read concurrency, filesystem durability and operational recovery point/time targets remain unset production decisions. No production database was opened, migrated or configured.

## 2026-11-18 registry ownership and SQLite operational follow-up

The synthetic registry, capture gate, freshness policy and SQLite operational evidence are described in `REGISTRY_OWNERSHIP_AND_VERSIONING.md`, `RAW_EVIDENCE_AND_FRESHNESS_CONTRACTS.md` and `SQLITE_OPERATIONAL_READINESS.md`. These are implemented isolated prototypes and proposals; they do not activate or designate production authority or runtime settings.

The synthetic registry prototype enforces scoped registration, immutable versioned records, compare-and-swap allocation, canonical digest verification, cross-registry references and append-only deprecation/invalidation events. The proposed consistent model is one reviewed, version-controlled registry release bundle as the authoritative production source, with runtime indexes rebuildable from that bundle. Engineering has not assigned a human or organizational authority. A user decision is required to designate who can approve releases and authorize registrar scopes. Until then production registration/release remains blocked; synthetic engineering can continue.

The synthetic SQLite rehearsal demonstrates transaction atomicity for tested process termination and simulated full-disk write failure, reader snapshots alongside a writer, explicit lock behavior, integrity checks, and stdlib online backup/restore. Its five-run synthetic workload and environment details are recorded in the operational proposal. The measurements do not select production settings or establish target-device durability. Production timeout/retry budget, checkpoint cadence, size/disk reserve, backup schedule/retention, RPO/RTO, filesystem and power-loss requirements remain unselected.

Freshness evaluation is fail-closed without separately evidenced event-age, publication-delay and retrieval-delay limits. Historical fallback must be explicitly enabled and bounded by a versioned policy. Market closure/holiday exceptions require an explicit calendar evidence reference. H4 remains unavailable under H4-03. Capture profiles are disabled unless stage-specific retention/use permissions and required attribution are evidenced; provider account/upstream terms and exact retention remain unknown for proposed feeds. See the latest verification section for exact synthetic test results.

## 2026-11-18 Stage E-G synthetic follow-up

`MACRO_NEWS_CONTEXT_CONTRACT.md`, `AI_ANALYST_WORKFLOW.md` and `DASHBOARD_ANALYSIS_CONTRACT.md` record the new synthetic boundaries. Macro/calendar/news/sentiment records carry separate event/publication/retrieval semantics, revisions, attribution, completeness references and explicit freshness policy. They cannot turn unknown source rights into eligibility. The analyst layer binds persisted input/output provenance and uses a mandatory verifier before any injected completion; its response envelope requires scenario citations, validates contextual sources and rejects ungrounded numeric claims. The frontend offers only a user-selected, conspicuously synthetic output-contract preview; no research API or real market output was added.

Synthetic verification is recorded in `PHASE_2_5_18_VERIFICATION.md`: backend full suite 499 passed; focused macro/AI/provenance tests 42 passed; frontend typecheck/tests/build passed. The archive → deterministic analysis → unavailable context → insufficient-evidence NO TRADE → invalidation-warning path is tested. The analyst wrapper rejects an available H4 input while H4-03 is deferred and reports market-data state/time. The dashboard preview remains separate from the backend output. Production macro/news sources, external AI use, Stage B registry authority and SQLite targets, production API integration, DEC-04 and H4-03 remain open/deferred as applicable.


## 2026-11-19 production registry governance amendment

The Project Owner designated themselves Project Owner and Registry Release Approver for preparation of a governance/trust-anchor design. This designation is not production release or activation authorization. `docs/REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md` is **PROPOSED — AWAITING PROJECT OWNER REVIEW**. It reuses the canonical release bundle and HASH-01 framing, separates bundle-preparation registrar identity from approval, and proposes offline Ed25519 with independent trust-manifest bootstrap, key rotation/revocation and owner-controlled recovery. No production key was created, no crypto dependency added, and no production release capability enabled.

The synthetic registry adds versioned approval schemas and isolated immutable approval/revocation history, using a verifier injection seam and test-only HMAC. Tests establish synthetic digest/signature checking, authorization separation, replay/rollback rejection, revocation state and transaction recovery; they do not establish production cryptographic security. Full verification and exact commands are recorded in `PHASE_2_5_18_VERIFICATION.md`. DEC-04 and H4-03 remain deferred.
