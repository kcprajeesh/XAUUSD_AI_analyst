# Synthetic analysis provenance contract

Status: implemented and verified for isolated synthetic fixtures only. The module is not imported by the running application and does not establish production defaults or provider eligibility.

## Immutable chain

The disposable archive persists a canonical `xau.input-manifest.v1` payload and framed digest when it snapshots one whole promoted retrieval per timeframe. Its ordered selections bind retrieval IDs, generation numbers, exact ranges and revision IDs. A derived run must match the selected timeframe window and every analyzed candle must carry retrieval and revision IDs included in that manifest. Invalidated input manifests are rejected for new runs.

The deterministic engine output is represented by `xau.analysis-output.v1`; its canonical payload contains the analysis output identity, input manifest identity and a stable JSON serialization of the complete result packet. The existing derived-manifest contract is extended as `xau.derived-manifest.v2`; it binds both manifest and output IDs/digests, selected retrieval and revision IDs, deterministic algorithm/version, full parameter context, policy ID, timeframe/window, creation time, schema IDs, canonicalization profile, framing version, and unavailable timeframe/input states. The v1 serializer remains available for historical verification. Digests are out-of-payload metadata; no object contains its own digest.

All three structured objects use the existing registered canonical JSON profile and digest framing. Caller-supplied limits are mandatory. Test limits are fixtures, not production limits. `persist_provenance` re-parses and re-hashes both payloads, verifies cross-object identity/digest bindings and inserts output plus derived manifest inside one `BEGIN IMMEDIATE` transaction. Identical pair replays are idempotent; reused identities with changed content fail. Immutable triggers prohibit updates/deletes. A trigger failure or process exit before commit leaves neither record. Later invalidation does not erase historical analysis; its revision IDs are returned as warnings.

Unavailable and unsupported timeframes are copied from the packet into provenance. This records absence; it does not make missing inputs eligible. The current synthetic archive still requires all five timeframe retrieval snapshots, so it is a verification harness and not the production input-selection policy. H4 production aggregation remains deferred under H4-03.

## Scope limits

- No provider, external AI, application service or production database is connected.
- This proves deterministic replay and SQLite transaction behavior only for synthetic fixtures.
- Provider-specific raw capture profiles, account permissions, production registry ownership, operating limits, freshness/lookback policy, backup/recovery targets and migration/cutover remain unresolved.
- DEC-04 and H4-03 remain deferred; no live provider or production activation is implied.
