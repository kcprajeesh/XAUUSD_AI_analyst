# Stage 5E.3 — Phase 2.5.12

## Canonical Contract Decision Record

**Record status:** User-approved decision record, limited to the 27 decision IDs below.

**Mode:** Strict read-only documentation and decision recording. This record does not authorize implementation, schema or database changes, migrations, tests, production configuration, provider integration, or deployment.

## 1. Approval provenance

The user explicitly approved the assistant's recommended Phase 2.5.12 dispositions as written. This approval applies to the 27 decision IDs listed in the Phase 2.5.11 decision matrix, including the stated amendments and deferred decisions.

This approval records only those dispositions and their stated scope. It does not separately approve technical rules beyond that recommendation set, nor does it authorize implementation.

## 2. Source and decision provenance

### Verified project-source facts

- `docs/DATA_FOUNDATION.md` documents exact `Decimal` handling for normalized values, rejects binary floats and booleans for normalized prices/volume, and says values are not silently rounded or quantized. It documents aware UTC instants, offset conversion, preservation of source timestamp spelling, rejection of excessive fractional precision, and six-digit UTC index keys.
- `docs/PROVIDER_NEUTRAL_DATA_CONTRACT_DESIGN.md` notes that an already-decoded float cannot recover its original JSON decimal token. It describes optional H4 aggregation design, not an approved canonical replay manifest.
- `docs/MILESTONE_5E.md` records append-only observations and four-H1 aggregation behavior with source candle IDs.
- `docs/MILESTONE_5E_1.md` records SHA-256 request identities. Those request identities are not thereby established as using the content-digest framing in this record.

These are documented project facts, not approval of a new canonical profile.

### Prior phase provenance

- Phase 2.5.6 report: unavailable; contents are not reconstructed.
- Phase 2.5.7 report: unavailable; contents are not reconstructed.
- Phase 2.5.8: available in conversation context, not as a project report.
- Phases 2.5.9 and 2.5.10: proposal stages in conversation.
- Phase 2.5.11: prepared the decision matrix.
- Phase 2.5.12: records the user's explicit approval of the recommended dispositions.

## 3. Approved dispositions

The disposition labels below are the approved labels. **ACCEPT** and **AMEND** record approved rules; **DEFER** records that the decision remains open and is not approved as a production behavior.

### ACCEPT — 13 decisions

| ID | Approved rule | Provenance and compatibility note |
|---|---|---|
| CJ-01 | Parse strict UTF-8 and reject a leading BOM. | Phase 2.5.11 recommendation. Inputs previously tolerated with a BOM are rejected. |
| CJ-02 | Reject malformed JSON, trailing content, and duplicate keys after escape decoding and before normalization. | Phase 2.5.11 recommendation. Prevents parser-dependent duplicate-key interpretation. |
| CJ-03 | Canonical JSON has no whitespace outside strings; object keys sort by ascending UTF-8 byte sequence. | Phase 2.5.11 recommendation. Different key-order profiles produce different canonical bytes. |
| CJ-04 | Escape quote and backslash; encode U+0000–U+001F as lowercase `\u00xx`; do not escape slash; emit other valid Unicode scalar values as literal UTF-8. | Phase 2.5.11 recommendation. Escape-profile changes require a new canonicalization profile. |
| CJ-07 | Declare required/optional and nullable/non-null states separately. Omission and `null` remain distinct. | Phase 2.5.11 recommendation. Schema changes can alter canonical bytes and compatibility. |
| CJ-08 | Arrays are ordered by default. Set-like arrays declare identity and sort key, sort by canonical element bytes, and reject duplicates. H1 lineage arrays remain ordered. | Phase 2.5.11 recommendation. Changing array classification or sort rules requires versioned handling. |
| HASH-03 | SHA-256 output is 32 bytes; canonical text, when used, is 64 lowercase hexadecimal characters. Reject malformed canonical digest text. | Phase 2.5.11 recommendation. Does not reinterpret existing request hashes. |
| HASH-04 | Store digest metadata outside its own hashed payload. Metadata includes algorithm, digest, domain, profile ID, framing version, object category, and schema version. | Phase 2.5.11 recommendation. Readers must retain support for historical metadata. |
| ID-01 | Logical object IDs remain stable across revisions; observation/revision IDs identify immutable records; identifiers are allocated independently of content digests. | Phase 2.5.11 recommendation. No existing project ID format is asserted. |
| ID-03 | Page ordinal is zero-based within retrieval; row ordinal is zero-based within page and assigned before sorting/deduplication. Ordinals are immutable. ID collisions are integrity failures and are never resolved by digest reuse. | Phase 2.5.11 recommendation. Changing ordinal meaning would impair lineage interpretation. |
| H4-02 | Replay manifest and H4 aggregate output are separate objects. Output binds its identity and replay-manifest ID/digest; output digest covers the output payload without its own digest metadata. | Phase 2.5.11 recommendation. Requires separate schemas/domains; does not define H4 production policy. |
| VEC-01 | Preserve the six Phase 2.5.9 vectors as illustrative inputs only. H4 vectors with placeholders remain incomplete. No executable verification or expected digest values are claimed. | Phase 2.5.11 recommendation. Vectors require later separately authorized verification. |
| HIST-01 | Preserve historical digest values and original metadata. Canonicalization changes require new profile/schema/framing versions. Never rewrite historical digests or relabel old records. | Phase 2.5.11 recommendation. Historical readers/verifiers may be needed. |

