import type { ReactNode } from 'react';
import { CalendarDays, Globe2, Layers3, Newspaper, Settings2, ShieldCheck } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { TIMEFRAMES, TIMEZONES, validateDisplayTimezone } from '../preferences';
import type { PersistedAnalysisProjection } from '../analysisApi';

function Panel({ id, title, icon: Icon, children }: {
  id: string; title: string; icon: LucideIcon; children: ReactNode;
}) {
  return (
    <section id={id} className="intelligence-panel" aria-labelledby={`${id}-heading`} tabIndex={-1}>
      <div className="panel-header"><h3 id={`${id}-heading`}><Icon aria-hidden="true" size={18} />{title}</h3></div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function MultiTimeframePanel({ timeframe, analysis = null }: {
  timeframe: string; analysis?: PersistedAnalysisProjection | null;
}) {
  const frameIds: Record<string, string> = { Daily: '1D', '4H': '4H', '1H': '1H', '15M': '15M', '5M': '5M' };
  return (
    <Panel id="timeframe-analysis" title="Multi-timeframe analysis" icon={Layers3}>
      <p className="panel-description">Context across the supported research horizons.</p>
      {analysis ? <p className="panel-footnote" role="status">Persisted synthetic output · {analysis.analysis_id} · read only · not live market data</p> : null}
      <table className="timeframe-table">
        <caption className="sr-only">Stored deterministic evidence by timeframe. Synthetic archive results are not live market data.</caption>
        <thead><tr><th scope="col">Timeframe</th><th scope="col">Assessment</th><th scope="col">Evidence</th></tr></thead>
        <tbody>{TIMEFRAMES.map((value) => {
          const frameId = frameIds[value];
          const state = frameId === '4H' ? 'unsupported' : analysis?.timeframe_availability[frameId] ?? 'unavailable';
          const evidence = analysis?.analysis_output.evidence.filter((item) => item.timeframe === frameId) ?? [];
          return <tr key={value} data-active={timeframe === value}>
            <th scope="row">{value}{timeframe === value ? <span className="sr-only">, selected chart timeframe</span> : null}</th>
            <td>{state}</td><td>{frameId === '4H' ? 'H4-03 deferred; analysis disabled.' : evidence.length
              ? evidence.map((item) => `${item.evidence_type}: ${item.description} · ${item.value ?? 'No numeric value'}${item.units ? ` ${item.units}` : ''} · ${item.quality}`).join(' · ')
              : analysis ? 'No persisted deterministic evidence for this timeframe.' : 'Awaiting verified data'}</td>
          </tr>;
        })}</tbody>
      </table>
      <p className="panel-footnote">No live directional assessment without an eligible, verified source. Persisted calculations are shown as stored and are not reinterpreted here.</p>
    </Panel>
  );
}

export function AnalystPanel() {
  return (
    <section id="analysis" className="analyst-panel" aria-labelledby="analyst-heading" data-state="insufficient_evidence" tabIndex={-1}>
      <div className="analyst-heading"><ShieldCheck aria-hidden="true" size={22} />
        <h3 id="analyst-heading">Central AI Analyst</h3><span className="availability">Insufficient evidence</span>
      </div>
      <div className="analyst-conclusion">
        <h4>NO TRADE — DATA NOT VERIFIED</h4>
        <p id="analysis-unavailable">No eligible live market-data provider is configured. A stored synthetic analysis does not establish a current market signal.</p>
      </div>
      <dl className="analyst-output">
        <div><dt>Higher-timeframe bias</dt><dd>Not assessed</dd></div>
        <div><dt>Intraday bias</dt><dd>Not assessed</dd></div>
        <div><dt>Key levels & invalidation</dt><dd>Unavailable</dd></div>
        <div><dt>Analysis timestamp</dt><dd>No analysis generated</dd></div>
      </dl>
      <div className="analyst-requirements">
        <span>What is missing</span>
        <p>Verified price history, macro context, and source provenance.</p>
      </div>
      <button className="analysis-action" type="button" disabled aria-describedby="analysis-unavailable">Run analysis</button>
    </section>
  );
}

export function MacroPanel() {
  return (
    <Panel id="macro" title="Macro intelligence" icon={Globe2}>
      <p className="panel-description">The broader context for gold.</p>
      <dl className="context-list">
        <div><dt>US dollar index (DXY)</dt><dd>Unavailable</dd></div>
        <div><dt>Treasury yields</dt><dd>Unavailable</dd></div>
        <div><dt>Inflation outlook</dt><dd>Unavailable</dd></div>
        <div><dt>Federal Reserve</dt><dd>Unavailable</dd></div>
      </dl>
      <p className="panel-footnote">Awaiting verified releases and economic calendar data.</p>
    </Panel>
  );
}

export function SentimentPanel() {
  return (
    <Panel id="sentiment" title="Sentiment & news" icon={Newspaper}>
      <dl className="context-list"><div><dt>Market sentiment</dt><dd>Unavailable</dd></div></dl>
      <div className="news-empty"><Newspaper aria-hidden="true" size={24} />
        <p>No verified news is available.</p><span>Awaiting source-backed headlines.</span>
      </div>
    </Panel>
  );
}

export function EvidencePanel() {
  return (
    <Panel id="evidence" title="Evidence quality" icon={ShieldCheck}>
      <dl className="context-list">
        <div><dt>Quality</dt><dd>Unassessed</dd></div>
        <div><dt>Source coverage</dt><dd>Unavailable</dd></div>
        <div><dt>Data freshness</dt><dd>Unavailable</dd></div>
        <div><dt>Last verified update</dt><dd>No source timestamp</dd></div>
      </dl>
      <p className="panel-footnote">Freshness needs a verified source timestamp.</p>
      <details className="evidence-details">
        <summary>Evidence required for research</summary>
        <ul>
          <li>Attributed sources and verified timestamps.</li>
          <li>Complete, validated price history for each timeframe.</li>
          <li>Traceable inputs for supporting and conflicting evidence.</li>
        </ul>
      </details>
    </Panel>
  );
}

export function CalendarPanel() {
  return (
    <Panel id="calendar" title="Economic calendar" icon={CalendarDays}>
      <div className="news-empty calendar-empty"><CalendarDays aria-hidden="true" size={24} />
        <p>Event data is unavailable.</p><span>Upcoming releases and event risk need a verified calendar source.</span>
      </div>
      <dl className="context-list">
        <div><dt>Next relevant release</dt><dd>Unavailable</dd></div>
        <div><dt>Event risk</dt><dd>Unassessed</dd></div>
      </dl>
      <p className="panel-footnote">Unavailable events do not imply a quiet calendar.</p>
    </Panel>
  );
}

export function TimezoneControl({ id, timezone, onTimezoneChange }: {
  id: string; timezone: string; onTimezoneChange: (timezone: string) => void;
}) {
  return (
    <label className="timezone" htmlFor={id}>Display timezone
      <select id={id} name="display-timezone" value={timezone} onChange={(event) => onTimezoneChange(validateDisplayTimezone(event.target.value))}>
        {TIMEZONES.map((zone) => <option key={zone.value} value={zone.value}>{zone.label}</option>)}
      </select>
    </label>
  );
}

export function SettingsPanel({ timezone, onTimezoneChange }: {
  timezone: string; onTimezoneChange: (timezone: string) => void;
}) {
  return (
    <Panel id="settings" title="Settings & providers" icon={Settings2}>
      <div className="display-settings">
        <TimezoneControl id="settings-timezone" timezone={timezone} onTimezoneChange={onTimezoneChange} />
        <p>Applies to this workspace. Source timestamps remain in UTC.</p>
      </div>
      <dl className="context-list provider-settings">
        <div><dt>Market data provider</dt><dd>Not connected to workspace</dd></div>
        <div><dt>AI provider & model</dt><dd>Status unavailable</dd></div>
        <div><dt>News & calendar sources</dt><dd>Not connected to workspace</dd></div>
      </dl>
      <p className="panel-footnote">Provider configuration is managed on the backend. This workspace has no access to credentials.</p>
    </Panel>
  );
}
