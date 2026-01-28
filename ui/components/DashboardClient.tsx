"use client";

import { useCallback, useState, useEffect } from "react";
import { usePolling, formatRelativeTime } from "@/lib/usePolling";
import { signalsApi, tradesApi, politiciansApi, systemApi, actionsApi } from "@/lib/api";
import type { SystemStats, TradeStats, TradeSignal, Politician } from "@/lib/types";
import ControlPanel from "./ControlPanel";

// Polling interval: 30 seconds
const POLL_INTERVAL = 30000;

export default function DashboardClient() {
    const [relativeTime, setRelativeTime] = useState<string>("—");

    // Poll dashboard data
    const fetchDashboardData = useCallback(async () => {
        const [stats, tradeStats, pendingSignals, politicians, actionStatus] = await Promise.all([
            systemApi.getStats().catch(() => null),
            tradesApi.getStats().catch(() => null),
            signalsApi.getPending().catch(() => []),
            politiciansApi.list().catch(() => []),
            actionsApi.getStatus().catch(() => null),
        ]);
        return { stats, tradeStats, pendingSignals, politicians, actionStatus };
    }, []);

    const { data, isLoading, isRefreshing, lastUpdated, refresh } = usePolling(
        fetchDashboardData,
        POLL_INTERVAL
    );

    // Update relative time every second
    useEffect(() => {
        const timer = setInterval(() => {
            setRelativeTime(formatRelativeTime(lastUpdated));
        }, 1000);
        return () => clearInterval(timer);
    }, [lastUpdated]);

    const stats = data?.stats;
    const tradeStats = data?.tradeStats;
    const pendingSignals = data?.pendingSignals ?? [];
    const politicians = data?.politicians ?? [];
    const actionStatus = data?.actionStatus ?? null;

    if (isLoading) {
        return <DashboardSkeleton />;
    }

    return (
        <>
            <header className="page-header">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                        <h1 className="page-title">Dashboard</h1>
                        <p className="page-subtitle">Congressional trading activity overview</p>
                    </div>
                    <RefreshIndicator
                        isRefreshing={isRefreshing}
                        lastUpdated={relativeTime}
                        onRefresh={refresh}
                    />
                </div>
            </header>

            {/* Control Panel */}
            <ControlPanel actionStatus={actionStatus} onActionComplete={refresh} />

            {/* Stats Grid */}
            <div className="stats-grid">
                <StatCard label="Total Signals" value={stats?.total_signals ?? "—"} />
                <StatCard
                    label="Pending Signals"
                    value={stats?.pending_signals ?? "—"}
                    highlight={stats?.pending_signals ? stats.pending_signals > 0 : false}
                />
                <StatCard label="Total Trades" value={tradeStats?.total_trades ?? "—"} />
                <StatCard
                    label="Win Rate"
                    value={tradeStats ? `${tradeStats.win_rate}%` : "—"}
                    isProfit={tradeStats ? tradeStats.win_rate >= 50 : undefined}
                />
                <StatCard
                    label="Realized P&L"
                    value={tradeStats ? formatCurrency(tradeStats.realized_pnl) : "—"}
                    isProfit={tradeStats ? tradeStats.realized_pnl >= 0 : undefined}
                />
                <StatCard label="Politicians Tracked" value={politicians.length} />
            </div>


            <div className="content-grid">
                {/* Pending Signals */}
                <div className="table-container">
                    <div className="table-header">
                        <h2 className="table-title">Pending Signals</h2>
                        <span className="badge badge-pending">{pendingSignals.length} pending</span>
                    </div>

                    {pendingSignals.length === 0 ? (
                        <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-secondary)" }}>
                            No pending signals
                        </div>
                    ) : (
                        <table className="table">
                            <thead>
                                <tr>
                                    <th>Ticker</th>
                                    <th>Politician</th>
                                    <th>Type</th>
                                    <th>Amount</th>
                                    <th>Lag</th>
                                </tr>
                            </thead>
                            <tbody>
                                {pendingSignals.slice(0, 5).map((signal: TradeSignal) => (
                                    <tr key={signal.id}>
                                        <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                                            {signal.ticker}
                                        </td>
                                        <td>{signal.politician}</td>
                                        <td>
                                            <span className={`badge badge-${signal.trade_type.toLowerCase()}`}>
                                                {signal.trade_type}
                                            </span>
                                        </td>
                                        <td style={{ fontFamily: "var(--font-mono)" }}>
                                            {formatCurrency(signal.amount_midpoint)}
                                        </td>
                                        <td>
                                            <span
                                                style={{
                                                    color: signal.lag_days <= 10 ? "var(--profit)" : "var(--pending)",
                                                }}
                                            >
                                                {signal.lag_days}d
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>

                {/* Politicians */}
                <div className="table-container">
                    <div className="table-header">
                        <h2 className="table-title">Tracked Politicians</h2>
                    </div>

                    {politicians.length === 0 ? (
                        <div style={{ padding: "2rem", textAlign: "center", color: "var(--text-secondary)" }}>
                            No politicians tracked
                        </div>
                    ) : (
                        <table className="table">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Chamber</th>
                                </tr>
                            </thead>
                            <tbody>
                                {politicians.slice(0, 8).map((p: Politician) => (
                                    <tr key={p.name}>
                                        <td>{p.name}</td>
                                        <td>
                                            <span className={`badge badge-${p.chamber}`}>{p.chamber}</span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>
        </>
    );
}

// Refresh Indicator Component
function RefreshIndicator({
    isRefreshing,
    lastUpdated,
    onRefresh,
}: {
    isRefreshing: boolean;
    lastUpdated: string;
    onRefresh: () => void;
}) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                Updated {lastUpdated}
            </span>
            <button
                onClick={onRefresh}
                disabled={isRefreshing}
                className="btn btn-secondary"
                style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
            >
                {isRefreshing ? (
                    <span className="refresh-spinner">↻</span>
                ) : (
                    "↻ Refresh"
                )}
            </button>
        </div>
    );
}

// Stat Card Component
function StatCard({
    label,
    value,
    isProfit,
    highlight,
}: {
    label: string;
    value: string | number;
    isProfit?: boolean;
    highlight?: boolean;
}) {
    let valueClass = "stat-value";
    if (isProfit === true) valueClass += " profit";
    if (isProfit === false) valueClass += " loss";

    return (
        <div
            className="stat-card"
            style={highlight ? { borderColor: "var(--pending)" } : undefined}
        >
            <div className="stat-label">{label}</div>
            <div className={valueClass}>{value}</div>
        </div>
    );
}

// Loading Skeleton
function DashboardSkeleton() {
    return (
        <>
            <header className="page-header">
                <h1 className="page-title">Dashboard</h1>
                <p className="page-subtitle">Loading...</p>
            </header>
            <div className="stats-grid">
                {[...Array(6)].map((_, i) => (
                    <div key={i} className="stat-card">
                        <div className="skeleton" style={{ height: "1rem", width: "60%", marginBottom: "0.5rem" }} />
                        <div className="skeleton" style={{ height: "2rem", width: "40%" }} />
                    </div>
                ))}
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
