"use client";

import { useState, useEffect } from "react";
import { actionsApi, politiciansApi } from "@/lib/api";

interface HealthStatus {
    status: string;
    components: {
        trading212: { configured: boolean; environment: string };
        openrouter: { configured: boolean; model: string };
        database: { exists: boolean; size_mb: number; signals: number; trades: number };
        cookies: { configured: boolean };
        whitelist: { configured: boolean };
    };
    running_tasks: { scraper: boolean; trader: boolean };
}

interface CookieStatus {
    configured: boolean;
    last_modified: string | null;
    has_csrftoken: boolean;
    has_sessionid: boolean;
}

interface SchedulerSettings {
    market_open_hour: number;
    market_close_hour: number;
    market_hours_min_interval: number;
    market_hours_max_interval: number;
    off_hours_interval: number;
}

export default function SettingsPage() {
    const [health, setHealth] = useState<HealthStatus | null>(null);
    const [cookies, setCookies] = useState<CookieStatus | null>(null);
    const [scheduler, setScheduler] = useState<SchedulerSettings | null>(null);
    const [loading, setLoading] = useState(true);
    const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

    // Cookie form
    const [csrftoken, setCsrftoken] = useState("");
    const [sessionid, setSessionid] = useState("");
    const [cookieLoading, setCookieLoading] = useState(false);
    const [rawJson, setRawJson] = useState("");
    const [cookieMode, setCookieMode] = useState<"simple" | "json">("simple");

    // Add politician form
    const [politicianName, setPoliticianName] = useState("");
    const [politicianChamber, setPoliticianChamber] = useState<"house" | "senate">("house");
    const [politicianLoading, setPoliticianLoading] = useState(false);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [healthData, cookiesData, schedulerData] = await Promise.all([
                actionsApi.getFullHealth().catch(() => null),
                actionsApi.getCookiesStatus().catch(() => null),
                actionsApi.getSchedulerSettings().catch(() => null),
            ]);
            setHealth(healthData);
            setCookies(cookiesData);
            setScheduler(schedulerData);
        } catch (error) {
            console.error("Failed to load settings:", error);
        } finally {
            setLoading(false);
        }
    };

    const handleUpdateCookies = async (e: React.FormEvent) => {
        e.preventDefault();

        if (cookieMode === "simple") {
            if (!csrftoken || !sessionid) {
                setMessage({ type: "error", text: "Both cookies are required" });
                return;
            }
        } else {
            if (!rawJson) {
                setMessage({ type: "error", text: "JSON content is required" });
                return;
            }
        }

        setCookieLoading(true);
        setMessage(null);

        try {
            const result = await actionsApi.updateCookies(
                cookieMode === "simple" ? csrftoken : undefined,
                cookieMode === "simple" ? sessionid : undefined,
                cookieMode === "json" ? rawJson : undefined
            );
            setMessage({ type: "success", text: result.message });
            setCsrftoken("");
            setSessionid("");
            setRawJson("");
            loadData();
        } catch (error) {
            setMessage({ type: "error", text: error instanceof Error ? error.message : "Failed to update cookies" });
        } finally {
            setCookieLoading(false);
        }
    };

    const handleAddPolitician = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!politicianName) {
            setMessage({ type: "error", text: "Politician name is required" });
            return;
        }

        setPoliticianLoading(true);
        setMessage(null);

        try {
            await politiciansApi.add({
                name: politicianName,
                chamber: politicianChamber,
            });
            setMessage({ type: "success", text: `Added ${politicianName} to whitelist` });
            setPoliticianName("");
        } catch (error) {
            setMessage({ type: "error", text: error instanceof Error ? error.message : "Failed to add politician" });
        } finally {
            setPoliticianLoading(false);
        }
    };

    if (loading) {
        return (
            <div className="settings-page">
                <header className="page-header">
                    <h1 className="page-title">Settings</h1>
                    <p className="page-subtitle">Loading...</p>
                </header>
            </div>
        );
    }

    return (
        <div className="settings-page">
            <header className="page-header">
                <h1 className="page-title">⚙️ Settings & Management</h1>
                <p className="page-subtitle">Configure system settings, update cookies, and manage politicians</p>
            </header>

            {message && (
                <div className={`settings-message ${message.type}`}>
                    {message.type === "success" ? "✓" : "✗"} {message.text}
                </div>
            )}

            <div className="settings-grid">
                {/* System Health */}
                <div className="settings-card">
                    <h2 className="settings-card-title">🩺 System Health</h2>
                    <div className="health-status">
                        <div className={`health-badge ${health?.status === "healthy" ? "healthy" : "degraded"}`}>
                            {health?.status === "healthy" ? "✓ All Systems Go" : "⚠ Degraded"}
                        </div>
                    </div>
                    <div className="health-grid">
                        <HealthItem
                            label="Trading212"
                            ok={health?.components.trading212.configured ?? false}
                            detail={health?.components.trading212.environment ?? "—"}
                        />
                        <HealthItem
                            label="OpenRouter"
                            ok={health?.components.openrouter.configured ?? false}
                            detail={health?.components.openrouter.model?.split("/")[1] ?? "—"}
                        />
                        <HealthItem
                            label="Database"
                            ok={health?.components.database.exists ?? false}
                            detail={`${health?.components.database.size_mb ?? 0} MB`}
                        />
                        <HealthItem
                            label="Cookies"
                            ok={health?.components.cookies.configured ?? false}
                            detail={cookies?.configured ? "Valid" : "Expired"}
                        />
                    </div>
                </div>

                {/* Scheduler Info */}
                <div className="settings-card">
                    <h2 className="settings-card-title">⏰ Scheduler Settings</h2>
                    <div className="scheduler-info">
                        <div className="scheduler-row">
                            <span className="scheduler-label">Market Hours</span>
                            <span className="scheduler-value">
                                {scheduler?.market_open_hour}:00 - {scheduler?.market_close_hour}:00 ET
                            </span>
                        </div>
                        <div className="scheduler-row">
                            <span className="scheduler-label">Market Interval</span>
                            <span className="scheduler-value">
                                {scheduler?.market_hours_min_interval}-{scheduler?.market_hours_max_interval} min
                            </span>
                        </div>
                        <div className="scheduler-row">
                            <span className="scheduler-label">Off-Hours Interval</span>
                            <span className="scheduler-value">
                                {scheduler?.off_hours_interval} min ({(scheduler?.off_hours_interval ?? 0) / 60}h)
                            </span>
                        </div>
                    </div>
                    <p className="settings-help">
                        Edit <code>config/settings.py</code> to change scheduler settings.
                    </p>
                </div>

                {/* Cookie Management */}
                <div className="settings-card settings-card-wide">
                    <h2 className="settings-card-title">🍪 Senate Cookie Management</h2>
                    <div className="cookie-status">
                        <div className={`cookie-indicator ${cookies?.configured ? "valid" : "expired"}`}>
                            {cookies?.configured ? "✓ Cookies Valid" : "⚠ Cookies Expired"}
                        </div>
                        {cookies?.last_modified && (
                            <span className="cookie-updated">
                                Last updated: {new Date(cookies.last_modified).toLocaleString()}
                            </span>
                        )}
                    </div>

                    <div className="cookie-tabs" style={{ marginBottom: "1rem" }}>
                        <button
                            className={`toggle-btn ${cookieMode === "simple" ? "active" : ""}`}
                            onClick={() => setCookieMode("simple")}
                            style={{ marginRight: "10px" }}
                        >
                            Simple (Session ID)
                        </button>
                        <button
                            className={`toggle-btn ${cookieMode === "json" ? "active" : ""}`}
                            onClick={() => setCookieMode("json")}
                        >
                            Advanced (Raw JSON)
                        </button>
                    </div>

                    <form onSubmit={handleUpdateCookies} className="cookie-form">
                        <div className="cookie-instructions">
                            <p><strong>To update cookies:</strong></p>
                            <ol>
                                <li>Open <a href="https://efdsearch.senate.gov/search/" target="_blank" rel="noopener noreferrer">efdsearch.senate.gov</a></li>
                                <li>Complete the CAPTCHA/checkbox</li>
                                {cookieMode === "simple" ? (
                                    <>
                                        <li>Open DevTools (F12) → Application → Cookies</li>
                                        <li>Copy the cookie values below</li>
                                    </>
                                ) : (
                                    <>
                                        <li>Use an extension like "EditThisCookie" to export as JSON</li>
                                        <li>Or paste the full cookie array from DevTools</li>
                                    </>
                                )}
                            </ol>
                        </div>

                        {cookieMode === "simple" ? (
                            <>
                                <div className="form-group">
                                    <label htmlFor="csrftoken">csrftoken</label>
                                    <input
                                        id="csrftoken"
                                        type="text"
                                        value={csrftoken}
                                        onChange={(e) => setCsrftoken(e.target.value)}
                                        placeholder="Enter csrftoken value"
                                        className="input"
                                    />
                                </div>
                                <div className="form-group">
                                    <label htmlFor="sessionid">sessionid</label>
                                    <input
                                        id="sessionid"
                                        type="text"
                                        value={sessionid}
                                        onChange={(e) => setSessionid(e.target.value)}
                                        placeholder="Enter sessionid value"
                                        className="input"
                                    />
                                </div>
                            </>
                        ) : (
                            <div className="form-group">
                                <label htmlFor="rawJson">Raw Cookies JSON</label>
                                <textarea
                                    id="rawJson"
                                    value={rawJson}
                                    onChange={(e) => setRawJson(e.target.value)}
                                    placeholder='[{"name": "csrftoken", "value": "..."}]'
                                    className="input"
                                    style={{ minHeight: "150px", fontFamily: "monospace" }}
                                />
                            </div>
                        )}

                        <button type="submit" className="btn btn-primary" disabled={cookieLoading}>
                            {cookieLoading ? "Updating..." : "Update Cookies"}
                        </button>
                    </form>
                </div>

                {/* Quick Add Politician */}
                <div className="settings-card">
                    <h2 className="settings-card-title">👤 Quick Add Politician</h2>
                    <form onSubmit={handleAddPolitician} className="politician-form">
                        <div className="form-group">
                            <label htmlFor="politicianName">Name</label>
                            <input
                                id="politicianName"
                                type="text"
                                value={politicianName}
                                onChange={(e) => setPoliticianName(e.target.value)}
                                placeholder="e.g., Nancy Pelosi"
                                className="input"
                            />
                        </div>
                        <div className="form-group">
                            <label>Chamber</label>
                            <div className="chamber-toggle">
                                <button
                                    type="button"
                                    className={`toggle-btn ${politicianChamber === "house" ? "active" : ""}`}
                                    onClick={() => setPoliticianChamber("house")}
                                >
                                    House
                                </button>
                                <button
                                    type="button"
                                    className={`toggle-btn ${politicianChamber === "senate" ? "active" : ""}`}
                                    onClick={() => setPoliticianChamber("senate")}
                                >
                                    Senate
                                </button>
                            </div>
                        </div>
                        <button type="submit" className="btn btn-primary" disabled={politicianLoading}>
                            {politicianLoading ? "Adding..." : "Add to Whitelist"}
                        </button>
                    </form>
                    <p className="settings-help">
                        Visit <a href="/politicians">Politicians page</a> to view and manage the full list.
                    </p>
                </div>

                {/* Quick Links */}
                <div className="settings-card">
                    <h2 className="settings-card-title">🔗 Quick Links</h2>
                    <div className="quick-links">
                        <a href="https://www.capitoltrades.com/" target="_blank" rel="noopener noreferrer" className="quick-link">
                            📊 Capitol Trades
                        </a>
                        <a href="https://unusualwhales.com/congress" target="_blank" rel="noopener noreferrer" className="quick-link">
                            🐋 Unusual Whales
                        </a>
                        <a href="https://efdsearch.senate.gov/search/" target="_blank" rel="noopener noreferrer" className="quick-link">
                            🏛️ Senate Disclosures
                        </a>
                        <a href="https://disclosures-clerk.house.gov/FinancialDisclosure" target="_blank" rel="noopener noreferrer" className="quick-link">
                            🏠 House Disclosures
                        </a>
                        <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer" className="quick-link">
                            📖 API Docs
                        </a>
                    </div>
                </div>
            </div>
        </div>
    );
}

function HealthItem({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
    return (
        <div className="health-item">
            <div className={`health-dot ${ok ? "ok" : "error"}`} />
            <div className="health-info">
                <span className="health-label">{label}</span>
                <span className="health-detail">{detail}</span>
            </div>
        </div>
    );
}
