# Production registry governance — security review for Project Owner

## Remediation update — 2026-11-19

The findings below are retained as the original review baseline. This update supersedes their “missing implementation” statements only where explicitly marked. **Production approval remains pending.** Synthetic tests use injected HMAC and are not Ed25519 security evidence.

| Finding | Current status | Evidence / remaining limit |
|---|---|---|
| Registry identity not bound from bundle through signature | **SYNTHETICALLY IMPLEMENTED AND VERIFIED** | Release v2 carries `registry_id`; approval v2 signs and binds registry ID, release format, exact digest, predecessor ID and digest. Target-registry verification rejects substitution. Release v1 is accepted only through the explicit historical-unbound path and is not approvable. |
| Unsigned local revocation and rollback | **SYNTHETICALLY IMPLEMENTED AND VERIFIED** | Signed revocation/checkpoint schemas, sequence and predecessor chain, external pinned checkpoint input, immutable rows and independent exported-chain verification. The old unsigned `revoke_approval` API now rejects. HMAC callbacks demonstrate only the contract/control flow. An owner-held checkpoint or separately protected backup is still required operationally; SQLite alone cannot stop rollback. |
| Genesis bootstrap | **SYNTHETICALLY IMPLEMENTED AND VERIFIED** | Trust-manifest schema v2 binds registry ID, primary and recovery public keys/versions and initial checkpoint; primary signs the manifest and recovery key proves possession over the same canonical bytes. Verifier requires separately supplied manifest digest and primary-key fingerprint pins. Storing the manifest beside the database does not establish trust. The actual out-of-band channel and human ceremony remain owner decisions. |
| Compromise recovery | **RESOLVED IN DESIGN; SYNTHETIC RECOVERY PATH VERIFIED** | Recovery-key authority can sign an emergency revocation without the compromised primary. Normal old-primary-plus-recovery rotation is specified separately but is not implemented as a trust-manifest transition. Total key loss requires owner-run out-of-band rebootstrap. |
| Signing compatibility metadata | **SYNTHETICALLY IMPLEMENTED AND VERIFIED** | Approval v2 binds release/approval schema versions, canonicalization profile, framing version, algorithm, compatibility object, timestamp and key identity/version. Signature is excluded from signing bytes; the signature-bearing record has its own digest. Historical v1 verification remains explicit and unbound to registry identity. |
| Ed25519 implementation | **BLOCKED** | `cryptography` is not installed in the current Python 3.13 Termux environment. No Ed25519 known-answer test was run; HMAC fixtures are not a substitute. Dependency approval and target-platform validation remain open. |

## Documentation reconciliation — 2026-11-20

The later sections of this file preserve the original pre-remediation security review. Its original executive findings 1–5 and sections 1–13 record what was missing at that review point; they are audit history, not current implementation status. The remediation table and exact v2/revocation material above govern current state. In particular:

- The original statement that release payloads lack `registry_id` is superseded: new release/approval v2 binds it; v1 is historical-only and cannot be newly approved.
- The original unsigned-local-revocation finding is superseded for the synthetic contract: the old API rejects, signed revocation/checkpoint records are verified with HMAC test callbacks, and an independently pinned checkpoint digest is required. No external checkpoint store exists; SQLite remains rollbackable.
- The original “no genesis contract” finding is superseded by synthetic trust-manifest v2 with primary signature, recovery proof of possession, pinned manifest digest and primary fingerprint, and a sequence-0 checkpoint. The real owner verification channel is not implemented.
- The original v1 approval-byte description is historical. Approval v2's structured compatibility metadata, v2 signing schema/profile and separate full-record digest are the current synthetic contracts. Neither version has been exercised with real Ed25519.
- The original finding about compatibility metadata embedded as a JSON string is superseded in approval v2 by the registered structured compatibility object. Cross-language real-Ed25519 test vectors remain unimplemented.
- Normal trust-manifest/key rotation remains designed but not implemented. HMAC fixtures provide no production cryptographic assurance. Android/Termux Ed25519 support, physical custody, off-device checkpoint storage, retention and restoration remain unverified.

### Exact v2 signed payload and revocation semantics

