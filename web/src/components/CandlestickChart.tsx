import { useEffect, useRef, useState, type FC } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { Maximize2, Minimize2 } from 'lucide-react';
import { CandleBar, CandlePayload, Timeframe } from '../types';

interface CandlestickChartProps {
  assetId: string;
  yesAssetId: string;
  noAssetId: string;
  outcomeLabel: 'YES' | 'NO';
  slug: string;
  candidateName?: string;
  isMultiCandidate: boolean;
  liveCandle: { asset_id: string; candle: CandleBar } | null;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onSelectContract: (assetId: string) => void;
  onStatsUpdate?: (stats: {
    current_price: number;
    change_24h_pct: number;
    volume_24h: number;
    open_interest: number;
  }) => void;
}

const TIMEFRAMES: Timeframe[] = ['1M', '5M', '15M', '1H', '1D'];

const TF_SECONDS: Record<Timeframe, number> = {
  '1M': 60,
  '5M': 300,
  '15M': 900,
  '1H': 3600,
  '1D': 86400,
};

function formatCompactUsd(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

export const CandlestickChart: FC<CandlestickChartProps> = ({
  assetId,
  yesAssetId,
  noAssetId,
  outcomeLabel,
  slug,
  candidateName,
  isMultiCandidate,
  liveCandle,
  isExpanded,
  onToggleExpand,
  onSelectContract,
  onStatsUpdate,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  const [timeframe, setTimeframe] = useState<Timeframe>('15M');
  const [bars, setBars] = useState<CandleBar[]>([]);
  const [hoveredBar, setHoveredBar] = useState<CandleBar | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const barsRef = useRef<CandleBar[]>([]);
  const minVolTrackerRef = useRef<Map<number, number>>(new Map());
  const onStatsRef = useRef(onStatsUpdate);
  onStatsRef.current = onStatsUpdate;

  // Create chart instance once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: '#0B0E14' },
        textColor: '#94A3B8',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: '#141B29' },
        horzLines: { color: '#141B29' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#475569', labelBackgroundColor: '#1E293B' },
        horzLine: { color: '#475569', labelBackgroundColor: '#1E293B' },
      },
      rightPriceScale: {
        borderColor: '#1E293B',
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor: '#1E293B',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
      },
      localization: {
        priceFormatter: (price: number) => `$${price.toFixed(3)}`,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10B981',
      downColor: '#EF4444',
      borderVisible: false,
      wickUpColor: '#10B981',
      wickDownColor: '#EF4444',
      priceFormat: {
        type: 'price',
        precision: 3,
        minMove: 0.001,
      },
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0.0 },
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) {
        setHoveredBar(null);
        return;
      }
      const t = Number(param.time);
      const match = barsRef.current.find(b => b.time === t) || null;
      setHoveredBar(match);
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          chart.applyOptions({ width: Math.floor(width), height: Math.floor(height) });
        }
      }
    });
    resizeObserver.observe(el);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // Load candles whenever assetId or timeframe changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    minVolTrackerRef.current.clear();

    fetch(`/api/candles/${assetId}?tf=${timeframe}`)
      .then(res => res.json())
      .then((payload: CandlePayload) => {
        if (cancelled || !payload || !Array.isArray(payload.candles)) return;
        const loaded = payload.candles;
        barsRef.current = loaded;
        setBars(loaded);
        setHoveredBar(null);

        if (candleSeriesRef.current && volumeSeriesRef.current) {
          candleSeriesRef.current.setData(
            loaded.map(b => ({
              time: b.time as UTCTimestamp,
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
            }))
          );
          volumeSeriesRef.current.setData(
            loaded.map(b => ({
              time: b.time as UTCTimestamp,
              value: b.volume,
              color: b.close >= b.open ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
            }))
          );
          chartRef.current?.timeScale().fitContent();
        }

        onStatsRef.current?.({
          current_price: payload.current_price,
          change_24h_pct: payload.change_24h_pct,
          volume_24h: payload.volume_24h,
          open_interest: payload.open_interest,
        });
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load candles:', err);
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [assetId, timeframe]);

  // Apply real-time 1-minute candle delta into active timeframe series
  useEffect(() => {
    if (!liveCandle || liveCandle.asset_id !== assetId) return;
    if (!candleSeriesRef.current || !volumeSeriesRef.current || barsRef.current.length === 0) return;

    const incoming = liveCandle.candle;
    const bucketSec = TF_SECONDS[timeframe];
    const bucketTime = Math.floor(incoming.time / bucketSec) * bucketSec;

    const prevMinuteVol = minVolTrackerRef.current.get(incoming.time) ?? incoming.volume;
    const deltaVol = Math.max(0, incoming.volume - prevMinuteVol);
    minVolTrackerRef.current.set(incoming.time, incoming.volume);

    const list = barsRef.current;
    const last = list[list.length - 1];
    let updated: CandleBar;

    if (bucketTime < last.time) return;

    if (bucketTime === last.time) {
      updated = {
        time: bucketTime,
        open: last.open,
        high: Math.max(last.high, incoming.high),
        low: Math.min(last.low, incoming.low),
        close: incoming.close,
        volume: timeframe === '1M' ? incoming.volume : Math.round((last.volume + deltaVol) * 100) / 100,
      };
      list[list.length - 1] = updated;
    } else {
      updated = {
        time: bucketTime,
        open: last.close,
        high: Math.max(last.close, incoming.high),
        low: Math.min(last.close, incoming.low),
        close: incoming.close,
        volume: incoming.volume,
      };
      list.push(updated);
    }

    setBars([...list]);
    candleSeriesRef.current.update({
      time: updated.time as UTCTimestamp,
      open: updated.open,
      high: updated.high,
      low: updated.low,
      close: updated.close,
    });
    volumeSeriesRef.current.update({
      time: updated.time as UTCTimestamp,
      value: updated.volume,
      color: updated.close >= updated.open ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)',
    });
  }, [liveCandle, assetId, timeframe]);

  const activeBar = hoveredBar ?? (bars.length > 0 ? bars[bars.length - 1] : null);
  const barChangePct =
    activeBar && activeBar.open > 0
      ? ((activeBar.close - activeBar.open) / activeBar.open) * 100
      : 0;

  const contractSlug = slug.toUpperCase();

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0B0E14] border-r border-b border-term-border select-none">
      {/* Top Contract Bar & YES/NO Contract Toggle */}
      <div className="px-3 py-1.5 border-b border-term-border bg-[#0E121A] flex flex-wrap items-center justify-between gap-2 shrink-0">
        <div className="flex items-center space-x-2 min-w-0">
          <span className="w-2 h-2 rounded-full bg-sky-400 shrink-0"></span>
          <span className="text-[11px] font-mono text-slate-300 font-semibold truncate">
            POLYMARKET:{contractSlug}
            {isMultiCandidate && candidateName ? `:${candidateName.toUpperCase().replace(/\s+/g, '-')}` : ''}
          </span>
          <div className="flex items-center space-x-1 ml-1 shrink-0">
            <button
              onClick={() => onSelectContract(yesAssetId)}
              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors ${
                outcomeLabel === 'YES'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'bg-[#141A24] text-slate-400 border border-term-border hover:text-white'
              }`}
            >
              YES Contract
            </button>
            <button
              onClick={() => onSelectContract(noAssetId)}
              className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors ${
                outcomeLabel === 'NO'
                  ? 'bg-red-600 text-white shadow-xs'
                  : 'bg-[#141A24] text-slate-400 border border-term-border hover:text-white'
              }`}
            >
              NO Contract
            </button>
          </div>
        </div>

        {/* Timeframe Controls */}
        <div className="flex items-center space-x-1 shrink-0">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold transition-colors ${
                timeframe === tf
                  ? 'bg-sky-600 text-white'
                  : 'bg-[#141A24] text-slate-400 border border-term-border hover:text-white'
              }`}
            >
              {tf}
            </button>
          ))}
          <button
            onClick={() => chartRef.current?.timeScale().fitContent()}
            className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#141A24] text-slate-400 border border-term-border hover:text-white"
            title="Fit chart content"
          >
            Fit
          </button>
          <button
            onClick={onToggleExpand}
            className="p-1 rounded text-slate-400 bg-[#141A24] border border-term-border hover:text-white"
            title={isExpanded ? 'Restore split layout' : 'Expand chart height'}
          >
            {isExpanded ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* OHLCV Live Readout Bar */}
      <div className="px-3 py-1 border-b border-term-border/60 bg-[#0B0E14] flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] font-mono shrink-0">
        {activeBar ? (
          <>
            <span className="text-slate-500">
              O: <b className="text-slate-200">${activeBar.open.toFixed(3)}</b>
            </span>
            <span className="text-slate-500">
              H: <b className="text-emerald-400">${activeBar.high.toFixed(3)}</b>
            </span>
            <span className="text-slate-500">
              L: <b className="text-red-400">${activeBar.low.toFixed(3)}</b>
            </span>
            <span className="text-slate-500">
              C: <b className={activeBar.close >= activeBar.open ? 'text-emerald-400' : 'text-red-400'}>${activeBar.close.toFixed(3)}</b>
            </span>
            <span className="text-slate-500">
              CHG:{' '}
              <b className={barChangePct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {barChangePct >= 0 ? '+' : ''}
                {barChangePct.toFixed(2)}%
              </b>
            </span>
            <span className="text-slate-500">
              VOL: <b className="text-sky-400">{formatCompactUsd(activeBar.volume)}</b>
            </span>
          </>
        ) : (
          <span className="text-slate-500">Loading OHLCV series...</span>
        )}
      </div>

      {/* Lightweight Charts Canvas */}
      <div className="relative flex-1 min-h-0 w-full">
        <div ref={containerRef} className="w-full h-full" />
        {loading && (
          <div className="absolute inset-0 bg-[#0B0E14]/60 flex items-center justify-center text-xs text-slate-400 font-mono">
            Loading {timeframe} candlesticks...
          </div>
        )}
      </div>
    </div>
  );
};

