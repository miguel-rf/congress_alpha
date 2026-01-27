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

            {/* Filters */}
            <div style={{ marginBottom: "1.5rem", display: "flex", gap: "1rem" }}>
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
                                        <span className={`badge badge-${signal.processed ? "processed" : "pending"}`}>
                                            {signal.processed ? "Processed" : "Pending"}
                                        </span>
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
