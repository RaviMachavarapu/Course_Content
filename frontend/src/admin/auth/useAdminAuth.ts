import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, reportSessionEnded } from "@/lib/api";
import { dropUserData, reportLogoutFailure } from "@/lib/sessionCache";
import type { User } from "@/student/auth/api";
import { adminAuthApi } from "./api";

const ADMIN_SESSION_KEY = ["admin", "session"] as const;

export function useAdminSession(): {
  user: User | null;
  isPending: boolean;
  /** `/me` failed for another reason than "signed out" (5xx, network). */
  isError: boolean;
  refetch: () => unknown;
} {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ADMIN_SESSION_KEY,
    queryFn: async () => {
      try {
        return await adminAuthApi.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          // signed in a moment ago: the session ended (expiry, reset, deactivation)
          if (qc.getQueryData(ADMIN_SESSION_KEY)) reportSessionEnded("/api/admin/auth/me");
          return null;
        }
        throw err;
      }
    },
    staleTime: 60_000,
  });
  return {
    user: q.data ?? null,
    isPending: q.isPending,
    isError: q.isError && q.data == null,
    refetch: q.refetch,
  };
}

export function useAdminLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      email,
      password,
      remember = true,
    }: {
      email: string;
      password: string;
      remember?: boolean;
    }) => adminAuthApi.login(email, password, remember),
    onSuccess: (user) => {
      // a different user may have used this tab: start from an empty cache
      qc.clear();
      qc.setQueryData(ADMIN_SESSION_KEY, user);
    },
  });
}

export function useAdminLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => adminAuthApi.logout(),
    onSuccess: () => {
      qc.clear();
      qc.setQueryData(ADMIN_SESSION_KEY, null);
    },
    onError: (err) => {
      // Still signed in on the server: keep the session, but don't keep the
      // cached data around either, and say so instead of navigating away.
      dropUserData(qc);
      reportLogoutFailure(err);
    },
  });
}
