/**
 * Hook: fetch run detail from GET /runs/{runId}.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { workflowApi } from "@/features/workflow/api/workflowApi";
import { extractErrorMessage } from "@/shared/lib/axios";
import type { RunDetail } from "@/shared/types";

export function useRun(runId: string | undefined) {
  const [data, setData] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchRun = useCallback(() => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    workflowApi
      .getRun(runId)
      .then((d) => { if (mountedRef.current) setData(d); })
      .catch((err) => { if (mountedRef.current) setError(extractErrorMessage(err)); })
      .finally(() => { if (mountedRef.current) setLoading(false); });
  }, [runId]);

  useEffect(() => {
    fetchRun();
  }, [fetchRun]);

  return { data, loading, error, refetch: fetchRun };
}
