import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

test('Vite rejects invalid display settings and unsupported public variables', () => {
  const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('VITE_')));
  for (const variables of [
    { VITE_DISPLAY_TIMEZONE: 'Asia/Invalid' },
    { VITE_UNSUPPORTED: 'placeholder' },
  ]) {
    const result = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js'], {
      env: { ...cleanEnv, ...variables }, encoding: 'utf8', timeout: 10000,
    });
    assert.ifError(result.error);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Unsupported (display timezone|public environment variable)/);
  }
});