### AMEND — 12 decisions

| ID | Approved amended rule | Provenance and compatibility note |
|---|---|---|
| CJ-05 | Field names use ASCII lowercase snake case matching `[a-z][a-z0-9_]*`. Reject unknown fields; there is no implicit extension mechanism. Adding/changing schema fields requires appropriate schema versioning. Schema changes and canonicalization-profile changes are distinct: a schema-only change does not automatically require a new canonicalization profile unless canonical bytes or canonicalization rules change. | Phase 2.5.11 amendment, clarified by the user. Unknown fields formerly accepted become invalid. |
| CJ-06 | Detect duplicate JSON object keys after escape decoding and before NFC. Apply NFC only to schema-declared `semantic_text` fields. Preserve IDs, hashes, raw source values, provider tokens, and opaque cursors unchanged under the approved exclusions. For set-like arrays, normalize declared semantic text before canonical duplicate detection and sorting; reject elements that become equal after normalization. Ordered arrays preserve order and may contain equal values when their schema permits. ASCII-only field names cannot have NFC key collisions. | Phase 2.5.11 amendment, clarified in Phase 2.5.15. Per-field declarations are required; changing them can change digests. |
| CJ-09 | Canonical values may contain strings, booleans, null, schema-bounded integers, arrays, and objects. Decimal market values are strings. Reject binary floats, unsupported types, and undeclared coercions. | Phase 2.5.11 amendment. Numeric fields must be typed in schemas; floats are incompatible with normalized financial values. |
| DEC-01 | Accept decimal strings, integer JSON tokens, and JSON numeric tokens parsed exactly from original lexemes. Input grammar: `-?(0\|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?`. Reject booleans and binary floating-point values. Parse exponents exactly. | Phase 2.5.11 amendment and project exact-decimal policy. Requires lossless token parsing; no float conversion is permitted. |
| DEC-02 | Canonical decimal output removes fractional trailing zeroes, removes an unnecessary decimal point, emits no exponent, normalizes every negative-zero representation to `"0"`, and never rounds or quantizes. Canonical grammar is `0\|-?(0\|[1-9][0-9]*)(\.[0-9]*[1-9])?`, with the additional rule that the exact string `-0` is not canonical output. | Phase 2.5.11 amendment. This exclusion resolves the grammar's otherwise permitted `-0`; numeric value remains exactly normalized to `0`. No financial precision or scale is set. |
| DEC-03 | Configure independent limits: `max_document_bytes`, `max_decimal_token_bytes`, `max_significand_digits`, `max_abs_exponent`, and `max_canonical_output_bytes`. Exceeding a limit yields a typed failure. Never truncate, round, partially serialize, or silently substitute. | Phase 2.5.11 amendment. Numerical values remain deferred. |
| TS-01 | Accept complete timestamps with seconds and explicit `Z` or numeric `±HH:MM` offset, with 1–6 fractional digits. Canonical output is UTC `YYYY-MM-DDTHH:mm:ss.ffffffZ`. | Phase 2.5.11 amendment and project UTC policy. Inputs beyond six fractional digits are handled under TS-02. |
| TS-02 | Retain candidate offset syntax range `00:00` through `23:59`, with minutes `00`–`59`. Reject offset seconds, leap seconds, invalid offsets, and UTC conversion outside years `0001`–`9999`. Explicitly reject `-00:00` for normalized instants unless a separately documented provider-specific contract preserves and defines its unknown-offset semantics. Do not silently treat `-00:00` as confirmed UTC. | Phase 2.5.11 amendment. Narrowing the offset maximum later changes accepted inputs. No global naive-time interpretation is created. |
| TS-03 | Preserve original source timestamp spelling and interpretation separately where schema permits. Do not globally interpret naive timestamps as UTC. Provider-specific naive-time behavior remains separately documented. No daily candle boundary is approved. | Phase 2.5.11 amendment and project source timestamp policy. Provider contracts remain necessary for any naive timestamp admission. |
| HASH-01 | Frame as: 10-byte magic `58 41 55 2D 43 41 4E 4F 4E 00`; 2-byte unsigned big-endian framing version, candidate value `1`; 2-byte unsigned big-endian domain byte length; ASCII domain; 2-byte unsigned big-endian profile byte length; ASCII profile ID; 8-byte unsigned big-endian payload byte length; payload bytes. All lengths count bytes. Reject invalid encodings, unsupported versions, unregistered domains/profiles, and limit violations before hashing. Never wrap or truncate. Structured canonical objects use canonical UTF-8 JSON. Raw response evidence hashes the exact retained bytes unchanged, without parsing, normalizing, decompressing, re-encoding, or rewriting. The raw-byte profile ID in the frame binds the representation identity to the digest. | Phase 2.5.11 amendment, clarified in Phase 2.5.15. Raw and structured payloads must not be conflated. Any framing change needs versioned compatibility. |
| HASH-02 | The structured JSON profile candidate remains `xau.canon.json-utf8-nfc-decimal-utc6.v1`. Raw evidence uses domain `evidence.raw` with a separate registered immutable raw-byte profile. Candidate IDs: `xau.raw-bytes.wire.v1`, `xau.raw-bytes.decompressed-body.v1`, `xau.raw-bytes.retained-body.v1`, and `xau.raw-bytes.custom.<registered-name>.v1`. Every profile maps one-to-one to a registered representation identifier and precisely defined capture boundary. The registry defines included/excluded bytes; a changed boundary requires a new version; retired profiles remain valid for historical verification; custom representations require registration before use. Never infer the representation from provider, media type, or content-encoding headers. These candidates do not assert that the project currently retains any such representation. | Phase 2.5.11 amendment, clarified in Phase 2.5.15. Profile and registry names remain design candidates; no production profile is activated. |
| ID-02 | Retrieval, page, occurrence, and parsed-row IDs are independently allocated in declared namespaces. Repeated identical content at different received ordinals remains separate occurrence evidence. Namespace ownership, uniqueness scope, allocation, and collision behavior must be defined before implementation. Do not invent or claim an existing project ID format. | Phase 2.5.11 amendment. Allocation details remain implementation prerequisites, not established formats. |
| H4-01 | Replay manifest binds `series_id`, `bucket_open`, `bucket_close`, interval/timeframe, retrieval ID, selected input manifest ID and digest, snapshot ID when supported by source schema, aggregation policy, immutable algorithm version, and exactly four ordered H1 observation revisions, each with observation ID, revision ID, ordinal, and content digest. All four H1 inputs must share series, retrieval, and selected input manifest. Verify exact order and relationship to declared bucket and algorithm policy. Never use a mutable-current pointer or silently substitute. | Phase 2.5.11 amendment. The manifest identity is stronger; production alignment, eligibility, and volume remain deferred. |

