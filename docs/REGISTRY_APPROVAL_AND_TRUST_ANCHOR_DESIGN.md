# Production registry approval and trust-anchor design

**Status: PROPOSED — AWAITING PROJECT OWNER REVIEW**  
Prepared: 2026-11-19  
Authority recorded: Project Owner and Registry Release Approver.

## Documentation reconciliation — 2026-11-20

The original proposal text below is retained as review history. The “Cryptographic profile (proposed)” and old signing-byte example use the pre-remediation v1 approval schema; they are superseded for new approvals by the v2 signing contract in “Version 2 registry identity and signing compatibility” below and by `docs/REGISTRY_GOVERNANCE_SECURITY_REVIEW.md`. New synthetic releases and approvals use v2; release/approval v1 is historical-only. The v2 canonical signing payload and full-record digest are unchanged by this reconciliation.

The original key-rotation bullets are policy proposals, not implemented behavior. Current implementation has synthetic genesis v2 and signed revocation/checkpoint records, but no signed trust-manifest successor or routine rotation protocol. Synthetic signatures use HMAC callbacks only. There is no production Ed25519 implementation; Android/Termux compatibility, physical key custody, external checkpoint storage and recovery remain unverified. SQLite is not independent rollback protection. No production trust anchor or release is active.

**Security remediation addendum (2026-11-19):** Synthetic release/approval v2, genesis, signed revocation and checkpoint contracts are now implemented in the isolated prototype. They use injected test HMAC only. No production Ed25519 implementation, key, trust anchor, release path or activation exists. The exact updated profile and remaining owner decisions are recorded in `docs/REGISTRY_GOVERNANCE_SECURITY_REVIEW.md`.

This document prepares a reviewable production design. It does not authorize or enable a production release, trust anchor, migration, database, deployment or provider. The implementation described under “Synthetic implementation status” is disconnected, uses test-only HMAC material, and cannot publish production registry state.

## Executive summary

Use the existing canonical registry bundle and framed digest contracts. A scoped registrar prepares an immutable candidate; the Project Owner reviews its exact digest and signs a versioned approval record using an offline Ed25519 key. Consumers verify the bundle, approval signature, key validity/revocation state, predecessor chain and monotonic registry version before use. The signing private key never enters the application, CI, registry database, source control or Termux environment.

Keep the registry release-approver identity and registrar identity separate. A registered approval is not itself an activated release: publication remains disabled until this design and its implementation receive a separate explicit owner approval. Production signing, key enrollment and release verification are not implemented.

## Authority and responsibility model

The Project Owner and Registry Release Approver is authorized, subject to reviewing and separately approving this design, to:

- Approve or reject the exact immutable registry release bundle and compatibility statement.
- Grant, restrict and revoke registrar identities and registry scopes.
- Enroll, rotate, suspend and revoke trust-anchor keys and choose recovery arrangements.
- Revoke approval of a compromised or invalid release and suspend subsequent publication pending recovery.
- Approve retention and custody rules for approval artifacts, revocation records and audit evidence.

Preparation is a registrar capability. Approval is a distinct signing capability. Registrar registration cannot grant approval authority. A registrar cannot approve a bundle whose `prepared_by_registrar_id` equals the approver identity. This separates technical identities and credentials; because this is a single-owner project, it does not create independent human four-eyes control. The owner can ultimately control both roles, which is a documented residual risk.

Audit every registrar-scope grant/change/revocation, trust-key enrollment/rotation/revocation, approval/rejection, publication, release revocation and recovery. Each audit event records actor/key identity and version, UTC time, target identity/digest, previous event/head, reason/change reference and resulting state. Production audit records must be signed and retained outside the writable registry database; local append-only SQLite triggers alone are not tamper evidence.

## Release lifecycle

