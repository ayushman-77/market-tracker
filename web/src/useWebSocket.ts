import { useCallback, useEffect, useRef, useState } from 'react';
import { ConnectionState, LeaderboardEntry, OrderbookSnapshot, PaperStatus, TradeItem } from './types';

interface UseWebSocketOptions {
  activeAssetId: string;
}

export function useWebSocket({ activeAssetId }: UseWebSocketOptions) {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionState>('connecting');
  const [rttMs, setRttMs] = useState<number | null>(null);
  const [gapCount, setGapCount] = useState<number>(0);

  const [orderbook, setOrderbook] = useState<OrderbookSnapshot | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [trades, setTrades] = useState<TradeItem[]>([]);
  const [paperStatus, setPaperStatus] = useState<PaperStatus | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const lastPaperFetch = useRef<number>(0);
  const seqTracker = useRef<Record<string, number>>({
    book: -1,
    leaderboard: -1,
    trades: -1,
    paper: -1,
  });

  const sendJson = useCallback((data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const resyncStream = useCallback((stream: string) => {
    console.warn(`[MarketTracker WS] Gaps detected in ${stream} stream. Resyncing...`);
    setConnectionStatus('resyncing');
    setGapCount(prev => prev + 1);
    sendJson({ type: 'resync', stream, asset_id: activeAssetId });
  }, [activeAssetId, sendJson]);

  const resyncAll = useCallback(() => {
    setConnectionStatus('resyncing');
    sendJson({ type: 'resync', stream: null, asset_id: activeAssetId });
  }, [activeAssetId, sendJson]);

  useEffect(() => {
    let reconnectTimeout: any = null;
    let pingInterval: any = null;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // When running with Vite proxy or directly on port 8000
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws`;

    function connect() {
      setConnectionStatus('connecting');
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionStatus('connected');
        // Initial fetch of paper status to ensure immediate availability
        fetch('/api/paper/status')
          .then(r => r.json())
          .then(d => setPaperStatus(d))
          .catch(() => {});

        // Subscribe to active asset
        ws.send(JSON.stringify({ type: 'subscribe', stream: null, asset_id: activeAssetId }));

        // Ping every 3 seconds for RTT
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping', client_ts: performance.now() }));
          }
        }, 3000);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === 'pong') {
            const now = performance.now();
            setRttMs(Math.round(now - msg.client_ts));
            return;
          }

          const stream = msg.stream;
          const seq = msg.seq;

          // Sequence Gap Detection (Strictly Monotonic per stream)
          if (seq !== undefined && stream && msg.type !== 'snapshot') {
            const lastSeq = seqTracker.current[stream];
            if (lastSeq !== -1 && seq > lastSeq + 1) {
              console.error(`[MarketTracker Gap] Stream ${stream} dropped frames! Expected seq=${lastSeq + 1}, got seq=${seq}`);
              resyncStream(stream);
              return;
            }
            seqTracker.current[stream] = seq;
          } else if (seq !== undefined && stream && msg.type === 'snapshot') {
            seqTracker.current[stream] = seq;
            setConnectionStatus('connected');
          }

          // Process snapshots & deltas
          if (stream === 'book') {
            if (msg.type === 'snapshot') {
              setOrderbook(msg.data);
            } else if (msg.type === 'delta') {
              setOrderbook((prev) => {
                if (!prev || prev.asset_id !== msg.asset_id) return prev;
                // Merge deltas into bids and asks
                const bidMap = new Map(prev.bids.map(b => [b.price, b.size]));
                const askMap = new Map(prev.asks.map(a => [a.price, a.size]));

                for (const d of msg.deltas) {
                  const targetMap = d.side === 'BUY' ? bidMap : askMap;
                  if (d.size <= 1e-6) {
                    targetMap.delete(d.price);
                  } else {
                    targetMap.set(d.price, d.size);
                  }
                }

                const updatedBids = Array.from(bidMap.entries())
                  .map(([price, size]) => ({ price, size }))
                  .sort((a, b) => b.price - a.price)
                  .slice(0, 25);

                const updatedAsks = Array.from(askMap.entries())
                  .map(([price, size]) => ({ price, size }))
                  .sort((a, b) => a.price - b.price)
                  .slice(0, 25);

                return {
                  ...prev,
                  best_bid: msg.summary?.best_bid ?? prev.best_bid,
                  best_ask: msg.summary?.best_ask ?? prev.best_ask,
                  mid: msg.summary?.mid ?? prev.mid,
                  spread: msg.summary?.spread ?? prev.spread,
                  imbalance: msg.summary?.imbalance ?? prev.imbalance,
                  bids: updatedBids,
                  asks: updatedAsks,
                  sequence: seq,
                };
              });
            }
          } else if (stream === 'leaderboard') {
            if (msg.type === 'snapshot' || msg.type === 'delta') {
              setLeaderboard(msg.data || msg.wallets || []);
            }
          } else if (stream === 'trades') {
            if (msg.trades) {
              setTrades(prev => [...msg.trades, ...prev].slice(0, 100));
            }
          } else if (stream === 'paper') {
            if (msg.type === 'snapshot') {
              setPaperStatus(msg.data);
            } else if (msg.type === 'delta') {
              // Throttled refresh (at most once every 1000ms) to avoid spamming /api/paper/status
              const now = performance.now();
              if (now - lastPaperFetch.current >= 1000) {
                lastPaperFetch.current = now;
                fetch('/api/paper/status')
                  .then(r => r.json())
                  .then(d => setPaperStatus(d))
                  .catch(() => {});
              }
            }
          }
        } catch (err) {
          console.error('[MarketTracker WS] Message parse error:', err);
        }
      };

      ws.onclose = () => {
        setConnectionStatus('disconnected');
        clearInterval(pingInterval);
        reconnectTimeout = setTimeout(connect, 2000);
      };

      ws.onerror = (err) => {
        console.error('[MarketTracker WS] Socket error:', err);
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout);
      clearInterval(pingInterval);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [activeAssetId, resyncStream]);

  return {
    connectionStatus,
    rttMs,
    gapCount,
    orderbook,
    leaderboard,
    trades,
    paperStatus,
    resyncAll,
    sendJson,
  };
}
