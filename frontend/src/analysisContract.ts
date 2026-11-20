export type FeedState = 'available' | 'unavailable' | 'unverified' | 'incomplete' | 'stale' | 'conflicting';
export type TimeframeView = {
  timeframe: '1D' | '4H' | '1H' | '15M' | '5M';
  state: 'available' | 'unavailable' | 'unsupported';
  summary: string;
};

export type DashboardAnalysis = {
  schema_version: '1.0';
  environment: 'synthetic_fixture';
  created_at: string;
  input_manifest_id: string;
  derived_manifest_id: string;
  market: { symbol: 'XAUUSD'; status: FeedState; price: null; source: string; retrieved_at: string | null };
  timeframes: TimeframeView[];
  analyst: {
    status: 'complete' | 'insufficient_evidence' | 'unavailable' | 'invalid_response';
    bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'INSUFFICIENT EVIDENCE';
    stance: 'BUY SETUP' | 'SELL SETUP' | 'WAIT' | 'NO TRADE';
    summary: string;
    bullish_scenario: string;
    bearish_scenario: string;
    invalidation: string;
    risk_reward: string;
    evidence_quality: string;
  };
  context: { calendar: FeedState; macro: FeedState; news: FeedState; sentiment: FeedState; unavailable_reasons: string[] };
  warnings: string[];
};

export function validateDashboardAnalysis(value: unknown): DashboardAnalysis {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('Analysis output is invalid');
  const item = value as Partial<DashboardAnalysis>;
  if (!item.market || !item.analyst || !item.context) throw new Error('Analysis output is invalid');
  const context = item.context;
  if (item.schema_version !== '1.0' || item.environment !== 'synthetic_fixture'
    || typeof item.created_at !== 'string' || !Number.isFinite(Date.parse(item.created_at))
    || typeof item.input_manifest_id !== 'string' || typeof item.derived_manifest_id !== 'string'
    || item.market.symbol !== 'XAUUSD' || item.market.price !== null || typeof item.market.source !== 'string'
    || !Array.isArray(item.timeframes) || item.timeframes.length !== 5
    || !Array.isArray(item.warnings)) {
    throw new Error('Analysis output is invalid');
  }
  const expected = new Set(['1D', '4H', '1H', '15M', '5M']);
  if (item.timeframes.some((tf) => !tf || !expected.delete(tf.timeframe)
    || !['available', 'unavailable', 'unsupported'].includes(tf.state) || typeof tf.summary !== 'string')) {
    throw new Error('Analysis timeframe set is invalid');
  }
  const states: FeedState[] = ['available', 'unavailable', 'unverified', 'incomplete', 'stale', 'conflicting'];
  if (expected.size || !states.includes(item.market.status)
    || !['complete', 'insufficient_evidence', 'unavailable', 'invalid_response'].includes(item.analyst.status)
    || !['BULLISH', 'BEARISH', 'NEUTRAL', 'INSUFFICIENT EVIDENCE'].includes(item.analyst.bias)
    || !['BUY SETUP', 'SELL SETUP', 'WAIT', 'NO TRADE'].includes(item.analyst.stance)
    || item.analyst.stance !== 'NO TRADE' && item.analyst.status === 'insufficient_evidence'
    || !['calendar', 'macro', 'news', 'sentiment'].every((key) => states.includes(context[key as keyof typeof context] as FeedState))) {
    throw new Error('Analysis safety state is invalid');
  }
  return item as DashboardAnalysis;
}