1. A registrar with explicit registry and bundle-preparation scopes proposes immutable registry entry versions and a change reference. It cannot mint owner approval credentials.
2. Generate the complete release bundle from one consistent snapshot. Bundle identity is `sha256:<digest>` over the existing canonical JSON and HASH-01 framed bytes. The release ID is outside the hashed payload.
3. Verify every entry digest, schema/profile/framing reference, namespace, provider/capture policy reference, lifecycle event, compatibility declaration and predecessor link. Reject unknown, incompatible, deprecated or invalidated dependencies as applicable.
4. Submit the exact bundle bytes, digest, proposed monotonic registry version, predecessor release ID, compatibility statement, change record and validation output as a candidate.
5. The Project Owner reviews those exact immutable bytes and the review output. Any edit creates a new digest and requires a new review.
6. Authenticate the approval with the enrolled approval key. The signature covers the canonical approval payload, which includes the exact release ID and digest, registry ID/version, predecessor, registrar identity, approval decision, key ID/version, timestamp and compatibility metadata.
7. Publication accepts only a verified `approve` decision, an unused approval identity, the next version after the last approved head, the correct predecessor, an active non-revoked key, and a registrar with the required scope. A `reject` decision is durably auditable but does not advance the approved head.
8. Publish the immutable bundle and signed approval artifact together. Consumers verify both before resolving registry definitions; they pin exact entry and release identities. Consumers keep a monotonic version floor or a trusted transparency checkpoint so a valid old signature cannot silently roll the consumer back.
9. Revoke a release by publishing a signed revocation record bound to the release digest and reason. Consumers fail closed when the release is revoked or when revocation state is stale/unavailable.
10. Recover only from verified immutable bundle, approval and audit artifacts into a new empty catalog. Verify signatures, key history, predecessor chain, record digests, registry integrity and foreign keys before enabling reads. Never overwrite or merge into an existing production catalog as a recovery shortcut.

### Abuse and replay controls

| Threat | Required control |
|---|---|
| Approval of a different bundle than reviewed | Signature binds exact `release_id` and `release_digest`; changed bytes/digest invalidate the approval. Approval UI shows the digest computed from candidate bytes and the signer confirms that digest. |
| Duplicate identity or approval replay | Immutable unique approval ID; unique approved release ID and registry-version slot; exact replay is idempotent at most and cannot republish; revoked approvals are permanently rejected. |
| Version rollback | Approval requires next monotonic registry version and exact prior approved release ID. Consumers persist a version floor/checkpoint; recovery cannot lower it without an explicit owner-controlled recovery ceremony. |
| Unauthorized publication | Separate registrar and approver keys/identities; verify registry scopes, approval decision/signature and current revocation state before publication. No public production release endpoint exists in this milestone. |
| Registrar self-approval | Reject when approval key identity equals the candidate's registrar identity. Keep registrar credentials out of the signing device and signing credentials out of CI. |
| Reuse of revoked/expired/superseded key | New approvals require an active key within its validity interval. Revoked keys invalidate approvals per the selected revocation policy; superseded/expired keys may verify historical approvals only if signed during their valid period and not revoked. |
| Tampering after approval | Signature authenticates canonical approval bytes and release digest; immutable bundle digest and append-only signed revocation/audit chain detect changes. A database alone is not the trust source. |
| Approval-service or repository rollback | Consumer monotonic checkpoint, signed current trust/revocation manifest, and independently retained checkpoint. Without a fresh trusted checkpoint, fail closed for current release selection. |

## Trust-anchor architecture

### Recommendation

Use Ed25519 for registry approval signatures, backed by an offline signing key. Prefer a hardware-backed token/HSM only after verifying that the specific device supports Ed25519 signing with the required key non-exportability and recovery semantics. Do not assume Android Keystore, a Termux device, or any attached authenticator provides that capability.

