# Registry ownership and versioning proposal

Status: synthetic registry interface and approval verification are implemented and tested. The Project Owner has designated themselves **Project Owner and Registry Release Approver**. The production governance design is **PROPOSED — AWAITING PROJECT OWNER REVIEW**; this designation does not authorize release, trust-anchor activation, migration or deployment. See `docs/REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md`.

## Current registry inventory

| Registry | Current authoritative source in this repository | Owns / state |
|---|---|---|
| Canonical object schemas | `backend/app/data/evidence_contracts.py:SCHEMAS`; primitives in `backend/app/canonical.py` | Versioned field shapes, nullability, decimal/timestamp/integer rules and array identity. Source code is current authority. |
| Canonicalization profiles | `canonical_digest.py` profile definitions and `evidence_contracts.py:_REGISTRATION_ROWS` | Canonical JSON normalization, timestamp/decimal form and field schema binding. Current profile ID is explicit; no production profile is activated. |
| Digest registrations | `structured_profile_registry()` plus explicit `RawProfile` values | Domain, profile, framing version, object category, schema version and schema. The structured registry is fixture/source-code owned; there is no account-specific raw profile registration. |
| Identity namespaces | `identity_namespace_registry()` and `canonical_identity.py` | Category, owner string and uniqueness scope. Reservation is callback-owned; a production namespace authority is not selected. |
| Provider eligibility | `provider_contracts.py` (`Gate`, `ProviderEligibilityV1`) | Required permission, attribution, freshness, completeness and operational evidence. Contract exists; Twelve Data and SiftingIO account records remain UNVERIFIED. |
| Retrieval/completeness | `provider_contracts.py` and `evidence_contracts.py` retrieval/completeness schemas | Whole retrieval identity, cursor/page chain and completeness evidence; there is no live provider adapter registration. |
| Input manifests | `InputManifest`, `MANIFEST_SCHEMA`, isolated `SyntheticArchive` | Immutable whole retrieval/revision selection and canonical digest. |
| Derived manifests | `DerivedManifest` v1 and `DerivedManifestV2` v2 | Analysis algorithm/version, input/output digests, selected revision lineage, parameters, window, schemas and unavailable inputs. |
| Algorithms | `analysis/engine.py`, indicator/structure/SMC modules and explicit method strings | Algorithm ID/version and calculation semantics. No dynamic algorithm registry or production release exists. |
| Invalidation | `INVALIDATION_SCHEMA`, `SyntheticArchive.invalidations` | Append-only revision-targeted invalidation events. Reason codes are currently caller text; reason-code catalog has not been registered. |
| Raw capture/retention | `capture_contracts.py`, `RawProfile`, approved P-01/P-02 retention classes | Exact capture boundary and permission gates. Candidate profiles fail closed while rights or retention terms are unknown. |
| Freshness/lookback | `freshness.py:FreshnessPolicyV1` | Versioned event age, publication delay, whole-retrieval fallback and explicit unavailable reasons. No production thresholds are supplied. |

## Consistent ownership model

Use one logical catalog keyed by `(registry_id, entry_key, version)`. Every immutable entry has a canonical definition digest, registrar identity, registration time, change/review reference, explicit predecessor version and references to other versioned entries. Lifecycle changes are append-only events (`deprecated`, `invalidated`); invalidation is terminal. Consumers pin exact versions and verify the entry payload, digest profile/framing, references and lifecycle state. Deprecated versions remain resolvable for historical verification only; invalidated versions cannot be resolved for new or historical use.

The versioned registry release bundle is now specified and implemented in the isolated `SyntheticRegistry` prototype. Each export is a transactionally consistent snapshot of immutable entries and lifecycle events. Its `release_id` is `sha256:<framed digest>` over the versioned canonical payload; the ID is outside that payload. The payload includes the release schema version, creation time, previous release ID, scoped bundle-preparation registrar and `change_reference`, plus a stable ordered representation of every registered entry and lifecycle event. Entry digests remain independently verifiable. A valid release can reconstruct an empty synthetic catalog; recovery rejects occupied catalogs, unknown references, bad digests, version gaps and invalid integrity. Runtime SQLite remains a rebuildable index, not an authoritative release source. The synthetic authority is not a real owner or production trust anchor.

### Release and compatibility rules

- Entry identity remains `(registry_id, entry_key, positive integer version)`. Versions advance monotonically by one after an explicit predecessor compare-and-swap; versions are never reused, including after deprecation or invalidation.
- A definition change always creates a new entry version. Compatibility is declared and reviewed inside the definition/change record; the registry does not infer compatibility from a version number. Schema/profile changes must publish a new schema/profile identity when canonical interpretation changes. Consumers pin exact identities and versions.
- Release format `1` is immutable. Any incompatible bundle-envelope change requires a new release schema/profile/framing registration and a distinct format version. Release IDs are content-derived, so an exact replay yields the same identity; changed content yields another identity.
- Bundle preparation requires the registrar's `bundle` scope and a `change_reference`; that identity cannot stand in for approval. The synthetic approval path separately verifies a versioned signed approval record through an injected verifier, with HMAC test fixtures only. The production signature mechanism and trust anchor are not implemented. Production release remains disabled pending review and separate activation authorization.
- Preserve every approved release artifact and its predecessor link. The prototype does not prune releases. Production retention duration, storage location and deletion/legal-hold rules require the designated authority; no history may be removed from a release chain until that policy is approved.
- Recovery procedure: verify release identity/digest and registered schema/profile, initialize a new empty synthetic catalog with the same approved registry catalog, reconstruct exact entries and lifecycle events transactionally, then run SQLite integrity, foreign-key and entry-digest checks. Never reconstruct over an existing catalog. Production restore additionally needs signed artifacts, key rotation/revocation, backup custody and rehearsed target-store procedures.

