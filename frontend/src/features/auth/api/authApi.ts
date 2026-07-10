import { api } from "@/shared/lib/axios";
import type { TokenResponse, User } from "@/shared/types";

export interface RegisterPayload {
  email: string;
  password: string;
  full_name?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    api.post<User>("/auth/register", payload).then((r) => r.data),

  login: (payload: LoginPayload) =>
    api.post<TokenResponse>("/auth/login", payload).then((r) => r.data),

  refresh: (refreshToken: string) =>
    api
      .post<TokenResponse>("/auth/refresh", { refresh_token: refreshToken })
      .then((r) => r.data),

  me: () => api.get<User>("/users/me").then((r) => r.data),
};
