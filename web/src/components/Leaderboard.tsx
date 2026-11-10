import { useEffect, useRef, useState, type FC, type RefObject } from 'react';
import { Search, Trophy } from 'lucide-react';
import { LeaderboardEntry } from '../types';

interface LeaderboardProps {
  entries: LeaderboardEntry[];
  selectedIndex: number;
  onSelectIndex: (idx: number) => void;
  onOpenWallet: (wallet: string) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  searchInputRef: RefObject<HTMLInputElement>;
}

export const Leaderboard: FC<LeaderboardProps> = ({
  entries,
  selectedIndex,
  onSelectIndex,
  onOpenWallet,
  searchQuery,
  onSearchChange,
  searchInputRef,
}) => {
  const prevPnlRef = useRef<Record<string, number>>({});
  const [flashStates, setFlashStates] = useState<Record<string, 'up' | 'down'>>({});

  // Detect PnL change per wallet to trigger green/red flash
  useEffect(() => {
    const list = entries || [];
    const newFlashes: Record<string, 'up' | 'down'> = {};
    for (const e of list) {
      const prev = prevPnlRef.current[e.wallet];
      if (prev !== undefined && Math.abs(e.total_pnl - prev) >= 0.25) {
        newFlashes[e.wallet] = e.total_pnl > prev ? 'up' : 'down';
      }
      prevPnlRef.current[e.wallet] = e.total_pnl;
    }

    if (Object.keys(newFlashes).length > 0) {
      setFlashStates(newFlashes);
      const timer = setTimeout(() => setFlashStates({}), 600);
      return () => clearTimeout(timer);
    }
  }, [entries]);

  const filteredEntries = (entries || []).filter(e =>
    e.wallet.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0E121A] border-r border-term-border">
      {/* Panel Header & Search */}
      <div className="p-2 border-b border-term-border flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-start space-x-1.5 min-w-0">
          <Trophy className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
          <div className="flex flex-col leading-tight min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-slate-300 whitespace-nowrap">TOP TRADERS</span>
              <span className="text-[10px] text-slate-500 font-normal whitespace-nowrap">[{entries.length} active]</span>
            </div>
            <span className="text-[10px] text-slate-400 font-medium whitespace-nowrap">(HOT SoA LEADERBOARD)</span>
          </div>
        </div>

        {/* Search input with shortcut hint */}
        <div className="relative w-40 lg:w-44 shrink-0">
          <Search className="w-3 h-3 absolute left-2 top-2 text-slate-500" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search wallet ( / )"
            className="w-full bg-[#141A24] border border-term-border rounded text-[11px] pl-6 pr-6 py-1 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 font-mono"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-2 top-1 text-slate-500 hover:text-white text-xs"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Table Header */}
      <div className="grid grid-cols-12 px-2 py-1 text-[10px] font-semibold text-slate-500 border-b border-term-border bg-[#0B0E14] uppercase tracking-wider shrink-0">
        <div className="col-span-1 text-center">#</div>
        <div className="col-span-4">Wallet</div>
        <div className="col-span-3 text-right">Total PnL</div>
        <div className="col-span-2 text-right">Realized</div>
        <div className="col-span-2 text-right">Fees</div>
      </div>

      {/* Scrollable Virtualized/Dense Rows */}
      <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-term-border/40 text-xs">
        {filteredEntries.length === 0 ? (
          <div className="p-4 text-center text-slate-600 text-xs">No wallets match query</div>
        ) : (
          filteredEntries.map((e, idx) => {
            const isSelected = idx === selectedIndex;
            const flash = flashStates[e.wallet];
            const pnlColor = e.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400';

            return (
              <div
                key={e.wallet}
                onClick={() => {
                  onSelectIndex(idx);
                  onOpenWallet(e.wallet);
                }}
                className={`grid grid-cols-12 px-2 py-1.5 cursor-pointer transition-colors items-center font-mono select-none ${
                  isSelected ? 'bg-sky-950/40 border-l-2 border-sky-400 text-white' : 'hover:bg-term-hover text-slate-300'
                }`}
              >
                <div className="col-span-1 text-center text-[11px] font-bold text-slate-500">
                  {e.rank}
                </div>
                <div className="col-span-4 flex items-center space-x-1 overflow-hidden">
                  <span className="truncate text-slate-200 hover:text-sky-400">
                    {e.wallet.slice(0, 6)}...{e.wallet.slice(-4)}
                  </span>
                </div>
                <div className={`col-span-3 text-right font-semibold rounded px-1 transition-all duration-300 ${pnlColor} ${
                  flash === 'up'
                    ? 'bg-emerald-900/60 text-emerald-200 ring-1 ring-emerald-500/50'
                    : flash === 'down'
                    ? 'bg-red-900/60 text-red-200 ring-1 ring-red-500/50'
                    : ''
                }`}>
                  {e.total_pnl >= 0 ? '+' : ''}${e.total_pnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="col-span-2 text-right text-slate-400 text-[11px]">
                  ${e.realized_pnl.toFixed(2)}
                </div>
                <div className="col-span-2 text-right text-slate-500 text-[11px]">
                  ${e.fees_paid.toFixed(2)}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Quick Nav Footer */}
      <div className="p-1 px-2 border-t border-term-border bg-[#0B0E14] text-[10px] text-slate-500 flex justify-between items-center shrink-0">
        <span>Navigate: <kbd className="px-1 py-0.5 bg-term-card border border-term-border rounded text-slate-400">j</kbd> / <kbd className="px-1 py-0.5 bg-term-card border border-term-border rounded text-slate-400">k</kbd></span>
        <span>Open: <kbd className="px-1 py-0.5 bg-term-card border border-term-border rounded text-slate-400">Enter</kbd></span>
      </div>
    </div>
  );
};
