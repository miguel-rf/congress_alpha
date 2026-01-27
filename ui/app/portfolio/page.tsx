import { portfolioApi } from "@/lib/api";
import type { Position, AccountSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

async function fetchPortfolio() {
    try {
        const [positions, summary] = await Promise.all([
            portfolioApi.getPositions(),
            portfolioApi.getSummary(),
        ]);
        return { positions, summary, error: null };
    } catch (err) {
        return { positions: [], summary: null, error: String(err) };
    }
}

export default async function PortfolioPage() {
    const { positions, summary, error } = await fetchPortfolio();

    return (
        <>
            <header className="page-header">
                <h1 className="page-title">Portfolio</h1>
                <p className="page-subtitle">Trading212 account positions and performance</p>
            </header>

            {error && (
                <div className="card" style={{ background: "rgba(248, 81, 73, 0.1)", borderColor: "var(--loss)", marginBottom: "1.5rem" }}>
                    <p style={{ color: "var(--loss)" }}>
                        ⚠️ Unable to fetch portfolio data. Ensure Trading212 API is configured and the backend is running.
                    </p>
                </div>
            )}

            {/* Account Summary */}
            {summary && (
                <div className="stats-grid">
                    <div className="stat-card">
                        <div className="stat-label">Total Value</div>
                        <div className="stat-value">{formatCurrency(summary.total_value)}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Cash Available</div>
                        <div className="stat-value">{formatCurrency(summary.cash_available)}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Invested Value</div>
                        <div className="stat-value">{formatCurrency(summary.invested_value)}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Unrealized P&L</div>
                        <div className={`stat-value ${summary.unrealized_pnl >= 0 ? "profit" : "loss"}`}>
                            {formatCurrency(summary.unrealized_pnl)}
                        </div>
                    </div>
                </div>
            )}

            {/* Positions Table */}
            <div className="table-container">
                <div className="table-header">
                    <h2 className="table-title">Open Positions</h2>
                    <span>{positions.length} positions</span>
                </div>

                {positions.length === 0 ? (
                    <div style={{ padding: "3rem", textAlign: "center", color: "var(--text-secondary)" }}>
                        {error ? "Portfolio data unavailable" : "No open positions"}
                    </div>
                ) : (
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Ticker</th>
                                <th>Quantity</th>
                                <th>Avg Price</th>
                                <th>Current Price</th>
                                <th>Market Value</th>
                                <th>P&L</th>
                                <th>P&L %</th>
                            </tr>
                        </thead>
                        <tbody>
                            {positions.map((pos: Position) => (
                                <tr key={pos.ticker}>
                                    <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                                        {pos.ticker}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {pos.quantity.toFixed(2)}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        ${pos.average_price.toFixed(2)}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {pos.current_price ? `$${pos.current_price.toFixed(2)}` : "—"}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {pos.market_value ? formatCurrency(pos.market_value) : "—"}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {pos.pnl !== null ? (
                                            <span style={{ color: pos.pnl >= 0 ? "var(--profit)" : "var(--loss)" }}>
                                                {formatCurrency(pos.pnl)}
                                            </span>
                                        ) : "—"}
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        {pos.pnl_percent !== null ? (
                                            <span style={{ color: pos.pnl_percent >= 0 ? "var(--profit)" : "var(--loss)" }}>
                                                {pos.pnl_percent >= 0 ? "+" : ""}{pos.pnl_percent.toFixed(2)}%
                                            </span>
                                        ) : "—"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </>
    );
}

function formatCurrency(value: number): string {
    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);
}
