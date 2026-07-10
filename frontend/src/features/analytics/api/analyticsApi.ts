import { api } from "@/shared/lib/axios";
import type { AnalyticsOverview, RunHistoryResponse } from "@/shared/types";

async function getOverview(): Promise<AnalyticsOverview> {
  const { data } = await api.get<AnalyticsOverview>("/analytics/overview");
  return data;
}

async function getRuns(offset = 0, limit = 20): Promise<RunHistoryResponse> {
  const { data } = await api.get<RunHistoryResponse>("/analytics/runs", {
    params: { offset, limit },
  });
  return data;
}

export const analyticsApi = { getOverview, getRuns };
