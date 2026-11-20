# Registry Governance — Project Owner Decision Package

**Status: PREPARED FOR PROJECT OWNER REVIEW — NO PRODUCTION AUTHORIZATION**  
Prepared: 2026-11-19  
Authority: Project Owner and Registry Release Approver

Documentation consistency update: 2026-11-20. Historical wording is preserved and explicitly superseded where applicable below.

This package collects the remaining trust-anchor choices into an actionable review. It does not approve implementation, generate keys, enroll a trust anchor, publish a release, or activate production. The Project Owner remains the only designated human release authority; no additional approver is proposed.

## Readiness evidence and boundaries

| Evidence class | Current state |
|---|---|
| Design | The v2 release/approval signing and record-digest contracts, genesis pinning, signed revocation/checkpoint chain, and owner-controlled recovery model are specified. The production custody ceremony, normal trust-manifest update protocol, external checkpoint operation, retention rules, and target platform are still decisions or designs. |
| Synthetic verification | Registry suite: 36 tests; full backend: 542 tests. Frontend typecheck, 20 tests and build also passed. These tests exercise the synthetic contracts and failure paths. |
| Real cryptographic verification | **NOT PERFORMED.** Synthetic signature callbacks use HMAC-SHA256. They prove neither Ed25519 correctness nor asymmetric security. `cryptography` is not installed. No RFC 8032 known-answer vectors were run. |
| Operational verification | **NOT PERFORMED.** No real key, device, backup, independent checkpoint repository, recovery drill, or production consumer was used. SQLite is not independent rollback protection. |

New releases must continue using the existing release v2 and approval v2 contracts. Their canonical signing and separate full-record digest contracts are preserved. Release v1 remains historical-only and cannot be newly approved. Do not reinterpret v1 as v2 or use its old unbound registry identity. The review/design documents retain some original baseline passages that describe v1 or unsigned revocation; the dated reconciliation addenda now label these passages as historical and point to current contracts without deleting audit history.

## A. Ed25519 library and supported platforms

**Current implementation:** Release/approval v2 has an injected signing/verifying boundary; tests inject HMAC. There is no Ed25519 code or crypto dependency.