| Governance question | Proposed rule / implementation evidence |
|---|---|
| What is owned? | Schemas, canonicalization/digest profiles, namespaces, provider/retrieval contracts, manifests, algorithms, invalidation rules, capture/retention and freshness policies use the same registry envelope. |
| Authoritative source | Proposed repository-controlled immutable registry bundle; current code catalogs remain the present implementation source until bundle migration is separately designed. |
| Who may register? | A software release workflow accepts entries only from a configured registrar identity with explicit registry scope. `SyntheticRegistry` requires injected scopes; it does not invent the production registrar. |
| Uniqueness | SQLite primary key `(registry_id, entry_key, version)`; exact replay is idempotent; changed content at an existing identity/version is rejected. |
| Version allocation | Positive integer versions advance exactly from the caller's `expected_previous_version`; `BEGIN IMMEDIATE` serializes registration and stale concurrent proposals fail. |
| Review | Each entry binds a `change_reference`; lifecycle events bind registrar, reason and time. Production workflow must require an approved review reference before release. |
| Historical immutability | Database triggers prohibit entry/event update or delete; new definitions require a new version. Historical resolution verifies digest and version. |
| Deprecation/invalidation | Deprecation blocks new consumers but allows historical resolution. Invalidation is terminal and blocks all resolution. A replacement is a new version. |
| Concurrent conflicts | Unique keys plus `BEGIN IMMEDIATE` and predecessor-version compare-and-swap yield one winner; losing writer gets a version conflict and must reread. |
| Consumer verification | Resolve exact identity/version; verify canonical payload digest and registered profile/schema/framing; validate all referenced entries are active; record pinned registry version in analysis provenance. |
| Release integrity/reconstruction | `SyntheticRegistry.export_release()` snapshots entries and lifecycle events in one read transaction, then emits a canonical digest-derived identity. `verify_release()` checks framing, schema and identity; `reconstruct_release()` restores only to an empty catalog in one write transaction and verifies entry chain/references and database integrity. Tests cover tampering, scope, historical lifecycle, reference order and occupied-target rejection. |

Cross-reference direction is constrained: profiles and namespaces reference schemas; provider contracts reference capture/retrieval/retention contracts; retrieval contracts reference schemas/provider/freshness; manifests reference schema/retrieval/namespace; algorithms reference schema/manifest; invalidation policies reference schema/manifest; freshness references retrieval; capture profiles reference provider/profile/retention. Unknown, incompatible, deprecated or invalidated references fail registration. No provider-eligibility assertion is generated by a registry entry.

## Authority and review state

The designated Project Owner and Registry Release Approver may review and approve/reject an exact candidate, set registrar scopes, and direct trust-anchor enrollment, rotation or revocation. A registrar identity never inherits approval authority. The recorded designation authorizes preparation of the design only: no production registrar, trust key, signed approval or release is active. The owner-review questions and recommended trust-anchor design are in `docs/REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md`.

Until that proposal and a later production implementation are separately reviewed and activation is explicitly authorized, synthetic registry work may continue while production publication, trust-anchor activation, migration and deployment remain disabled.

## Security remediation status (2026-11-19)

Current synthetic release format v2 binds `registry_id` into the canonical bundle. Approval v2 signs that identity alongside release identity/digest, registry version, predecessor ID/digest, registrar, decision, timestamp, key identity/version, algorithm and schema/canonicalization/framing/compatibility metadata. Release/approval v1 remains historical-only; v1 release verification is explicitly opt-in, warns that registry identity was unbound, and cannot be newly approved. New approvals require v2. The earlier release-format-1 paragraph above describes the original format and does not supersede these v2 rules.

The isolated prototype now defines trust-manifest v2 genesis with primary signature, recovery proof of possession, independently supplied manifest-digest and primary-fingerprint pins, plus a sequence-0 checkpoint. Signed revocations bind append sequence, separate `effective_sequence`, target, authority and previous checkpoint; signed checkpoints bind predecessor and event digests. Verification requires the independently supplied latest checkpoint digest. The old unsigned `revoke_approval` method rejects; local SQLite triggers and digest checks are integrity checks only, not independent rollback protection. HMAC fixtures are synthetic only. Normal trust-manifest rotation is designed but not implemented. Production Ed25519, Android/Termux compatibility, physical custody, external checkpoint storage/recovery, and production release remain unverified or disabled. See `docs/REGISTRY_GOVERNANCE_SECURITY_REVIEW.md` and the owner decisions in `docs/REGISTRY_GOVERNANCE_OWNER_DECISIONS.md`.

Documentation consistency update: 2026-11-20. The preceding inventory remains a snapshot of repository ownership and synthetic interfaces; the dated release/security clarification above governs current v2 versus historical-v1 status and current trust/revocation limits.
