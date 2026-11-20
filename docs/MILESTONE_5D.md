# Milestone 5D — Deterministic XAUUSD Technical Analysis Engine

**Status:** Offline deterministic calculations over validated Stage 5C evidence packets. No live provider, AI inference, market-data request, broker, execution, scheduler, or frontend integration was added. Stage 5B provider infrastructure and Stage 5C contracts remain unchanged.

## Architecture and evidence flow

`backend/app/analysis/engine.py` accepts an `EvidencePacket`, revalidates it through the existing Stage 5C Pydantic contract, calculates each available timeframe independently, and returns a new validated packet with appended `EvidenceRecord`s. It does not read SQLite, call providers, select credentials, aggregate candles, or mutate the input packet. The original source/feed/instrument and native/aggregated candle origin remain in the returned packet. Unavailable timeframes stay unavailable.

Each generated record includes the input source ID, timeframe, exact Decimal values (where numeric), candle IDs, calculation method, observation time, quality, and an ID derived deterministically from source, timeframe, method, references, label and value. Indicator points and generated records use the latest referenced closed-candle boundary as their deterministic calculation/observation time. This makes a revised value produce a different ID when its evidence changes. There is no cross-packet history store; Milestone 4 retains candle revisions separately.

Confirmed swing records reference the full left/pivot/right window. Their `observed_at` is the close of the final right-side confirmation candle, so a pivot is not represented as known before confirmation. BOS/CHoCH and sweep evidence includes the swing confirmation window plus the break/sweep candle. FVG/OB records include formation and observed mitigation/invalidation candle references. The output packet is validated again, including its evidence/timeframe references and Stage 5C aggregated-4H constraints.

## Indicators

All calculations use `Decimal` only, under a fixed 34-significant-digit decimal context. Values are not quantized to an assumed market tick size. The result represents a deterministic calculation from normalized source values; it does not claim more source precision than `SourceIdentity` reports.

- **EMA 20/50/200:** seed with the simple average of the first `n` closes; then `EMA = alpha × close + (1 − alpha) × previous EMA`, `alpha = 2/(n+1)`. No result before `n` closed candles. The engine emits the latest calculated value for each period and an EMA-ordering trend observation once all three exist.
- **RSI 14:** price changes are split into gains/losses. Initial average gain/loss is the mean of the first 14 changes; later averages use Wilder smoothing `(previous × 13 + current)/14`. First result requires 15 closes. Zero average loss returns 100; a fully flat series returns 50; zero gain with positive loss returns 0.
- **ATR 14:** true range is `high − low` for the first candle, then the maximum of `high − low`, `abs(high − previous close)`, and `abs(low − previous close)`. The first ATR is the mean of 14 true ranges; later values use Wilder smoothing. This incorporates price gaps across source candles. It does not fill missing time intervals. The engine only emits a current ATR evidence record; the internal per-candle ATR series is used for objective OB qualification.

If warm-up is incomplete, the engine emits `UNSUPPORTED` indicator evidence rather than zero or a fabricated value. If the input timeframe is flagged stale, invalid, incomplete, or partial, quality propagates to generated records. Any forming/unverified candle in a timeframe makes calculated evidence provisional; that candle is excluded from calculations and cannot confirm a swing, break, sweep, gap, or zone.

## Market structure and liquidity

- **Swings:** explicit left/right widths (defaults 2/2), strict unique high/low extreme across the complete window. A pivot is confirmed only after all right-side candles close. Tied extremes are not pivots under this rule. Defaults are a transparent convention, not a universally optimal setting.
- **BOS/CHoCH:** only a candle close crossing a previously confirmed swing level is recorded. A break is emitted on the crossing close, not on a wick or on every later close beyond the level. First directional break in the supplied sequence is labeled BOS; a later break against the last recorded direction is CHoCH. No provisional intrabar event is emitted.
- **Potential buy/sell-side liquidity:** confirmed swing highs/lows are references, not predictions. Equal highs/lows are pairs of confirmed like-side swings within a caller-configurable absolute Decimal tolerance (default 0.10 source price units); their recorded level is the pair mean.
- **Sweep:** confirmed swing level is wicked through and the same candle closes back on the original side. High sweep is described as a buy-side sweep with bearish rejection; low sweep as sell-side sweep with bullish rejection. No future liquidity-taking claim is made.

## Fair Value Gaps and order blocks

- **FVG:** three-candle non-overlap. Bullish when candle 1 high is below candle 3 low, bounded by those prices; bearish when candle 1 low is above candle 3 high. Each boundary is a separate evidence record because Stage 5C `EvidenceRecord` holds one numeric value. Later candle overlap marks partial mitigation; reaching/passing the far boundary marks full mitigation. References include formation and touch/fill candles. A detected zone is not described as tradable.
- **Order block:** an explicitly heuristic rule. For a close-based BOS/CHoCH, require the break candle's high-low range to be at least a configurable multiple of its Wilder ATR (default 1.5). Select the last opposing-color candle after the broken swing and before the break; use its full low/high as zone. The break confirms the zone. Later overlap marks mitigation; a later close beyond the zone's invalidating edge marks it invalidated. Both mitigation and invalidation references are retained. This is a mechanical candle rule only, not a claim about institutional activity or order flow.

## Premium and discount

