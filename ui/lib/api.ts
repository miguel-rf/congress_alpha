/**
 * API Client for Congressional Alpha Backend
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class ApiError extends Error {
    constructor(public status: number, message: string) {
        super(message);
        this.name = "ApiError";
    }
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;

    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...options?.headers,
        },
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: "Unknown error" }));
        throw new ApiError(response.status, error.detail || "Request failed");
    }

    return response.json();
}

// Signals API
export const signalsApi = {
    list: (params?: { page?: number; page_size?: number; processed?: boolean }) => {
        const searchParams = new URLSearchParams();
        if (params?.page) searchParams.set("page", String(params.page));
        if (params?.page_size) searchParams.set("page_size", String(params.page_size));
        if (params?.processed !== undefined) searchParams.set("processed", String(params.processed));

        const query = searchParams.toString();
        return request<import("./types").PaginatedSignals>(`/api/signals${query ? `?${query}` : ""}`);
    },

    getPending: () => request<import("./types").TradeSignal[]>("/api/signals/pending"),

    getConfirmations: () => request<import("./types").TradeSignal[]>("/api/signals/confirmations"),

    getById: (id: number) => request<import("./types").TradeSignal>(`/api/signals/${id}`),

    markProcessed: (id: number) => request<{ status: string; message: string }>(`/api/signals/${id}/process`, { method: "POST" }),

    confirm: (id: number) => request<{ status: string; message: string }>(`/api/signals/${id}/confirm`, { method: "POST" }),

    reject: (id: number) => request<{ status: string; message: string }>(`/api/signals/${id}/reject`, { method: "POST" }),

    delete: (id: number) => request<{ status: string; message: string }>(`/api/signals/${id}`, { method: "DELETE" }),

    deleteAll: (processedOnly: boolean = false) => 
        request<{ status: string; message: string; deleted_count: number }>(
            `/api/signals?processed_only=${processedOnly}`, 
            { method: "DELETE" }
        ),
};

// Trades API
export const tradesApi = {
    list: (params?: { page?: number; page_size?: number; ticker?: string }) => {
        const searchParams = new URLSearchParams();
        if (params?.page) searchParams.set("page", String(params.page));
        if (params?.page_size) searchParams.set("page_size", String(params.page_size));
        if (params?.ticker) searchParams.set("ticker", params.ticker);

        const query = searchParams.toString();
        return request<import("./types").PaginatedTrades>(`/api/trades${query ? `?${query}` : ""}`);
    },

    getStats: () => request<import("./types").TradeStats>("/api/trades/stats"),

    getByTicker: (ticker: string) => request<import("./types").Trade[]>(`/api/trades/ticker/${ticker}`),
};

// Portfolio API
export const portfolioApi = {
    getPositions: () => request<import("./types").Position[]>("/api/portfolio/positions"),

    getSummary: () => request<import("./types").AccountSummary>("/api/portfolio/summary"),

    getCash: () => request<{ free: number; total: number; currency: string }>("/api/portfolio/cash"),
};

// Politicians API
export const politiciansApi = {
    list: () => request<import("./types").Politician[]>("/api/politicians"),

    getCount: () => request<import("./types").PoliticianCount>("/api/politicians/count"),

    add: (politician: { name: string; chamber: string; notes?: string }) =>
        request<import("./types").Politician>("/api/politicians", {
            method: "POST",
            body: JSON.stringify(politician),
        }),

    remove: (name: string) =>
        request<{ status: string; message: string }>(`/api/politicians/${encodeURIComponent(name)}`, {
            method: "DELETE",
        }),
};

// System API
export const systemApi = {
    getStats: () => request<import("./types").SystemStats>("/api/stats"),

    getLogs: (params?: { limit?: number; level?: string }) => {
        const searchParams = new URLSearchParams();
        if (params?.limit) searchParams.set("limit", String(params.limit));
        if (params?.level) searchParams.set("level", params.level);

        const query = searchParams.toString();
        return request<import("./types").LogEntry[]>(`/api/logs${query ? `?${query}` : ""}`);
    },

    getConfig: () => request<import("./types").SystemConfig>("/api/config"),

    getSchedulerStatus: () => request<import("./types").SchedulerStatus>("/api/scheduler/status"),
};

// Health check
export const healthApi = {
    check: () => request<{ status: string }>("/health"),
};

// Actions API - Control scraper and trading from dashboard
export const actionsApi = {
    getStatus: () => request<{ scraper_running: boolean; trader_running: boolean }>("/api/actions/status"),

    triggerScrape: () => request<{ success: boolean; message: string; task_id?: string }>("/api/actions/scrape", { method: "POST" }),

    triggerTrade: () => request<{ success: boolean; message: string; task_id?: string }>("/api/actions/trade", { method: "POST" }),

    triggerFullCycle: () => request<{ success: boolean; message: string; task_id?: string }>("/api/actions/cycle", { method: "POST" }),

    stopTasks: () => request<{ success: boolean; message: string }>("/api/actions/stop", { method: "POST" }),

    // Cookie management
    getCookiesStatus: () => request<{
        configured: boolean;
        last_modified: string | null;
        has_csrftoken: boolean;
        has_sessionid: boolean;
    }>("/api/actions/cookies"),

    updateCookies: (csrftoken?: string, sessionid?: string, raw_json?: string) =>
        request<{ success: boolean; message: string }>("/api/actions/cookies", {
            method: "POST",
            body: JSON.stringify({ csrftoken, sessionid, raw_json }),
        }),

    testCookies: () =>
        request<{ success: boolean; message: string }>("/api/actions/cookies/test", {
            method: "POST"
        }),

    testOpenRouter: () =>
        request<{ success: boolean; message: string }>("/api/actions/openrouter/test", {
            method: "POST"
        }),

    // Scheduler settings
    getSchedulerSettings: () => request<{
        market_open_hour: number;
        market_close_hour: number;
        market_hours_min_interval: number;
        market_hours_max_interval: number;
        off_hours_interval: number;
        jitter_min: number;
        jitter_max: number;
    }>("/api/actions/scheduler/settings"),

    // Full system health
    getFullHealth: () => request<{
        status: string;
        components: {
            trading212: { configured: boolean; environment: string };
            openrouter: { configured: boolean; model: string };
            database: { exists: boolean; size_mb: number; signals: number; trades: number };
            cookies: { configured: boolean };
            whitelist: { configured: boolean };
        };
        running_tasks: { scraper: boolean; trader: boolean };
    }>("/api/actions/health/full"),

    // Database cleanup
    cleanupDatabase: () => request<{ success: boolean; message: string }>("/api/actions/database/cleanup", { method: "POST" }),
};
