import { api } from "@/shared/lib/axios";
import type { PaginatedResponse, Project } from "@/shared/types";

export interface CreateProjectPayload {
  name: string;
  description?: string;
  requirements: string;
  tech_stack?: Record<string, unknown>;
}

export interface UpdateProjectPayload {
  name?: string;
  description?: string;
  requirements?: string;
  tech_stack?: Record<string, unknown>;
}

export interface ListProjectsParams {
  status?: string;
  offset?: number;
  limit?: number;
}

export const projectsApi = {
  list: (params: ListProjectsParams = {}) =>
    api
      .get<PaginatedResponse<Project>>("/projects", { params })
      .then((r) => r.data),

  get: (id: string) => api.get<Project>(`/projects/${id}`).then((r) => r.data),

  create: (payload: CreateProjectPayload) =>
    api.post<Project>("/projects", payload).then((r) => r.data),

  update: (id: string, payload: UpdateProjectPayload) =>
    api.put<Project>(`/projects/${id}`, payload).then((r) => r.data),

  remove: (id: string) => api.delete(`/projects/${id}`).then((r) => r.data),
};