### DEFER — 2 decisions

| ID | Deferred decision and approved boundary | Provenance and consequence |
|---|---|---|
| DEC-04 | Numerical resource-limit selection is deferred. Candidate A: 1 MiB document, 64 KiB decimal token, 1,024 significand digits, absolute exponent 1,024, 4 KiB canonical output. Candidate B: 8 MiB, 1 MiB, 4,096 digits, absolute exponent 4,096, 16 KiB output. Candidate C: 32 MiB, 4 MiB, 16,384 digits, absolute exponent 16,384, 64 KiB output. These are unvalidated review options only; no production default is selected. | Phase 2.5.11 amendment. Values require separate evidence and approval; behavior cannot be configured for production from these candidates alone. |
| H4-03 | Defer production H4 bucket alignment, candle eligibility, and volume aggregation to a separate data-policy phase. Replay identity does not authorize production aggregation behavior. | Phase 2.5.11 recommendation. No H4 production behavior follows from this record. |

## 3.1 Raw and structured digest profile boundary

- Structured objects use `xau.canon.json-utf8-nfc-decimal-utc6.v1` and canonical UTF-8 JSON payload bytes.
- Raw evidence uses domain `evidence.raw`, a registered raw-byte profile, and the exact retained byte sequence. It must not use the structured JSON profile or be silently converted to structured JSON.
- The candidate raw profile registry defines the representation identifier and capture boundary. Candidate boundary meanings are:

| Candidate raw profile ID | Candidate representation ID | Registered byte boundary |
|---|---|---|
| `xau.raw-bytes.wire.v1` | `xau.evidence-representation.wire.v1` | Exact octet sequence captured at a registered transport capture point, before transformations outside that boundary. The registry identifies the capture layer and explicitly lists included/excluded framing bytes. |
| `xau.raw-bytes.decompressed-body.v1` | `xau.evidence-representation.decompressed-body.v1` | Exact bytes after the declared content-decompression step and before character decoding or parsing. Response headers and transport framing are excluded. |
| `xau.raw-bytes.retained-body.v1` | `xau.evidence-representation.retained-body.v1` | Exact byte sequence stored as the evidence object. Separately stored metadata is excluded; the registry records any prior transformation. |
| `xau.raw-bytes.custom.<registered-name>.v1` | `xau.evidence-representation.custom.<registered-name>.v1` | Custom registry entry must state the exact capture point and every included/excluded byte class before use. |

