import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { dropUserData, reportLogoutFailure } from "@/lib/sessionCache";
import { studentAuthApi, type User } from "./api";

const SESSION_KEY = ["student", "session"] as const;

/** Current student, or `null` when unauthenticated. `isPending` while first loading. */
export function useStudentSession(): {
  user: User | null;
  isPending: boolean;
} {
  const q = useQuery({
    queryKey: SESSION_KEY,
    queryFn: async () => {
      try {
        return await studentAuthApi.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    },
    staleTime: 60_000,
  });
  return { user: q.data ?? null, isPending: q.isPending };
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      studentAuthApi.login(email, password),
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
