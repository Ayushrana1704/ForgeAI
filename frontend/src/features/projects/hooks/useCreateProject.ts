import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { projectsApi, type CreateProjectPayload } from "../api/projectsApi";
import { extractErrorMessage } from "@/shared/lib/axios";

export function useCreateProject() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const create = async (payload: CreateProjectPayload) => {
    setLoading(true);
    setError(null);
    try {
      const project = await projectsApi.create(payload);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return { create, loading, error };
}
