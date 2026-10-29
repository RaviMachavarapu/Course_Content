import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, reportSessionEnded } from "@/lib/api";
import { dropUserData, reportLogoutFailure } from "@/lib/sessionCache";
import { studentAuthApi, type User } from "./api";

const SESSION_KEY = ["student", "session"] as const;

/** Current student, or `null` when unauthenticated. `isPending` while first loading. */
export function useStudentSession(): {
  user: User | null;
  isPending: boolean;
  /** `/me` failed for another reason than "signed out" (5xx, network). */
  isError: boolean;
  refetch: () => unknown;
} {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: SESSION_KEY,
    queryFn: async () => {
      try {
        return await studentAuthApi.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          // signed in a moment ago: the session ended (expiry, reset, deactivation)
          if (qc.getQueryData(SESSION_KEY)) reportSessionEnded("/api/student/auth/me");
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

export function useLogin() {
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
    }) => studentAuthApi.login(email, password, remember),
    onSuccess: (user) => {
      // a different user may have used this tab: start from an empty cache
      qc.clear();
      qc.setQueryData(SESSION_KEY, user);
    },
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { email: string; password: string; displayName: string }) =>
      studentAuthApi.register(v.email, v.password, v.displayName),
    onSuccess: (user) => {
      // a different user may have used this tab: start from an empty cache
      qc.clear();
      qc.setQueryData(SESSION_KEY, user);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => studentAuthApi.logout(),
    onSuccess: () => {
      qc.clear();
      qc.setQueryData(SESSION_KEY, null);
    },
    onError: (err) => {
      // Still signed in on the server: keep the session, but don't keep the
      // cached data around either, and say so instead of navigating away.
      dropUserData(qc);
      reportLogoutFailure(err);
    },
  });
}
