"use client";

import { useCallback, useState, useEffect } from "react";
import { usePolling, formatRelativeTime } from "@/lib/usePolling";
import { signalsApi } from "@/lib/api";
import type { TradeSignal, PaginatedSignals } from "@/lib/types";
import { useSearchParams, useRouter } from "next/navigation";

const POLL_INTERVAL = 30000;

export default function SignalsClient() {
    const searchParams = useSearchParams();
    const router = useRouter();
    const [relativeTime, setRelativeTime] = useState<string>("—");
    const [actionLoading, setActionLoading] = useState<number | null>(null);

    const page = searchParams.get("page") ? parseInt(searchParams.get("page")!) : 1;
    const processedParam = searchParams.get("processed");
    const processed = processedParam === "true" ? true : processedParam === "false" ? false : undefined;

    const fetchSignals = useCallback(async () => {
        return await signalsApi.list({ page, page_size: 20, processed });
    }, [page, processed]);

    const { data: signals, isLoading, isRefreshing, lastUpdated, refresh } = usePolling(
        fetchSignals,
        POLL_INTERVAL
    );

    useEffect(() => {
        const timer = setInterval(() => {
            setRelativeTime(formatRelativeTime(lastUpdated));
        }, 1000);
        return () => clearInterval(timer);
    }, [lastUpdated]);

    const setFilter = (value: string | undefined) => {
        const params = new URLSearchParams();
        if (value !== undefined) params.set("processed", value);
        router.push(`/signals${params.toString() ? `?${params.toString()}` : ""}`);
    };

    const handleConfirm = async (signalId: number) => {
        setActionLoading(signalId);
        try {
            await signalsApi.confirm(signalId);
            refresh();
        } catch (error) {
            console.error("Failed to confirm signal:", error);
        } finally {
            setActionLoading(null);
        }
    };

    const handleReject = async (signalId: number) => {
        setActionLoading(signalId);
        try {
            await signalsApi.reject(signalId);
            refresh();
        } catch (error) {
            console.error("Failed to reject signal:", error);
        } finally {
            setActionLoading(null);
        }
    };

    const handleDelete = async (signalId: number) => {
        if (!confirm("Are you sure you want to delete this signal?")) return;
        
        setActionLoading(signalId);
        try {
            await signalsApi.delete(signalId);
            refresh();
        } catch (error) {
            console.error("Failed to delete signal:", error);
        } finally {
            setActionLoading(null);
        }
    };

    const handleDeleteAll = async (processedOnly: boolean) => {
        const message = processedOnly 
            ? "Are you sure you want to delete all PROCESSED signals?" 
            : "Are you sure you want to delete ALL signals? This cannot be undone!";
        
        if (!confirm(message)) return;
        
        try {
            const result = await signalsApi.deleteAll(processedOnly);
            alert(`Deleted ${result.deleted_count} signals`);
            refresh();
        } catch (error) {
            console.error("Failed to delete signals:", error);
        }
    };

    if (isLoading || !signals) {
        return <SignalsSkeleton />;
    }

    return (
        <>
            <header className="page-header">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                        <h1 className="page-title">Trade Signals</h1>
                        <p className="page-subtitle">Congressional disclosure signals for copy-trading</p>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                        <div className="live-indicator">
                            <span className="live-dot"></span>
                            <span>Live</span>
                        </div>
                        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                            {relativeTime}
                        </span>
                        <button
                            onClick={refresh}
                            disabled={isRefreshing}
                            className="btn btn-secondary"
                            style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
                        >
                            {isRefreshing ? <span className="refresh-spinner">↻</span> : "↻"}
                        </button>
                    </div>
                </div>
            </header>

            {/* Filters and Actions */}
            <div style={{ marginBottom: "1.5rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ display: "flex", gap: "1rem" }}>
                <button
                    onClick={() => setFilter(undefined)}
                    className={`btn ${processed === undefined ? "btn-primary" : "btn-secondary"}`}
                >
                    All
                </button>
                <button
                    onClick={() => setFilter("false")}
                    className={`btn ${processed === false ? "btn-primary" : "btn-secondary"}`}
                >
                    Pending
                </button>
                <button
                    onClick={() => setFilter("true")}
                    className={`btn ${processed === true ? "btn-primary" : "btn-secondary"}`}
                >
                    Processed
                </button>
                </div>
                
                {/* Delete Actions */}
                <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button
                        onClick={() => handleDeleteAll(true)}
                        className="btn btn-secondary"
                        style={{ fontSize: "0.75rem" }}
                        title="Delete only processed/executed signals"
                    >
                        🗑️ Clear Processed
                    </button>
                    <button
                        onClick={() => handleDeleteAll(false)}
                        className="btn btn-danger"
                        style={{ fontSize: "0.75rem" }}
                        title="Delete ALL signals (cannot be undone)"
                    >
                        🗑️ Delete All
                    </button>
                </div>
            </div>

            {/* Signals Table */}
            <div className="table-container">
                <div className="table-header">
                    <h2 className="table-title">Signals ({signals.total})</h2>
                    <span>Page {signals.page} of {signals.pages}</span>
                </div>

                {signals.items.length === 0 ? (
                    <div style={{ padding: "3rem", textAlign: "center", color: "var(--text-secondary)" }}>
                        No signals found
                    </div>
                ) : (
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Ticker</th>
                                <th>Politician</th>
                                <th>Chamber</th>
                                <th>Type</th>
                                <th>Amount</th>
                                <th>Trade Date</th>
                                <th>Lag</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {signals.items.map((signal: TradeSignal) => (
                                <tr key={signal.id}>
                                    <td style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                                        {signal.ticker}
                                    </td>
                                    <td>{signal.politician}</td>
                                    <td>
                                        <span className={`badge badge-${signal.chamber}`}>{signal.chamber}</span>
                                    </td>
                                    <td>
                                        <span className={`badge badge-${signal.trade_type.toLowerCase()}`}>
                                            {signal.trade_type}
                                        </span>
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)" }}>
                                        ${signal.amount_midpoint.toLocaleString()}
                                    </td>
                                    <td>{signal.trade_date}</td>
                                    <td>
                                        <span
                                            style={{
                                                color:
                                                    signal.lag_days <= 10
                                                        ? "var(--profit)"
                                                        : signal.lag_days <= 45
                                                            ? "var(--pending)"
                                                            : "var(--loss)",
                                            }}
                                        >
                                            {signal.lag_days}d
                                        </span>
                                    </td>
                                    <td>
                                        <span className={`badge badge-${signal.status || (signal.processed ? "executed" : "pending")}`}>
                                            {getStatusLabel(signal)}
                                        </span>
                                    </td>
                                    <td>
                                        <div style={{ display: "flex", gap: "0.5rem" }}>
                                            {signal.status === "pending_confirmation" && signal.id && (
                                                <>
                                                    <button
                                                        onClick={() => handleConfirm(signal.id!)}
                                                        disabled={actionLoading === signal.id}
                                                        className="btn btn-success"
                                                        style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
                                                    >
                                                        {actionLoading === signal.id ? "..." : signal.trade_type === "purchase" ? "Buy" : "Sell"}
                                                    </button>
                                                    <button
                                                        onClick={() => handleReject(signal.id!)}
                                                        disabled={actionLoading === signal.id}
                                                        className="btn btn-danger"
                                                        style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
                                                    >
                                                        {actionLoading === signal.id ? "..." : "Reject"}
                                                    </button>
                                                </>
                                            )}
                                            {signal.id && (
                                                <button
                                                    onClick={() => handleDelete(signal.id!)}
                                                    disabled={actionLoading === signal.id}
                                                    className="btn btn-secondary"
                                                    style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
                                                    title="Delete this signal"
                                                >
                                                    {actionLoading === signal.id ? "..." : "🗑️"}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}

                {/* Pagination */}
                {signals.pages > 1 && (
                    <div style={{ padding: "1rem", display: "flex", justifyContent: "center", gap: "0.5rem" }}>
                        {signals.page > 1 && (
                            <button
                                onClick={() => {
                                    const params = new URLSearchParams();
                                    params.set("page", String(signals.page - 1));
                                    if (processed !== undefined) params.set("processed", String(processed));
                                    router.push(`/signals?${params.toString()}`);
                                }}
                                className="btn btn-secondary"
                            >
                                ← Previous
                            </button>
                        )}
                        {signals.page < signals.pages && (
                            <button
                                onClick={() => {
                                    const params = new URLSearchParams();
                                    params.set("page", String(signals.page + 1));
                                    if (processed !== undefined) params.set("processed", String(processed));
                                    router.push(`/signals?${params.toString()}`);
                                }}
                                className="btn btn-secondary"
                            >
                                Next →
                            </button>
                        )}
                    </div>
                )}
            </div>
        </>
    );
}

function SignalsSkeleton() {
    return (
        <>
            <header className="page-header">
                <h1 className="page-title">Trade Signals</h1>
                <p className="page-subtitle">Loading...</p>
            </header>
            <div className="table-container">
                <div style={{ padding: "3rem", textAlign: "center" }}>
                    <div className="skeleton" style={{ height: "2rem", width: "200px", margin: "0 auto" }} />
                </div>
            </div>
        </>
    );
}

function getStatusLabel(signal: TradeSignal): string {
    if (signal.status === "pending_confirmation") return "Needs Confirmation";
    if (signal.status === "confirmed") return "Confirmed";
    if (signal.status === "rejected") return "Rejected";
    if (signal.status === "executed" || signal.processed) return "Executed";
    return "Pending";
}
