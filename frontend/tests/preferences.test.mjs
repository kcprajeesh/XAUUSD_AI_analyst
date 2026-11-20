import assert from 'node:assert/strict';
import test from 'node:test';
import { formatTimestamp, TIMEFRAMES, TIMEZONES, validateDisplayTimezone } from '../src/preferences.ts';

test('approved timeframes and named display zones are available', () => {
  assert.deepEqual(TIMEFRAMES, ['Daily', '4H', '1H', '15M', '5M']);
  for (const zone of TIMEZONES) assert.equal(validateDisplayTimezone(zone.value), zone.value);
  assert.throws(() => validateDisplayTimezone('Asia/Invalid'));
  assert.throws(() => validateDisplayTimezone(''));
});

test('UTC instants display correctly in Qatar and India', () => {
  const instant = '2026-01-15T12:00:00Z';
  assert.match(formatTimestamp(instant, 'Asia/Qatar'), /15:00:00/);
  assert.match(formatTimestamp(instant, 'Asia/Kolkata'), /17:30:00/);
  assert.match(formatTimestamp(instant, 'UTC'), /12:00:00/);
});

test('London and New York follow winter, summer and DST transitions', () => {
  assert.match(formatTimestamp('2026-01-15T12:00:00Z', 'Europe/London'), /12:00:00/);
  assert.match(formatTimestamp('2026-07-15T12:00:00Z', 'Europe/London'), /13:00:00/);
  assert.match(formatTimestamp('2026-01-15T12:00:00Z', 'America/New_York'), /07:00:00/);
  assert.match(formatTimestamp('2026-07-15T12:00:00Z', 'America/New_York'), /08:00:00/);
  assert.match(formatTimestamp('2026-03-08T06:59:00Z', 'America/New_York'), /01:59:00/);
  assert.match(formatTimestamp('2026-03-08T07:00:00Z', 'America/New_York'), /03:00:00/);
  assert.match(formatTimestamp('2026-11-01T05:59:00Z', 'America/New_York'), /01:59:00/);
  assert.match(formatTimestamp('2026-11-01T06:00:00Z', 'America/New_York'), /01:00:00/);
});

test('invalid or timezone-naive timestamps cannot be displayed', () => {
  for (const instant of ['badZ', '2026-01-15T12:00:00', '2026-01-15T12:00:00+03:00']) {
    assert.throws(() => formatTimestamp(instant, 'Asia/Qatar'));
  }
});
