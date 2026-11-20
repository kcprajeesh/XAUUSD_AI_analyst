import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const projection = {
  schema_version: 'xau.dashboard-analysis.v1', environment: 'synthetic_archive', analysis_id: 'persisted-output-17', status: 'historical_invalidated',
  analysis_timestamp: '2026-01-02T00:00:00Z', market_data_status: 'incomplete',
  market_data_timestamp: '2026-01-02T00:00:00Z', freshness_status: 'unassessed', source_eligibility_status: 'unverified',
  source_attribution: ['synthetic-provider'], retrieval_completeness: { 'retrieval-1h': 'verified' },
  timeframe_availability: { '1D': 'unavailable', '4H': 'unsupported', '1M': 'unsupported' },
  analyst_outcome: 'unavailable', analyst_unavailable_reason: 'no_persisted_analyst_report', evidence_quality: 'incomplete',
  unavailable_inputs: ['macro:no_persisted_context', 'news:no_persisted_context'],
  invalidation_warnings: ['invalidated_revision:revision-17'], input_manifest_id: 'input-17', input_manifest_digest: 'a'.repeat(64),
  derived_manifest_id: 'derived-17', derived_manifest_digest: 'b'.repeat(64), analysis_output_digest: 'c'.repeat(64),
  algorithm_id: 'xau.deterministic.research', algorithm_version: '1',
  analysis_output: { analysis_id: 'packet-17', analysis_at: '2026-01-02T00:00:00Z', retrieved_at: '2026-01-02T00:00:00Z',
    requested_timeframes: ['1D', '4H'], timeframes: [{ timeframe: '4H', state: 'unsupported' }],
    evidence: [{ evidence_id: 'evidence-17', evidence_type: 'swing_high', description: 'Persisted swing high', value: '2010.25', units: 'USD_per_troy_ounce', timeframe: '1H', quality: 'verified' }] },
};

test('analysis API validates responses and reports unavailable/error states', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const originalFetch = globalThis.fetch;
  try {
    const { validatePersistedAnalysis, fetchPersistedAnalysis } = await server.ssrLoadModule('/src/analysisApi.ts');
    assert.equal(validatePersistedAnalysis(projection).analysis_id, 'persisted-output-17');
    assert.throws(() => validatePersistedAnalysis({ ...projection, analysis_id: '' }), /malformed/);
    assert.throws(() => validatePersistedAnalysis({ ...projection, ai_report: { status: 'complete' } }), /AI report is malformed/);
    globalThis.fetch = async () => new Response(JSON.stringify(projection), { status: 200 });
    assert.equal((await fetchPersistedAnalysis('persisted-output-17')).analysis_output.evidence[0].value, '2010.25');
    globalThis.fetch = async () => new Response('', { status: 404 });
    await assert.rejects(fetchPersistedAnalysis('missing'), /analysis_not_found/);
    globalThis.fetch = async () => new Response('', { status: 503 });
    await assert.rejects(fetchPersistedAnalysis('offline'), /analysis_projection_unavailable/);
    globalThis.fetch = async () => new Response('not json', { status: 200 });
    await assert.rejects(fetchPersistedAnalysis('malformed'));
  } finally {
    globalThis.fetch = originalFetch;
    await server.close();
  }
});

test('dashboard renders the persisted AI report identity, synthetic status and NO TRADE evidence', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { PersistedAnalysisPanel } = await server.ssrLoadModule('/src/components/PersistedAnalysisPanel.tsx');
    const report = { status: 'insufficient_evidence', report_id: 'report-17', report_digest: 'd'.repeat(64),
      request_id: 'request-17', request_digest: 'e'.repeat(64), response_id: 'response-17', response_digest: 'f'.repeat(64),
      provider_id: 'synthetic-fixture', model_id: 'no-call', prompt_version: 'prompt-v1',
      report: { status: 'insufficient_evidence', analysis: { bias: 'NEUTRAL', trade_stance: 'NO TRADE',
        rationale: [{ text: 'Required evidence gates did not pass.' }], confidence_explanation: [], invalidating_conditions: [] },
        report: null, unavailable_inputs: ['4h:unsupported'] } };
    const html = renderToStaticMarkup(createElement(PersistedAnalysisPanel, {
      result: { ...projection, analyst_outcome: 'insufficient_evidence', analyst_unavailable_reason: 'insufficient_evidence', ai_report: report },
    }));
    assert.ok(html.includes('report-17'));
    assert.ok(html.includes('synthetic-fixture / no-call'));
    assert.ok(html.includes('NO TRADE'));
    assert.ok(html.includes('not a live recommendation'));
  } finally {
    await server.close();
  }
});

