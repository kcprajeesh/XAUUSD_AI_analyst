import { syntheticAnalysis } from '../syntheticAnalysis';

export function SyntheticWorkflowPanel() {
  const result = syntheticAnalysis;
  return (
    <section className="synthetic-panel" aria-labelledby="synthetic-heading">
      <div className="synthetic-banner" role="status">SYNTHETIC FIXTURE · NOT LIVE MARKET DATA</div>
      <h3 id="synthetic-heading">Verified analysis-output contract preview</h3>
      <p>{result.analyst.summary}</p>
      <dl className="context-list">
        <div><dt>Market price</dt><dd>Unavailable</dd></div>
        <div><dt>Market source</dt><dd>{result.market.source}</dd></div>
        <div><dt>Market status</dt><dd>{result.market.status}</dd></div>
        <div><dt>Last update</dt><dd>{result.market.retrieved_at ?? 'No verified timestamp'}</dd></div>
        <div><dt>AI outcome</dt><dd>{result.analyst.bias} · {result.analyst.stance}</dd></div>
        <div><dt>Evidence quality</dt><dd>{result.analyst.evidence_quality}</dd></div>
        <div><dt>Invalidation</dt><dd>{result.analyst.invalidation}</dd></div>
        <div><dt>Risk/reward</dt><dd>{result.analyst.risk_reward}</dd></div>
        <div><dt>Input manifest</dt><dd>{result.input_manifest_id}</dd></div>
        <div><dt>Derived manifest</dt><dd>{result.derived_manifest_id}</dd></div>
      </dl>
      <div className="synthetic-timeframes">
        {result.timeframes.map((item) => <div key={item.timeframe}>
          <strong>{item.timeframe}</strong><span>{item.state}</span><p>{item.summary}</p>
        </div>)}
      </div>
      <div className="synthetic-scenarios">
        <div><h4>Bullish scenario</h4><p>{result.analyst.bullish_scenario}</p></div>
        <div><h4>Bearish scenario</h4><p>{result.analyst.bearish_scenario}</p></div>
      </div>
      <ul className="synthetic-warnings">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
      <p className="panel-footnote">Calendar, macro, news and sentiment: unavailable. {result.context.unavailable_reasons.join(' ')}</p>
      <p className="panel-footnote">Provenance timestamp: {result.created_at}. Synthetic manifest identifiers are examples, not archived market evidence.</p>
    </section>
  );
}
