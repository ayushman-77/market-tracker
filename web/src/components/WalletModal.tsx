import { useEffect, useState, type FC } from 'react';
import { X } from 'lucide-react';
import { WalletDrilldown } from '../types';

interface WalletModalProps {
  wallet: string | null;
  onClose: () => void;
}

export const WalletModal: FC<WalletModalProps> = ({ wallet, onClose }) => {
  const [data, setData] = useState<WalletDrilldown | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!wallet) return;
    setLoading(true);
    fetch(`/api/wallets/${wallet}`)
      .then(res => res.json())
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load wallet drilldown:', err);
        setLoading(false);
      });
  }, [wallet]);

  if (!wallet) return null;

  // Render SVG Sparkline / PnL Curve
  const renderPnlChart = (points: Array<{ timestamp: number; pnl: number }>) => {
    if (!points || points.length < 2) {
      return (
        <div className="h-28 flex items-center justify-center text-slate-600 text-xs">
          Accumulating PnL history...
        </div>
      );
    }

    const pnls = points.map(p => p.pnl);
    const minPnl = Math.min(...pnls, 0);
    const maxPnl = Math.max(...pnls, 1);
    const range = maxPnl - minPnl || 1;

    const width = 450;
    const height = 110;
    const padding = 10;

    const coords = points.map((p, idx) => {
      const x = padding + (idx / (points.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((p.pnl - minPnl) / range) * (height - 2 * padding);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const isProfitable = points[points.length - 1].pnl >= 0;
    const strokeColor = isProfitable ? '#10B981' : '#EF4444';
    const fillColor = isProfitable ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)';

    const pathData = `M ${coords.join(' L ')}`;
    const areaData = `M ${coords[0]} L ${coords.join(' L ')} L ${width - padding},${height} L ${padding},${height} Z`;

    return (
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-28 overflow-visible">
        <path d={areaData} fill={fillColor} />
        <path d={pathData} fill="none" stroke={strokeColor} strokeWidth="2" strokeLinecap="round" />
        {/* Baseline 0 */}
        <line
          x1={padding}
          y1={height - padding - ((0 - minPnl) / range) * (height - 2 * padding)}
          x2={width - padding}
          y2={height - padding - ((0 - minPnl) / range) * (height - 2 * padding)}
          stroke="#334155"
          strokeDasharray="3,3"
          strokeWidth="1"
        />
      </svg>
    );
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-[#11151F] border border-term-border rounded-lg shadow-2xl w-full max-w-xl overflow-hidden font-mono flex flex-col max-h-[90vh]">
        {/* Modal Header */}
        <div className="p-3 bg-[#0B0E14] border-b border-term-border flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold text-slate-400">WALLET DRILLDOWN:</span>
            <span className="text-xs text-sky-400 font-bold">{wallet}</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white hover:bg-term-card rounded transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        {loading || !data ? (
          <div className="p-8 text-center text-slate-500 text-xs">
            Querying PnL registers...
          </div>
        ) : (
          <div className="p-4 overflow-y-auto space-y-4 text-xs">
            {/* PnL Statistics Overview */}
            <div className="grid grid-cols-4 gap-2 text-center">
              <div className="bg-[#141A24] p-2 rounded border border-term-border">
                <div className="text-[10px] text-slate-500 uppercase">Total PnL</div>
                <div className={`text-sm font-bold ${data.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {data.total_pnl >= 0 ? '+' : ''}${data.total_pnl.toFixed(2)}
                </div>
              </div>
              <div className="bg-[#141A24] p-2 rounded border border-term-border">
                <div className="text-[10px] text-slate-500 uppercase">Realized PnL</div>
                <div className="text-sm font-semibold text-slate-300">
                  ${data.realized_pnl.toFixed(2)}
                </div>
              </div>
              <div className="bg-[#141A24] p-2 rounded border border-term-border">
                <div className="text-[10px] text-slate-500 uppercase">Unrealized</div>
                <div className="text-sm font-semibold text-slate-300">
                  ${data.unrealized_pnl.toFixed(2)}
                </div>
              </div>
              <div className="bg-[#141A24] p-2 rounded border border-term-border">
                <div className="text-[10px] text-slate-500 uppercase">Fees Deducted</div>
                <div className="text-sm font-semibold text-slate-400">
                  ${data.total_fees.toFixed(2)}
                </div>
              </div>
            </div>

            {/* PnL Historical Equity Curve */}
            <div className="bg-[#141A24] p-3 rounded border border-term-border">
              <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1 flex justify-between">
                <span>PnL Trajectory (Mark-to-Market)</span>
                <span className="text-[10px] text-slate-500">Prediction Market Accounting</span>
              </div>
              {renderPnlChart(data.pnl_history)}
            </div>

            {/* Open Positions Table */}
            <div>
              <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                Open Token Positions
              </div>
              <div className="border border-term-border rounded overflow-hidden divide-y divide-term-border/50">
                <div className="grid grid-cols-4 px-2 py-1 bg-[#0B0E14] text-[10px] text-slate-500 font-semibold uppercase">
                  <div>Outcome Token</div>
                  <div className="text-right">Size</div>
                  <div className="text-right">Cost Basis</div>
                  <div className="text-right">Unrealized</div>
                </div>
                {data.positions.map(p => (
                  <div key={p.asset_id} className="grid grid-cols-4 px-2 py-1.5 items-center hover:bg-term-hover">
                    <div className="text-slate-200 font-semibold truncate">{p.asset_id}</div>
                    <div className="text-right text-slate-300">{p.size.toFixed(1)}</div>
                    <div className="text-right text-slate-400">${p.cost_basis.toFixed(3)}</div>
                    <div className={`text-right font-semibold ${p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {p.unrealized_pnl >= 0 ? '+' : ''}${p.unrealized_pnl.toFixed(2)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Wallet Trade History */}
            <div>
              <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                Recent Fills
              </div>
              <div className="border border-term-border rounded overflow-hidden divide-y divide-term-border/40 max-h-36 overflow-y-auto">
                {data.recent_trades.length === 0 ? (
                  <div className="p-3 text-center text-slate-600 text-xs">No recent trades found</div>
                ) : (
                  data.recent_trades.map(t => (
                    <div key={t.event_id} className="flex justify-between items-center px-2 py-1 text-[11px] hover:bg-term-hover">
                      <div className="flex items-center space-x-1.5">
                        <span className={`px-1 py-0.2 rounded font-bold text-[9px] ${
                          t.side === 'BUY' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
                        }`}>
                          {t.side}
                        </span>
                        <span className="text-slate-300">{t.size} @ ${t.price.toFixed(3)}</span>
                      </div>
                      <span className="text-slate-500 text-[10px]">
                        {new Date(t.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {/* Modal Footer */}
        <div className="p-2 px-4 bg-[#0B0E14] border-t border-term-border text-[10px] text-slate-500 flex items-center">
          <span>Press <kbd className="px-1 py-0.5 bg-term-card border border-term-border rounded text-slate-400">Esc</kbd> to return</span>
        </div>
      </div>
    </div>
  );
};
