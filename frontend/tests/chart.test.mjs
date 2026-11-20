import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
const { createEmptyChart } = await server.ssrLoadModule('/src/chart.ts');
await server.close();

test('empty chart resizes, preserves attribution and cannot display invented data', () => {
  const container = {};
  const calls = [];
  const chart = { addSeries: (...args) => calls.push(args), remove: () => calls.push('removed') };
  const library = {
    ColorType: { Solid: 'solid' }, CandlestickSeries: 'candlestick',
    createChart: (element, options) => {
      assert.equal(element, container);
      assert.equal(options.autoSize, true);
      assert.equal(options.layout.attributionLogo, true);
      assert.equal(options.rightPriceScale.visible, false);
      assert.equal(options.timeScale.visible, false);
      assert.equal(options.handleScroll, false);
      assert.equal(options.handleScale, false);
      return chart;
    },
  };
  const mounted = createEmptyChart(container, library);
  assert.equal(mounted, chart);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'candlestick');
  assert.equal(calls[0][1].priceLineVisible, false);
  assert.equal(calls[0][1].lastValueVisible, false);
  mounted.remove();
  assert.equal(calls.at(-1), 'removed');
});

test('chart is removed if series initialization fails', () => {
  const error = new Error('Series initialization failed');
  let removed = 0;
  const library = {
    ColorType: { Solid: 'solid' }, CandlestickSeries: 'candlestick',
    createChart: () => ({ addSeries: () => { throw error; }, remove: () => { removed += 1; } }),
  };
  assert.throws(() => createEmptyChart({}, library), (actual) => actual === error);
  assert.equal(removed, 1);
});

test('chart factory failure is propagated without creating a partial series', () => {
  const library = { ColorType: { Solid: 'solid' }, createChart: () => { throw new Error('Canvas unavailable'); } };
  assert.throws(() => createEmptyChart({}, library), /Canvas unavailable/);
});

test('synthetic candles reach the chart in UTC and labels use Asia/Qatar', () => {
  const data = [{ time: 1795132800, open: 2000, high: 2002, low: 1999, close: 2001 }];
  let supplied;
  let options;
  let fitted = false;
  const chart = { addSeries: () => ({ setData: (values) => { supplied = values; } }),
    timeScale: () => ({ fitContent: () => { fitted = true; } }), remove() {} };
  const library = { ColorType: { Solid: 'solid' }, CandlestickSeries: 'candlestick',
    createChart: (_container, value) => { options = value; return chart; } };
  assert.equal(createEmptyChart({}, library, data), chart);
  assert.equal(supplied, data);
  assert.equal(fitted, true);
  assert.equal(options.timeScale.visible, true);
  assert.match(options.localization.timeFormatter(data[0].time), /03:00:00/);
});

test('failure to load synthetic series removes the partial chart', () => {
  let removed = false;
  const library = { ColorType: { Solid: 'solid' }, CandlestickSeries: 'candlestick', createChart: () => ({
    addSeries: () => ({ setData: () => { throw new Error('invalid series'); } }), remove: () => { removed = true; },
  }) };
  assert.throws(() => createEmptyChart({}, library, [{ time: 1, open: 1, high: 1, low: 1, close: 1 }]), /invalid series/);
  assert.equal(removed, true);
});