Approval v2 canonicalizes the object described by `REGISTRY_APPROVAL_SIGNING_V2_SCHEMA`, then applies the registered `registry.approval-signing.v2` framing profile. Its fields are: `approval_id`, `approval_schema_version`, `approval_timestamp`, `approver_id`, `canonicalization_profile`, structured `compatibility_metadata`, `decision`, `framing_version`, `key_id`, `key_version`, `previous_release_digest`, `previous_release_id`, `prepared_by_registrar_id`, `registry_id`, `registry_version`, `release_digest`, `release_format_version`, `release_id`, and `signature_algorithm`. The signature is absent from these bytes. The final record, including the signature, is separately digested with `registry.approval-record.v2`.

The release bundle itself has a separate canonical digest over `REGISTRY_RELEASE_V2_SCHEMA`, including its `registry_id`. Verification compares the embedded ID with the actual target registry ID, release identity, and approval binding. No consumer may silently parse v1 as v2.

Revocation `sequence` is the append-only event/checkpoint sequence. `effective_sequence` explicitly records the registry release sequence from which the target revocation applies; it is a separate sequence domain and is not compared numerically with the event sequence. Each revocation binds target kind/ID/digest, authority key ID/version, effective time, previous checkpoint digest and registry ID. A signed checkpoint binds the event digest and predecessor checkpoint. Current-state verification requires an independently retained latest checkpoint digest; the local database is only a cache.

### Candidate Ed25519 implementation assessment

