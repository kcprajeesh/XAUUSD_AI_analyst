export type HealthResponse = {
  status: 'ok';
  service: 'XAUUSD AI Analyst';
  timestamp: string;
};

export async function readHealth(signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<HealthResponse> {
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(10_000)]);
  const response = await fetcher('/api/health', { signal: requestSignal, credentials: 'omit', cache: 'no-store' });
  if (!response.ok || response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
    throw new Error('Backend health is unavailable');
  }
  const value: unknown = await response.json();
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Backend health response is invalid');
  }
  const health = value as Record<string, unknown>;
  if (Object.keys(health).length !== 3 || health.status !== 'ok' || health.service !== 'XAUUSD AI Analyst'
    || typeof health.timestamp !== 'string'
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(health.timestamp)
    || health.timestamp.startsWith('0000-')
    || !Number.isFinite(Date.parse(health.timestamp))) {
    throw new Error('Backend health response is invalid');
  }
  const milliseconds = health.timestamp.replace(/(?:\.(\d{1,6}))?Z$/, (_, fraction = '') => `.${fraction.padEnd(3, '0').slice(0, 3)}Z`);
  if (new Date(health.timestamp).toISOString() !== milliseconds) {
    throw new Error('Backend health response is invalid');
  }
  return health as HealthResponse;
}
