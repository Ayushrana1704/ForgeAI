/**
 * Fetches both analytics endpoints in parallel and surfaces combined state.
 *
 * Re-fetches when the component mounts.  Call `refetch()` to force a refresh.
 */
import { useState, useEffect, useCallback } from "react";
import { analyticsApi } from "@/features/analytics/api/analyticsApi";
import type { AnalyticsOverview, RunHistoryResponse } from "@/shared/types";

interface AnalyticsState {
  overview: AnalyticsOverview | null;
  history: RunHistoryResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useAnalytics(): AnalyticsState {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [history, setHistory] = useState<RunHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, hist] = await Promise.all([
        analyticsApi.getOverview(),
        analyticsApi.getRuns(0, 20),
      ]);
      setOverview(ov);
      setHistory(hist);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load analytics";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return { overview, history, loading, error, refetch: fetchAll };
}