For the present Termux/Android development environment, do not create the production key on the phone. If no suitable hardware-backed Ed25519 signer is available, use a dedicated offline signing environment with a vetted, pinned crypto implementation and an encrypted removable backup kept separately under the Project Owner's control. Unlock and sign only after reviewing a candidate digest. A general online OS key store may protect a convenience key against casual file theft but is not the recommended root of trust. Do not silently fall back to another algorithm; any alternative needs a reviewed profile and owner decision.

Enroll a primary key and a separately stored recovery key, both controlled by the same designated Project Owner. The recovery key is not a second human approver; it allows owner-controlled rotation/revocation if the primary device is lost. Bootstrap their public-key fingerprints out of band, record the verification method in the signed trust manifest and distribute the pinned root fingerprint independently of the registry bundle it authenticates. Avoid circular trust where a registry release is the only source of its own key.

### Cryptographic profile (proposed)

**Historical draft note:** The v1 field and framing references in this original proposal are not the current approval payload. Preserve them for audit; apply the v2 contract below for new synthetic verification and any future production proposal.

- **Algorithm:** Ed25519, pure EdDSA as defined by the selected vetted implementation; no prehash variant and no algorithm negotiation from unsigned input.
- **Key sizes:** 32-byte raw public key; 32-byte private seed held only by the signer; 64-byte signature.
- **Key ID:** lowercase hex `SHA-256(ASCII("XAU-REGISTRY-ED25519-v1") || 0x00 || raw_public_key)`. Key version is a separate positive monotonic integer per key identity/authority.
- **Public-key encoding:** exactly 32 raw bytes represented as unpadded base64url in the signed trust-anchor manifest; enforce canonical re-encoding and reject alternate spellings.
- **Signature encoding:** exactly 64 bytes represented as 128 lowercase hexadecimal characters in the approval record.
- **Signed bytes:** `frame_payload(canonical_json(approval_signing_payload, REGISTRY_APPROVAL_SIGNING_SCHEMA), approval_profile, digest_registry, limit)`. The existing `frame_payload` v1 framing includes `XAU-CANON\0`, framing version, domain, profile ID, payload length and canonical payload. The approval payload excludes the signature itself.
- **Digest binding:** the signing payload includes registry ID/version, exact release ID and SHA-256 digest, predecessor ID, registrar ID, approval decision/time, key identity/version, compatibility metadata, canonicalization profile and framing version. The complete approval record (including signature) has a separate digest under the registered `registry.approval-record` profile. Neither digest contains itself.
- **Key identity/version:** consumers require an exact `(key_id, key_version)` record from the independently trusted key manifest. Unknown key, algorithm mismatch, malformed key/signature, revoked key or invalid signing time is rejected.

The current project codec has SHA-256 framing v1 but no Ed25519 implementation or Python cryptographic package. Production code must use a reviewed implementation pinned in the approved dependency lock, with known-answer and negative test vectors. Do not call OpenSSL through shell commands from the service as an implicit signer.

## Approval record and consumer checks

Current synthetic schema: `xau.registry-approval.v2`; signing payload schema: `xau.registry-approval-signing.v2`. Historical v1 records retain their explicit historical verifier and are not emitted for new approvals. Required v2 record fields are:

- Approval ID, registry ID and monotonic registry version.
- Release ID, exact release digest, and predecessor release ID.
- Prepared-by registrar identity and approving Project Owner identity.
- Trust-anchor key ID/version and signature algorithm.
- UTC approval timestamp and `approve` or `reject` decision.
- Canonical compatibility metadata, canonicalization profile and framing version.
- Signature bytes in the profile's canonical encoding.

Validation order: validate exact schema and canonical metadata; verify release bundle ID/digest and predecessor; resolve the exact enrolled key version; check approver identity and role separation; check key state and approval timestamp; reconstruct the framed signing bytes; verify the signature; verify record digest; consult revocation state; enforce monotonic head/version; then allow use only for an approved active release. A historical decision can remain verifiable with a superseded key, but it must not be selected as the current head. Unknown or stale revocation state fails closed.

