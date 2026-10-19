import { apiFetch } from "@/lib/api";

export type UserRole = "student" | "admin";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

interface UserEnvelope {
  user: User;
}

const BASE = "/api/student/auth";

export const studentAuthApi = {
  me: () => apiFetch<UserEnvelope>(`${BASE}/me`).then((r) => r.user),

  login: (email: string, password: string) =>
    apiFetch<UserEnvelope>(`${BASE}/login`, {
      method: "POST",
      body: { email, password },
    }).then((r) => r.user),

  register: (email: string, password: string, display_name: string) =>
    apiFetch<UserEnvelope>(`${BASE}/register`, {
      method: "POST",
      body: { email, password, display_name },
    }).then((r) => r.user),

  logout: () => apiFetch<void>(`${BASE}/logout`, { method: "POST" }),

  requestPasswordReset: (email: string) =>
    apiFetch<void>(`${BASE}/password-reset/request`, { method: "POST", body: { email } }),

  confirmPasswordReset: (token: string, password: string) =>
    apiFetch<void>(`${BASE}/password-reset/confirm`, {
      method: "POST",
      body: { token, password },
    }),
};
