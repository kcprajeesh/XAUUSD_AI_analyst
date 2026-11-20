import { validateDashboardAnalysis } from './analysisContract';

// This fixture deliberately contains no market price or directional conclusion.
export const syntheticAnalysis = validateDashboardAnalysis({
  schema_version: '1.0',
  environment: 'synthetic_fixture',
  created_at: '2026-11-18T12:00:00Z',
  input_manifest_id: 'synthetic-input-fixture',
  derived_manifest_id: 'synthetic-derived-fixture',
  market: { symbol: 'XAUUSD', status: 'unavailable', price: null, source: 'synthetic test only', retrieved_at: null },
  timeframes: [
    { timeframe: '1D', state: 'unavailable', summary: 'No eligible evidence in this fixture.' },
    { timeframe: '4H', state: 'unsupported', summary: 'H4-03 production policy is deferred.' },
    { timeframe: '1H', state: 'available', summary: 'Synthetic deterministic output exists; this is not a market observation.' },
    { timeframe: '15M', state: 'unavailable', summary: 'No eligible evidence in this fixture.' },
    { timeframe: '5M', state: 'unavailable', summary: 'No eligible evidence in this fixture.' },
  ],
  analyst: {
    status: 'insufficient_evidence', bias: 'INSUFFICIENT EVIDENCE', stance: 'NO TRADE',
    summary: 'No market conclusion: this fixture has no eligible XAUUSD price evidence.',
    bullish_scenario: 'Unavailable until verified evidence is supplied.',
    bearish_scenario: 'Unavailable until verified evidence is supplied.',
    invalidation: 'Not assessed.', risk_reward: 'Not assessed.', evidence_quality: 'Incomplete synthetic fixture',
  },
  context: { calendar: 'unavailable', macro: 'unavailable', news: 'unavailable', sentiment: 'unavailable',
    unavailable_reasons: ['No eligible calendar, macro, news or sentiment sources are connected.'] },
  warnings: ['Synthetic fixture — never live market data.', 'Missing and unsupported inputs force an insufficient-evidence outcome.',
    '1M is unsupported by the current evidence packet contract.'],
});
