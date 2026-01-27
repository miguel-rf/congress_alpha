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

    getById: (id: number) => request<import("./types").TradeSignal>(`/api/signals/${id}`),

    markProcessed: (id: number) => request<{ status: string; message: string }>(`/api/signals/${id}/process`, { method: "POST" }),
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
