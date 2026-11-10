import { useEffect, useRef, useState } from 'react';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Header } from './components/Header';
import { Leaderboard } from './components/Leaderboard';
import { OrderbookLadder } from './components/OrderbookLadder';
import { PaperTradingPanel } from './components/PaperTradingPanel';
import { ShortcutModal } from './components/ShortcutModal';
import { WalletModal } from './components/WalletModal';
import { Market } from './types';
import { useWebSocket } from './useWebSocket';

export function App() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [activeAssetId, setActiveAssetId] = useState<string>('tok_btc_100k_yes');
  const [selectedWallet, setSelectedWallet] = useState<string | null>(null);
  const [leaderboardIndex, setLeaderboardIndex] = useState<number>(0);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isHelpOpen, setIsHelpOpen] = useState<boolean>(false);

  const searchInputRef = useRef<HTMLInputElement>(null);

  // Load markets metadata on mount
  useEffect(() => {
    fetch('/api/markets')
      .then(res => res.json())
      .then((data: Market[]) => {
        setMarkets(data);
        if (data.length > 0) {
          setActiveAssetId(data[0].asset_id);
        }
      })
      .catch(err => console.error('Failed to load markets:', err));
  }, []);

  // Real-time WebSocket hook with gap detection and delta decoding
  const {
    connectionStatus,
    rttMs,
    gapCount,
    orderbook,
    leaderboard,
    paperStatus,
    resyncAll,
  } = useWebSocket({ activeAssetId });

  // Global Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is currently typing in an input
      const isInputActive = document.activeElement === searchInputRef.current;

      if (e.key === 'Escape') {
        if (isHelpOpen) {
          setIsHelpOpen(false);
          return;
        }
        if (selectedWallet) {
          setSelectedWallet(null);
          return;
        }
        if (isInputActive) {
          searchInputRef.current?.blur();
          return;
        }
      }

      if (isInputActive) return;

      if (e.key === '/') {
        e.preventDefault();
        searchInputRef.current?.focus();
      } else if (e.key === 'j') {
        e.preventDefault();
        setLeaderboardIndex(prev => Math.min(leaderboard.length - 1, prev + 1));
      } else if (e.key === 'k') {
        e.preventDefault();
        setLeaderboardIndex(prev => Math.max(0, prev - 1));
      } else if (e.key === 'Enter') {
        if (leaderboard[leaderboardIndex]) {
          setSelectedWallet(leaderboard[leaderboardIndex].wallet);
        }
      } else if (e.key === '?') {
        e.preventDefault();
        setIsHelpOpen(prev => !prev);
      } else if (e.key === 'r') {
        e.preventDefault();
        resyncAll();
      } else if (e.key === '1' && markets[0]) {
        setActiveAssetId(markets[0].asset_id);
      } else if (e.key === '2' && markets[1]) {
        setActiveAssetId(markets[1].asset_id);
      } else if (e.key === '3' && markets[2]) {
        setActiveAssetId(markets[2].asset_id);
      } else if (e.key === 'b') {
        // Quick paper BUY
        fetch('/api/paper/order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ asset_id: activeAssetId, side: 'BUY', size: 100, price: null }),
        });
      } else if (e.key === 's') {
        // Quick paper SELL
        fetch('/api/paper/order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ asset_id: activeAssetId, side: 'SELL', size: 100, price: null }),
        });
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isHelpOpen, selectedWallet, leaderboard, leaderboardIndex, markets, activeAssetId, resyncAll]);

  return (
    <ErrorBoundary>
      <div className="flex flex-col h-screen w-screen bg-[#0B0E14] overflow-hidden text-slate-200">
        {/* Top Application Header */}
        <Header
          markets={markets}
          activeAssetId={activeAssetId}
          onSelectMarket={setActiveAssetId}
          connectionStatus={connectionStatus}
          rttMs={rttMs}
          gapCount={gapCount}
          onResync={resyncAll}
          onOpenHelp={() => setIsHelpOpen(true)}
        />

        {/* Main Trading Terminal Layout: 3 Columns */}
        <main className="flex-1 min-h-0 grid grid-cols-12 overflow-hidden">
          {/* Left: Leaderboard (4 cols) */}
          <section className="col-span-12 md:col-span-4 h-full min-h-0 overflow-hidden">
            <Leaderboard
              entries={leaderboard}
              selectedIndex={leaderboardIndex}
              onSelectIndex={setLeaderboardIndex}
              onOpenWallet={setSelectedWallet}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              searchInputRef={searchInputRef}
            />
          </section>

          {/* Center: Live Orderbook Ladder (4 cols) */}
          <section className="col-span-12 md:col-span-4 h-full min-h-0 overflow-hidden">
            <OrderbookLadder
              orderbook={orderbook}
            />
          </section>

          {/* Right: Paper Trading & Signals Panel (4 cols) */}
          <section className="col-span-12 md:col-span-4 h-full min-h-0 overflow-hidden">
            <PaperTradingPanel
              status={paperStatus}
              activeAssetId={activeAssetId}
              onRefresh={resyncAll}
            />
          </section>
        </main>

        {/* Wallet Drilldown Modal */}
        <WalletModal
          wallet={selectedWallet}
          onClose={() => setSelectedWallet(null)}
        />

        {/* Shortcut Cheat Sheet Modal */}
        <ShortcutModal
          isOpen={isHelpOpen}
          onClose={() => setIsHelpOpen(false)}
        />
      </div>
    </ErrorBoundary>
  );
}

export default App;
