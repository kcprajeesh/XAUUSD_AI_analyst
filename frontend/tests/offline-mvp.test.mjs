import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const backend = fileURLToPath(new URL('../../backend/', import.meta.url));

test('offline end-to-end: real synthetic pipeline, mock Analyst, archive, API, frontend and chart projection', async () => {
  const output = execFileSync(`${backend}.venv/bin/python`, ['-c', `
import json, sys, tempfile, socket
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
sys.path.insert(0,'tests')
from test_offline_mvp import seed_analysis, api_get, create_app, NOW, fixture_page, stage_synthetic_pages, CandleStore

def forbidden(*args, **kwargs):
    raise AssertionError('External network is forbidden')
with patch.object(socket.socket,'connect',forbidden), patch.object(socket.socket,'connect_ex',forbidden):
    with tempfile.TemporaryDirectory() as directory:
        path, identity = seed_analysis(Path(directory))
        app = create_app(path,clock=lambda:NOW+timedelta(seconds=2))
        status, view = api_get(app,'/api/v1/analysis/'+identity)
        assert status == 200
        market = api_get(app,'/api/v1/market-data/status')[1]
        stale = create_app(path,clock=lambda:NOW+timedelta(hours=2))
        rejected = api_get(stale,'/api/v1/analysis/'+identity)
        missing = api_get(app,'/api/v1/analysis/missing')
        from app.data import refresh
        with patch.object(refresh,'_unresolved',[(None,None)]):
            cleanup = api_get(app,'/api/v1/analysis/'+identity)
        with CandleStore(Path(directory)/'api-candles.synthetic.sqlite3') as store:
            spec,page = fixture_page('1h',300)
            try:
                stage_synthetic_pages(store,spec,[page.model_dump(mode='json')|{'next_cursor':'bad'+chr(10)+'cursor'}],now=NOW)
            except Exception as error:
                assert str(error) == 'invalid_cursor'
        cursor = api_get(app,'/api/v1/analysis/'+identity)
        assert cursor[0] == 409
        print(json.dumps(dict(view=view,market=market,stale=rejected,missing=missing,cleanup=cleanup,cursor=cursor)))
`], { cwd: backend, encoding: 'utf8', maxBuffer: 8_000_000 });
  const payload = JSON.parse(output);
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const originalFetch = globalThis.fetch;
  const originalNow = Date.now;
  try {
    Date.now = () => Date.parse('2026-11-20T00:00:02Z');
    const { fetchPersistedAnalysis, fetchMarketDataStatus } = await server.ssrLoadModule('/src/analysisApi.ts');
    const { MarketChart } = await server.ssrLoadModule('/src/components/MarketChart.tsx');
    const { PersistedAnalysisPanel } = await server.ssrLoadModule('/src/components/PersistedAnalysisPanel.tsx');
    const { createEmptyChart } = await server.ssrLoadModule('/src/chart.ts');
    globalThis.fetch = async (url) => new Response(JSON.stringify(url === '/api/v1/market-data/status'
      ? payload.market : payload.view), { status: 200 });
    const [view, market] = await Promise.all([fetchPersistedAnalysis(payload.view.analysis_id), fetchMarketDataStatus()]);
    assert.equal(market.analysis_available, true);
    assert.equal(view.ai_report.provider_id, 'offline-mock');
    assert.equal(view.candles.length, 800);
    assert.deepEqual(view.analysis_output.requested_timeframes, ['1D', '1H', '15M']);
    assert.equal(view.timeframe_availability['4H'], 'unsupported');
    const chart = renderToStaticMarkup(createElement(MarketChart, { timeframe: '1H', analysis: view }));
    const report = renderToStaticMarkup(createElement(PersistedAnalysisPanel, { result: view }));
    assert.match(chart, /SYNTHETIC FIXTURE/);
    assert.match(chart, /03:00:00/);
    assert.match(report, /offline-mock/);
    assert.match(report, /synthetic policy only/);
    assert.match(report, /NOT LIVE MARKET DATA/);
    let projected;
    createEmptyChart({}, { ColorType: { Solid: 'solid' }, CandlestickSeries: 'candles', createChart: () => ({
      addSeries: () => ({ setData: (values) => { projected = values; } }), timeScale: () => ({ fitContent() {} }), remove() {},
    }) }, view.candles.filter((c) => c.timeframe === '1H').map((c) => ({ time: Date.parse(c.opened_at)/1000,
      open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close) })));
    assert.equal(projected.length, 300);
    for (const failure of [payload.stale, payload.missing, payload.cleanup, payload.cursor]) {
      globalThis.fetch = async () => new Response(JSON.stringify(failure[1]), { status: failure[0] });
      await assert.rejects(fetchPersistedAnalysis(payload.view.analysis_id));
    }
  } finally {
    Date.now = originalNow;
    globalThis.fetch = originalFetch;
    await server.close();
  }
});
