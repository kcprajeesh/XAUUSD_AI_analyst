export type ProjectedCandle = {
  timeframe: '1D' | '1H' | '15M'; opened_at: string; closed_at: string;
  open: string; high: string; low: string; close: string;
};

export type PersistedAnalysisProjection = {
  schema_version: 'xau.dashboard-analysis.v1';
  environment: 'synthetic_archive';
  analysis_id: string;
  status: 'available' | 'historical_invalidated';
  analysis_timestamp: string;
  market_data_status: 'available' | 'incomplete' | 'unavailable';
  market_data_timestamp: string;
  freshness_status: 'unassessed' | 'fresh';
  valid_until?: string | null;
  candles?: ProjectedCandle[];
  source_eligibility_status: 'unverified';
  source_attribution: string[];
  retrieval_completeness: Record<string, 'verified' | 'incomplete' | 'unsupported' | 'collecting'>;
  timeframe_availability: Record<string, 'available' | 'unavailable' | 'unsupported'>;
  analyst_outcome: 'unavailable' | 'complete' | 'insufficient_evidence';
  analyst_unavailable_reason: string;
  ai_report: null | {
    status: 'complete' | 'insufficient_evidence' | 'unavailable' | 'invalid_response';
    report_id: string | null; report_digest: string | null; response_id: string; response_digest: string;
    request_id: string; request_digest: string; provider_id: string; model_id: string; prompt_version: string;
    report: Record<string, unknown> | null;
  };
  evidence_quality: string;
  unavailable_inputs: string[];
  invalidation_warnings: string[];
  input_manifest_id: string;
  input_manifest_digest: string;
  derived_manifest_id: string;
  derived_manifest_digest: string;
  analysis_output_digest: string;
  algorithm_id: string;
  algorithm_version: string;
  analysis_output: {
    analysis_id: string;
    analysis_at: string;
    retrieved_at: string;
    requested_timeframes: string[];
    timeframes: Array<{ timeframe: string; state: string }>;
    evidence: Array<{ evidence_id: string; evidence_type: string; description: string; value: string | null; units: string | null; timeframe: string | null; quality: string }>;
  };
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export function validatePersistedAnalysis(value: unknown, now = Date.now()): PersistedAnalysisProjection {
  if (!isRecord(value) || !isRecord(value.analysis_output)
    || value.schema_version !== 'xau.dashboard-analysis.v1'
    || value.environment !== 'synthetic_archive'
    || typeof value.analysis_id !== 'string' || typeof value.analysis_output.analysis_id !== 'string'
    || !['available', 'historical_invalidated'].includes(String(value.status))
    || !['available', 'incomplete', 'unavailable'].includes(String(value.market_data_status))
    || !['unavailable', 'complete', 'insufficient_evidence'].includes(String(value.analyst_outcome))
    || !Array.isArray(value.source_attribution) || !isRecord(value.retrieval_completeness) || !Array.isArray(value.unavailable_inputs)
    || !Array.isArray(value.invalidation_warnings) || !isRecord(value.timeframe_availability)
    || !Array.isArray(value.analysis_output.timeframes) || !Array.isArray(value.analysis_output.evidence)
    || !['analysis_timestamp', 'market_data_timestamp'].every((key) => typeof value[key] === 'string' && Number.isFinite(Date.parse(value[key] as string)))
    || Object.values(value.retrieval_completeness as Record<string, unknown>).some((state) =>
      !['verified', 'incomplete', 'unsupported', 'collecting'].includes(String(state)))
    || !['analysis_id', 'analyst_unavailable_reason', 'evidence_quality', 'input_manifest_id', 'derived_manifest_id',
      'algorithm_id', 'algorithm_version'].every((key) => typeof value[key] === 'string' && value[key].length > 0)
    || !['input_manifest_digest', 'derived_manifest_digest', 'analysis_output_digest'].every((key) =>
      typeof value[key] === 'string' && /^[0-9a-f]{64}$/.test(value[key] as string))) {
    throw new Error('Persisted analysis response is malformed');
  }
  if (value.ai_report !== undefined && value.ai_report !== null) {
    const report = value.ai_report;
    if (!isRecord(report) || !['complete', 'insufficient_evidence', 'unavailable', 'invalid_response'].includes(String(report.status))
      || !['response_id', 'response_digest', 'request_id', 'request_digest', 'provider_id', 'model_id', 'prompt_version'].every((key) => typeof report[key] === 'string')
      || !['response_digest', 'request_digest'].every((key) => /^[0-9a-f]{64}$/.test(report[key] as string))
      || (report.report_digest !== null && (typeof report.report_digest !== 'string' || !/^[0-9a-f]{64}$/.test(report.report_digest)))
      || (report.report_id !== null && typeof report.report_id !== 'string')
      || (report.report !== null && !isRecord(report.report))) throw new Error('Persisted AI report is malformed');
  }
  if (!['unassessed', 'fresh'].includes(String(value.freshness_status))) throw new Error('Invalid freshness status');
  if (value.freshness_status === 'fresh') {
    if (typeof value.valid_until !== 'string' || !value.valid_until.endsWith('Z')
      || !Number.isFinite(Date.parse(value.valid_until)) || Date.parse(value.valid_until) <= now
      || value.status !== 'available' || value.market_data_status !== 'available'
      || value.analyst_outcome !== 'complete' || !Array.isArray(value.candles)) throw new Error('stale_or_invalid_evidence');
    validateCandles(value.candles, now);
  } else if (Array.isArray(value.candles) && value.candles.length) throw new Error('Unassessed candles are unavailable');
  return value as unknown as PersistedAnalysisProjection;
}

export async function fetchPersistedAnalysis(analysisId: string, signal?: AbortSignal): Promise<PersistedAnalysisProjection> {
  const response = await fetch(`/api/v1/analysis/${encodeURIComponent(analysisId)}`, {
    headers: { Accept: 'application/json' }, cache: 'no-store', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(5000)]) : AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(response.status === 404 ? 'analysis_not_found'
    : response.status === 503 ? 'analysis_projection_unavailable' : `analysis_request_failed_${response.status}`);
  const result = validatePersistedAnalysis(await response.json());
  if (result.analysis_id !== analysisId) throw new Error('analysis_identity_mismatch');
  return result;
}


function validateCandles(values: unknown[], now: number) {
  const steps: Record<string, number> = { '1D': 86400000, '1H': 3600000, '15M': 900000 };
  const counts: Record<string, number> = { '1D': 0, '1H': 0, '15M': 0 };
  const previous: Record<string, number> = {};
  if (values.length > 6000) throw new Error('Synthetic candle bound exceeded');
  for (const value of values) {
    if (!isRecord(value) || typeof value.timeframe !== 'string' || !(value.timeframe in steps)
      || !['opened_at', 'closed_at'].every((key) => typeof value[key] === 'string'
        && (value[key] as string).endsWith('Z') && Number.isFinite(Date.parse(value[key] as string)))
      || !['open', 'high', 'low', 'close'].every((key) => typeof value[key] === 'string'
        && Number.isFinite(Number(value[key])) && Number(value[key]) > 0)) throw new Error('Invalid synthetic candle');
    const opened = Date.parse(value.opened_at as string);
    const closed = Date.parse(value.closed_at as string);
    const frame = value.timeframe;
    if (closed > now || opened % steps[frame] !== 0 || closed - opened !== steps[frame] || (previous[frame] !== undefined && opened - previous[frame] !== steps[frame])
      || Number(value.low) > Math.min(Number(value.open), Number(value.close))
      || Number(value.high) < Math.max(Number(value.open), Number(value.close))
      || Number(value.low) > Number(value.high)) throw new Error('Gapped or invalid synthetic candle');
    previous[frame] = opened;
    counts[frame] += 1;
  }
  if (counts['1D'] < 200 || counts['1H'] < 300 || counts['15M'] < 300) throw new Error('Insufficient synthetic depth');
}

export type MarketDataStatus = {
  analysis_available: boolean; analysis_id: string | null; freshness_status: 'fresh' | 'unavailable';
  source_label: string; updated_at: string | null; valid_until: string | null; error_category: string | null;
};

export function validateMarketDataStatus(value: unknown, now = Date.now()): MarketDataStatus {
  if (!isRecord(value) || typeof value.analysis_available !== 'boolean' || typeof value.source_label !== 'string') {
    throw new Error('Malformed market-data status');
  }
  // The dormant original service remains a valid unavailable source.
  if (value.provider === 'siftingio' && value.analysis_available === false && Array.isArray(value.timeframes)) {
    return { analysis_available: false, analysis_id: null, freshness_status: 'unavailable', source_label: value.source_label,
      updated_at: null, valid_until: null, error_category: 'startup_ingestion_disabled' };
  }
  if (value.environment !== 'synthetic_archive' || !['fresh', 'unavailable'].includes(String(value.freshness_status))) {
    throw new Error('Malformed market-data status');
  }
  if (value.analysis_available && (value.freshness_status !== 'fresh' || typeof value.analysis_id !== 'string'
    || !value.analysis_id || ![value.updated_at, value.valid_until].every((item) => typeof item === 'string'
      && item.endsWith('Z') && Number.isFinite(Date.parse(item))) || Date.parse(value.valid_until as string) <= now)) {
    throw new Error('stale_or_invalid_evidence');
  }
  if (!value.analysis_available && (value.analysis_id !== null || value.valid_until !== null || value.freshness_status !== 'unavailable')) {
    throw new Error('Unavailable source claims analysis');
  }
  return value as unknown as MarketDataStatus;
}

export async function fetchMarketDataStatus(signal?: AbortSignal): Promise<MarketDataStatus> {
  const response = await fetch('/api/v1/market-data/status', { headers: { Accept: 'application/json' }, cache: 'no-store',
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(5000)]) : AbortSignal.timeout(5000) });
  if (!response.ok) throw new Error('market_data_status_unavailable');
  return validateMarketDataStatus(await response.json());
}