These are candidate definitions only. A candidate profile is not registered or usable until its registry entry gives the precise capture layer/step and all included and excluded bytes. For `decompressed-body`, that entry also identifies the decompression transformation/version. These candidates do not assert that any representation is currently captured or retained. The registry must be immutable by version; changing a boundary requires a new profile ID. Retired profiles remain available for historical verification, and custom registrations must exist before use.

Raw digest metadata is stored outside the hashed payload and includes the representation identifier, raw-byte profile ID, immutable reference to the exact retained byte sequence, byte length, and the existing algorithm, digest, domain, framing version, object category, and schema/profile metadata. The profile ID is included in the hash frame. The registered profile must map one-to-one to the declared representation identifier.

Verification resolves the immutable byte reference, retrieves that exact byte sequence, checks its byte length and registered profile/representation mapping, then hashes the unchanged bytes using the declared frame and `evidence.raw` domain. Missing, unknown, inconsistent, or unresolvable metadata makes verification fail. No representation is inferred from provider, media type, or content-encoding headers. Decompression or another transformation creates a distinct representation and requires a separately identified byte sequence and matching registered profile. Identical bytes under different raw profiles produce different framed messages and SHA-256 inputs because the profile IDs differ; their digest identities remain distinct even though no claim is made that SHA-256 collisions are mathematically impossible.

## 3.2 NFC and array collision behavior

Duplicate JSON object keys are detected after escape decoding and before NFC normalization. NFC applies only to schema-declared `semantic_text` fields; there is no global Unicode normalization. For set-like arrays, normalize declared semantic text before canonical duplicate detection and sorting. Reject elements that become equal after normalization. Ordered arrays preserve their order and may contain equal values when the schema permits. IDs, hashes, raw source values, provider tokens, and opaque cursors retain the approved exclusions from normalization.

## 4. Canonical contract boundaries

1. This decision record approves canonical identity decisions only; it does not approve implementation.
2. It does not authorize schema or database changes or migrations.
3. Existing SHA-256 request identities remain distinct from the proposed content-digest framing unless independently verified.
4. Historical digests retain their original basis and metadata.
5. Golden vectors remain illustrative; no executable verification or expected digest values are claimed.
6. Raw response evidence and structured canonical JSON are distinct digest payload types. Raw evidence hashes the exact retained representation identified by its digest basis.
7. No market precision, tick size, scale, or instrument-specific financial limits are established.
8. No global naive-timestamp-as-UTC policy is approved.
9. No H4 production aggregation policy is approved.

## 5. Independent architecture decisions remain unresolved

These decisions are outside the canonical identity approval:

- Legacy analysis eligibility.
- Raw response retention scope.
- Invalid-row retention duration.
- Provider completeness.
- Freshness thresholds.
- Lookback limits.
- Daily candle boundary.
- Invalidation semantics.
- SQLite runtime configuration.
- Migration/cutover policy.
- Provider permissions and retention requirements.
- H4 production bucket alignment, candle eligibility, and volume aggregation.

No approval is inferred for these items.

## 6. Final status

Canonical identity decision dispositions recorded: **YES**.

Canonical contract decision package approved by user: **YES, within the exact scope of the approved ACCEPT/AMEND/DEFER dispositions**.

Production canonical profile implemented: **NO**.

Source code changed: **NO**.

Schema/database changed: **NO**.

Migrations executed: **NO**.

Golden vectors executable-verified: **NO**.

Independent architecture decisions approved: **NO**.

Implementation authorized: **NO**.

Production deployment authorized: **NO**.

The next step may be a separate read-only canonical contract publication/consistency review. Implementation must not begin under this approval.

## 7. Amendment history

### Phase 2.5.15 — Approved clarification amendment

- **Source:** Phase 2.5.14 consistency audit and its proposed amendments.
- **Approval:** The user approved incorporation of those amendments in Phase 2.5.15.
- **Source verification:** The Phase 2.5.14 audit and Phase 2.5.12 record were reviewed. No additional project source documents were independently inspected for this amendment.
- **Sections changed:** CJ-06; DEC-03 wording only; HASH-01; HASH-02; new Sections 3.1 and 3.2; this amendment history.
- **Disposition preservation:** All 27 original decision rows and their ACCEPT/AMEND/DEFER dispositions remain unchanged. DEC-04 candidate values and DEFER status are unchanged; H4-03 remains DEFER.
- **Scope:** Documentation-only amendment to clarify raw representation/profile binding and NFC collision behavior and remove the redundant DEC-04 cross-reference.
- **Authorization:** Implementation and production activation remain unauthorized.
