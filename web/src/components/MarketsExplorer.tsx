import { useMemo, useState, type FC, type RefObject } from 'react';
import { BarChart3, Flame, Globe2, Search, Sparkles, TrendingUp, Trophy, Users } from 'lucide-react';
import { EventCandidate, EventMarket } from '../types';

interface MarketsExplorerProps {
  events: EventMarket[];
  categories: string[];
  traderCount: number;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  searchInputRef: RefObject<HTMLInputElement>;
  onSelectQuestion: (event: EventMarket, candidate?: EventCandidate, side?: 'YES' | 'NO') => void;
  onOpenTerminal: () => void;
}

const CATEGORY_BADGE_STYLES: Record<string, string> = {
  Crypto: 'bg-amber-950/70 text-amber-300 border-amber-800/80',
  Politics: 'bg-sky-950/70 text-sky-300 border-sky-800/80',
  Sports: 'bg-emerald-950/70 text-emerald-300 border-emerald-800/80',
  Geography: 'bg-teal-950/70 text-teal-300 border-teal-800/80',
  'Economy & Tech': 'bg-violet-950/70 text-violet-300 border-violet-800/80',
};

function formatCompactUsd(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

export const MarketsExplorer: FC<MarketsExplorerProps> = ({
  events,
  categories,
  traderCount,
  searchQuery,
  onSearchChange,
  searchInputRef,
  onSelectQuestion,
  onOpenTerminal,
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [typeFilter, setTypeFilter] = useState<'all' | 'multi' | 'binary'>('all');
  const [sortBy, setSortBy] = useState<'volume' | 'change'>('volume');

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { All: events.length };
    for (const c of categories) counts[c] = 0;
    for (const ev of events) {
      counts[ev.category] = (counts[ev.category] ?? 0) + 1;
    }
    return counts;
  }, [events, categories]);

  const filteredEvents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return events
      .filter(ev => {
        if (selectedCategory !== 'All' && ev.category !== selectedCategory) return false;
        if (typeFilter === 'multi' && !ev.is_multi_candidate) return false;
        if (typeFilter === 'binary' && ev.is_multi_candidate) return false;
        if (!q) return true;
        return (
          ev.question.toLowerCase().includes(q) ||
          ev.category.toLowerCase().includes(q) ||
          ev.candidates.some(c => c.name.toLowerCase().includes(q))
        );
      })
      .sort((a, b) => {
        if (sortBy === 'change') {
          return Math.abs(b.change_24h_pct) - Math.abs(a.change_24h_pct);
        }
        return b.volume_24h - a.volume_24h;
      });
  }, [events, selectedCategory, typeFilter, sortBy, searchQuery]);

  const totalVolume = useMemo(
    () => events.reduce((acc, ev) => acc + ev.volume_24h, 0),
    [events]
  );

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0B0E14] overflow-hidden">
      {/* Top Hero / Filter Bar */}
      <div className="px-4 py-3 border-b border-term-border bg-[#0E121A] shrink-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center flex-wrap gap-3">
            <div className="flex items-center space-x-2">
              <Globe2 className="w-4 h-4 text-sky-400" />
              <h1 className="text-sm font-bold tracking-wide text-white uppercase">
                Prediction Markets Catalog
              </h1>
            </div>
            <div className="flex items-center space-x-2 text-[11px] font-mono text-slate-400">
              <span className="px-2 py-0.5 rounded bg-[#141A24] border border-term-border text-sky-300">
                {events.length} Questions
              </span>
              <span className="px-2 py-0.5 rounded bg-[#141A24] border border-term-border text-emerald-300">
                {categories.length} Domains
              </span>
              <span className="px-2 py-0.5 rounded bg-[#141A24] border border-term-border text-amber-300 flex items-center space-x-1">
                <Users className="w-3 h-3" />
                <span>{traderCount} Active Traders</span>
              </span>
              <span className="hidden sm:inline px-2 py-0.5 rounded bg-[#141A24] border border-term-border text-slate-300">
                24h Vol: {formatCompactUsd(totalVolume)}
              </span>
            </div>
          </div>

          <button
            onClick={onOpenTerminal}
            className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold flex items-center space-x-1.5 transition-colors cursor-pointer"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Open Active Chart & Terminal</span>
          </button>
        </div>

        {/* Domain Tabs + Search + Filters */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center flex-wrap gap-1.5">
            {['All', ...categories].map(cat => {
              const active = selectedCategory === cat;
              return (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors cursor-pointer ${
                    active
                      ? 'bg-sky-950 text-sky-300 border-sky-600 font-semibold'
                      : 'bg-[#141A24] text-slate-400 border-term-border hover:text-white hover:bg-term-hover'
                  }`}
                >
                  {cat}{' '}
                  <span className="text-[10px] opacity-75 font-mono">
                    ({categoryCounts[cat] ?? 0})
                  </span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center flex-wrap gap-2">
            {/* Search input */}
            <div className="relative w-56 sm:w-64">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2 text-slate-500" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={e => onSearchChange(e.target.value)}
                placeholder="Search questions or candidates ( / )"
                className="w-full bg-[#141A24] border border-term-border rounded text-xs pl-8 pr-6 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500 font-mono"
              />
              {searchQuery && (
                <button
                  onClick={() => onSearchChange('')}
                  className="absolute right-2 top-1 text-slate-500 hover:text-white text-sm"
                >
                  ×
                </button>
              )}
            </div>

            {/* Type filter */}
            <div className="flex items-center bg-[#141A24] border border-term-border rounded p-0.5 text-[11px]">
              {(['all', 'multi', 'binary'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTypeFilter(t)}
                  className={`px-2 py-0.5 rounded capitalize cursor-pointer ${
                    typeFilter === t ? 'bg-slate-700 text-white font-semibold' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {t === 'multi' ? 'Multi-Candidate' : t}
                </button>
              ))}
            </div>

            {/* Sort */}
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value as 'volume' | 'change')}
              className="bg-[#141A24] border border-term-border rounded px-2 py-1 text-[11px] text-slate-300 focus:outline-none focus:border-sky-500 cursor-pointer"
            >
              <option value="volume">Sort: 24h Volume</option>
              <option value="change">Sort: Biggest Movers</option>
            </select>
          </div>
        </div>
      </div>

      {/* Questions Grid */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {filteredEvents.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs">
            <span>No questions match your search criteria.</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filteredEvents.map(ev => {
              const badgeClass =
                CATEGORY_BADGE_STYLES[ev.category] ||
                'bg-slate-800 text-slate-300 border-slate-700';
              const lead = ev.candidates[0];
              const chgColor =
                ev.change_24h_pct >= 0 ? 'text-emerald-400' : 'text-red-400';

              return (
                <div
                  key={ev.event_id}
                  onClick={() => onSelectQuestion(ev, lead, 'YES')}
                  className="bg-[#0E121A] hover:bg-[#121824] border border-term-border hover:border-sky-600/70 rounded-lg p-3.5 flex flex-col justify-between gap-3 cursor-pointer transition-all group"
                >
                  {/* Card Meta Header */}
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center space-x-1.5">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${badgeClass}`}
                        >
                          {ev.category}
                        </span>
                        {ev.is_multi_candidate && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800/80 text-slate-300 border border-slate-700 flex items-center space-x-1">
                            <Sparkles className="w-2.5 h-2.5 text-amber-400" />
                            <span>{ev.candidates.length} Options</span>
                          </span>
                        )}
                      </div>

                      <div className="flex items-center space-x-2 text-[11px] font-mono">
                        <span className="text-slate-400">{formatCompactUsd(ev.volume_24h)} Vol</span>
                        <span className={`font-semibold ${chgColor}`}>
                          {ev.change_24h_pct >= 0 ? '+' : ''}
                          {ev.change_24h_pct.toFixed(1)}%
                        </span>
                      </div>
                    </div>

                    {/* Question Headline */}
                    <h2 className="text-sm font-semibold text-slate-100 group-hover:text-sky-300 transition-colors leading-snug">
                      {ev.question}
                    </h2>
                  </div>

                  {/* Candidates / Outcomes Preview */}
                  {ev.is_multi_candidate ? (
                    <div className="space-y-1.5">
                      {ev.candidates.slice(0, 4).map(cand => {
                        const yesCents = Math.round(cand.yes_price * 100);
                        const noCents = Math.round(cand.no_price * 100);
                        return (
                          <div
                            key={cand.yes_asset_id}
                            onClick={e => {
                              e.stopPropagation();
                              onSelectQuestion(ev, cand, 'YES');
                            }}
                            className="flex items-center justify-between gap-2 px-2 py-1 rounded bg-[#141A24] hover:bg-[#1B2332] border border-term-border/70 text-xs transition-colors"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex justify-between items-center mb-0.5">
                                <span className="text-slate-200 font-medium truncate">
                                  {cand.name}
                                </span>
                                <span className="font-mono font-bold text-white ml-2">
                                  {(cand.yes_price * 100).toFixed(1)}%
                                </span>
                              </div>
                              <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-sky-500"
                                  style={{ width: `${Math.min(100, cand.yes_price * 100)}%` }}
                                />
                              </div>
                            </div>

                            <div className="flex items-center space-x-1 shrink-0 font-mono text-[10px]">
                              <button
                                onClick={e => {
                                  e.stopPropagation();
                                  onSelectQuestion(ev, cand, 'YES');
                                }}
                                className="px-1.5 py-0.5 rounded bg-emerald-950/70 hover:bg-emerald-700 text-emerald-300 hover:text-white border border-emerald-800/80"
                              >
                                Y {yesCents}¢
                              </button>
                              <button
                                onClick={e => {
                                  e.stopPropagation();
                                  onSelectQuestion(ev, cand, 'NO');
                                }}
                                className="px-1.5 py-0.5 rounded bg-red-950/70 hover:bg-red-700 text-red-300 hover:text-white border border-red-800/80"
                              >
                                N {noCents}¢
                              </button>
                            </div>
                          </div>
                        );
                      })}
                      {ev.candidates.length > 4 && (
                        <div className="text-[10px] text-slate-500 text-right font-mono">
                          +{ev.candidates.length - 4} more options inside chart view
                        </div>
                      )}
                    </div>
                  ) : (
                    lead && (
                      <div className="space-y-2">
                        <div className="grid grid-cols-2 gap-2 font-mono">
                          <button
                            onClick={e => {
                              e.stopPropagation();
                              onSelectQuestion(ev, lead, 'YES');
                            }}
                            className="flex items-center justify-between px-2.5 py-1.5 rounded bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800/70 text-xs"
                          >
                            <span className="text-emerald-400 font-bold">YES</span>
                            <span className="text-white font-bold">
                              {(lead.yes_price * 100).toFixed(1)}¢
                            </span>
                          </button>
                          <button
                            onClick={e => {
                              e.stopPropagation();
                              onSelectQuestion(ev, lead, 'NO');
                            }}
                            className="flex items-center justify-between px-2.5 py-1.5 rounded bg-red-950/40 hover:bg-red-900/60 border border-red-800/70 text-xs"
                          >
                            <span className="text-red-400 font-bold">NO</span>
                            <span className="text-white font-bold">
                              {(lead.no_price * 100).toFixed(1)}¢
                            </span>
                          </button>
                        </div>
                      </div>
                    )
                  )}

                  {/* Footer CTA */}
                  <div className="pt-2 border-t border-term-border/50 flex items-center justify-between text-[10px] text-slate-500 font-mono">
                    <span className="flex items-center space-x-1">
                      <Flame className="w-3 h-3 text-amber-500" />
                      <span>OI: {formatCompactUsd(ev.open_interest)}</span>
                    </span>
                    <span className="text-sky-400 group-hover:underline flex items-center space-x-1">
                      <TrendingUp className="w-3 h-3" />
                      <span>View Live Graph & Book →</span>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Bottom Status Strip */}
      <div className="px-4 py-1.5 border-t border-term-border bg-[#0E121A] text-[10px] font-mono text-slate-500 flex justify-between items-center shrink-0">
        <div className="flex items-center space-x-3">
          <span>Click any question or candidate to open its live Candlestick Graph, L2 Orderbook & Paper Broker</span>
        </div>
        <div className="flex items-center space-x-1.5 text-amber-400">
          <Trophy className="w-3 h-3" />
          <span>{traderCount} traders competing live</span>
        </div>
      </div>
    </div>
  );
};

