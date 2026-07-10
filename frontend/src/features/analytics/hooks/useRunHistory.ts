/**
 * useRunHistory — data hook for the Run History page (/runs).
 *
 * Fetches up to 100 runs in a single request, then filters and searches
 * client-side so every keystroke is instant with no round-trips.
 *
 * Exposes:
 *  runs          — filtered + searched subset of the fetched data
 *  total         — server-side total (may exceed 100 if account is large)
 *  loading / error / refetch — standard async state
 *  search / setSearch        — project name filter (case-insensitive substring)
 *  statusFilter / setStatusFilter — "all" | RunStatusValue
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { analyticsApi } from "@/features/analytics/api/analyticsApi";
import type { RunHistoryItem, RunStatusValue } from "@/shared/types";

export type StatusFilter = RunStatusValue | "all";

interface RunHistoryState {
  runs: RunHistoryItem[];       // filtered view
  allRuns: RunHistoryItem[];    // full fetched list (pre-filter)
  total: number;                // server total (may be > allRuns.length)
  loading: boolean;
  error: string | null;
  search: string;
  setSearch: (v: string) => void;
  statusFilter: StatusFilter;
  setStatusFilter: (v: StatusFilter) => void;
  refetch: () => void;
}

const PAGE_SIZE = 100; // fetch cap; covers most accounts without pagination

export function useRunHistory(): RunHistoryState {
  const [allRuns, setAllRuns] = useState<RunHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await analyticsApi.getRuns(0, PAGE_SIZE);
      setAllRuns(data.items);
      setTotal(data.total);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load run history";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Client-side filtering — O(n) over ≤100 items, fast enough
  const runs = useMemo(() => {
    let result = allRuns;

    if (statusFilter !== "all") {
      result = result.filter((r) => r.status === statusFilter);
    }

    const q = search.trim().toLowerCase();
    if (q) {
      result = result.filter((r) => r.project_name.toLowerCase().includes(q));
    }

    return result;
  }, [allRuns, statusFilter, search]);

  return {
    runs,
    allRuns,
    total,
    loading,
    error,
    search,
    setSearch,
    statusFilter,
    setStatusFilter,
    refetch: fetchRuns,
  };
}
