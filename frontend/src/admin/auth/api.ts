import { apiFetch } from "@/lib/api";
import type { User } from "@/student/auth/api";

interface UserEnvelope {
  user: User;
}

const BASE = "/api/admin/auth";

export const adminAuthApi = {
  me: () => apiFetch<UserEnvelope>(`${BASE}/me`).then((r) => r.user),
  login: (email: string, password: string) =>
    apiFetch<UserEnvelope>(`${BASE}/login`, { method: "POST", body: { email, password } }).then(
      (r) => r.user,
    ),
  logout: () => apiFetch<void>(`${BASE}/logout`, { method: "POST" }),

  requestPasswordReset: (email: string) =>
    apiFetch<void>(`${BASE}/password-reset/request`, { method: "POST", body: { email } }),

  confirmPasswordReset: (token: string, password: string) =>
    apiFetch<void>(`${BASE}/password-reset/confirm`, {
      method: "POST",
      body: { token, password },
    }),
};