An approval reference string in a change or bundle is audit metadata only. It is not proof of approval and cannot substitute for the signed approval record.

## Key custody, rotation, and recovery

- Keep private key material out of source control, environment variables, application processes, CI, SQLite, logs, backups of the registry and support tickets. Only the offline signer handles it.
- Protect the offline primary key with a hardware token where verified, or encrypted offline media and an owner-controlled passphrase. Store a separate encrypted recovery copy under separate physical custody. Restrict access to the Project Owner; never copy the recovery secret into the development phone.
- Enroll keys using a signed trust-anchor manifest with key ID, version, public key, owner role, activation time, optional expiry, state and predecessor. Bootstrap the first manifest from independently verified fingerprints. A normal key cannot add itself as trusted.
- Rotate by preparing a new key pair offline, verifying its fingerprint, signing a trust-manifest update with the current key and recovery key according to the owner-approved procedure, publishing an overlap period, then marking the old key superseded. Old signatures remain historical-verifiable only for timestamps before supersession/expiry.
- Revoke a compromised key using an uncompromised recovery key; mark it terminally revoked in a signed revocation manifest, identify affected approvals/releases, suspend publishing, and force consumers to refresh revocation state before new use. If both keys are unavailable, stop release use and bootstrap a replacement only through a documented out-of-band owner verification of the new root fingerprint.
- Lost device without suspected compromise: suspend the lost key, recover from a tested separate backup, enroll a new key, and record all steps. Suspected compromise: treat as compromised, revoke immediately, rotate recovery and primary keys if exposed, re-approve unaffected current bundle under the new root, and audit affected consumer checkpoints.
- Test recovery with synthetic keys and disposable data before owner review. A production drill needs the owner's separate authorization and must not touch existing production stores.

No key lifetime or rotation interval is selected here. The owner must decide whether to use an expiry window and the operational cadence; all production limits remain unconfigured until approval.

## Operational and security procedures

**Registrar lifecycle:** issue unique machine identities with least-privilege registry scopes; require reviewed change references; log issuance, scope changes, expiration and revocation; rotate credentials after personnel/device/CI compromise. Registrar credentials authorize preparation only.

**Approval:** export candidate to immutable local file; verify it offline; show the full digest, predecessor/version, compatibility report and change reference on the signer; sign only the exact digest; immediately verify the generated signature with the enrolled public key; store the signature artifact beside the bundle; never silently retry or change fields after signing.

**Audit and backup:** retain the original signed bundle, approval, key manifest, revocation events, verification output and checkpoint together. Keep at least one owner-controlled copy separate from the registry database. Record a signed hash-chain/checkpoint to a separately controlled append-only destination selected by the owner. Local SQLite triggers detect ordinary edits but cannot protect against a privileged database/file rewrite or rollback.

**Emergency suspension:** disable candidate publication and consumer promotion; preserve artifacts and logs; revoke a key/release through an authenticated signed event; notify consumers by the owner-approved channel; require a fresh signed trust/revocation manifest and monotonic checkpoint before resuming.

## Alternatives and trade-offs

| Option | Benefit | Limitation / fit |
|---|---|---|
| Offline Ed25519 key (recommended) | Simple, fast, widely supported, public verification, no online signing endpoint | Requires disciplined offline custody and tested recovery; a lost sole key can halt releases. |
| Hardware-backed signer | Better private-key isolation and physical confirmation | Device/OS support and backup semantics vary; Ed25519 may not be available. Verify actual hardware and API before selection. |
| OS-protected key storage | Convenient on the current phone and may benefit from device unlock protections | Hardware-backed status is platform-dependent; compromised unlocked device/app may invoke the key. Not the preferred root without verified capabilities. |
| Online signing service | Convenient centralized policy/audit | Adds a service, credentials, availability and compromise surface; external service/spending/operations need separate authorization. Not proposed now. |
| HMAC/shared secret | Small synthetic test fixture | Anyone able to verify can also forge. Not acceptable for production approval signatures. |

