import { useEffect, useRef, useState, type FC } from 'react';
import { Layers } from 'lucide-react';
import { OrderbookSnapshot } from '../types';

interface OrderbookLadderProps {
  orderbook: OrderbookSnapshot | null;
  onSelectPrice?: (price: number) => void;
}

export const OrderbookLadder: FC<OrderbookLadderProps> = ({
  orderbook,
  onSelectPrice,
}) => {
  const asksRef = useRef<HTMLDivElement>(null);
  const bidsRef = useRef<HTMLDivElement>(null);
  const [askLimit, setAskLimit] = useState<number>(13);
  const [bidLimit, setBidLimit] = useState<number>(13);
  const hasBook = orderbook !== null;

  useEffect(() => {
    const asksEl = asksRef.current;
    const bidsEl = bidsRef.current;
    if (!asksEl && !bidsEl) return;

    const ROW_HEIGHT = 21;
    const updateCounts = () => {
      if (asksEl && asksEl.clientHeight > 0) {
        setAskLimit(Math.max(4, Math.min(25, Math.floor(asksEl.clientHeight / ROW_HEIGHT))));
      }
      if (bidsEl && bidsEl.clientHeight > 0) {
        setBidLimit(Math.max(4, Math.min(25, Math.floor(bidsEl.clientHeight / ROW_HEIGHT))));
      }
    };

    updateCounts();
    const observer = new ResizeObserver(updateCounts);
    if (asksEl) observer.observe(asksEl);
    if (bidsEl) observer.observe(bidsEl);
    return () => observer.disconnect();
  }, [hasBook]);

  if (!orderbook) {
    return (
      <div className="flex flex-col h-full bg-[#0E121A] border-r border-term-border items-center justify-center p-4 text-slate-500 text-xs">
        <Layers className="w-6 h-6 mb-2 animate-spin text-sky-400" />
        <span>Loading L2 Orderbook...</span>
      </div>
    );
  }

  const bids = orderbook.bids || [];
  const asks = orderbook.asks || [];

  // Calculate max depth for relative horizontal bars
  const maxBidSize = Math.max(...bids.map(b => b.size), 100);
  const maxAskSize = Math.max(...asks.map(a => a.size), 100);
  const maxDepth = Math.max(maxBidSize, maxAskSize);

  // Cumulative depth totals
  const totalBidDepth = bids.reduce((acc, b) => acc + b.size, 0);
  const totalAskDepth = asks.reduce((acc, a) => acc + a.size, 0);

  // Imbalance in [-1, +1]
  const imbalance = orderbook.imbalance ?? 0.0;
  const imbalancePct = Math.round((imbalance + 1.0) * 50); // maps -1..1 to 0..100%

  // Top N asks that cleanly fit inside the visible asks panel
  const displayAsks = [...asks.slice(0, askLimit)].reverse();
  // Top N bids that cleanly fit inside the visible bids panel
  const displayBids = bids.slice(0, bidLimit);

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0E121A] border-r border-term-border">
      {/* Ladder Header */}
      <div className="p-2 border-b border-term-border flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-300">
          <Layers className="w-3.5 h-3.5 text-sky-400" />
          <span>L2 ORDERBOOK (1,001 L1 CACHE LEVELS)</span>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">
          tick: 0.001
        </span>
      </div>

      {/* Imbalance Meter */}
      <div className="px-3 py-1.5 border-b border-term-border bg-[#0B0E14] text-xs shrink-0">
        <div className="flex justify-between items-center text-[10px] text-slate-400 mb-1">
          <span>Bid Depth: <b className="text-emerald-400 font-mono">{totalBidDepth.toLocaleString()}</b></span>
          <span className="font-semibold text-slate-300">
            Imbalance: <b className={imbalance >= 0 ? 'text-emerald-400' : 'text-red-400'}>
              {(imbalance * 100).toFixed(1)}%
            </b>
          </span>
          <span>Ask Depth: <b className="text-red-400 font-mono">{totalAskDepth.toLocaleString()}</b></span>
        </div>
        <div className="w-full h-1.5 bg-red-950/60 rounded-full overflow-hidden flex">
          <div
            className="h-full bg-emerald-500 transition-all duration-150"
            style={{ width: `${imbalancePct}%` }}
          ></div>
          <div
            className="h-full bg-red-500 transition-all duration-150"
            style={{ width: `${100 - imbalancePct}%` }}
          ></div>
        </div>
      </div>

      {/* Column Labels */}
      <div className="grid grid-cols-3 px-3 py-1 text-[10px] font-semibold text-slate-500 border-b border-term-border bg-[#0B0E14] uppercase shrink-0">
        <div>Price ($)</div>
        <div className="text-right">Size</div>
        <div className="text-right">Depth Bar</div>
      </div>

      {/* ASKS (Red) */}
      <div
        ref={asksRef}
        className="flex-1 min-h-0 overflow-hidden flex flex-col justify-end divide-y divide-term-border/20 text-xs"
      >
        {displayAsks.map((ask) => {
          const depthPct = Math.min(100, Math.round((ask.size / maxDepth) * 100));
          return (
            <div
              key={`ask-${ask.price}`}
              onClick={() => onSelectPrice?.(ask.price)}
              className="grid grid-cols-3 px-3 flex-1 min-h-0 max-h-[28px] hover:bg-red-950/20 cursor-pointer font-mono relative items-center select-none"
            >
              <div className="text-red-400 font-semibold">{ask.price.toFixed(3)}</div>
              <div className="text-right text-slate-300">{ask.size.toFixed(1)}</div>
              <div className="flex justify-end items-center pl-2">
                <div
                  className="h-3 bg-red-500/25 border-r border-red-500/60 rounded-xs transition-all duration-100"
                  style={{ width: `${depthPct}%` }}
                ></div>
              </div>
            </div>
          );
        })}
      </div>

      {/* SPREAD / MID BANNER */}
      <div className="px-3 py-1.5 bg-[#141A24] border-y border-term-border flex items-center justify-between font-mono text-xs select-none shrink-0">
        <div className="flex items-center space-x-2">
          <span className="text-[10px] text-slate-500 uppercase">Mid:</span>
          <span className="font-bold text-white text-sm">
            {orderbook.mid !== null ? `$${orderbook.mid.toFixed(3)}` : '---'}
          </span>
        </div>
        <div className="flex items-center space-x-2">
          <span className="text-[10px] text-slate-500 uppercase">Spread:</span>
          <span className="text-slate-300 font-medium">
            {orderbook.spread !== null ? `$${orderbook.spread.toFixed(3)}` : '---'}
          </span>
        </div>
      </div>

      {/* BIDS (Green) */}
      <div
        ref={bidsRef}
        className="flex-1 min-h-0 overflow-hidden flex flex-col justify-start divide-y divide-term-border/20 text-xs"
      >
        {displayBids.map((bid) => {
          const depthPct = Math.min(100, Math.round((bid.size / maxDepth) * 100));
          return (
            <div
              key={`bid-${bid.price}`}
              onClick={() => onSelectPrice?.(bid.price)}
              className="grid grid-cols-3 px-3 flex-1 min-h-0 max-h-[28px] hover:bg-emerald-950/20 cursor-pointer font-mono relative items-center select-none"
            >
              <div className="text-emerald-400 font-semibold">{bid.price.toFixed(3)}</div>
              <div className="text-right text-slate-300">{bid.size.toFixed(1)}</div>
              <div className="flex justify-end items-center pl-2">
                <div
                  className="h-3 bg-emerald-500/25 border-r border-emerald-500/60 rounded-xs transition-all duration-100"
                  style={{ width: `${depthPct}%` }}
                ></div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
