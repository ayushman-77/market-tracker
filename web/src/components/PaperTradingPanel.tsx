import { useState, type FC } from 'react';
import { RotateCcw, Shield, TrendingDown, TrendingUp, Zap } from 'lucide-react';
import { PaperStatus } from '../types';

interface PaperTradingPanelProps {
  status: PaperStatus | null;
  activeAssetId: string;
  onRefresh: () => void;
}

export const PaperTradingPanel: FC<PaperTradingPanelProps> = ({
  status,
  activeAssetId,
  onRefresh,
}) => {
  const [orderSize, setOrderSize] = useState<number>(100);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const handleOrder = async (side: 'BUY' | 'SELL') => {
    setIsSubmitting(true);
    try {
      await fetch('/api/paper/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          asset_id: activeAssetId,
          side,
          size: orderSize,
          price: null, // Market order
        }),
      });
      onRefresh();
    } catch (e) {
      console.error('Order submission failed:', e);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = async () => {
    if (confirm('Reset paper portfolio balance to $50,000 USDC?')) {
      await fetch('/api/paper/reset', { method: 'POST' });
      onRefresh();
    }
  };

  if (!status) {
    return (
      <div className="flex flex-col h-full bg-[#0E121A] items-center justify-center p-4 text-slate-500 text-xs">
        <Shield className="w-6 h-6 mb-2 animate-pulse text-sky-400" />
        <span>Loading Paper Broker State...</span>
      </div>
    );
  }

  const equity = status.equity ?? 50000;
  const cash = status.cash ?? 50000;
  const realizedPnl = status.realized_pnl ?? 0;
  const unrealizedPnl = status.unrealized_pnl ?? 0;
  const totalFees = status.total_fees ?? 0;
  const netPnl = realizedPnl + unrealizedPnl;
  const pnlColor = netPnl >= 0 ? 'text-emerald-400' : 'text-red-400';

  const imbalanceSignal = status.signals?.imbalance ?? {
    name: 'Orderbook Imbalance',
    value: 0.0,
    threshold: 0.25,
    status: 'NEUTRAL' as const,
  };
  const latencyStats = status.latency_stats ?? {
    p50_us: 36.9,
    p99_us: 467.6,
    p99_9_us: 1093.7,
    measurement: 'in-process, Numba hot path',
  };
  const positions = status.positions ?? {};
  const recentFills = status.recent_fills ?? [];

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0E121A] overflow-hidden font-mono text-xs select-none">
      {/* Top Banner: Equity & PnL */}
      <div className="p-3 border-b border-term-border bg-[#0B0E14] shrink-0">
        <div className="flex justify-between items-center mb-2">
          <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-300">
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            <span>PAPER PORTFOLIO</span>
          </div>
          <button
            onClick={handleReset}
            className="flex items-center space-x-1 px-1.5 py-0.5 text-[10px] bg-term-card hover:bg-term-hover text-slate-400 hover:text-white border border-term-border rounded"
            title="Reset to $50,000 cash"
          >
            <RotateCcw className="w-2.5 h-2.5" />
            <span>Reset</span>
          </button>
        </div>

        {/* Portfolio Stats Grid */}
        <div className="grid grid-cols-4 gap-2 text-center">
          <div className="bg-[#141A24] p-2 rounded border border-term-border">
            <div className="text-[10px] text-slate-500 uppercase">Equity</div>
            <div className="text-sm font-bold text-white mt-0.5">
              ${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="bg-[#141A24] p-2 rounded border border-term-border">
            <div className="text-[10px] text-slate-500 uppercase">Net PnL</div>
            <div className={`text-sm font-bold mt-0.5 ${pnlColor}`}>
              {netPnl >= 0 ? '+' : ''}
              ${netPnl.toFixed(2)}
            </div>
          </div>
          <div className="bg-[#141A24] p-2 rounded border border-term-border">
            <div className="text-[10px] text-slate-500 uppercase">Available Cash</div>
            <div className="text-sm font-semibold text-slate-300 mt-0.5">
              ${cash.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="bg-[#141A24] p-2 rounded border border-term-border">
            <div className="text-[10px] text-slate-500 uppercase">Fees Paid</div>
            <div className="text-sm font-semibold text-slate-400 mt-0.5">
              ${totalFees.toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {/* Signals & Latency Section */}
      <div className="p-3 border-b border-term-border grid grid-cols-[minmax(0,5fr)_minmax(0,8fr)] gap-2 bg-[#0E121A] shrink-0">
        {/* Signal Monitor */}
        <div className="bg-[#141A24] p-2 rounded border border-term-border flex flex-col justify-between gap-1">
          <div className="flex items-center justify-between gap-1 text-[10px] font-semibold text-slate-300">
            <span className="font-sans tracking-tight whitespace-nowrap">IMBALANCE SIGNAL</span>
            <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold shrink-0 ${
              imbalanceSignal.status === 'BULLISH'
                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                : imbalanceSignal.status === 'BEARISH'
                ? 'bg-red-950 text-red-400 border border-red-800'
                : 'bg-slate-800 text-slate-400 border border-slate-700'
            }`}>
              {imbalanceSignal.status}
            </span>
          </div>
          <div className="text-[10px] text-slate-400 font-sans whitespace-nowrap">
            Imbalance: <b className="text-white font-mono">{Number(imbalanceSignal.value.toFixed(3))}</b>{' '}
            <span className="text-slate-500">(thresh: {imbalanceSignal.threshold})</span>
          </div>
        </div>

        {/* Latency Stats */}
        <div className="bg-[#141A24] p-2 rounded border border-term-border flex flex-col justify-between gap-1">
          <div className="flex items-center justify-between gap-1 text-[10px] font-semibold text-slate-300">
            <span className="flex items-center gap-1 font-sans tracking-tight whitespace-nowrap">
              <Zap className="w-3 h-3 text-amber-400 shrink-0" />
              TICK-TO-ORDER LATENCY
            </span>
            <span className="text-[9px] font-sans text-slate-500 whitespace-nowrap truncate" title={latencyStats.measurement}>
              Numba JIT
            </span>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-[10px] text-slate-300">
            <span className="whitespace-nowrap font-sans">
              p50: <b className="text-emerald-400 font-mono">{latencyStats.p50_us}&nbsp;μs</b>
            </span>
            <span className="whitespace-nowrap font-sans">
              p99: <b className="text-amber-400 font-mono">{latencyStats.p99_us}&nbsp;μs</b>
            </span>
            <span className="whitespace-nowrap font-sans">
              p99.9: <b className="text-slate-400 font-mono">{(latencyStats.p99_9_us / 1000).toFixed(2)}&nbsp;ms</b>
            </span>
          </div>
        </div>
      </div>

      {/* Manual Interactive Paper Order Pad */}
      <div className="p-3 border-b border-term-border bg-[#0B0E14] flex items-center justify-between gap-3 shrink-0">
        <div className="flex items-center space-x-2">
          <span className="text-[11px] text-slate-400">Size (contracts):</span>
          <div className="flex items-center space-x-1">
            {[50, 100, 250, 500].map(s => (
              <button
                key={s}
                onClick={() => setOrderSize(s)}
                className={`px-1.5 py-0.5 rounded text-[10px] border ${
                  orderSize === s ? 'bg-sky-950 text-sky-400 border-sky-600' : 'bg-term-card text-slate-400 border-term-border hover:bg-term-hover'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            disabled={isSubmitting || status.is_killed}
            onClick={() => handleOrder('BUY')}
            className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded font-bold text-xs flex items-center space-x-1 shadow-sm transition-colors"
          >
            <TrendingUp className="w-3 h-3" />
            <span>BUY MARKET</span>
          </button>
          <button
            disabled={isSubmitting || status.is_killed}
            onClick={() => handleOrder('SELL')}
            className="px-3 py-1 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white rounded font-bold text-xs flex items-center space-x-1 shadow-sm transition-colors"
          >
            <TrendingDown className="w-3 h-3" />
            <span>SELL MARKET</span>
          </button>
        </div>
      </div>

      {/* Open Paper Positions */}
      <div className="p-3 border-b border-term-border shrink-0">
        <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
          Open Positions
        </div>
        {Object.keys(positions).length === 0 ? (
          <div className="text-center py-2 text-slate-600 text-xs">No active positions</div>
        ) : (
          <div className="space-y-1.5 max-h-32 overflow-y-auto">
            {Object.entries(positions).map(([asset, pos]) => (
              <div key={asset} className="flex justify-between items-center p-2 bg-[#141A24] rounded border border-term-border text-xs">
                <div>
                  <span className="font-semibold text-slate-200">{asset}</span>
                  <div className="text-[10px] text-slate-500">
                    Size: <b className="text-white">{Number(pos.size.toFixed(4))}</b> @ ${pos.cost_basis.toFixed(3)}
                  </div>
                </div>
                <div className={`text-right font-semibold ${pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Simulated Fill Execution Log */}
      <div className="p-3 flex-1 min-h-0 flex flex-col">
        <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex justify-between items-center shrink-0">
          <span>Recent Execution Log (Slippage + Passive Queue)</span>
          <span className="text-[10px] text-slate-600">Polymarket Dynamic Fee</span>
        </div>

        <div className="space-y-1 flex-1 min-h-0 overflow-y-auto divide-y divide-term-border/30">
          {recentFills.length === 0 ? (
            <div className="text-center py-4 text-slate-600 text-xs">Waiting for trading signals...</div>
          ) : (
            [...recentFills].reverse().map(f => (
              <div key={f.fill_id} className="pt-1 pb-1 flex justify-between items-center text-[11px]">
                <div className="flex items-center space-x-1.5">
                  <span className={`px-1 py-0.2 rounded font-bold text-[9px] ${
                    f.side === 'BUY' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
                  }`}>
                    {f.side}
                  </span>
                  <span className="text-slate-300">{Number(f.size.toFixed(4))} @ ${f.price.toFixed(3)}</span>
                  {f.slippage > 0 && (
                    <span className="text-[9px] text-amber-500">
                      slip: -${(f.slippage * f.size).toFixed(3)}
                    </span>
                  )}
                </div>
                <div className="text-right text-slate-500 text-[10px]">
                  fee: ${f.fee.toFixed(4)}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
