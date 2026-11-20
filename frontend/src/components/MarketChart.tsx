import { useEffect, useMemo, useRef, useState } from 'react';
import type { IChartApi } from 'lightweight-charts';
import { ChartNoAxesCombined } from 'lucide-react';
import { createEmptyChart } from '../chart';
import type { PersistedAnalysisProjection } from '../analysisApi';
import { formatTimestamp } from '../preferences';

export function MarketChart({ timeframe, analysis, timezone = 'Asia/Qatar' }: { timeframe: string; analysis?: PersistedAnalysisProjection | null; timezone?: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [chartUnavailable, setChartUnavailable] = useState(false);

  const candles = useMemo(() => analysis?.freshness_status === 'fresh'
    ? (analysis.candles ?? []).filter((c) => c.timeframe === (timeframe === 'Daily' ? '1D' : timeframe)) : [], [analysis, timeframe]);
  const latest = candles.at(-1);

  useEffect(() => {
    const element = container.current!;
    let disposed = false;
    let chart: IChartApi | undefined;
    import('lightweight-charts').then((library) => {
      if (!disposed) {
        setChartUnavailable(false);
        chart = createEmptyChart(element, library, candles.map((c) => ({ time: Date.parse(c.opened_at) / 1000,
          open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close) })), timezone);
      }
    }).catch(() => {
      if (!disposed) setChartUnavailable(true);
    });
    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [candles, timezone]);

  return (
    <>
      <div className="chart-surface">
        <div className="chart-canvas" ref={container} aria-hidden="true" inert />
        {!latest ? <div className="empty-market" role="status">
          <span className="empty-icon"><ChartNoAxesCombined aria-hidden="true" size={28} /></span>
          <h4>Market data is not connected</h4>
          <p>Prices and the {timeframe} chart will appear when a verified data source is available.</p>
          <span className="availability">Awaiting market data</span>
          {chartUnavailable ? <p>Chart surface unavailable. Reload to try again.</p> : null}
        </div> : null}
      </div>
      {latest ? <p role="status">SYNTHETIC FIXTURE — NOT LIVE MARKET DATA. Latest closed candle: <time dateTime={latest.closed_at}>{formatTimestamp(latest.closed_at, timezone)} ({timezone})</time>.
        Open {latest.open} · High {latest.high} · Low {latest.low} · Close {latest.close}.
        {chartUnavailable ? ' Chart surface unavailable; candle summary remains available.' : ''}</p> : null}
      <div className="chart-footnote">
        <span>{latest ? `SYNTHETIC FIXTURE · ${timeframe} · ${candles.length} closed candles · ${timezone}`
          : `${timeframe} timeframe · No verified price history loaded`}</span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView <span className="sr-only">(opens in a new tab)</span></a>
      </div>
    </>
  );
}