The range is formed from the latest consecutive, opposite-type confirmed swing pair with different candle indexes. The range endpoints are the swing high and swing low; equilibrium is their arithmetic midpoint. The current latest closed close is described as premium, discount, or equilibrium relative to that midpoint. Range evidence cites both confirmation windows. When the selected swing pair changes, the evidence IDs change; prior packets are immutable and this module does not rewrite cross-packet history.

## Sessions and timezone handling

Timestamps remain aware UTC. Session classification converts each latest closed candle opening into IANA zones, then stores the corresponding `Asia/Qatar` local time in the session evidence description. Default configurable wall-clock windows are Asian 08:00–15:00 `Asia/Qatar`, London 08:00–17:00 `Europe/London`, and New York 08:00–17:00 `America/New_York`; overlap is the interval when both London and New York labels are active. Python `zoneinfo` applies London/New York DST; Qatar has no DST rule in the IANA database. Session labels are context only, based on the candle opening instant, and are not entry signals. These default hours are design assumptions and should be confirmed before product use.

## Volume and timeframe rules

Only the latest closed source volume observation per timeframe is copied with its existing `VolumeType`; tick count remains tick count, and this engine computes no volume spike or exchange-volume statistic. Missing volume remains absent. No volume semantics are merged across feeds.

`1D`, `4H`, `1H`, `15M`, and `5M` use the packet's separate timeframe records. This engine never resamples. Native 4H remains native; aggregated 4H remains aggregated. Stage 5C validates an aggregate as exactly four consecutive, UTC-aligned, closed, native 1H candles with matching OHLC and same-type volume where supplied. An unsupported or unavailable 4H timeframe remains so.

Missing-candle, duplicate, outlier, stale, invalid, conflicting-source, unsupported-derivation, and incomplete-context flags are not erased. Invalid OHLC cannot enter a packet because Stage 5C rejects it; `INVALID_CANDLES` quality reports cause generated records to be invalid. There is no universal freshness limit. The engine does not infer missing openings from cadence or exchange calendars; it propagates the input packet's explicit gap/quality reporting.

## Synthetic verification

`backend/tests/test_analysis_engine.py` has 22 offline tests covering known EMA values/warm-up; rising/falling/flat RSI; ATR warm-up and price-gap true range; swing confirmation and no forming-candle look-ahead; bullish BOS, bearish BOS and CHoCH; equal highs/lows and tolerance; confirmed wick rejection; bullish/bearish FVG, partial/full mitigation; OB displacement qualification and invalidation; premium/discount midpoint; Qatar/London/New York local time, standard-time/DST and overlap; native and aggregated 4H preservation; missing/stale quality; invalid OHLC/float rejection; tick-count semantics; evidence IDs/provenance, packet validation, repeatability, and unsupported indicator warm-up. All fixtures are explicitly synthetic, not market observations.

Verification:

- Focused engine tests: **22 passed**.
- Full backend suite: **149 passed**.
- Backend `.venv/bin/python -m pip check`: **No broken requirements found**.
- Frontend `npm run typecheck`: passed.
- Frontend `npm test`: **9 passed**.
- Frontend `npm run build`: passed.
- No dependency or lockfile changed. No live data or AI inference was used.

## Limitations and unresolved decisions

- Swing widths, equal-level tolerance, OB displacement multiple, and session hours are configurable defaults, not validated trading parameters.
- Structure classification is deterministic but heuristic; first break is BOS because no prior bias is inferred, and subsequent opposite break is CHoCH.
- OB logic cannot establish participation or institutional intent; the label is only the defined candle-zone heuristic.
- No independent market calendar exists, so session labels describe the candle opening only and gaps are not synthesized or calendar-verified.
- No kill-zone hours are configured or emitted because no approved kill-zone definition exists. No stop, target, trade setup, risk score, AI report, strategy, backtest, or recommendation is calculated.
- Long histories can create many FVG/liquidity records; production history-window and output-size policy remains unresolved.
- Decimal output precision is computational precision, not a guarantee about source tick precision.
- Evidence IDs are stable for equivalent inputs but this module does not persist revisions; cross-packet history remains a future integration concern.

## Files changed

- Added `backend/app/analysis/__init__.py`
- Added `backend/app/analysis/engine.py`
- Added `backend/app/analysis/indicators.py`
- Added `backend/app/analysis/market_structure.py`
- Added `backend/app/analysis/sessions.py`
- Added `backend/app/analysis/smc.py`
- Added `backend/tests/test_analysis_engine.py`
- Added this document
- Graphify-derived index/graph files are refreshed by the required local `graphify update .` command.

No Stage 5B/5C provider/evidence/response contract, Milestone 4 data adapter/storage/schema, API route, configuration, dependency manifest, frontend file, credential, or market-data fixture was modified.

## Rollback

Remove the new `backend/app/analysis/` package, `backend/tests/test_analysis_engine.py`, and this document. Refresh Graphify from the rolled-back source with `. .venv-graphify/bin/activate && graphify update .`. No database migration, provider setting, secret, network state, or existing source/schema rollback is needed. Then run the backend and frontend checks listed above.

## Stop boundary

No live market-data request, AI call, inference, credential read, account/billing change, scheduler, dashboard integration, broker connection, or order execution occurred. Stage 5E requires separate authorization.
