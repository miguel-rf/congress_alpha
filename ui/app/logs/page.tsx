import { systemApi } from "@/lib/api";
import type { LogEntry, SystemConfig, SchedulerStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

async function fetchSystemData() {
    try {
        const [logs, config, schedulerStatus] = await Promise.all([
            systemApi.getLogs({ limit: 100 }),
            systemApi.getConfig(),
            systemApi.getSchedulerStatus(),
        ]);
        return { logs, config, schedulerStatus };
    } catch {
        return { logs: [], config: null, schedulerStatus: null };
    }
}

export default async function LogsPage() {
    const { logs, config, schedulerStatus } = await fetchSystemData();

    return (
        <>
            <header className="page-header">
                <h1 className="page-title">System Logs</h1>
                <p className="page-subtitle">Monitor system activity and configuration</p>
            </header>

            {/* System Status */}
            <div className="content-grid" style={{ marginBottom: "1.5rem" }}>
                {/* Scheduler Status */}
                <div className="card">
                    <h3 style={{ marginBottom: "1rem", fontSize: "1rem" }}>Scheduler Status</h3>
                    {schedulerStatus ? (
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                            <div>
                                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Market Hours:</span>
                                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.25rem" }}>
                                    <span className={`status-dot ${schedulerStatus.is_market_hours ? "online" : "offline"}`}></span>
                                    <span>{schedulerStatus.is_market_hours ? "Open" : "Closed"}</span>
                                </div>
                            </div>
                            <div>
                                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Interval:</span>
                                <div style={{ marginTop: "0.25rem" }}>{schedulerStatus.interval_minutes} minutes</div>
                            </div>
                            <div>
                                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Market Open:</span>
                                <div style={{ marginTop: "0.25rem" }}>{schedulerStatus.market_open}</div>
                            </div>
                            <div>
                                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>Market Close:</span>
                                <div style={{ marginTop: "0.25rem" }}>{schedulerStatus.market_close}</div>
                            </div>
                        </div>
                    ) : (
                        <p style={{ color: "var(--text-muted)" }}>Unable to fetch scheduler status</p>
                    )}
                </div>

                {/* Configuration */}
                <div className="card">
                    <h3 style={{ marginBottom: "1rem", fontSize: "1rem" }}>Configuration</h3>
                    {config ? (
                        <div style={{ fontSize: "0.875rem" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                                <span style={{ color: "var(--text-secondary)" }}>Trading212:</span>
                                <span className={`badge ${config.trading212_configured ? "badge-processed" : "badge-pending"}`}>
                                    {config.trading212_configured ? `${config.trading212_environment}` : "Not configured"}
                                </span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                                <span style={{ color: "var(--text-secondary)" }}>OpenRouter:</span>
                                <span className={`badge ${config.openrouter_configured ? "badge-processed" : "badge-pending"}`}>
                                    {config.openrouter_configured ? "Configured" : "Not configured"}
                                </span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                                <span style={{ color: "var(--text-secondary)" }}>Min Market Cap:</span>
                                <span>${(config.min_market_cap / 1_000_000).toFixed(0)}M</span>
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between" }}>
                                <span style={{ color: "var(--text-secondary)" }}>Wash Sale Days:</span>
                                <span>{config.wash_sale_days} days</span>
                            </div>
                        </div>
                    ) : (
                        <p style={{ color: "var(--text-muted)" }}>Unable to fetch configuration</p>
                    )}
                </div>
            </div>

            {/* Logs Table */}
            <div className="table-container">
                <div className="table-header">
                    <h2 className="table-title">Recent Logs</h2>
                    <span>{logs.length} entries</span>
                </div>

                {logs.length === 0 ? (
                    <div style={{ padding: "3rem", textAlign: "center", color: "var(--text-secondary)" }}>
                        No log entries found
                    </div>
                ) : (
                    <table className="table">
                        <thead>
                            <tr>
                                <th style={{ width: "100px" }}>Level</th>
                                <th style={{ width: "150px" }}>Module</th>
                                <th>Message</th>
                                <th style={{ width: "150px" }}>Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {logs.map((log: LogEntry) => (
                                <tr key={log.id}>
                                    <td>
                                        <span className={`badge ${getLevelBadge(log.level)}`}>
                                            {log.level}
                                        </span>
                                    </td>
                                    <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                                        {log.module}
                                    </td>
                                    <td style={{ fontSize: "0.875rem" }}>{log.message}</td>
                                    <td style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                                        {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
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

function getLevelBadge(level: string): string {
    switch (level.toUpperCase()) {
        case "ERROR":
            return "badge-sell";
        case "WARNING":
            return "badge-pending";
        case "INFO":
            return "badge-processed";
        default:
            return "";
    }
}
