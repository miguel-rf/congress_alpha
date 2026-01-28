"use client";

import { useState } from "react";
import { actionsApi } from "@/lib/api";

interface ActionStatus {
    scraper_running: boolean;
    trader_running: boolean;
}

export default function ControlPanel({
    actionStatus,
    onActionComplete,
}: {
    actionStatus: ActionStatus | null;
    onActionComplete: () => void;
}) {
    const [loading, setLoading] = useState<string | null>(null);
    const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

    const scraperRunning = actionStatus?.scraper_running ?? false;
    const traderRunning = actionStatus?.trader_running ?? false;
    const anyRunning = scraperRunning || traderRunning;

    const handleAction = async (
        action: "scrape" | "trade" | "cycle",
        apiCall: () => Promise<{ success: boolean; message: string }>
    ) => {
        setLoading(action);
        setMessage(null);

        try {
            const result = await apiCall();
            setMessage({ type: "success", text: result.message });
            // Refresh data after a delay
            setTimeout(onActionComplete, 1000);
        } catch (error) {
            setMessage({
                type: "error",
                text: error instanceof Error ? error.message : "Action failed",
            });
        } finally {
            setLoading(null);
        }
    };

    return (
        <div className="control-panel">
            <div className="control-panel-header">
                <h2 className="table-title">⚡ Control Panel</h2>
                <div className="status-indicator">
                    {anyRunning ? (
                        <span className="status-badge running">
                            <span className="pulse" /> Running
                        </span>
                    ) : (
                        <span className="status-badge idle">Idle</span>
                    )}
                </div>
            </div>

            <div className="control-panel-buttons">
                <button
                    className="btn btn-action btn-scrape"
                    onClick={() => handleAction("scrape", actionsApi.triggerScrape)}
                    disabled={loading !== null || scraperRunning}
                >
                    {loading === "scrape" || scraperRunning ? (
                        <span className="btn-loading">
                            <span className="spinner" /> {scraperRunning ? "Scraping..." : "Starting..."}
                        </span>
                    ) : (
                        <>
                            <span className="btn-icon">🔍</span>
                            Run Scraper
                        </>
                    )}
                </button>

                <button
                    className="btn btn-action btn-trade"
                    onClick={() => handleAction("trade", actionsApi.triggerTrade)}
                    disabled={loading !== null || traderRunning}
                >
                    {loading === "trade" || traderRunning ? (
                        <span className="btn-loading">
                            <span className="spinner" /> {traderRunning ? "Trading..." : "Starting..."}
                        </span>
                    ) : (
                        <>
                            <span className="btn-icon">💹</span>
                            Execute Trades
                        </>
                    )}
                </button>

                <button
                    className="btn btn-action btn-cycle"
                    onClick={() => handleAction("cycle", actionsApi.triggerFullCycle)}
                    disabled={loading !== null || anyRunning}
                >
                    {loading === "cycle" || anyRunning ? (
                        <span className="btn-loading">
                            <span className="spinner" /> Running...
                        </span>
                    ) : (
                        <>
                            <span className="btn-icon">🔄</span>
                            Full Cycle
                        </>
                    )}
                </button>
            </div>

            {message && (
                <div className={`control-message ${message.type}`}>
                    {message.type === "success" ? "✓" : "✗"} {message.text}
                </div>
            )}

            <div className="control-panel-help">
                <p><strong>🔍 Scraper:</strong> Fetch new disclosures from House & Senate</p>
                <p><strong>💹 Trades:</strong> Process pending signals and execute trades</p>
                <p><strong>🔄 Full Cycle:</strong> Run both scraper and trades sequentially</p>
            </div>
        </div>
    );
}
