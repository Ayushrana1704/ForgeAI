import { useEffect, useState } from "react";
import { projectsApi } from "../api/projectsApi";
import type { PaginatedResponse, Project } from "@/shared/types";
import { extractErrorMessage } from "@/shared/lib/axios";

export function useProjects() {
  const [data, setData] = useState<PaginatedResponse<Project> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProjects = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await projectsApi.list({ limit: 50 });
      setData(result);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchProjects();
  }, []);

  return { data, loading, error, refetch: fetchProjects };
}
