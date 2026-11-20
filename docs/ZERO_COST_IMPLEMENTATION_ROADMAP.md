# Zero-Cost Implementation Roadmap

This roadmap describes possible future work under [ZERO_COST_POLICY.md](ZERO_COST_POLICY.md). **Listing a stage does not authorize it.** Each stage requires explicit approval before implementation begins. Approval of one stage does not approve later stages. Every stage must preserve a $0/month operating target and stop if permissions, cost, provider behavior, or evidence requirements cannot be met safely.

The existing Milestone 1, Milestone 2, and Milestone 4 records remain historical records of completed work. This roadmap does not alter those milestones or authorize Milestone 5/live integration.

## Stage 1: Repository audit — completed

**Scope:** Read-only inspection of the frontend/backend architecture, dependencies, contracts, SQLite, configuration, tests, and documented provider claims.

**Acceptance criteria:** The audit identified the current offline-only data foundation, lack of AI or provider transport, dependency/service cost exposure, free-provider limitations, and licensing/behavior questions. No files were changed, no credentials were accessed, and no provider requests were made.

**Risks and dependencies:** Public provider plan pages may change; some quota/plan claims conflict across vendor pages. The audit is a dated snapshot, not a guarantee of entitlement or future availability.

**Stop condition:** Stop at the report. This stage is complete and grants no implementation authority.

## Stage 2: Zero-Cost Policy — this task

**Scope:** Establish financial, architecture, provider, data-integrity, quota, AI privacy, and failure-state rules in `docs/ZERO_COST_POLICY.md` and record this roadmap.

**Acceptance criteria:** Both documents exist; the policy reflects the audit without claiming unverified capabilities; the roadmap has approval gates and stop conditions; no application behavior, dependencies, or prior milestone records are changed.

**Risks and dependencies:** The policy documents boundaries but does not establish provider permissions, API access, data quality, or implementation readiness.

**Stop condition:** Stop after document review and report. Later work requires separate explicit approval.

## Stage 3: Provider permissions and historical API verification

**Scope:** Resolve provider terms and, only if separately approved, perform minimal authorized verification of the candidate historical API and the specific XAUUSD intervals needed. This stage may include contacting a provider only if that action is explicitly authorized.

**Acceptance criteria:** Written answers or authoritative terms resolve SiftingIO local retention and private AI-use questions; actual authorized access and response contract are verified without a purchase; intervals, timestamp meaning, volume meaning, pagination, forming-bar behavior, corrections, limits, and quota-stop responses are recorded. Any unverified item remains unsupported.

**Risks and dependencies:** Provider access may be unavailable or changed; asking for or receiving permissions may require user involvement; some behaviors may remain undocumented. No paid tier may be used to fill a gap.

**Stop condition:** Stop if permission is unclear, free entitlement is absent, verification would cost money, or behavior cannot be validated safely. Do not implement an adapter in this stage.

## Stage 4: Provider-neutral data contract design

**Scope:** Design, without live transport, the provider-neutral identities and contracts needed to represent verified providers separately while retaining the current data foundation's validation and provenance goals.

**Acceptance criteria:** Reviewable contract and migration proposal covers instrument types, native symbols/intervals, UTC timestamps, source precision, volume semantics, provenance, provider errors, quota states, stale states, unsupported timeframes, corrections, and compatibility with existing SQLite observations. A migration plan preserves existing Milestone 4 data and tests.

**Risks and dependencies:** Depends on Stage 3's verified provider facts. Premature abstractions or a schema migration could damage stored local research data or misrepresent sources.

**Stop condition:** Stop before code or schema changes unless a separate approval explicitly authorizes implementation and migration.

## Stage 5: SiftingIO integration — explicit authorization required

**Scope:** Implement only the verified and permission-approved SiftingIO free-tier path, with backend-only credentials if required, provider-specific series, quota enforcement, bounded requests, and local storage only as permitted.

**Acceptance criteria:** Synthetic tests cover documented payloads, errors, pagination, precision limits, source identity, volume labels, forming/stale behavior where verified, and exhausted quotas. Authorized verification confirms the contract. Calls stop at quota; there is no paid fallback, upgrade, or overage path; no unapproved 4H synthesis is present.