test('dashboard renders the exact requested persisted identity and historical provenance warnings', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { PersistedAnalysisPanel } = await server.ssrLoadModule('/src/components/PersistedAnalysisPanel.tsx');
    const html = renderToStaticMarkup(createElement(PersistedAnalysisPanel, { result: projection }));
    assert.ok(html.includes('Persisted analysis persisted-output-17'));
    assert.ok(html.includes('SYNTHETIC ARCHIVE · READ ONLY · NOT LIVE MARKET DATA'));
    assert.ok(html.includes('persisted-output-17 · ' + 'c'.repeat(64)));
    assert.ok(html.includes('input-17 · ' + 'a'.repeat(64)));
    assert.ok(html.includes('invalidated_revision:revision-17'));
    assert.ok(html.includes('4H: unsupported'));
    assert.ok(html.includes('1M: unsupported'));
    assert.ok(html.includes('(Asia/Qatar)'));
    assert.ok(html.includes('Freshness</dt><dd>unassessed · live freshness not established'));
    assert.ok(html.includes('Persisted swing high'));
    assert.ok(html.includes('No market price or AI bias is inferred'));
    assert.doesNotMatch(html, /BUY SETUP|SELL SETUP/);
  } finally {
    await server.close();
  }
});

test('multi-timeframe dashboard renders exact stored evidence and keeps H4 unavailable', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { MultiTimeframePanel } = await server.ssrLoadModule('/src/components/IntelligencePanels.tsx');
    const analysis = { ...projection,
      timeframe_availability: { '1D': 'available', '1H': 'available', '15M': 'available', '4H': 'unsupported' },
      analysis_output: { ...projection.analysis_output, evidence: [
        { evidence_id: 'd1-trend', evidence_type: 'trend', description: 'Daily EMA alignment bullish', value: 'bullish', units: null, timeframe: '1D', quality: 'verified' },
        { evidence_id: 'h1-atr', evidence_type: 'atr', description: 'H1 ATR 14', value: '12.5', units: 'USD_per_troy_ounce', timeframe: '1H', quality: 'verified' },
        { evidence_id: 'm15-resistance', evidence_type: 'resistance', description: '15M resistance', value: '2020', units: 'USD_per_troy_ounce', timeframe: '15M', quality: 'verified' },
      ] },
    };
    const html = renderToStaticMarkup(createElement(MultiTimeframePanel, { timeframe: 'Daily', analysis }));
    assert.ok(html.includes('Persisted synthetic output · persisted-output-17'));
    assert.ok(html.includes('Daily EMA alignment bullish'));
    assert.ok(html.includes('H1 ATR 14'));
    assert.ok(html.includes('15M resistance'));
    assert.ok(html.includes('H4-03 deferred; analysis disabled.'));
    assert.ok(html.includes('not live market data'));
  } finally {
    await server.close();
  }
});

test('dashboard presents complete persisted scenarios and model provenance without deriving a recommendation', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { PersistedAnalysisPanel } = await server.ssrLoadModule('/src/components/PersistedAnalysisPanel.tsx');
    const aiReport = { status: 'complete', report_id: 'report-complete', report_digest: 'd'.repeat(64),
      request_id: 'request-complete', request_digest: 'e'.repeat(64), response_id: 'response-complete', response_digest: 'f'.repeat(64),
      provider_id: 'synthetic-fixture', model_id: 'fixture-model', prompt_version: 'prompt-v2',
      report: { status: 'complete', provenance: { input_manifest_id: 'input-17', derived_manifest_id: 'derived-17' },
        analysis: { bias: 'BEARISH', trade_stance: 'WAIT', rationale: [{ text: 'Persisted deterministic context is mixed.', evidence_ids: ['evidence-17'] }],
          confidence_explanation: [{ text: 'Evidence is limited.', evidence_ids: ['evidence-17'] }],
          timeframes: [{ timeframe: '1H', direction: 'BEARISH', structure: [{ text: 'Structure is weak.' }] }],
          invalidating_conditions: [{ text: 'Reassessment is needed if structure changes.' }] },
        report: { bullish_scenario: { text: 'A recovery requires confirmation.' }, bearish_scenario: { text: 'Weak structure may persist.' },
          neutral_conditions: { text: 'Wait while evidence conflicts.' }, context_interpretations: [] }, unavailable_inputs: ['macro:unavailable'] } };
    const html = renderToStaticMarkup(createElement(PersistedAnalysisPanel, {
      result: { ...projection, analyst_outcome: 'complete', analyst_unavailable_reason: 'complete', ai_report: aiReport },
    }));
    assert.ok(html.includes('report-complete'));
    assert.ok(html.includes('BEARISH · WAIT'));
    assert.ok(html.includes('A recovery requires confirmation.'));
    assert.ok(html.includes('Weak structure may persist.'));
    assert.ok(html.includes('Wait while evidence conflicts.'));
    assert.ok(html.includes('fixture-model'));
    assert.ok(html.includes('evidence-17'));
    assert.ok(html.includes('not a live recommendation'));
  } finally {
    await server.close();
  }
});