**Unimplemented / unverified:** Library choice, locked version, build and runtime support on the actual signer and verifier targets, RFC test vectors, malformed-signature behavior, advisory/update procedure, and cross-platform verification. The inspected environment is Python 3.13.13 on Android 17 / aarch64; `cryptography` is absent. Its official documentation states Python 3.9+ and lists tested operating systems that do not include Android/Termux. Python-version compatibility therefore does not establish Termux compatibility. Source builds have native toolchain requirements. See [Ed25519 API](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/), [installation/platform guidance](https://cryptography.io/en/latest/installation/), and [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html).

**Options:**

| Option | Advantages | Disadvantages and consequences |
|---|---|---|
| Use `cryptography` on an officially tested host for offline signing and verification; keep Termux unable to accept registry releases until a supported verification target is established | Maintained Python API; standard Ed25519 interface; avoids assuming Android support | Adds a dependency and a separate supported host; does not solve verification inside Termux; owner must accept host and maintenance workflow |
| Validate/build `cryptography` on Termux and use it only if the exact Android build passes a documented support review | Could keep verification local to the current environment | Upstream does not list Android/Termux among tested platforms; native build and update burden; successful compilation alone is not a support or assurance claim |
| Select another maintained Ed25519 implementation with explicit Android support | May fit Termux better | Requires a separate supply-chain, API, vector, maintenance, and dependency review; no candidate is established here |

**Recommendation:** Preserve PureEd25519 and the current v2 signing bytes. Evaluate `cryptography` first on its documented supported target for an offline signer, but do not choose it for Android/Termux production verification without reproducible target evidence. If Termux must verify releases, evaluate a maintained Android-supported implementation separately. No HMAC, custom crypto, or silent algorithm fallback for production.

**Exact Project Owner approval required:** Select the implementation and the signer/verifier platform(s), or authorize a bounded dependency/platform evaluation without authorizing installation or signing. Accepting a new dependency requires a separate lockfile change authorization under project rules.

**Tests required before production approval:** RFC 8032 known-answer vectors; wrong-message, malformed, truncated and non-canonical signature/key rejection; public-key encoding/key-ID vectors; v2 canonical payload and framed-byte vectors; signature and full-record digest verification; cross-platform signatures verified identically; clean builds on each declared target; dependency pin, vulnerability/advisory process and upgrade compatibility review.

## B. Primary and recovery private-key custody

**Current implementation:** Genesis v2 binds primary and recovery public keys and requires both signatures/proof of possession in the synthetic contract. No private keys were created. The sole designated human is the Project Owner.

**Unimplemented / unverified:** Signer hardware capability, private-key generation and non-exportability, physical custody, encryption/passphrase recovery, access logging, backup integrity and restore drill. A synthetic HMAC key is not a custody model.

**Options:**

| Option | Advantages | Disadvantages and consequences |
|---|---|---|
| Hardware-backed Ed25519 signer, with separate recovery hardware/media, only after exact device/API testing | Stronger isolation if key is non-exportable and signing is constrained | Ed25519 may not be supported; recovery/backup may be impossible; device loss or vendor lock-in can halt releases |
| Dedicated offline signing host and encrypted removable primary/recovery media, stored separately | Practical and independent of the app/service; transparent recovery path | Exportable keys and removable media increase theft/copy risk; owner must protect passphrases and rehearse restoration |
| Android/Termux local key storage | Convenient for local operation | No evidence that the specific device/API provides required Ed25519 hardware isolation; compromise of unlocked device or app may expose or invoke key; not recommended as root custody |

**Recommendation:** Keep primary signing outside the application and development phone. Prefer a verified hardware-backed signer only when its Ed25519, custody and recovery properties are demonstrated. Otherwise use a dedicated offline host, encrypted media, and a separately held recovery copy. Access stays with the Project Owner; this is credential separation, not independent human approval. Treat unexplained loss as suspected compromise until assessed.

**Exact Project Owner approval required:** Choose the custody option; specify who physically holds the recovery copy (the owner, in a separate location), the acceptable passphrase/backup method, and whether any hardware capability is a prerequisite. No key should be generated until that choice and target are recorded.

**Tests required before production approval:** Synthetic restore rehearsal; selected signer capability and non-exportability evidence if applicable; generate/import/sign/verify round trip on the exact approved host; backup integrity and restore on a clean device; loss of primary, loss of recovery, wrong passphrase and duplicate-copy compromise exercises; confirm secrets never enter repository, app, CI, environment, SQLite, logs or registry artifacts.

## C. Independent genesis fingerprint and manifest verification

**Current implementation:** Trust-manifest v2 binds registry ID, primary/recovery key IDs, versions and public keys, algorithm, timestamp and initial checkpoint. Primary signs the canonical genesis payload and recovery key signs the same bytes as proof of possession. Synthetic verification requires an externally supplied manifest digest and primary-key fingerprint.

**Unimplemented / unverified:** The actual independent channel/device, the owner ceremony, how the consumer receives and stores pins, and recovery of those pins. A manifest or fingerprint stored only beside the database it authenticates is circular and not trusted.

**Options:** (1) owner checks a human-readable SHA-256 fingerprint on a physically separate device or printed record; (2) transfer the exact signed manifest and pins through a separate owner-controlled removable medium; (3) trust-on-first-use from the application/database. Option 3 is operationally easy but cannot authenticate the initial key and is rejected.

**Recommendation:** Use a two-part owner ceremony: independently verify the primary public-key fingerprint (key ID is SHA-256 over its domain prefix and raw public key) and the complete genesis-manifest digest through a separate channel/device; verify the primary signature and recovery proof; then store the pins outside the replaceable registry database. Record date, registry ID, trust-manifest version and verification method. This avoids circular trust without inventing another approver.

**Exact Project Owner approval required:** Choose and identify the independent channel and the consumer pin location; approve that no registry is usable before this ceremony has been completed.

**Tests required before production approval:** Clean-consumer bootstrap from only out-of-band pins; reject changed key, changed manifest, wrong registry, missing/replaced recovery key, invalid primary or recovery signature, and a database-only key; demonstrate restoring pins after application/device reinstall without consulting the registry database.

## D. Normal trust-manifest and key rotation

**Current implementation:** Approval key-version tests cover synthetic approval verification and historical signatures. Genesis trust-manifest v2 and signed revocation exist. There is no signed trust-manifest successor/rotation record or consumer rotation state machine.

**Unimplemented / unverified:** Successor schema, old/new key possession, authorization threshold, effective release sequence, overlap and retirement semantics, rollback protection, consumer rollout and recovery from a partially deployed rotation.

**Options:** (1) require signatures from both the currently trusted primary and the recovery key over the exact successor manifest; (2) primary alone; (3) recovery alone for routine rotation. Option 1 prevents either credential alone from silently rotating a healthy root but creates a two-key availability dependency. Options 2/3 reduce operational burden but allow one key compromise to replace the other in routine operation.

**Recommendation:** Planned rotation uses both old primary and recovery signatures over a successor manifest that binds registry ID, trust-manifest version, predecessor manifest digest, new key IDs/versions/public keys, effective registry release sequence, and timestamp. The Project Owner controls both keys. Overlap should be release-sequence based; do not choose a time duration without an operational requirement. Preserve old keys for historical signature verification while preventing new approvals after their retirement point.

**Exact Project Owner approval required:** Approve the two-signature routine rotation rule, the sequence boundary semantics, whether overlap is required, and which release sequence is the cutover. Approve a separately versioned successor schema before it is implemented.

**Tests required before production approval:** Valid dual-signed successor; either signature missing/invalid; wrong predecessor/version/registry; duplicate or replayed successor; release rollback; old key cannot approve after cutover but can verify allowed history; new key cannot approve before cutover; interrupted consumer migration; recovery from each valid overlap state.

## E. Emergency compromise recovery and total key loss

**Current implementation:** Synthetic recovery authority can append a signed revocation of the primary without the primary signing. The synthetic chain rejects a later event signed by that revoked key. This is HMAC control-flow evidence only. It does not yet install a signed successor trust manifest or authorize new production approvals.

**Unimplemented / unverified:** Production recovery authority scope, compromised-key exposure window, distribution and consumer convergence, successor enrollment, recovery-key compromise response, total-loss ceremony, and end-to-end restore. A compromised primary must never be required to authorize its own replacement.

**Options:** (1) recovery key alone may sign an emergency revocation and successor-root record; (2) require primary plus recovery even during compromise; (3) when both keys are lost/compromised, freeze and establish a new genesis by an owner-run independent fingerprint ceremony. Option 2 can make recovery impossible if the primary is compromised. Option 1 creates strong power in the recovery credential. Option 3 breaks cryptographic continuity but avoids pretending an untrusted key can restore it.

**Recommendation:** Keep routine rotation separate. On suspected primary compromise, immediately suspend publication and current-release promotion; treat the primary as untrusted; recovery key alone may revoke it and authorize an emergency successor manifest, with event/checkpoint recorded and independently pinned before resumption. If recovery key is also compromised or lost, stop release use and perform owner-controlled out-of-band rebootstrap with a new genesis. Preserve old records as historical artifacts but mark affected signatures untrusted from the documented effective sequence/time. Do not assert continuity through an untrusted key.

**Exact Project Owner approval required:** Grant the recovery key the narrowly scoped emergency authority to revoke/replace the primary without primary consent; approve the fail-closed freeze; approve the rebootstrap rule if both keys are lost. This grants authority to the Project Owner's recovery credential, not a new human approver.

**Tests required before production approval:** Recovery-key revocation of primary; reject primary-signed successor after revocation; reject replayed/stale checkpoint; recovery-key compromise path; no available trusted key; total key loss/new genesis; old bundle/release warning and rejection behavior; consumer notification and resumption only after fresh independently pinned checkpoint.

## F. Independent checkpoint storage, retention and restoration

**Current implementation:** Synthetic revocations and checkpoints are immutable SQLite rows; signed records chain to prior digests. The verifier accepts independently supplied genesis pins and latest checkpoint digest and verifies an exported history. This demonstrates integrity checks and pin comparison, not real independent storage or anti-rollback operations.

**Unimplemented / unverified:** Actual high-water checkpoint custody, delivery to consumers, backup independence, write/restore procedure, freshness policy, retention/deletion/legal hold, outage handling, monitoring and rollback alarm. SQLite alone cannot tell whether its own file has been replaced with an older valid copy.

**Options:**

| Option | Advantages | Disadvantages and consequences |
|---|---|---|
| Owner-held offline checkpoint plus separately protected backup | No service dependency or automatic spending; clear trust boundary | Manual update/distribution and possible staleness; owner must protect both copies and consumers must fail closed when freshness is unknown |
| Independent append-only service/object-lock/transparency store | Better availability and independent history distribution | Adds service, credentials, policy and potentially spending; must separately assess deletion/immutability guarantees; not authorized now |
| SQLite/database backup only | Simple restore | Not independent; attacker or operator can roll back both history and checkpoint together; does not meet anti-rollback requirement |

**Recommendation:** For initial single-owner operation, use an owner-held high-water checkpoint outside the registry database plus a separately protected backup in another location. Every accepted checkpoint update records registry ID, sequence, digest, time and custody location. On missing/stale/mismatched checkpoint, fail closed for current release selection. Restore only from a chain that reaches the independently held high-water digest. Choose a service later only if manual operations prove unsuitable and separate authorization is granted.

**Exact Project Owner approval required:** Choose the independent storage method and backup separation, define who updates/holds each copy, select a freshness and retention policy, and decide whether an external service is acceptable (any spending requires separate approval). No numeric retention or freshness threshold is proposed here.

**Tests required before production approval:** Write and verify checkpoint independently; restore registry from backup; reject valid-but-old DB/checkpoint, missing/deleted event, broken linkage and replayed checkpoint; simulate checkpoint-store outage and stale consumer; prove restore cannot lower high-water mark; exercise retention/deletion/legal-hold handling and document recovery time.

## G. Production implementation and activation are separate decisions

**Current implementation:** Production signing, keys, trust-anchor enrollment, registry publication and release activation are disabled. Synthetic release/approval v2 remains isolated. Existing owner designation authorizes design preparation only.

**Unimplemented / unverified:** All production cryptographic code, approved dependency lock, signer custody, trust enrollment, independent checkpoint store, operational monitoring, migration, deployment and recovery drill.

**Options:** (1) authorize a bounded non-activating implementation after A–F decisions; (2) authorize implementation and activation together; (3) defer both. Combining implementation and activation reduces ceremony but removes the owner's review gate after implementation evidence exists.

**Recommendation:** Separate gates. First authorize production implementation only, explicitly forbidding key generation, trust-anchor enrollment, publication, migration and deployment unless separately included. Require a reviewable implementation and test report. Then make a distinct activation decision covering key ceremony, registry release, deployment/migration scope, rollback and operational acceptance.

**Exact Project Owner approval required:** Later, separately approve (a) production implementation scope and dependency changes, then (b) production key generation/enrollment and release activation. This document requests neither approval.

**Tests required before implementation can be proposed for activation:** All A–F tests above; production-target Ed25519 vectors; API/schema compatibility and v1 historical-only checks; security review of secret boundaries; independent checkpoint rollback tests; clean restore and compromise drills; deployment/rollback rehearsal in disposable non-production infrastructure; monitoring and incident runbooks. No test suite by itself authorizes activation.

## Owner decision checklist

| ID | Decision | Recommended choice | Approval needed now? |
|---|---|---|---|
| A | Ed25519 library and signer/verifier platforms | PureEd25519; evaluate `cryptography` on a documented supported host; no Termux claim until verified | Yes, select target/evaluation scope; dependency installation remains separate |
| B | Primary/recovery custody | Offline owner-controlled primary and separately held encrypted recovery; verified hardware only if capability is evidenced | Yes |
| C | Genesis trust ceremony | Independent verification/pinning of both manifest digest and primary fingerprint; pins outside registry DB | Yes |
| D | Routine rotation | Old primary plus recovery signatures; release-sequence cutover and explicit overlap semantics | Yes |
| E | Emergency and total loss | Recovery-only primary revocation/replacement; freeze on uncertainty; new owner-pinned genesis after total loss | Yes |
| F | Checkpoint storage/retention | Owner-held high-water checkpoint plus separately protected backup; fail closed; owner sets retention/freshness | Yes |
| G1 | Production implementation | Separate, bounded authorization after A–F choices | No, not requested by this package |
| G2 | Production activation | Separate later approval after implementation and operational verification | No, not requested by this package |

## Contradictions and missing evidence

| Document / passage | Earlier claim | Reconciliation |
|---|---|---|
| `REGISTRY_GOVERNANCE_SECURITY_REVIEW.md`: original Executive assessment findings 1–5 and sections 1–13, especially 1–4, 6–7 and 9–10 | Missing registry identity binding; unsigned SQLite revocation; no genesis or recovery contracts; older v1 signing format | The 2026-11-20 note labels these as the original pre-remediation review baseline. The remediation table and v2/checkpoint sections state current synthetic behavior. Original text is preserved as audit history. |
| `REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md`: original “Cryptographic profile” and signing-byte description | Approval v1 schema/domain and old compatibility-metadata representation described as current | The 2026-11-20 note marks that draft as historical and points to v2 identity/signing/record-digest contracts. The v1 text is retained, not used for new approvals. |
| `REGISTRY_APPROVAL_AND_TRUST_ANCHOR_DESIGN.md`: original rotation/revocation bullets | Rotation and recovery can read as executable behavior | The dated note and current implementation status clarify these are design proposals; synthetic revocation exists, but trust-manifest successor and normal rotation do not. |
| `REGISTRY_OWNERSHIP_AND_VERSIONING.md`: release-format-1 bullet and earlier generic bundle summary | Format 1 and the bundle summary could be mistaken for the current release contract | The dated security-remediation section clarifies v1 is historical-only and v2 binds registry identity for new releases/approvals. |
| `RELEASE_READINESS_ASSESSMENT.md` and `MASTER_PROJECT_TRACKER.md` | No conflicting current governance claim found | Both preserve BLOCKED / owner-decision-pending status; the tracker links this package and distinguishes later implementation and activation approvals. |
| This owner decision package, earlier contradictions item 1 | Asked for reconciliation before implementation | Superseded by the reconciliation notes now recorded in the three documents above; the history is retained. |

Remaining missing evidence: trust-manifest genesis and revocation records use synthetic HMAC callbacks, not Ed25519 tests; there is no registered successor trust-manifest transition for routine rotation. Official `cryptography` documentation does not establish Termux/Android support. The independently supplied checkpoint is a function argument, not persistent external storage. No real anti-rollback, backup, retention, physical custody, or recovery operation has been verified. No production key, trusted initial fingerprint, approved crypto dependency, registry release, migration or activation exists.

Until the Project Owner resolves the decisions above and separately authorizes implementation and activation, production trust-anchor approval remains **BLOCKED**. DEC-04 and H4-03 remain deferred.
