import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ChartNoAxesCombined } from 'lucide-react';
import { formatTimestamp, TIMEFRAMES, validateDisplayTimezone } from './preferences';
import { Navigation } from './components/Navigation';
import { MarketChart } from './components/MarketChart';
import { BackendStatus } from './components/BackendStatus';
import { AnalystPanel, CalendarPanel, EvidencePanel, MacroPanel, MultiTimeframePanel, SentimentPanel, SettingsPanel, TimezoneControl } from './components/IntelligencePanels';
import { SyntheticWorkflowPanel } from './components/SyntheticWorkflowPanel';
import { PersistedAnalysisPanel } from './components/PersistedAnalysisPanel';
import { fetchMarketDataStatus, fetchPersistedAnalysis, type MarketDataStatus, type PersistedAnalysisProjection } from './analysisApi';

const defaultTimezone = validateDisplayTimezone(import.meta.env.VITE_DISPLAY_TIMEZONE ?? 'Asia/Qatar');

export function App({ initialSyntheticView = false }: { initialSyntheticView?: boolean } = {}) {
  const [timeframe, setTimeframe] = useState<string>('Daily');
  const [timezone, setTimezone] = useState(defaultTimezone);
  const [openedAt] = useState(() => new Date().toISOString());
  const [showSynthetic, setShowSynthetic] = useState(initialSyntheticView);
  const [analysisId, setAnalysisId] = useState('');
  const [persistedAnalysis, setPersistedAnalysis] = useState<PersistedAnalysisProjection | null>(null);
  const [analysisLoadState, setAnalysisLoadState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [analysisError, setAnalysisError] = useState('');
  const [marketStatus, setMarketStatus] = useState<MarketDataStatus | null>(null);
  const [statusRetry, setStatusRetry] = useState(0);
  const analysisRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function update() {
      try {
        const status = await fetchMarketDataStatus(controller.signal);
        if (controller.signal.aborted) return;
        setMarketStatus(status);
        if (status.analysis_available) setAnalysisId((current) => current || status.analysis_id || '');
        else setPersistedAnalysis((current) => current?.freshness_status === 'fresh' ? null : current);
      } catch {
        if (!controller.signal.aborted) {
          setMarketStatus(null);
          setPersistedAnalysis((current) => current?.freshness_status === 'fresh' ? null : current);
        }
      }
    }
    void update();
    const timer = setInterval(() => void update(), 15000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [statusRetry]);

  useEffect(() => () => analysisRequest.current?.abort(), []);
  useEffect(() => {
    const expirations = [marketStatus?.valid_until, persistedAnalysis?.valid_until].filter((value): value is string => !!value);
    if (!expirations.length) return;
    const timer = setTimeout(() => {
      setMarketStatus(null);
      setPersistedAnalysis((current) => current?.freshness_status === 'fresh' ? null : current);
    }, Math.min(2147483647, Math.max(0, Math.min(...expirations.map(Date.parse)) - Date.now())));
    return () => clearTimeout(timer);
  }, [marketStatus?.valid_until, persistedAnalysis?.valid_until]);


  async function loadPersistedAnalysis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = analysisId.trim();
    if (!id) return;
    analysisRequest.current?.abort();
    const controller = new AbortController();
    analysisRequest.current = controller;
    setPersistedAnalysis(null);
    setAnalysisLoadState('loading');
    setAnalysisError('');
    try {
      const [result, status] = await Promise.all([
        fetchPersistedAnalysis(id, controller.signal), fetchMarketDataStatus(controller.signal),
      ]);
      if (result.freshness_status === 'fresh' && !status.analysis_available) throw new Error('market_data_unavailable');
      setMarketStatus(status);
      if (controller.signal.aborted) return;
      setPersistedAnalysis(result);
      setAnalysisLoadState('idle');
    } catch (error) {
      if (controller.signal.aborted) return;
      setAnalysisLoadState('error');
      setAnalysisError(error instanceof Error ? error.message : 'analysis_request_failed');
    }
  }

  return (
    <div className="workspace">
      <a className="skip-link" href="#main-content">Skip to market intelligence</a>
      <header className="masthead">
        <div className="identity">
          <span className="brand-mark"><ChartNoAxesCombined aria-hidden="true" size={26} /></span>
          <div><h1 translate="no">XAUUSD AI Analyst</h1><p>Gold market intelligence</p></div>
        </div>
        <div className="stage"><span className="workspace-label">Research workspace</span><BackendStatus /></div>
      </header>

      <div className="application-layout">
      <Navigation />
      <main id="main-content" tabIndex={-1}>
        <section id="overview" aria-labelledby="overview-heading" tabIndex={-1}>
        <div className="toolbar">
          <div><h2 id="overview-heading">Gold overview</h2><p>The research view for spot gold.</p></div>
          <TimezoneControl id="overview-timezone" timezone={timezone} onTimezoneChange={setTimezone} />
        </div>

        <div className="market-overview">
          <div className="instrument"><span translate="no">XAUUSD</span><p>Spot gold / US dollar</p><span className="availability">Awaiting verified sources</span></div>
          <dl className="market-metrics">
            <div><dt>Last price</dt><dd>Unavailable</dd></div>
            <div><dt>Daily change</dt><dd>Unavailable</dd></div>
            <div><dt>Market source</dt><dd>Not connected</dd></div>
            <div><dt>Data freshness</dt><dd>Unassessed</dd></div>
          </dl>
        </div>
        <div className="data-notice"><p>Market prices remain unavailable until eligible live evidence is connected. Archived research can be inspected by immutable analysis ID.</p><div><a href="#settings">Review source settings</a><button type="button" onClick={() => setShowSynthetic((value) => !value)} aria-expanded={showSynthetic}>View synthetic example</button></div></div>
        {showSynthetic ? <SyntheticWorkflowPanel /> : null}
        <div className="data-notice" role="status">
          <p>Market-data availability: {marketStatus?.analysis_available ? 'SYNTHETIC FIXTURE — NOT LIVE MARKET DATA' : 'unavailable'}.
            Freshness: {marketStatus?.freshness_status ?? 'unavailable'}.
            {marketStatus?.updated_at ? ` Retrieved ${formatTimestamp(marketStatus.updated_at, timezone)} (${timezone}).` : ''}
            {marketStatus?.error_category ? ` ${marketStatus.error_category.replaceAll('_', ' ')}.` : ''}</p>
          <button type="button" onClick={() => setStatusRetry((value) => value + 1)}>Refresh market-data status</button>
        </div>
        <form className="analysis-lookup" onSubmit={loadPersistedAnalysis} aria-busy={analysisLoadState === 'loading'}>
          <label htmlFor="analysis-id">Immutable analysis ID</label>
          <input id="analysis-id" value={analysisId} onChange={(event) => setAnalysisId(event.target.value)} autoComplete="off" />
          <button type="submit" disabled={!analysisId.trim() || analysisLoadState === 'loading'}>
            {analysisLoadState === 'loading' ? 'Loading archived analysis…' : 'Load archived analysis'}
          </button>
          {analysisLoadState === 'error' ? <p role="alert">Archived analysis unavailable: {analysisError.replaceAll('_', ' ')}.</p> : null}
        </form>
        </section>

        <div className="research-grid">

        <section className="market-panel" aria-labelledby="market-heading">
          <div className="panel-header">
            <div className="chart-heading"><h3 id="market-heading">Price context</h3><span>XAUUSD</span></div>
            <div className="timeframes" role="group" aria-label="Timeframe">
              {TIMEFRAMES.map((value) => (
                <button type="button" key={value} aria-pressed={timeframe === value} disabled={value === '4H'}
                  aria-label={value === '4H' ? '4H timeframe unavailable while H4-03 is deferred' : value}
                  onClick={() => setTimeframe(value)}>{value}</button>
              ))}
            </div>
          </div>
          <MarketChart timeframe={timeframe} analysis={persistedAnalysis} timezone={timezone} />
        </section>

        {persistedAnalysis ? <section id="analysis" aria-label="Central AI Analyst">
          <PersistedAnalysisPanel result={persistedAnalysis} timezone={timezone} />
        </section> : <AnalystPanel />}
        <MultiTimeframePanel timeframe={timeframe} analysis={persistedAnalysis} />
        </div>

        <div className="context-grid">
          <MacroPanel /><SentimentPanel /><CalendarPanel />
        </div>
        <div className="source-grid">
          <EvidencePanel /><SettingsPanel timezone={timezone} onTimezoneChange={setTimezone} />
        </div>
      </main>
      </div>

      <footer>
        <p>Evidence before conclusions. No trade execution.</p>
        <p>Workspace opened <time dateTime={openedAt}>{formatTimestamp(openedAt, timezone)}</time></p>
      </footer>
    </div>
  );
}