The official `cryptography` Ed25519 API supports the standard 32-byte raw private seed/public-key inputs and 64-byte signatures; verification rejects invalid signatures. Its supported Python range includes the project interpreter version, but official installation guidance does not list Android/Termux as a supported wheel target and a source build has native Rust/C/OpenSSL requirements. The package is absent locally, so Termux buildability and runtime behavior are **unverified**. Do not install it or infer support from CPython compatibility alone. If later approved, pin a maintained release in the lock, validate a clean target build, run RFC 8032 known-answer and malformed-signature tests, track advisories, and define upgrade compatibility. See [Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/), [installation requirements](https://cryptography.io/en/latest/installation/), and [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html).

### Project Owner decisions still required

| Decision | Recommendation | Can engineering proceed without it? |
|---|---|---|
| Approve the exact Ed25519 profile and its dependency/platform target | Approve PureEd25519, exact schema/framing and a maintained implementation only after Termux/production-target build verification | Synthetic contract work can continue; production signing cannot. |
| Select primary and recovery key custody and genesis fingerprint channel | Prefer a verified offline signer and separately held recovery copy; require fingerprint verification through an independent channel/device | Synthetic tests can continue; production trust bootstrap cannot. |
| Approve emergency recovery authority and normal rotation ceremony | Recovery key may revoke a compromised primary; planned rotation requires old primary and recovery authorization | Synthetic emergency path exists; production trust transition cannot. |
| Select independently protected checkpoint/backup location and retention rules | Keep the current high-water checkpoint outside the registry database, plus a separately protected backup | Synthetic verification can continue; current production revocation state cannot be trusted without it. |
| Approve production implementation and activation | Separate approval after review, target testing and recovery exercise | Yes; production remains disabled. |

### Verification executed

- `cd backend && .venv/bin/python -m pytest tests/test_registry_approval.py tests/test_registry_prototype.py tests/test_registry_trust.py tests/test_evidence_contracts.py -q` — **36 passed in 1.22s**.
- `cd backend && .venv/bin/python -m pytest` — **542 passed in 18.14s**.
- `cd backend && .venv/bin/python -m pip check` — **No broken requirements found**.
- Frontend unchanged by these backend-only contract changes; nevertheless `cd frontend && npm run typecheck && npm test && npm run build` — typecheck passed, **20 tests passed**, production build passed (2,138 modules). Test output had a Vite websocket “port already in use” warning; it did not fail tests or build.
- Runtime assessment: Python **3.13.13**; `cryptography_installed=False`. No Ed25519 vectors ran. All registry signature fixtures are HMAC-only.

**Review status: DESIGN REVIEW — OWNER APPROVAL PENDING**  
Reviewed: 2026-11-19  
Scope: `REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md` and the actual isolated synthetic approval implementation/tests. This review does not authorize production keys, signing, release, migration, deployment or activation.

## Executive assessment

The proposal has the right high-level shape: immutable release bundles, a distinct approver key, a signature over a canonical framed approval payload, monotonic versioning, and offline custody. The synthetic code is useful for checking payload binding and append-only database behavior. It is not cryptographic evidence for Ed25519 and must not be treated as a production approval mechanism.

**Do not approve production implementation as currently specified.** Close these design blockers first:

1. A release bundle has no `registry_id`, while an approval accepts a caller-supplied `registry_id`. The current verifier cannot prove that the approval is for the registry represented by the bundle. Bind registry identity in the release payload or make the approval bind a cryptographically verified, uniquely scoped registry set.
2. Revocation events are local unsigned rows. Define signed key/release revocation records, trust-state sequencing and a fail-closed freshness rule before any consumer relies on revocation.
3. Specify the genesis trust ceremony, recovery authority and exact normal versus compromised-key rotation thresholds. “Current and recovery key according to owner procedure” is not an executable rule.
4. Define a single cross-language canonical representation for compatibility metadata. The current implementation serializes nested metadata into a JSON string using Python `json.dumps`; the string is then included in the outer canonical record. This is deterministic in the tested Python path but is not a complete interoperable serialization specification.
5. Define how consumers keep a rollback-resistant checkpoint independent of the registry database and how a lost checkpoint is recovered.

The detailed decisions below should be resolved before production cryptographic code is written. All production trust-anchor approval remains pending.

## 1. Ed25519 signing and verification specification

**Proposed design**

- Use RFC 8032 **PureEdDSA Ed25519**, not Ed25519ph, Ed25519ctx, a prehash variant, or algorithm negotiation from untrusted data. Ed25519 keys are 32-byte seeds/public keys and signatures are 64 bytes. The Ed25519 primitive receives the complete framed message below; its internal hashing is part of RFC 8032 and is not an extra application SHA-256 prehash.
- Verification accepts only the pinned algorithm identifier and exact encoded lengths. Reject malformed/non-canonical public keys and signatures according to the selected library's strict RFC 8032 behavior. Check RFC 8032 known-answer vectors and negative/malleability vectors.
- The key manifest binds algorithm, authority, key ID, key version, public key, activation/retirement/revocation state, and predecessor/rotation evidence. Unknown algorithms and keys fail closed.

**Existing evidence** — `backend/app/data/registry_approval.py` separates a `signer`/`verifier` callback from canonical payload construction. `ApprovalKey` contains an algorithm label and verification material. The synthetic tests implement HMAC-SHA256 callbacks.

**Missing implementation** — There is no Ed25519 signer/verifier, asymmetric key type, production trust manifest, strict public-key parser, library selection, or RFC vector suite.

**Security risk** — Treating the HMAC callback or shared `verification_material` as representative of asymmetric verification would let any verifier forge approvals and would falsely imply public-key authentication. Library differences in malformed point and signature handling can also produce inconsistent verification.

**Recommendation** — Accept PureEd25519/RFC 8032 as the algorithm target only after a vetted implementation and platform support are selected. Keep synthetic HMAC isolated behind test-only fixtures; production API types should take public verification keys only and must make it impossible to pass symmetric secrets as verifier material. Use official [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html) test vectors and the selected implementation's strict verification API.

## 2. Exact canonical bytes that are signed

**Proposed design**

For the current registered profile, let `P` be the UTF-8 bytes returned by:

```text
canonical_json(approval_signing_payload,
               REGISTRY_APPROVAL_SIGNING_SCHEMA,
               explicit CanonicalLimits)
```

The signed message is exactly `frame_payload(P, approval_signing_profile, digest_registry, max_payload_bytes)`. HASH-01 v1 emits:

```text
ASCII("XAU-CANON") || 0x00
|| uint16_be(1)
|| uint16_be(len(ASCII(domain))) || ASCII(domain)
|| uint16_be(len(ASCII(profile_id))) || ASCII(profile_id)
|| uint64_be(len(P)) || P
```

For the current approval registration, `domain` is `registry.approval-signing`, `profile_id` is `xau.canon.json-utf8-nfc-decimal-utc6.v1`, and the schema is `xau.registry-approval-signing.v1`. The payload fields are exactly those in `REGISTRY_APPROVAL_SIGNING_SCHEMA`: approval ID/time, approver, canonicalization profile, compatibility metadata string, decision, framing version, key ID/version, predecessor release ID, preparing registrar, registry ID/version, release digest/ID and signature algorithm. The signature is excluded. The release digest itself is the SHA-256 digest of its registered, framed canonical release payload; it is included in the signed approval payload. The approval record digest is computed separately over the full signature-inclusive record, with that digest kept outside its own digest payload.

**Existing evidence** — `canonical_digest.py:frame_payload` constructs this framing and enforces registered profile identity, v1, ASCII identifiers and explicit payload limit. `create_approval` canonicalizes the signing record, frames it and passes those bytes to the injected signer. `verify_approval` reconstructs the same bytes before calling the verifier.

**Missing implementation** — No byte-for-byte public Ed25519 vector covers an approval record. Nested compatibility metadata uses Python `json.dumps(..., sort_keys=True, separators=(",", ":"))` to form a string; there is no independent cross-language profile or fixture for that inner representation.

**Security risk** — Independent consumers could produce different approval bytes if they do not replicate Python's nested metadata encoding exactly. A byte-level mismatch can reject legitimate signatures; relaxed parsing can accept different semantics than were reviewed.

**Recommendation** — Freeze this field list, framing and byte sequence as a versioned signing profile and publish test vectors containing the input object, canonical payload hex, framed-message hex and expected verification outcome. Prefer a schema-directed nested compatibility object over canonical JSON embedded in a string; if changing the schema is incompatible, define and test its own exact inner canonicalization profile. Do not substitute RFC 8785/JCS for the existing project canonical format without a deliberate version change.

## 3. Public-key encoding and key ID

**Proposed design**

- Public key: 32 raw Ed25519 bytes, represented as exactly 43 unpadded base64url characters (canonical decode/re-encode required).
- Signature: 64 bytes, serialized as exactly 128 lowercase hex characters in the approval record.
- Proposed key ID: lowercase hex SHA-256 of `ASCII("XAU-REGISTRY-ED25519-v1") || 0x00 || raw_public_key`; key version is a separate positive monotonic integer.
- The trusted manifest must bind `(key_id, key_version, algorithm, authority/role, public_key, lifecycle state)` and reject duplicate IDs/versions and non-canonical encodings.

**Existing evidence** — The approval payload carries `key_id`, `key_version` and `signature_algorithm`; tests use fixture strings and shared HMAC material only.

**Missing implementation** — No key-ID computation, public-key encoding parser, public key record or key uniqueness registry exists.

**Security risk** — A display fingerprint is not automatically a trusted identity. Key ID/version can be spoofed unless resolved from a trusted manifest; accepting alternate base64 encodings or duplicated key identities creates ambiguous references.

**Recommendation** — Approve the proposed encoding and key-ID formula as a versioned profile, then test canonical re-encoding, wrong length, duplicate registration and unknown-key rejection. Treat the key ID as a locator/checksum, never as proof of ownership.

## 4. Trust-manifest bootstrap and initial trust

**Proposed design**

- Bootstrap the first trust manifest through an explicit out-of-band fingerprint ceremony. The owner verifies the full root public-key fingerprint over an independent channel/device and pins it in consumer configuration or a separately controlled trust store.
- The first manifest names primary and recovery keys, roles, versions, validity state and the root sequence. Later manifests must chain from a previously pinned trust state and be signed according to the chosen rotation threshold.
- Never obtain the only verification key from the registry release it is meant to authenticate. Missing, stale or sequence-rolled-back trust state means current release is unavailable.

**Existing evidence** — The design text calls for out-of-band bootstrap and says a normal key cannot add itself. There is no implementation.

**Missing implementation** — The exact artifact, fingerprint algorithm/presentation, who checks it, how a consumer receives its first pin, how key state is sequenced, and what happens if the bootstrap record is lost are unspecified.

**Security risk** — Trust-on-first-use, a key delivered only beside its signed bundle, or a bootstrap performed on a compromised device allows an attacker to replace both key and bundle. A forged root can authorize all future keys.

**Recommendation** — Require an owner-run genesis ceremony: independently verify and record a SHA-256 fingerprint of the raw public key plus role/version; retain a signed genesis manifest and a human-readable fingerprint on a separate channel; test verification from a clean consumer installation. Choose and record the actual second channel/device before key generation. Do not bootstrap on the Termux app device alone.

## 5. Primary and recovery private-key custody

**Proposed design** — Prefer an Ed25519-capable hardware-backed signer only after actual support, non-exportability and recovery behavior are verified. Otherwise use a dedicated offline signing environment, encrypted offline media and a separately held encrypted recovery copy. Keep both secrets out of the application, CI, source control, environment, SQLite, logs and the development phone. Distinct custody reduces one-device risk but does not create a second human approver.

**Existing evidence** — The proposal explicitly rejects assuming Android Keystore or Termux hardware support. No production keys were generated and no private-key code exists.

**Missing implementation** — No device capability evidence, custody inventory, passphrase policy, physical separation, access/recovery ceremony, backup integrity check or owner-run restore drill exists.

**Security risk** — Theft/loss of both copies can permanently halt releases; compromise of an unlocked signer permits fraudulent approvals; an encrypted backup can be unusable if its passphrase is lost or can become a second exposed signing key.

**Recommendation** — Do not generate a key until the owner chooses a verified signer and separately stored recovery method. Rehearse restore with synthetic keys first, then require an owner-authorized production recovery test. Maintain one owner in control and state plainly that this is single-human governance.

## 6. Key rotation and revocation

**Proposed design** — Monotonic key versions and trust-manifest sequence; normal rotation is authorized by the active old key and the designated recovery key, publishes a new key with an overlap state, then retires the old key. Revocation is terminal; consumers refresh trusted revocation state and fail closed if it is unavailable or stale.

**Existing evidence** — Synthetic `ApprovalKey.status` supports active/expired/superseded/revoked. Tests show a superseded key can verify a historical signature made within its validity period, cannot create a new approval, and a replacement key version can approve a subsequent release.

**Missing implementation** — No trust/key manifest, signed revocation artifact, revocation sequence, propagation mechanism, freshness threshold, signature threshold or compromised-current-key path exists. Synthetic `revoke_approval` takes an injected actor allowlist and writes unsigned event rows.

**Security risk** — Requiring the compromised old key to countersign its own revocation allows the attacker to block recovery. Conversely, allowing the recovery key alone without defining scope/sequence enables silent root replacement. Stale consumer revocation state can continue accepting compromised keys.

**Recommendation** — Define two distinct ceremonies: (a) planned rotation requiring old primary plus recovery confirmation; (b) suspected compromise requiring recovery authority to revoke/replace the primary without approval by the compromised key. Both must produce signed, monotonically sequenced trust/revocation manifests. No release may be accepted if the consumer cannot establish current-enough trust/revocation state. The owner must choose recovery-key authority and revocation freshness policy.

## 7. Lost-device and compromised-key recovery

**Proposed design** — Lost with no compromise evidence: suspend old key, restore from separate recovery custody, enroll a new version and audit. Suspected compromise: suspend publication; use uncompromised recovery authority to revoke the key, replace affected trust state, identify and re-review releases signed during the exposure window, and require consumers to refresh checkpoints. If both keys are unavailable, halt release use and rebootstrap only through a separately verified owner ceremony.

**Existing evidence** — The proposal describes these cases at a policy level. Synthetic tests model status changes and release revocation but do not exercise trusted key-manifest recovery.

**Missing implementation** — No recovery bundle, inventory, clean-device bootstrap, loss/compromise workflow, consumer notification, exposure-window rule or recovery exercise exists.

**Security risk** — A “lost but not compromised” classification may be wrong. Continuing trust during investigation risks accepting attacker-signed versions. Both-key loss or compromised recovery key needs root replacement.

**Recommendation** — Default to suspected compromise when custody cannot be established. Make publication suspension and consumer fail-closed behavior immediate; do not rely on an unsigned contact message. Define an out-of-band root recovery ceremony before owner approval.

## 8. Registrar authorization and separation of duties

**Proposed design** — Registrar machine identities get least-privilege, expiring scopes for exact registry domains and bundle preparation; approval key is offline and never available to registrar/CI. Reject self-approval. Log registrar issuance, scope change and revocation. The Project Owner remains the only designated human release approver.

**Existing evidence** — `SyntheticRegistry` receives an injected registrar authority mapping. Release export requires a `bundle` scope; approval checks `approver_id != prepared_by_registrar_id`; tests cover unauthorized registrar scope and self-approval.

**Missing implementation** — No production registrar credentials, scope grant/revocation record, expiry, authentication, approval UI, or owner role identity manifest exists. `verify_release` checks generic `bundle` scope, not an explicit registry scope against a registry ID embedded in the bundle. The approval's `registry_id` is caller-supplied.

**Security risk** — The registry identity mismatch described above can mis-scope approval. String identity inequality only prevents same-ID self-approval; it does not prove different humans or prevent the owner from controlling both credentials. A compromised registrar can prepare malicious candidates, though a sound offline owner review should stop publication.

**Recommendation** — Bind registry ID in the signed release payload and verify the registrar has both exact registry scope and bundle-preparation scope. Keep online registrar credentials short-lived and preparation-only. Treat same-owner separation as credential separation, not independent approval; require owner-visible digest review.

## 9. Approval record immutability and replay protection

**Proposed design** — Unique immutable approval ID; exact content replay is idempotent; changed content under same ID is rejected; only next registry version/predecessor can advance current head; rejected decisions are auditable without advancing the head; revoked records cannot be reused.

**Existing evidence** — Synthetic SQLite has primary/unique indexes and update/delete triggers. `record_approval` uses `BEGIN IMMEDIATE`, verifies signature/release, checks version and predecessor, makes exact replay return `False`, and rejects changed-content identity reuse. `verify_recorded_approval(current_only=True)` rejects a non-head approval.

**Missing implementation** — Database triggers do not protect against a privileged file rewrite, restoring an old copy, dropping triggers or replacing the database. The test named process-crash inserts directly in a child transaction and exits before commit; it does not crash the real approval service at every persistence boundary. No approval ID namespace reservation exists beyond SQLite uniqueness.

**Security risk** — Local database immutability is an operational guard, not a cryptographic append-only guarantee. A copied/restored old DB can appear internally consistent but stale. Exact replay currently revalidates as a *new* approval before finding the existing row, so replay after key expiry/supersession may fail rather than return the existing historical result; it does not overwrite data.

**Recommendation** — Preserve immutable rows but make external signed checkpoints the authority for current history. Add real service-boundary crash/reopen tests before production. Separate “retrieve existing identical record” from “authorize new approval”; replay must not require an expired key when it cannot create/change a record.

## 10. Audit/checkpoint integrity and retention

**Proposed design** — Retain release, approval, key manifests, signed revocations, consumer verification output and monotonic checkpoint together; keep a copy outside the registry database and publish signed hash-chain/checkpoint records to a separately controlled append-only store.

**Existing evidence** — SQLite approval and revocation tables have append-only triggers and a local integrity check for approval record digests. The design acknowledges privileged file rewrite is outside SQLite's guarantee.

**Missing implementation** — Revocation rows have no schema digest/signature, event chain, predecessor, checkpoint or retention/deletion handling. No external audit sink, independent timestamp, backup policy or restoration of trust state is implemented. Current tests only prove local SQL trigger behavior and rollback of an uncommitted transaction.

**Security risk** — An attacker with file/control-plane access can erase or rewrite both local history and revocation status; stale backup restore can resurrect a revoked key/release. Audit retention can also conflict with deletion or legal-hold rules.

**Recommendation** — Define append-only signed event schemas and a sequence/hash chain. Periodically sign a checkpoint with the active/recovery authority and retain it outside the registry store; consumers persist a high-water sequence. Choose retention and deletion rules before activation. Do not claim tamper evidence from SQLite triggers.

## 11. Cryptographic dependency selection and maintenance

**Proposed design** — Use one maintained implementation of RFC 8032 with a narrowly wrapped Ed25519 API, pinned in the approved lock for both offline signing and consumer verification. Test across actual deployment targets and keep private-key handling in a separate signer tool/process. A Python `cryptography` implementation is a candidate because it exposes Ed25519 primitives; it is not yet selected or installed.

**Existing evidence** — The project environment has no crypto package in this approval implementation; prior execution confirmed the Python `cryptography` package was absent. No dependency or production cryptographic primitive was added.

**Missing implementation** — Candidate evaluation, platform support (including Termux/deployment target), pinned version, SBOM, update cadence, vulnerability response, key format conversion and reproducible known-answer suite.

**Security risk** — Homemade crypto, subprocess signing through OpenSSL, abandoned dependencies, unreviewed updates or platform-specific behavior can undermine the trust root. Pinning without a vulnerability-update process can preserve a known flaw.

**Recommendation** — Evaluate maintained `cryptography` Ed25519 APIs against actual target support and audited release/maintenance policy; choose a supported exact version only after owner approves the added dependency. Pin it, monitor advisories, define emergency update and backward verification compatibility, and test RFC vectors in CI. The library's Ed25519 API is explicitly a security-sensitive (“Hazardous Materials”) interface; keep its use small and isolated ([official API documentation](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)).

## 12. Compatibility and rollback behavior

**Proposed design** — Approval schema, signing schema, canonicalization profile, framing version and algorithm are explicit and immutable. Release version increments by one and names the exact predecessor. Consumers pin versions and maintain a monotonic version floor/checkpoint. Historical signatures can be verified with superseded keys only for their signed validity period; revoked keys/releases are rejected under the approved revocation policy.

**Existing evidence** — Synthetic tests cover version 1→2 progression, predecessor mismatch, rollback rejection, wrong registry version and historical verification with a superseded key. The API validates schema and digest profile references.

**Missing implementation** — No consumer-held checkpoint outside the local registry DB; no compatibility matrix or migration policy for schema/profile/framing evolution; no rollback-recovery ceremony; no handling policy for consumers offline beyond a future fail-closed statement.

**Security risk** — A valid old signature remains valid if the consumer loses its high-water state or accepts a stale trust manifest. “Historical verification” can be confused with current-use eligibility. Schema changes could cause signature disagreement if the version is not pinned in the trust record.

**Recommendation** — Keep current and historical verification APIs distinct. Bind exact schema/profile/framing/algorithm and registry ID; reject unknown versions. Store checkpoint sequence and release floor outside the replaceable DB. Any intentional rollback must be a separately signed owner emergency directive naming from/to versions and reason, never simple truncation/reconstruction.

## 13. Threat model and residual risks

**Covered by proposed controls** — Registrar credential compromise; changed bundle after review; signature replay; wrong release digest; duplicate/reused identity; local accidental update; stale release selection; expired/superseded/revoked key; partial database transaction.

**Not fully covered** — Compromised owner signer or coercion; fraudulent initial fingerprint ceremony; recovery-key compromise; compromised offline host; stale/unavailable revocation distribution; rollback of both registry and local checkpoint; full device loss; an owner controlling both registrar and approver identities; software supply-chain compromise; semantically malicious registry content; denied/changed provider licensing; legal retention/deletion conflicts.

**Existing evidence** — Synthetic tests prove only injected-verifier behavior, digest/frame consistency, selected local SQLite constraints, version checks and transaction rollback. They do not prove Ed25519 security, signer isolation, trust bootstrap, hardware properties, external audit durability or production recovery.

**Recommendation** — Treat signature validity as proof only that a message was signed by a key that the consumer already trusts, not proof the registry is correct or its data rights are valid. Use independent checkpoints, offline custody and explicit fail-closed states; retain separate source-eligibility and technical review gates. A sole-owner governance model has residual single-person risk that cryptography cannot remove.

## Owner decision table

| Project Owner decision | Recommendation | Why it requires owner approval |
|---|---|---|
| Adopt the exact PureEd25519 profile, key ID/encoding, approval schema and framed message | Approve as specified above after adding the registry-ID binding and metadata canonicalization fixes | This defines the cryptographic trust contract; changing it later requires a versioned migration. |
| Select the implementation and approve the dependency/platform target | Evaluate and pin a maintained `cryptography` implementation if supported on the actual signer and consumer targets | Adds a cryptographic dependency and establishes the trust-root implementation. |
| Choose primary signer and recovery-key custody | Prefer verified hardware-backed Ed25519; otherwise dedicated offline signer plus separately held encrypted recovery copy | Determines real-world compromise and recovery exposure. |
| Approve genesis trust bootstrap and identity-verification channel | Require out-of-band fingerprint verification and separate checkpoint copy | A wrong genesis key invalidates all subsequent trust. |
| Set normal rotation, emergency revocation authority and validity/freshness policies | Normal: old + recovery confirmation. Compromise: recovery authority can revoke without compromised primary; define manifest/checkpoint sequencing | Recovery behavior and stale-revocation tolerance are operational policy, not cryptographic implementation defaults. |
| Select signed audit/checkpoint destination and retention/deletion/legal-hold rules | Separate append-only copy plus owner-held checkpoint; set retention only after applicable requirements are known | Affects external service/custody, cost, privacy and recoverability. |
| Approve final implementation and production activation | Separate later decision after security blockers close and implementation/recovery tests pass | Current designation and this review authorize preparation only. |

No production keys were created, no cryptographic dependency was installed, no production registry release or configuration was changed, and no activation was attempted. DEC-04 and H4-03 remain deferred.
