import { tradesApi } from "@/lib/api";
import type { Trade, TradeStats } from "@/lib/types";

export const dynamic = "force-dynamic";

async function fetchTrades(page: number) {
    try {
        const [trades, stats] = await Promise.all([
            tradesApi.list({ page, page_size: 20 }),
            tradesApi.getStats(),
        ]);
        return { trades, stats };
    } catch {
        return {
            trades: { items: [], total: 0, page: 1, page_size: 20, pages: 1 },
            stats: null
        };
    }
}

export default async function TradesPage({
    searchParams,
}: {
    searchParams: Promise<{ page?: string }>;
}) {
    const params = await searchParams;
    const page = params.page ? parseInt(params.page) : 1;
    const { trades, stats } = await fetchTrades(page);

    return (
        <>
            <header className="page-header">
                <h1 className="page-title">Trade History</h1>
                <p className="page-subtitle">Executed trades and performance metrics</p>
            </header>

            {/* Stats */}
            {stats && (
                <div className="stats-grid">
                    <div className="stat-card">
                        <div className="stat-label">Total Trades</div>
                        <div className="stat-value">{stats.total_trades}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Win Rate</div>
                        <div className={`stat-value ${stats.win_rate >= 50 ? "profit" : "loss"}`}>
                            {stats.win_rate}%
                        </div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Realized P&L</div>
                        <div className={`stat-value ${stats.realized_pnl >= 0 ? "profit" : "loss"}`}>
                            {formatCurrency(stats.realized_pnl)}
                        </div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Avg Trade Size</div>
                        <div className="stat-value">{formatCurrency(stats.avg_trade_size)}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Best Trade</div>
                        <div className="stat-value profit">
                            {stats.best_trade ? formatCurrency(stats.best_trade) : "—"}
                        </div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Worst Trade</div>
                        <div className="stat-value loss">
                            {stats.worst_trade ? formatCurrency(stats.worst_trade) : "—"}
                        </div>
                    </div>
                </div>
            )}

            {/* Trades Table */}
            <div className="table-container">
                <div className="table-header">
                    <h2 className="table-title">Executed Trades</h2>
                    <span>Page {trades.page} of {trades.pages}</span>
                </div>

                {trades.items.length === 0 ? (
                    <div style={{ padding: "3rem", textAlign: "center", color: "var(--text-secondary)" }}>
                        No trades executed yet
                    </div>
                ) : (
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Ticker</th>
                                <th>Type</th>
                                <th>Shares</th>
                                <th>Price</th>
                                <th>Total</th>
                                <th>P&L</th>
                                <th>Date</th>
                            </tr>
                        </thead>
                        <tbody>
                            {trades.items.map((trade: Trade) => (
                                <tr key={trade.id}>
                                    <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                                        {trade.ticker}
                                    </td>
                                    <td>
                                        <span className={`badge badge-${trade.trade_type}`}>
                                            {trade.trade_type.toUpperCase()}
                                        </span>
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {trade.shares.toFixed(2)}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        ${trade.price.toFixed(2)}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        ${(trade.shares * trade.price).toFixed(2)}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {trade.pnl !== null ? (
                                            <span style={{ color: trade.pnl >= 0 ? "var(--profit)" : "var(--loss)" }}>
                                                {formatCurrency(trade.pnl)}
                                            </span>
                                        ) : (
                                            <span style={{ color: "var(--text-muted)" }}>—</span>
                                        )}
                                    </td>
                                    <td>{new Date(trade.executed_at).toLocaleDateString()}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}

                {/* Pagination */}
                {trades.pages > 1 && (
                    <div style={{ padding: "1rem", display: "flex", justifyContent: "center", gap: "0.5rem" }}>
                        {trades.page > 1 && (
                            <a href={`/trades?page=${trades.page - 1}`} className="btn btn-secondary">
                                ← Previous
                            </a>
                        )}
                        {trades.page < trades.pages && (
                            <a href={`/trades?page=${trades.page + 1}`} className="btn btn-secondary">
                                Next →
                            </a>
                        )}
                    </div>
                )}
            </div>
        </>
    );
}

function formatCurrency(value: number): string {
    const formatted = new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    }).format(Math.abs(value));

    if (value < 0) return `-${formatted}`;
    if (value > 0) return `+${formatted}`;
    return formatted;
}
