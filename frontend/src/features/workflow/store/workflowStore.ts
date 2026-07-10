/**
 * Workflow Zustand store.
 *
 * Tracks:
 *  - Live SSE stream state (events, streaming flag, active runId)
 *  - Recent run records persisted to localStorage for the dashboard
 */
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { WorkflowEvent, RunRecord } from "@/shared/types";

interface WorkflowState {
  // ── Streaming (ephemeral — not persisted) ────────────────────────────────
  streamRunId: string | null;
  events: WorkflowEvent[];
  streaming: boolean;

  startStream: (runId: string) => void;
  addEvent: (event: WorkflowEvent) => void;
  endStream: () => void;

  // ── Recent runs (persisted to localStorage) ───────────────────────────────
  recentRuns: RunRecord[];

  /**
   * Upsert a run record.
   *
   * Deep-merges with an existing record for the same run_id so that
   * callers do not need to supply every field — e.g. RunDetailPage can
   * update status/artifacts without knowing the project_name, and
   * ProjectDetailPage can set the project_name without knowing the
   * artifact count.  Empty / undefined string values do NOT overwrite
   * non-empty existing values.
   */
  upsertRun: (record: RunRecord) => void;
}

export const useWorkflowStore = create<WorkflowState>()(
  persist(
    (set) => ({
      // Streaming
      streamRunId: null,
      events: [],
      streaming: false,

      startStream: (runId) =>
        set({ streamRunId: runId, events: [], streaming: true }),

      addEvent: (event) =>
        set((s) => ({ events: [...s.events, event] })),

      endStream: () =>
        set({ streaming: false }),

      // Recent runs
      recentRuns: [],

      upsertRun: (record) =>
        set((s) => {
          const existing = s.recentRuns.find((r) => r.run_id === record.run_id);
          const merged: RunRecord = {
            ...existing,
            ...record,
            // Preserve non-empty string fields from the existing record
            // so that callers that don't know e.g. project_name don't
            // overwrite what a previous caller already set.
            project_name:
              record.project_name || existing?.project_name || "",
          };
          const others = s.recentRuns.filter((r) => r.run_id !== record.run_id);
          return { recentRuns: [merged, ...others].slice(0, 20) };
        }),
    }),
    {
      name: "forgeai-workflow",
      storage: createJSONStorage(() => localStorage),
      // Only persist recent runs; streaming state is ephemeral
      partialize: (state) => ({ recentRuns: state.recentRuns }),
    }
  )
);
