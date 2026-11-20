import type * as ChartLibrary from 'lightweight-charts';
import { formatTimestamp } from './preferences';

export type ChartCandle = { time: number; open: number; high: number; low: number; close: number };

export function createEmptyChart(container: HTMLElement, library: typeof ChartLibrary, candles: ChartCandle[] = [], timezone = 'Asia/Qatar') {
  const chart = library.createChart(container, {
    autoSize: true,
    layout: {
      background: { type: library.ColorType.Solid, color: '#0e151f' },
      textColor: '#9aa6b5',
      attributionLogo: true,
    },
    grid: { vertLines: { color: '#1b2634' }, horzLines: { color: '#1b2634' } },
    localization: { timeFormatter: (time: ChartLibrary.Time) => typeof time === 'number'
      ? formatTimestamp(new Date(time * 1000).toISOString(), timezone) : String(time) },
    rightPriceScale: { visible: candles.length > 0 },
    timeScale: { visible: candles.length > 0, tickMarkFormatter: (time: ChartLibrary.Time) => typeof time === 'number'
      ? new Intl.DateTimeFormat('en-GB', { timeZone: timezone, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(time * 1000) : String(time) },
    handleScroll: false,
    handleScale: false,
  });
  try {
    const series = chart.addSeries(library.CandlestickSeries, {
      upColor: '#6ca58a', downColor: '#c57d80',
      wickUpColor: '#6ca58a', wickDownColor: '#c57d80', borderVisible: false,
      priceLineVisible: false, lastValueVisible: false,
    });
    if (candles.length) {
      series.setData(candles as ChartLibrary.CandlestickData<ChartLibrary.UTCTimestamp>[]);
      chart.timeScale().fitContent();
    }
    return chart;
  } catch (error) {
    chart.remove();
    throw error;
  }
}
