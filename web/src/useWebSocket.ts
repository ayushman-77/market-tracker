import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CandleBar,
  ConnectionState,
  LeaderboardEntry,
  OrderbookSnapshot,
  PaperStatus,
  TradeItem,
} from './types';

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
  const [liveCandle, setLiveCandle] = useState<{ asset_id: string; candle: CandleBar } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const activeAssetRef = useRef<string>(activeAssetId);
  const lastPaperFetch = useRef<number>(0);
  const seqTracker = useRef<Record<string, number>>({
    book: -1,
    leaderboard: -1,
    trades: -1,
    paper: -1,
    candles: -1,
  });

  useEffect(() => {
    activeAssetRef.current = activeAssetId;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      seqTracker.current.book = -1;
      seqTracker.current.candles = -1;
      wsRef.current.send(
        JSON.stringify({ type: 'subscribe', stream: null, asset_id: activeAssetId })
      );
      fetch('/api/paper/status')
        .then(r => r.json())
        .then(d => setPaperStatus(d))
        .catch(() => {});
    }
  }, [activeAssetId]);

  const sendJson = useCallback((data: unknown) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const resyncStream = useCallback((stream: string) => {
    console.warn(`[MarketTracker WS] Gaps detected in ${stream} stream. Resyncing...`);
    setConnectionStatus('resyncing');
    setGapCount(prev => prev + 1);
    sendJson({ type: 'resync', stream, asset_id: activeAssetRef.current });
  }, [sendJson]);

  const resyncAll = useCallback(() => {
    setConnectionStatus('resyncing');
    sendJson({ type: 'resync', stream: null, asset_id: activeAssetRef.current });
  }, [sendJson]);

  useEffect(() => {
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let pingInterval: ReturnType<typeof setInterval> | null = null;
    let isDisposed = false;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws`;

    function connect() {
      if (isDisposed) return;
      setConnectionStatus('connecting');
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionStatus('connected');
        fetch('/api/paper/status')
          .then(r => r.json())
          .then(d => setPaperStatus(d))
          .catch(() => {});

        ws.send(
          JSON.stringify({ type: 'subscribe', stream: null, asset_id: activeAssetRef.current })
        );

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

          const stream = msg.stream as string | undefined;
          const seq = msg.seq as number | undefined;

          if (seq !== undefined && stream && msg.type !== 'snapshot') {
            const lastSeq = seqTracker.current[stream] ?? -1;
            if (lastSeq !== -1 && seq > lastSeq + 1) {
              console.error(
                `[MarketTracker Gap] Stream ${stream} dropped frames! Expected seq=${lastSeq + 1}, got seq=${seq}`
              );
              if (stream !== 'candles') {
                resyncStream(stream);
                return;
              }
            }
            seqTracker.current[stream] = seq;
          } else if (seq !== undefined && stream && msg.type === 'snapshot') {
            seqTracker.current[stream] = seq;
            setConnectionStatus('connected');
          }

          if (stream === 'book') {
            if (msg.type === 'snapshot') {
              if (!msg.asset_id || msg.asset_id === activeAssetRef.current) {
                setOrderbook(msg.data);
              }
            } else if (msg.type === 'delta') {
              setOrderbook((prev) => {
                if (!prev || prev.asset_id !== msg.asset_id || msg.asset_id !== activeAssetRef.current) {
                  return prev;
                }
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
          } else if (stream === 'candles') {
            if (msg.type === 'delta' && msg.candle && msg.asset_id === activeAssetRef.current) {
              setLiveCandle({ asset_id: msg.asset_id, candle: msg.candle });
            }
          } else if (stream === 'paper') {
            if (msg.type === 'snapshot') {
              setPaperStatus(msg.data);
            } else if (msg.type === 'delta') {
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
        if (isDisposed) return;
        setConnectionStatus('disconnected');
        if (pingInterval) clearInterval(pingInterval);
        reconnectTimeout = setTimeout(connect, 2000);
      };

      ws.onerror = (err) => {
        console.error('[MarketTracker WS] Socket error:', err);
        ws.close();
      };
    }

    connect();

    return () => {
      isDisposed = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (pingInterval) clearInterval(pingInterval);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [resyncStream]);

  return {
    connectionStatus,
    rttMs,
    gapCount,
    orderbook,
    leaderboard,
    trades,
    paperStatus,
    liveCandle,
    resyncAll,
    sendJson,
  };
}