**Risks and dependencies:** Depends on Stages 3 and 4. Data rights, source availability, free-plan changes, and undocumented forming/correction semantics can block the work. Existing SQLite schema/version and Milestone 4 tests must remain compatible or be deliberately migrated with separate approval.

**Stop condition:** Stop on permission ambiguity, missing entitlement, cost, schema/data-loss risk, invalid responses, or any pressure to fabricate or silently substitute data. Do not continue to analysis/UI work automatically.

## Stage 6: Deterministic technical analysis

**Scope:** Add only specifically approved deterministic calculations using validated, provider-identified local candles. This stage does not add an AI API or trading behavior.

**Acceptance criteria:** Each calculation has defined inputs, interval/source constraints, reproducible output, and tests for missing, stale, invalid, and corrected data. Outputs cite their source series and timestamps. Tick counts are never presented as traded volume.

**Risks and dependencies:** Depends on valid data from approved source(s), permission to store/process that data, and explicit definitions for calculations. Incomplete data may make outputs unusable.

**Stop condition:** Stop when required inputs or methodology are unsupported; return insufficient evidence instead of estimates. No signals may be framed as trading instructions.

## Stage 7: Evidence and market-bias engine

**Scope:** Define and implement the evidence sufficiency rules and a single central market-bias assessment using approved deterministic evidence. Internal observations do not create competing analyst agents.

**Acceptance criteria:** Conclusions are traceable to source observations, calculations, timestamps, and limitations; missing, stale, conflicting, or inadequate inputs produce `insufficient_evidence`; no invented confidence percentages or price targets appear; analysis remains read-only.

**Risks and dependencies:** Depends on Stage 6 and verified freshness/calendar rules. A provider outage or correction can invalidate a previously sufficient assessment.

**Stop condition:** Stop if evidence cannot be audited or the requested conclusion exceeds what the evidence supports. No trading, broker, or execution features are permitted.

## Stage 8: Frontend market-data integration

**Scope:** Connect the local React shell to approved local backend read endpoints and present source-specific market data and explicit states.

**Acceptance criteria:** The UI shows provider/source identity, instrument type, source timestamp, stale/unavailable/quota/invalid/unsupported states, and insufficient evidence. Qatar display time remains the default; stored timestamps remain UTC. Provider series stay separate; unsupported 4H is visibly unavailable. No browser credentials or direct secret-bearing provider calls exist.

**Risks and dependencies:** Depends on Stages 5–7 and documented backend contracts. Browser display can make stale or mixed data look current if source identity and timestamps are omitted.

**Stop condition:** Stop if the backend cannot distinguish provider series or the UI would need to conceal missing, stale, or unsupported evidence.

## Stage 9: Manual AI analysis workflow and final verification

**Scope:** Document an optional manual ChatGPT workflow and verify the approved local application end to end. No AI API integration is included.

**Acceptance criteria:** The application remains useful when ChatGPT is not used. The workflow explains what evidence may be shared, requires provider terms to permit third-party AI use, preserves source/timestamp limitations, and treats AI output as interpretation rather than verified data. Final checks confirm no paid dependency, API, hosting, auto-upgrade, overage, credential leak, provider mixing, fabricated candle, or trade execution path was added.

**Risks and dependencies:** Depends on resolved provider terms and completed approved implementation stages. Manual ChatGPT access may have changing free-tier availability; sending data to a third party creates privacy and licensing exposure.

**Stop condition:** Do not send provider data to ChatGPT unless the relevant provider terms permit it. Stop final verification if any cost or data-integrity requirement fails. A completed roadmap does not authorize deployment, paid services, or trading capabilities.

## Open issues carried between stages

The following issues remain unresolved until authoritative verification is documented:

- SiftingIO local SQLite retention permission.
- SiftingIO private third-party AI inference permission.
- SiftingIO forming-candle behavior.
- Historical correction behavior.
- Free native XAUUSD 4H source.
- Long-term availability of free provider plans.

Until resolved, dependent functions remain disabled or explicitly unavailable. No stage automatically resolves an issue by choosing another provider, paying for access, or synthesizing data.
