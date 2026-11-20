import type { PersistedAnalysisProjection } from '../analysisApi';
import { formatTimestamp } from '../preferences';

const record = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === 'string' ? value : 'Unavailable';
const claimTexts = (value: unknown) => Array.isArray(value) ? value.map((item) => text(record(item).text)).join(' · ') : 'Unavailable';
const claimCitations = (value: unknown) => Array.isArray(value) ? [...new Set(value.flatMap((item) => {
  const claim = record(item);
  return [...(Array.isArray(claim.evidence_ids) ? claim.evidence_ids : []),
    ...(Array.isArray(claim.market_evidence_ids) ? claim.market_evidence_ids : []),
    ...(Array.isArray(claim.context_record_ids) ? claim.context_record_ids : [])];
}))].map(String).join(', ') || 'None' : 'None';

export function PersistedAnalysisPanel({ result, timezone = 'Asia/Qatar' }: {
  result: PersistedAnalysisProjection; timezone?: string;
}) {
  const localTime = (timestamp: string) => formatTimestamp(new Date(timestamp).toISOString(), timezone);
  return (
    <section className="synthetic-panel persisted-analysis" aria-labelledby="persisted-analysis-heading">
      <div className="synthetic-banner" role="status">SYNTHETIC ARCHIVE · READ ONLY · NOT LIVE MARKET DATA</div>
      <h3 id="persisted-analysis-heading">Persisted analysis {result.analysis_id}</h3>
      {result.status === 'historical_invalidated' ? <p role="alert">Historical evidence warning: {result.invalidation_warnings.join(', ')}</p> : null}
      <dl className="context-list">
        <div><dt>Persisted output</dt><dd>{result.analysis_id} · {result.analysis_output_digest}</dd></div>
        <div><dt>Analysis status</dt><dd>{result.status}</dd></div>
        <div><dt>Analysis timestamp</dt><dd><time dateTime={result.analysis_timestamp}>{localTime(result.analysis_timestamp)} ({timezone})</time></dd></div>
        <div><dt>Market data</dt><dd>{result.market_data_status}</dd></div>
        <div><dt>Input retrieved</dt><dd><time dateTime={result.market_data_timestamp}>{localTime(result.market_data_timestamp)} ({timezone})</time></dd></div>
        <div><dt>Source eligibility</dt><dd>{result.source_eligibility_status}</dd></div>
        <div><dt>Sources</dt><dd>{result.source_attribution.join(', ') || 'Unavailable'}</dd></div>
        <div><dt>Retrieval completeness</dt><dd>{Object.entries(result.retrieval_completeness).map(([id, state]) => `${id}: ${state}`).join(', ') || 'Unavailable'}</dd></div>
        <div><dt>Freshness</dt><dd>{result.freshness_status === 'fresh' ? 'fresh · synthetic policy only; live freshness not established' : 'unassessed · live freshness not established'}</dd></div>
        <div><dt>Evidence quality</dt><dd>{result.evidence_quality}</dd></div>
        <div><dt>Analyst conclusion</dt><dd>{result.ai_report?.status ?? `Unavailable · ${result.analyst_unavailable_reason}`}</dd></div>
        <div><dt>Input manifest</dt><dd>{result.input_manifest_id} · {result.input_manifest_digest}</dd></div>
        <div><dt>Derived manifest</dt><dd>{result.derived_manifest_id} · {result.derived_manifest_digest}</dd></div>
        <div><dt>Algorithm</dt><dd>{result.algorithm_id} v{result.algorithm_version}</dd></div>
      </dl>
      <h4>Persisted timeframe availability</h4>
      <ul>{Object.entries(result.timeframe_availability).map(([frame, state]) =>
        <li key={frame}>{frame}: {state}</li>)}</ul>
      <h4>Persisted deterministic evidence</h4>
      {result.analysis_output.evidence.length
        ? <ul className="persisted-evidence">{result.analysis_output.evidence.map((item) =>
          <li key={item.evidence_id}><strong>{item.evidence_type}</strong> · {item.description} · {item.value ?? 'No numeric value'}{item.units ? ` ${item.units}` : ''} · {item.quality}</li>)}</ul>
        : <p>No deterministic evidence records were persisted.</p>}
      <p>Unavailable inputs: {result.unavailable_inputs.join(', ') || 'None recorded'}</p>
      {result.ai_report ? <section aria-label="Persisted synthetic AI report">
        <h4>{result.ai_report.report_id ? 'Persisted synthetic AI report' : 'Synthetic AI request/response record · no report persisted'} · not a live recommendation</h4>
        <dl className="context-list">
          <div><dt>Report identity</dt><dd>{result.ai_report.report_id ?? `No valid report · ${result.ai_report.status}`} · {result.ai_report.report_digest ?? 'No report digest'}</dd></div>
          <div><dt>Request and response</dt><dd>{result.ai_report.request_id} · {result.ai_report.request_digest} / {result.ai_report.response_id} · {result.ai_report.response_digest}</dd></div>
          <div><dt>Provider / model</dt><dd>{result.ai_report.provider_id} / {result.ai_report.model_id}</dd></div>
          <div><dt>Prompt version</dt><dd>{result.ai_report.prompt_version}</dd></div>
        </dl>
        {result.ai_report.report ? (() => {
          const run = result.ai_report.report;
          const analysis = record(run.analysis);
          const scenarios = record(run.report);
          const provenance = record(run.provenance);
          return <>
            <h5>Outcome</h5><p>{text(record(analysis).bias)} · {text(record(analysis).trade_stance)} · {text(run.status)}</p>
            <h5>Summary and evidence</h5><p>{claimTexts(analysis.rationale)}</p>
            <p>Source evidence references: {claimCitations(analysis.rationale)}</p>
            <p>Confidence context: {claimTexts(analysis.confidence_explanation)}</p>
            <h5>Multi-timeframe interpretation</h5>
            {Array.isArray(analysis.timeframes) ? <ul>{analysis.timeframes.map((item) => {
              const frame = record(item);
              return <li key={text(frame.timeframe)}>{text(frame.timeframe)} · {text(frame.direction)} · {claimTexts(frame.structure)}</li>;
            })}</ul> : <p>Unavailable</p>}
            <h5>Bullish scenario</h5><p>{text(record(scenarios.bullish_scenario).text)}</p>
            <h5>Bearish scenario</h5><p>{text(record(scenarios.bearish_scenario).text)}</p>
            <h5>Neutral / no-trade conditions</h5><p>{text(record(scenarios.neutral_conditions).text)}</p>
            <h5>Macro / news context</h5><p>{claimTexts(scenarios.context_interpretations)}</p>
            <p>Context source references: {claimCitations(scenarios.context_interpretations)}</p>
            <h5>Invalidation and missing evidence</h5><p>{claimTexts(analysis.invalidating_conditions)} · {Array.isArray(run.unavailable_inputs) ? run.unavailable_inputs.join(', ') : 'No missing-input list'}</p>
            <p>Bound to {text(provenance.input_manifest_id)} / {text(provenance.derived_manifest_id)}; deterministic output {result.analysis_id}.</p>
          </>;
        })() : <p role="status">No valid analyst conclusion is available for this request.</p>}
        {result.status === 'historical_invalidated' ? <p role="alert">This stored report is historical and its underlying evidence has since been invalidated.</p> : null}
      </section> : null}
      <p className="panel-footnote">No market price or AI bias is inferred from this deterministic output. Historical invalidation does not rewrite the archived result.</p>
    </section>
  );
}