function freshProjection() {
  const base = Math.floor(Date.now() / 86400000) * 86400000;
  const candles = [['1D', 86400000, 200], ['1H', 3600000, 300], ['15M', 900000, 300]].flatMap(([timeframe, width, count]) =>
    Array.from({ length: count }, (_, index) => ({ timeframe,
      opened_at: new Date(base - width * (count - index)).toISOString(),
      closed_at: new Date(base - width * (count - index - 1)).toISOString(),
      open: '2000', high: '2002', low: '1999', close: '2001' })));
  return { ...projection, status: 'available', market_data_status: 'available', analyst_outcome: 'complete',
    freshness_status: 'fresh', valid_until: new Date(Date.now() + 3600000).toISOString(), candles };
}

test('fresh synthetic projection rejects stale, forming, gapped and malformed chart inputs', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { validatePersistedAnalysis } = await server.ssrLoadModule('/src/analysisApi.ts');
    const fresh = freshProjection();
    assert.equal(validatePersistedAnalysis(fresh).candles.length, 800);
    assert.throws(() => validatePersistedAnalysis({ ...fresh, valid_until: '2020-01-01T00:00:00Z' }), /stale/);
    assert.throws(() => validatePersistedAnalysis({ ...fresh, candles: fresh.candles.toSpliced(20, 1) }), /Gapped|Insufficient/);
    assert.throws(() => validatePersistedAnalysis({ ...fresh, candles: fresh.candles.map((c, i) => i ? c : { ...c, high: 'NaN' }) }), /Invalid/);
    assert.throws(() => validatePersistedAnalysis({ ...fresh, candles: fresh.candles.map((c, i) => i ? c : { ...c, closed_at: '2099-01-01T00:00:00Z' }) }), /invalid/);
  } finally { await server.close(); }
});

test('market-data endpoint validates availability, expiry and unavailable states', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const original = globalThis.fetch;
  try {
    const { validateMarketDataStatus, fetchMarketDataStatus, fetchPersistedAnalysis } = await server.ssrLoadModule('/src/analysisApi.ts');
    const fresh = freshProjection();
    const status = { environment: 'synthetic_archive', source_label: 'SYNTHETIC FIXTURE', analysis_available: true,
      analysis_id: fresh.analysis_id, freshness_status: 'fresh', valid_until: fresh.valid_until,
      updated_at: fresh.market_data_timestamp, error_category: null };
    globalThis.fetch = async (url) => {
      assert.equal(url, '/api/v1/market-data/status');
      return new Response(JSON.stringify(status), { status: 200 });
    };
    assert.equal((await fetchMarketDataStatus()).analysis_available, true);
    assert.throws(() => validateMarketDataStatus({ ...status, valid_until: '2020-01-01T00:00:00Z' }), /stale/);
    assert.throws(() => validateMarketDataStatus({ ...status, analysis_available: false }), /claims analysis/);
    assert.equal(validateMarketDataStatus({ provider: 'siftingio', source_label: 'unavailable', analysis_available: false, timeframes: [] }).analysis_available, false);
    globalThis.fetch = async () => new Response(JSON.stringify(fresh), { status: 200 });
    await assert.rejects(fetchPersistedAnalysis('different-id'), /identity_mismatch/);
  } finally { globalThis.fetch = original; await server.close(); }
});

test('chart and report visibly label fetched synthetic data and show Qatar timestamps', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { MarketChart } = await server.ssrLoadModule('/src/components/MarketChart.tsx');
    const { PersistedAnalysisPanel } = await server.ssrLoadModule('/src/components/PersistedAnalysisPanel.tsx');
    const fresh = freshProjection();
    const html = renderToStaticMarkup(createElement(MarketChart, { timeframe: '1H', analysis: fresh }));
    assert.match(html, /SYNTHETIC FIXTURE/);
    assert.match(html, /300 closed candles/);
    assert.match(html, /Asia\/Qatar/);
    assert.match(html, /03:00:00/);
    assert.match(html, /Open 2000/);
    const report = renderToStaticMarkup(createElement(PersistedAnalysisPanel, { result: fresh }));
    assert.match(report, /fresh · synthetic policy only/);
    assert.match(report, /NOT LIVE MARKET DATA/);
  } finally { await server.close(); }
});
