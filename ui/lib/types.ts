/**
 * TypeScript interfaces for Congressional Alpha API
 */

// Trade Signal
export interface TradeSignal {
    id: number | null;
    ticker: string;
    politician: string;
    trade_type: string;
    amount_midpoint: number;
    trade_date: string;
    disclosure_date: string;
    lag_days: number;
    signal_type: string;
    chamber: string;
    asset_name: string | null;
    pdf_url: string | null;
    processed: boolean;
    created_at: string | null;
}

export interface PaginatedSignals {
    items: TradeSignal[];
    total: number;
    page: number;
    page_size: number;
    pages: number;
}

// Trade History
export interface Trade {
    id: number | null;
    ticker: string;
    trade_type: string;
    shares: number;
    price: number;
    executed_at: string;
    pnl: number | null;
    signal_id: number | null;
}

export interface PaginatedTrades {
    items: Trade[];
    total: number;
    page: number;
    page_size: number;
    pages: number;
}

export interface TradeStats {
    total_trades: number;
    total_buys: number;
    total_sells: number;
    realized_pnl: number;
    win_rate: number;
    avg_trade_size: number;
    best_trade: number | null;
    worst_trade: number | null;
}

// Portfolio
export interface Position {
    ticker: string;
    quantity: number;
    average_price: number;
    current_price: number | null;
    market_value: number | null;
    pnl: number | null;
    pnl_percent: number | null;
}

export interface AccountSummary {
    total_value: number;
    cash_available: number;
    invested_value: number;
    unrealized_pnl: number;
    currency: string;
}

// Politicians
export interface Politician {
    name: string;
    chamber: string;
    notes: string;
}

export interface PoliticianCount {
    total: number;
    house: number;
    senate: number;
}

// System
export interface SystemStats {
    total_signals: number;
    pending_signals: number;
    processed_signals: number;
    total_trades: number;
    total_logs: number;
}

export interface LogEntry {
    id: number | null;
    level: string;
    module: string;
    message: string;
    created_at: string | null;
}

export interface SystemConfig {
    trading212_configured: boolean;
    trading212_environment: string;
    openrouter_configured: boolean;
    market_open_hour: number;
    market_close_hour: number;
    min_market_cap: number;
    wash_sale_days: number;
    immediate_signal_max_lag: number;
    stale_signal_threshold: number;
}

export interface SchedulerStatus {
    current_time_et: string;
    is_market_hours: boolean;
    market_open: string;
    market_close: string;
    interval_minutes: string;
}
