import type { FC } from 'react';
import { Activity, BarChart3, Globe2, HelpCircle, RefreshCw, Zap } from 'lucide-react';
import { ConnectionState, Market } from '../types';

interface HeaderProps {
  markets: Market[];
  activeAssetId: string;
  viewMode: 'markets' | 'terminal';
  onChangeView: (view: 'markets' | 'terminal') => void;
  onSelectMarket: (id: string) => void;
  connectionStatus: ConnectionState;
  rttMs: number | null;
  gapCount: number;
  onResync: () => void;
  onOpenHelp: () => void;
}

export const Header: FC<HeaderProps> = ({
  markets,
  activeAssetId,
  viewMode,
  onChangeView,
  onSelectMarket,
  connectionStatus,
  rttMs,
  gapCount,
  onResync,
  onOpenHelp,
}) => {
  return (
    <header className="h-12 border-b border-term-border bg-[#0E121A] px-3 flex items-center justify-between gap-2 select-none shrink-0">
      {/* Brand, View Switcher & Quick Market Switcher */}
      <div className="flex items-center space-x-2.5 min-w-0">
        <div
          onClick={() => onChangeView('markets')}
          className="flex items-center space-x-1.5 cursor-pointer shrink-0"
        >
          <div className="w-2.5 h-2.5 bg-sky-400 rounded-sm animate-pulse"></div>
          <span className="font-bold tracking-wider text-white text-sm">MARKETTRACKER</span>
          <span className="hidden sm:inline text-[10px] bg-sky-950 text-sky-400 border border-sky-800 px-1.5 py-0.2 rounded font-semibold">
            POLYMARKET L2
          </span>
        </div>

        <div className="h-4 w-px bg-term-border shrink-0"></div>

        {/* Navigation Switcher */}
        <div className="flex items-center bg-[#0B0E14] border border-term-border rounded p-0.5 text-[11px] shrink-0">
          <button
            onClick={() => onChangeView('markets')}
            className={`px-2 py-0.5 rounded flex items-center space-x-1 transition-colors cursor-pointer ${
              viewMode === 'markets'
                ? 'bg-sky-600 text-white font-semibold'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Globe2 className="w-3 h-3" />
            <span>Markets</span>
          </button>
          <button
            onClick={() => onChangeView('terminal')}
            className={`px-2 py-0.5 rounded flex items-center space-x-1 transition-colors cursor-pointer ${
              viewMode === 'terminal'
                ? 'bg-sky-600 text-white font-semibold'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <BarChart3 className="w-3 h-3" />
            <span>Chart Terminal</span>
          </button>
        </div>

        {/* Quick Market Switcher */}
        <select
          value={activeAssetId}
          onChange={(e) => {
            onSelectMarket(e.target.value);
            onChangeView('terminal');
          }}
          className="hidden xl:block max-w-[270px] truncate bg-term-card border border-term-border text-xs text-sky-300 font-medium px-2 py-1 rounded focus:outline-none focus:border-sky-500 cursor-pointer"
        >
          {markets.map(m => (
            <option key={m.asset_id} value={m.asset_id}>
              {m.category ? `[${m.category}] ` : ''}{m.question} [{m.outcome_label}]
            </option>
          ))}
        </select>
      </div>

      {/* Engine Stats Pills */}
      <div className="hidden lg:flex items-center space-x-2 text-xs shrink-0">
        <div className="flex items-center space-x-1.5 px-2 py-0.5 bg-term-card border border-term-border rounded text-slate-300">
          <Zap className="w-3 h-3 text-amber-400" />
          <span className="text-slate-500">In-Process Decision:</span>
          <span className="font-semibold text-emerald-400">36.9 μs</span>
          <span className="text-[10px] text-slate-500">(p50)</span>
        </div>

        <div className="flex items-center space-x-1.5 px-2 py-0.5 bg-term-card border border-term-border rounded text-slate-300">
          <Activity className="w-3 h-3 text-sky-400" />
          <span className="text-slate-500">Ingest:</span>
          <span className="font-semibold text-sky-300">200k rows/s</span>
        </div>
      </div>

      {/* Connection & Shortcuts */}
      <div className="flex items-center space-x-2 shrink-0">
        <div
          onClick={onResync}
          title="Click to force resync snapshots"
          className={`flex items-center space-x-1.5 px-2 py-0.5 rounded text-xs border cursor-pointer transition-colors ${
            connectionStatus === 'connected'
              ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/80 hover:bg-emerald-900/50'
              : connectionStatus === 'resyncing'
              ? 'bg-amber-950/40 text-amber-400 border-amber-800/80 animate-pulse'
              : 'bg-red-950/40 text-red-400 border-red-800/80'
          }`}
        >
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              connectionStatus === 'connected'
                ? 'bg-emerald-400 shadow-[0_0_8px_#10B981]'
                : connectionStatus === 'resyncing'
                ? 'bg-amber-400'
                : 'bg-red-400'
            }`}
          ></div>
          <span className="uppercase font-semibold tracking-wider text-[11px]">
            {connectionStatus}
          </span>
          {rttMs !== null && connectionStatus === 'connected' && (
            <span className="text-[10px] text-emerald-500/80">({rttMs}ms)</span>
          )}
          {gapCount > 0 && (
            <span className="text-[10px] text-amber-400/90 ml-1">[{gapCount} gaps recovered]</span>
          )}
          <RefreshCw className="w-2.5 h-2.5 ml-0.5 opacity-60 hover:opacity-100" />
        </div>

        <button
          onClick={onOpenHelp}
          className="p-1 text-slate-400 hover:text-white hover:bg-term-card rounded transition-colors cursor-pointer"
          title="Keyboard shortcuts (?)"
        >
          <HelpCircle className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};
