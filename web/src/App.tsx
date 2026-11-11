import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, CheckCircle2 } from 'lucide-react';
import { CandlestickChart } from './components/CandlestickChart';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Header } from './components/Header';
import { Leaderboard } from './components/Leaderboard';
import { MarketsExplorer } from './components/MarketsExplorer';
import { OrderbookLadder } from './components/OrderbookLadder';
import { PaperTradingPanel } from './components/PaperTradingPanel';
import { ShortcutModal } from './components/ShortcutModal';
import { WalletModal } from './components/WalletModal';
import { EventCandidate, EventMarket, Market } from './types';
import { useWebSocket } from './useWebSocket';

function formatCompactUsd(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2).replace(/\.00$/, '')}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

export function App() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [events, setEvents] = useState<EventMarket[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<'markets' | 'terminal'>('markets');
  const [activeAssetId, setActiveAssetId] = useState<string>('tok_btc_100k_yes');
  const [selectedWallet, setSelectedWallet] = useState<string | null>(null);
  const [leaderboardIndex, setLeaderboardIndex] = useState<number>(0);
  const [walletSearchQuery, setWalletSearchQuery] = useState<string>('');
  const [marketSearchQuery, setMarketSearchQuery] = useState<string>('');
  const [isHelpOpen, setIsHelpOpen] = useState<boolean>(false);
  const [isChartExpanded, setIsChartExpanded] = useState<boolean>(false);
  const [chartStats, setChartStats] = useState<{
    current_price: number;
    change_24h_pct: number;
    volume_24h: number;
    open_interest: number;
  } | null>(null);

  const walletSearchRef = useRef<HTMLInputElement>(null);
  const marketSearchRef = useRef<HTMLInputElement>(null);

  const fetchCatalog = useCallback(() => {
    fetch('/api/events')
      .then(res => res.json())
      .then((data: { categories: string[]; events: EventMarket[] }) => {
        if (Array.isArray(data.categories)) setCategories(data.categories);
        if (Array.isArray(data.events)) setEvents(data.events);
      })
      .catch(err => console.error('Failed to load events:', err));
  }, []);

  // Load markets & domain catalog on mount + periodic live odds refresh
  useEffect(() => {
    fetch('/api/markets')
      .then(res => res.json())
      .then((data: Market[]) => {
        setMarkets(data);
        if (data.length > 0) {
          setActiveAssetId(prev => prev || data[0].asset_id);
        }
      })
      .catch(err => console.error('Failed to load markets:', err));

    fetchCatalog();
    const timer = setInterval(fetchCatalog, 3000);
    return () => clearInterval(timer);
  }, [fetchCatalog]);

  const {
    connectionStatus,
    rttMs,
    gapCount,
    orderbook,
    leaderboard,
    paperStatus,
    liveCandle,
    resyncAll,
  } = useWebSocket({ activeAssetId });

  const marketLabels = useMemo(() => {
    const map: Record<string, string> = {};
    for (const m of markets) {
      map[m.asset_id] = `${m.question} [${m.outcome_label}]`;
    }
    return map;
  }, [markets]);

  const activeMeta = useMemo(
    () => markets.find(m => m.asset_id === activeAssetId),
    [markets, activeAssetId]
  );

  const activeEvent = useMemo(() => {
    if (activeMeta?.event_id) {
      const found = events.find(ev => ev.event_id === activeMeta.event_id);
      if (found) return found;
    }
    return (
      events.find(ev =>
        ev.candidates.some(
          c => c.yes_asset_id === activeAssetId || c.no_asset_id === activeAssetId
        )
      ) ?? events[0]
    );
  }, [events, activeMeta, activeAssetId]);

  const activeCandidate = useMemo(() => {
    if (!activeEvent) return undefined;
    return (
      activeEvent.candidates.find(
        c => c.yes_asset_id === activeAssetId || c.no_asset_id === activeAssetId
      ) ?? activeEvent.candidates[0]
    );
  }, [activeEvent, activeAssetId]);

  const activeOutcomeLabel: 'YES' | 'NO' =
    activeCandidate?.no_asset_id === activeAssetId ? 'NO' : 'YES';

  const handleSelectQuestion = useCallback(
    (ev: EventMarket, cand?: EventCandidate, side: 'YES' | 'NO' = 'YES') => {
      const chosen = cand ?? ev.candidates[0];
      if (!chosen) return;
      const targetId = side === 'NO' ? chosen.no_asset_id : chosen.yes_asset_id;
      setActiveAssetId(targetId);
      setViewMode('terminal');
    },
    []
  );

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement;
      const isInputActive =
        activeEl instanceof HTMLInputElement ||
        activeEl instanceof HTMLTextAreaElement ||
        activeEl instanceof HTMLSelectElement;

      if (e.key === 'Escape') {
        if (isHelpOpen) {
          setIsHelpOpen(false);
          return;
        }
        if (selectedWallet) {
          setSelectedWallet(null);
          return;
        }
        if (activeEl === walletSearchRef.current) {
          walletSearchRef.current?.blur();
          return;
        }
        if (activeEl === marketSearchRef.current) {
          marketSearchRef.current?.blur();
          return;
        }
      }

      if (isInputActive) return;

      if (e.key === '/') {
        e.preventDefault();
        if (viewMode === 'markets') {
          marketSearchRef.current?.focus();
        } else {
          walletSearchRef.current?.focus();
        }
      } else if (e.key === 'm') {
        e.preventDefault();
        setViewMode(prev => (prev === 'markets' ? 'terminal' : 'markets'));
      } else if (e.key === '?') {
        e.preventDefault();
        setIsHelpOpen(prev => !prev);
      } else if (e.key === 'r') {
        e.preventDefault();
        resyncAll();
      } else if (e.key === '1' && events[0]) {
        handleSelectQuestion(events[0]);
      } else if (e.key === '2' && events[1]) {
        handleSelectQuestion(events[1]);
      } else if (e.key === '3' && events[2]) {
        handleSelectQuestion(events[2]);
      } else if (viewMode === 'terminal') {
        if (e.key === 'j') {
          e.preventDefault();
          setLeaderboardIndex(prev => Math.min(leaderboard.length - 1, prev + 1));
        } else if (e.key === 'k') {
          e.preventDefault();
          setLeaderboardIndex(prev => Math.max(0, prev - 1));
        } else if (e.key === 'Enter') {
          if (leaderboard[leaderboardIndex]) {
            setSelectedWallet(leaderboard[leaderboardIndex].wallet);
          }
        } else if (e.key === 'b') {
          fetch('/api/paper/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ asset_id: activeAssetId, side: 'BUY', size: 100, price: null }),
          });
        } else if (e.key === 's') {
          fetch('/api/paper/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ asset_id: activeAssetId, side: 'SELL', size: 100, price: null }),
          });
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    viewMode,
    isHelpOpen,
    selectedWallet,
    leaderboard,
    leaderboardIndex,
    events,
    activeAssetId,
    resyncAll,
    handleSelectQuestion,
  ]);

  // Live implied YES & NO prices for cards
  const yesCardPrice = useMemo(() => {
    if (orderbook?.mid !== null && orderbook?.mid !== undefined) {
      return activeOutcomeLabel === 'YES'
        ? orderbook.mid
        : Math.max(0.001, Math.min(0.999, 1 - orderbook.mid));
    }
    return activeCandidate?.yes_price ?? 0.5;
  }, [orderbook, activeOutcomeLabel, activeCandidate]);

  const noCardPrice = Math.max(0.001, Math.min(0.999, 1 - yesCardPrice));
  const eventChange = chartStats?.change_24h_pct ?? activeCandidate?.change_24h_pct ?? 0;
  const eventVolume = chartStats?.volume_24h ?? activeEvent?.volume_24h ?? 0;
  const eventOI = chartStats?.open_interest ?? activeEvent?.open_interest ?? 0;

  return (
    <ErrorBoundary>
      <div className="flex flex-col h-screen w-screen bg-[#0B0E14] overflow-hidden text-slate-200">
        <Header
          markets={markets}
          activeAssetId={activeAssetId}
          viewMode={viewMode}
          onChangeView={setViewMode}
          onSelectMarket={setActiveAssetId}
          connectionStatus={connectionStatus}
          rttMs={rttMs}
          gapCount={gapCount}
          onResync={resyncAll}
          onOpenHelp={() => setIsHelpOpen(true)}
        />

        {viewMode === 'markets' ? (
          <main className="flex-1 min-h-0 overflow-hidden">
            <MarketsExplorer
              events={events}
              categories={categories}
              traderCount={leaderboard.length || 100}
              searchQuery={marketSearchQuery}
              onSearchChange={setMarketSearchQuery}
              searchInputRef={marketSearchRef}
              onSelectQuestion={handleSelectQuestion}
              onOpenTerminal={() => setViewMode('terminal')}
            />
          </main>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {/* Active Question Banner (matches Polymarket terminal header) */}
            <div className="px-3 py-2 border-b border-term-border bg-[#0E121A] flex flex-wrap items-center justify-between gap-2 shrink-0">
              <div className="flex items-start sm:items-center gap-2.5 min-w-0">
                <button
                  onClick={() => setViewMode('markets')}
                  className="px-2 py-1 rounded bg-[#141A24] hover:bg-[#1B2332] border border-term-border text-xs text-slate-300 hover:text-white flex items-center space-x-1 shrink-0 cursor-pointer"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>All Questions ({events.length || 50})</span>
                </button>

                <div className="min-w-0">
                  <div className="flex items-center flex-wrap gap-1.5 mb-0.5 text-[10px] font-mono">
                    <span className="px-1.5 py-0.2 rounded bg-sky-950 text-sky-300 border border-sky-800 uppercase font-bold">
                      {activeEvent?.category ?? activeMeta?.category ?? 'MARKET'}
                    </span>
                    <span className="px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 uppercase font-bold flex items-center space-x-1">
                      <CheckCircle2 className="w-2.5 h-2.5" />
                      <span>ACTIVE</span>
                    </span>
                    <span className="text-slate-500 hidden sm:inline">
                      Oracle: {activeEvent?.oracle ?? 'UMA Optimistic Oracle v2'}
                    </span>
                  </div>
                  <h1 className="text-sm font-bold text-white truncate">
                    {activeEvent?.question ?? activeMeta?.event_question ?? activeMeta?.question}
                    {activeEvent?.is_multi_candidate && activeCandidate
                      ? ` — ${activeCandidate.name}`
                      : ''}
                  </h1>
                </div>
              </div>

              {/* 24h Telemetry Metrics */}
              <div className="flex items-center space-x-4 text-xs font-mono shrink-0">
                <div>
                  <div className="text-[9px] text-slate-500 uppercase">24H Volume</div>
                  <div className="font-bold text-white">{formatCompactUsd(eventVolume)}</div>
                </div>
                <div>
                  <div className="text-[9px] text-slate-500 uppercase">Open Interest</div>
                  <div className="font-bold text-white">{formatCompactUsd(eventOI)}</div>
                </div>
                <div>
                  <div className="text-[9px] text-slate-500 uppercase">24H Change</div>
                  <div
                    className={`font-bold ${
                      eventChange >= 0 ? 'text-emerald-400' : 'text-red-400'
                    }`}
                  >
                    {eventChange >= 0 ? '+' : ''}
                    {eventChange.toFixed(2)}%
                  </div>
                </div>
              </div>
            </div>

            {/* Multi-Candidate Contract Strip (e.g. JD Vance, Gavin Newsom, Jon Ossoff, AOC, Other) */}
            {activeEvent?.is_multi_candidate && activeEvent.candidates.length > 1 && (
              <div className="px-3 py-1.5 border-b border-term-border bg-[#0B0E14] flex items-center gap-2 overflow-x-auto shrink-0">
                <span className="text-[10px] font-mono uppercase text-slate-500 shrink-0">
                  Candidates:
                </span>
                {activeEvent.candidates.map(cand => {
                  const isSelected =
                    cand.yes_asset_id === activeAssetId || cand.no_asset_id === activeAssetId;
                  return (
                    <button
                      key={cand.yes_asset_id}
                      onClick={() =>
                        setActiveAssetId(
                          activeOutcomeLabel === 'NO' ? cand.no_asset_id : cand.yes_asset_id
                        )
                      }
                      className={`px-2.5 py-1 rounded border text-xs font-mono flex items-center space-x-2 shrink-0 transition-colors cursor-pointer ${
                        isSelected
                          ? 'bg-sky-950/70 border-sky-500 text-white font-semibold'
                          : 'bg-[#141A24] border-term-border text-slate-300 hover:border-slate-500 hover:text-white'
                      }`}
                    >
                      <span>{cand.name}</span>
                      <span className="text-emerald-400 font-bold">
                        {Math.round(cand.yes_price * 100)}¢
                      </span>
                      <span className="text-[10px] text-slate-500">
                        ({(cand.yes_price * 100).toFixed(1)}%)
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* Main 12-Col Terminal Workspace (Graph + Leaderboard + Orderbook + Paper Portfolio) */}
            <main className="flex-1 min-h-0 grid grid-cols-12 overflow-hidden">
              {/* Left 6 Cols: Candlestick Chart + Top 100 Traders Leaderboard */}
              <section className="col-span-12 lg:col-span-6 h-full min-h-0 flex flex-col overflow-hidden">
                <div className={isChartExpanded ? 'flex-1 min-h-0' : 'flex-[1.35] min-h-[250px]'}>
                  <CandlestickChart
                    assetId={activeAssetId}
                    yesAssetId={activeCandidate?.yes_asset_id ?? activeAssetId}
                    noAssetId={
                      activeCandidate?.no_asset_id ??
                      activeMeta?.paired_asset_id ??
                      activeAssetId
                    }
                    outcomeLabel={activeOutcomeLabel}
                    slug={activeEvent?.slug ?? activeMeta?.slug ?? activeAssetId}
                    candidateName={activeCandidate?.name}
                    isMultiCandidate={Boolean(activeEvent?.is_multi_candidate)}
                    liveCandle={liveCandle}
                    isExpanded={isChartExpanded}
                    onToggleExpand={() => setIsChartExpanded(prev => !prev)}
                    onSelectContract={setActiveAssetId}
                    onStatsUpdate={setChartStats}
                  />
                </div>

                {!isChartExpanded && (
                  <div className="flex-1 min-h-[190px] overflow-hidden">
                    <Leaderboard
                      entries={leaderboard}
                      selectedIndex={leaderboardIndex}
                      onSelectIndex={setLeaderboardIndex}
                      onOpenWallet={setSelectedWallet}
                      searchQuery={walletSearchQuery}
                      onSearchChange={setWalletSearchQuery}
                      searchInputRef={walletSearchRef}
                    />
                  </div>
                )}
              </section>

              {/* Middle 3 Cols: YES/NO Odds Cards + L2 Orderbook Ladder */}
              <section className="col-span-12 lg:col-span-3 h-full min-h-0 flex flex-col overflow-hidden">
                {activeCandidate && (
                  <div className="grid grid-cols-2 gap-2 p-2 bg-[#0B0E14] border-r border-b border-term-border shrink-0 font-mono">
                    <button
                      onClick={() => setActiveAssetId(activeCandidate.yes_asset_id)}
                      className={`p-2 rounded border text-left transition-all cursor-pointer ${
                        activeOutcomeLabel === 'YES'
                          ? 'bg-emerald-950/50 border-emerald-600'
                          : 'bg-[#141A24] border-term-border hover:border-emerald-800'
                      }`}
                    >
                      <div className="text-[10px] text-emerald-400 font-semibold uppercase">
                        YES Price
                      </div>
                      <div className="text-lg font-bold text-white leading-tight mt-0.5">
                        ${yesCardPrice.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {Math.round(yesCardPrice * 100)}¢ Implied Odds
                      </div>
                    </button>

                    <button
                      onClick={() => setActiveAssetId(activeCandidate.no_asset_id)}
                      className={`p-2 rounded border text-left transition-all cursor-pointer ${
                        activeOutcomeLabel === 'NO'
                          ? 'bg-red-950/50 border-red-600'
                          : 'bg-[#141A24] border-term-border hover:border-red-800'
                      }`}
                    >
                      <div className="text-[10px] text-red-400 font-semibold uppercase">
                        NO Price
                      </div>
                      <div className="text-lg font-bold text-white leading-tight mt-0.5">
                        ${noCardPrice.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {Math.round(noCardPrice * 100)}¢ Implied Odds
                      </div>
                    </button>
                  </div>
                )}

                <div className="flex-1 min-h-0 overflow-hidden">
                  <OrderbookLadder orderbook={orderbook} />
                </div>
              </section>

              {/* Right 3 Cols: Paper Trading & Signals Panel */}
              <section className="col-span-12 lg:col-span-3 h-full min-h-0 overflow-hidden">
                <PaperTradingPanel
                  status={paperStatus}
                  activeAssetId={activeAssetId}
                  marketLabels={marketLabels}
                  onRefresh={resyncAll}
                />
              </section>
            </main>
          </div>
        )}

        <WalletModal
          wallet={selectedWallet}
          onClose={() => setSelectedWallet(null)}
        />

        <ShortcutModal
          isOpen={isHelpOpen}
          onClose={() => setIsHelpOpen(false)}
        />
      </div>
    </ErrorBoundary>
  );
}

export default App;
