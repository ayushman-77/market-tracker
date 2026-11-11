export interface Market {
  asset_id: string;
  condition_id: string;
  event_id?: string;
  question: string;
  event_question?: string;
  outcome_label: string;
  candidate_name?: string;
  category?: string;
  slug?: string;
  paired_asset_id?: string;
  tick_size: number;
}

export interface EventCandidate {
  name: string;
  yes_asset_id: string;
  no_asset_id: string;
  yes_price: number;
  no_price: number;
  change_24h_pct: number;
  volume_24h: number;
  spread: number;
}

export interface EventMarket {
  event_id: string;
  condition_id: string;
  slug: string;
  category: string;
  question: string;
  oracle: string;
  active: boolean;
  is_multi_candidate: boolean;
  volume_24h: number;
  open_interest: number;
  change_24h_pct: number;
  primary_asset_id: string;
  candidates: EventCandidate[];
}

export type Timeframe = '1M' | '5M' | '15M' | '1H' | '1D';

export interface CandleBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlePayload {
  asset_id: string;
  yes_asset_id: string;
  no_asset_id: string;
  outcome_label: string;
  timeframe: Timeframe;
  current_price: number;
  open_24h: number;
  change_24h_pct: number;
  volume_24h: number;
  open_interest: number;
  candles: CandleBar[];
}

export interface LadderLevel {
  price: number;
  size: number;
}

export interface OrderbookSnapshot {
  asset_id: string;
  best_bid: number | null;
  best_ask: number | null;
  mid: number | null;
  spread: number | null;
  imbalance: number;
  bids: LadderLevel[];
  asks: LadderLevel[];
  book_hash: string;
  sequence?: number;
}

export interface LeaderboardEntry {
  rank: number;
  wallet: string;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  fees_paid: number;
}

export interface PositionDetail {
  wallet: string;
  asset_id: string;
  outcome_idx: number;
  size: number;
  cost_basis: number;
  realized_pnl: number;
  unrealized_pnl: number;
  fees_paid: number;
  total_pnl: number;
  last_price: number;
}

export interface PnLPoint {
  timestamp: number;
  pnl: number;
}

export interface TradeItem {
  event_id: string;
  asset_id: string;
  maker_wallet?: string;
  taker_wallet?: string;
  side: 'BUY' | 'SELL';
  price: number;
  size: number;
  usd_value: number;
  fee: number;
  timestamp: string;
}

export interface WalletDrilldown {
  wallet: string;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_fees: number;
  positions: PositionDetail[];
  pnl_history: PnLPoint[];
  recent_trades: TradeItem[];
}

export interface PaperFill {
  fill_id: string;
  order_id: string;
  asset_id: string;
  side: 'BUY' | 'SELL';
  price: number;
  size: number;
  fee: number;
  slippage: number;
  is_passive: boolean;
  timestamp: string;
}

export interface PaperPosition {
  size: number;
  cost_basis: number;
  unrealized_pnl: number;
}

export interface PaperStatus {
  cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_fees: number;
  is_killed: boolean;
  positions: Record<string, PaperPosition>;
  signals: {
    imbalance: {
      name: string;
      value: number;
      threshold: number;
      status: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
    };
    smart_money: {
      name: string;
      top_n: number;
      window_seconds: number;
      status: string;
    };
  };
  latency_stats: {
    p50_us: number;
    p99_us: number;
    p99_9_us: number;
    measurement: string;
  };
  recent_fills: PaperFill[];
  recent_decisions: Array<{
    signal: string;
    action: string;
    target_price?: number;
    order_size?: number;
    reason: string;
    timestamp: string;
  }>;
}

export type ConnectionState = 'connected' | 'connecting' | 'disconnected' | 'resyncing';