## Threat model and limits

Protect against accidental/hostile registry changes, compromised registrar credentials, altered release artifacts, approval replay, stale/rollback releases, key expiration/revocation, ordinary database edits and device loss. Ed25519 signatures plus canonical digest binding establish authenticity only when the key is correctly enrolled and the signer reviewed the exact bundle. They do not prove that registry definitions are semantically correct, that source licenses are valid, or that a sole owner has independently reviewed their own work.

Residual risks include malicious or compromised owner signing device, coercion, collusion with a registrar, compromised offline host, weak recovery backup custody, forged bootstrap fingerprints, rollback by a consumer without an independent version checkpoint, source-control history rewrite, local audit-log rewrite, stale revocation distribution, implementation or dependency vulnerabilities, and loss of both keys. Hardware/organizational controls and independent review reduce some risks but are not available or assumed here.

## Synthetic implementation status

Implemented in the disconnected synthetic registry:

- Release format v2 and approval v2 schema/profile; the release payload includes `registry_id`, and the exact approval signing payload binds that ID to the target registry plus release digest, version, predecessor ID/digest, registrar, decision, timestamp, key ID/version, algorithm and compatibility/canonicalization/framing metadata.
- Signature is excluded from signing bytes; the complete signature-bearing record receives a separate digest. Historical release/approval v1 is never silently reinterpreted; unbound v1 release verification is explicitly historical-only and cannot be newly approved.
- Synthetic genesis trust manifest and sequence-0 checkpoint; primary and recovery keys sign/prove possession over one canonical payload, and verification requires out-of-band manifest digest and primary fingerprint pins. Signed revocation and checkpoint records chain sequence, predecessor digest, event digest, trust-manifest digest, authority key identity/version, target and effective release sequence.
- Synthetic SQLite writes are transactional and immutable; append requires the separately supplied trusted checkpoint digest to match local head. Independent exported-chain verification checks pinned genesis and latest checkpoint. The legacy unsigned `revoke_approval` path rejects.
- HMAC-SHA256 test keys and injected callbacks only. These verify schema, canonical framing, digest binding and rejection paths; they are **not** public-key cryptography, do not establish Ed25519 security, and do not protect against rollback of a database and its local checkpoint together.

Not implemented: Ed25519 signing/verification, production key store/enrollment, signed trust-manifest successor/normal rotation, production emergency procedures, independent checkpoint service/device integration, external audit retention, publication/consumer activation, production approval UI or migration. Production release remains disabled.

## Explicit decisions awaiting Project Owner review

1. Approve or change the proposed Ed25519 signature profile and canonical signing message.
2. Select custody after verifying actual support: preferred hardware-backed Ed25519 token/HSM, otherwise offline encrypted signing host/media; confirm the primary and separate recovery-key arrangement.
3. Approve trust-manifest bootstrap, key expiry/rotation policy, compromise response and out-of-band recovery-fingerprint process. No duration or numeric policy has been invented.
4. Select the independently controlled signed audit/checkpoint storage and retention/deletion/legal-hold policy.
5. Approve the vetted Ed25519 implementation/dependency and test-vector plan before implementation. No dependency was added in this preparation.
6. After those decisions, review the production implementation and separately authorize activation. This preparation itself does not grant activation authority.

Until the owner reviews and separately approves the final design and implementation, production trust-anchor enrollment, signing, release publication, migration and deployment remain disabled. DEC-04 and H4-03 remain deferred.

## Version 2 registry identity and signing compatibility

Release format v2 includes `registry_id` in the canonical bundle payload under `xau.registry-release.v2`. Approval schema v2 independently binds that same ID, `release_id`, release format, digest, version and exact predecessor release ID/digest. The verifier compares the bundle identity to the target registry identity before accepting the approval. V1 bundles remain historical-only through an explicit compatibility option and warning; they cannot be submitted as new approvals. There is no implicit reinterpretation between versions.

