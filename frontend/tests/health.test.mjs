import assert from 'node:assert/strict';
import test from 'node:test';
import { readHealth } from '../src/health.ts';

const valid = { status: 'ok', service: 'XAUUSD AI Analyst', timestamp: '2026-11-18T12:00:00.123456Z' };
const signal = new AbortController().signal;

test('health uses the local API proxy without credentials and validates the public contract', async () => {
  const result = await readHealth(signal, async (url, options) => {
    assert.equal(url, '/api/health');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal instanceof AbortSignal);
    assert.equal(options.signal.aborted, false);
    return Response.json(valid);
  });
  assert.deepEqual(result, valid);
});

test('HTTP failures, non-JSON, invalid contracts and network failures keep health unavailable', async () => {
  for (const response of [
    new Response('unavailable', { status: 503 }),
    new Response('<html></html>'),
    new Response(JSON.stringify(valid), { headers: { 'content-type': 'application/json-invalid' } }),
    Response.json(null),
    Response.json({ ...valid, status: 'ready' }),
    Response.json({ ...valid, service: 'Other service' }),
    Response.json({ ...valid, timestamp: '2026-11-18T12:00:00+03:00' }),
    Response.json({ ...valid, timestamp: 'invalid' }),
    Response.json({ ...valid, timestamp: '2026-02-30T12:00:00Z' }),
    Response.json({ ...valid, timestamp: '2026-11-18T24:00:00Z' }),
    Response.json({ ...valid, timestamp: '0000-01-01T00:00:00Z' }),
    Response.json({ ...valid, market_ready: true }),
  ]) {
    await assert.rejects(readHealth(signal, async () => response), /Backend health/);
  }
  await assert.rejects(readHealth(signal, async () => { throw new Error('Network unavailable'); }));
});

test('stalled health requests expire so the workspace can offer retry', async (context) => {
  const controller = new AbortController();
  context.mock.method(AbortSignal, 'timeout', (milliseconds) => {
    assert.equal(milliseconds, 10_000);
    return controller.signal;
  });
  const pending = readHealth(signal, async (_, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
  }));
  controller.abort(new DOMException('Health deadline expired', 'TimeoutError'));
  await assert.rejects(pending, { name: 'TimeoutError' });
});

test('health cancellation reaches the transport', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(readHealth(controller.signal, async (_, options) => {
    options.signal.throwIfAborted();
  }), { name: 'AbortError' });
});
