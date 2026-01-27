"use client";

import { useState, useEffect, useCallback } from "react";

/**
 * Custom hook for polling data at regular intervals
 * @param fetchFn - Async function that returns data
 * @param interval - Polling interval in milliseconds (default: 30000)
 * @param enabled - Whether polling is enabled (default: true)
 */
export function usePolling<T>(
    fetchFn: () => Promise<T>,
    interval: number = 30000,
    enabled: boolean = true
) {
    const [data, setData] = useState<T | null>(null);
    const [error, setError] = useState<Error | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const fetchData = useCallback(async (isInitial: boolean = false) => {
        try {
            if (isInitial) {
                setIsLoading(true);
            } else {
                setIsRefreshing(true);
            }

            const result = await fetchFn();
            setData(result);
            setError(null);
            setLastUpdated(new Date());
        } catch (err) {
            setError(err instanceof Error ? err : new Error("Failed to fetch"));
        } finally {
            setIsLoading(false);
            setIsRefreshing(false);
        }
    }, [fetchFn]);

    // Initial fetch
    useEffect(() => {
        fetchData(true);
    }, [fetchData]);

    // Polling interval
    useEffect(() => {
        if (!enabled) return;

        const timer = setInterval(() => {
            fetchData(false);
        }, interval);

        return () => clearInterval(timer);
    }, [fetchData, interval, enabled]);

    // Manual refresh
    const refresh = useCallback(() => {
        fetchData(false);
    }, [fetchData]);

    return {
        data,
        error,
        isLoading,
        isRefreshing,
        lastUpdated,
        refresh,
    };
}

/**
 * Format relative time (e.g., "5 seconds ago")
 */
export function formatRelativeTime(date: Date | null): string {
    if (!date) return "Never";

    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

    if (seconds < 5) return "Just now";
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
}