The exact signature payload is the canonical JSON bytes for `REGISTRY_APPROVAL_SIGNING_V2_SCHEMA`, passed to the `registry.approval-signing.v2` framed digest profile. It includes approval ID/schema version, registry ID/version, release ID/format/digest, predecessor ID/digest, registrar ID, approver ID, decision, timestamp, key ID/version/algorithm, canonicalization profile, framing version and structured compatibility metadata. The `signature` field is excluded. The signature-bearing full approval record is separately hashed using `registry.approval-record.v2`; its digest is not embedded inside that record. Release bundle digest is independently computed from the complete canonical v2 release payload.

## Genesis and revocation checkpoint protocol (synthetic contract)

Genesis trust-manifest schema v2 binds the initial registry ID, primary and recovery key IDs/versions/public keys, signature algorithm and initial checkpoint ID. The primary signs the canonical genesis payload and the recovery key provides a second proof-of-possession signature over those same bytes; both signatures are covered by the full-record digest. A consumer must receive both the expected genesis-manifest digest and primary-key fingerprint through an independent owner-controlled channel; checking a manifest stored beside the registry is insufficient. The initial sequence-0 checkpoint binds the genesis manifest digest and a fixed empty-history digest. Trust is established only after out-of-band pin comparison and both signature verifications.

Each revocation has an append sequence, explicit `effective_sequence`, target kind/ID/digest, authority key ID/version, reason code, effective timestamp, event timestamp and previous checkpoint digest. A checkpoint signs registry ID, append sequence, predecessor checkpoint digest, revocation digest, genesis trust-manifest digest and authority key ID/version. Writes are transactional and append-only in the synthetic SQLite prototype. To verify current state, a consumer also needs a latest checkpoint digest retained independently from that database. Local SQLite cannot prove that its own latest row has not been rolled back or deleted.

The synthetic verifier accepts primary or recovery keys enrolled by genesis. The emergency recovery test demonstrates recovery-key revocation without a primary signature. This does not yet implement trust-manifest successor transitions or production consumer checkpoint persistence. Normal rotation is proposed as old-primary plus recovery authorization, with an explicit effective release sequence, overlap window and retirement; emergency rotation permits the recovery key to revoke a suspected-compromised primary without relying on it. If both keys are lost or compromised, freeze releases and rebootstrap only through owner-controlled out-of-band fingerprint verification. Exact overlap/freshness/retention rules remain unselected.

## Ed25519 candidate and environment limits

### Local synthetic adapter check (2026-11-19)

The native Termux package `python-cryptography` 48.0.1-1 is installed and imported through the existing backend virtual environment, which includes Termux system site-packages. Synthetic tests passed the RFC 8032 Ed25519 vector, exact 32-byte raw public-key export, 64-byte deterministic signature, valid verification, and invalid-signature rejection. The registry callback adapter receives in-memory private-key objects indexed by raw public key; verification uses the public bytes held by the supplied synthetic `ApprovalKey`. The synthetic approval, genesis trust, revocation, and checkpoint flows use the existing v2 canonical payloads and framing.

For a local synthetic run, install the native Termux package `python-cryptography` (not the PyPI package), then provide ephemeral `Ed25519PrivateKey` objects to `ed25519_signer({raw_public_key: private_key})`. Pass `ed25519_verify` to the existing approval/trust verifier parameters and put the matching raw public key in each test `ApprovalKey.verification_material`. The RFC seed in tests is public test material only. No project dependency or lockfile was changed.

This confirms functional behavior only on this Termux device; upstream `cryptography` platform guidance does not establish Android/Termux as a supported platform. There is no production key configuration, custody, genesis enrollment, recovery, trust-anchor activation, or registry release. Those remain blocked pending Project Owner decisions, key-custody design, compatibility/update controls, and separately authorized production implementation and activation.
