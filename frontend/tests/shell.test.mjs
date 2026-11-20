import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

test('React shell renders all sections, truthful unavailable states and accessible controls without browser globals', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { App } = await server.ssrLoadModule('/src/App.tsx');
    const html = renderToStaticMarkup(createElement(App));
    for (const id of ['overview', 'analysis', 'timeframe-analysis', 'macro', 'sentiment', 'calendar', 'evidence', 'settings']) {
      assert.ok(html.includes(`href="#${id}"`));
      assert.ok(html.includes(`id="${id}"`));
    }
    for (const title of ['Gold overview', 'Price context', 'Multi-timeframe analysis', 'Central AI Analyst', 'Macro intelligence', 'Sentiment &amp; news', 'Economic calendar', 'Evidence quality', 'Settings &amp; providers']) {
      assert.ok(html.includes(title), title);
    }
    assert.ok(html.includes('data-state="insufficient_evidence"'));
    assert.ok(html.includes('NO TRADE — DATA NOT VERIFIED'));
    assert.ok(html.includes('No eligible live market-data provider is configured.'));
    assert.ok(html.includes('H4-03 deferred; analysis disabled.'));
    assert.match(html, /<dt>Last price<\/dt><dd>Unavailable<\/dd>/);
    assert.match(html, /<dt>Market source<\/dt><dd>Not connected<\/dd>/);
    assert.ok(html.includes('No verified news is available.'));
    assert.ok(html.includes('No source timestamp'));
    assert.ok(html.includes('No verified price history loaded'));
    assert.ok(html.includes('Event data is unavailable.'));
    assert.ok(html.includes('Unavailable events do not imply a quiet calendar.'));
    assert.ok(html.includes('This workspace has no access to credentials.'));
    assert.ok(html.includes('Evidence required for research'));
    assert.match(html, /<button[^>]+disabled=""[^>]+aria-describedby="analysis-unavailable"[^>]*>Run analysis<\/button>/);
    assert.ok(html.includes('aria-hidden="true" inert=""'));
    assert.ok(html.includes('href="#main-content"'));
    assert.match(html, /<option value="Asia\/Qatar" selected="">Qatar<\/option>/);
    assert.match(html, /<option value="Asia\/Kolkata">India<\/option>/);
    assert.equal((html.match(/aria-pressed="/g) ?? []).length, 5);
    assert.match(html, /disabled="" aria-label="4H timeframe unavailable while H4-03 is deferred"/);
    assert.doesNotMatch(html, /\d+(?:\.\d+)?%|\$\d|Buy now|Sell now/i);
    assert.match(html, /<label for="analysis-id">Immutable analysis ID<\/label><input[^>]*id="analysis-id"/);
    assert.doesNotMatch(html, /type="password"|Save settings|Generate analysis/i);
  } finally {
    await server.close();
  }
});

test('timezone control sends validated IANA zones and renders the current selection', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { TimezoneControl } = await server.ssrLoadModule('/src/components/IntelligencePanels.tsx');
    const selected = [];
    const control = TimezoneControl({ id: 'test-timezone', timezone: 'Asia/Kolkata', onTimezoneChange: (value) => selected.push(value) });
    const select = control.props.children.find((child) => child?.type === 'select');
    select.props.onChange({ target: { value: 'Europe/London' } });
    assert.deepEqual(selected, ['Europe/London']);
    assert.throws(() => select.props.onChange({ target: { value: '+03:00' } }), /Unsupported display timezone/);
    assert.equal(selected.length, 1);
    const html = renderToStaticMarkup(control);
    assert.match(html, /<label[^>]+for="test-timezone"/);
    assert.match(html, /<option value="Asia\/Kolkata" selected="">India<\/option>/);
  } finally {
    await server.close();
  }
});

test('each selected chart timeframe stays visible in the multi-timeframe evidence table', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { MultiTimeframePanel } = await server.ssrLoadModule('/src/components/IntelligencePanels.tsx');
    for (const timeframe of ['Daily', '4H', '1H', '15M', '5M']) {
      const html = renderToStaticMarkup(createElement(MultiTimeframePanel, { timeframe }));
      assert.equal((html.match(/data-active="true"/g) ?? []).length, 1);
      assert.ok(html.includes(`<th scope="row">${timeframe}<span class="sr-only">, selected chart timeframe</span>`));
      assert.equal((html.match(/<td>unavailable<\/td>/g) ?? []).length, 4);
      assert.equal((html.match(/<td>unsupported<\/td>/g) ?? []).length, 1);
    }
  } finally {
    await server.close();
  }
});

test('synthetic analysis is opt-in, unmistakably labeled and never supplies a market price', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  try {
    const { App } = await server.ssrLoadModule('/src/App.tsx');
    const { syntheticAnalysis } = await server.ssrLoadModule('/src/syntheticAnalysis.ts');
    const unavailable = renderToStaticMarkup(createElement(App));
    assert.doesNotMatch(unavailable, /SYNTHETIC FIXTURE/);
    assert.equal(syntheticAnalysis.market.price, null);
    const preview = renderToStaticMarkup(createElement(App, { initialSyntheticView: true }));
    assert.match(preview, /SYNTHETIC FIXTURE · NOT LIVE MARKET DATA/);
    assert.match(preview, /INSUFFICIENT EVIDENCE · NO TRADE/);
    assert.match(preview, /H4-03 production policy is deferred/);
    assert.match(preview, /1M is unsupported by the current evidence packet contract/);
    assert.match(preview, /Calendar, macro, news and sentiment: unavailable/);
    assert.match(preview, /synthetic-input-fixture/);
    assert.doesNotMatch(preview, /Market price<\/dt><dd>\d/);
  } finally {
    await server.close();
  }
});
