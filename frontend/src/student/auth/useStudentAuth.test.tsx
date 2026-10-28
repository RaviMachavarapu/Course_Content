import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { useAdminLogin, useAdminLogout } from "@/admin/auth/useAdminAuth";
import { useUIStore } from "@/lib/store";
import { mockFetch } from "./authTestUtils";
import { useLogin, useLogout } from "./useStudentAuth";

afterEach(() => {
  vi.unstubAllGlobals();
  useUIStore.setState({ toasts: [] });
});

const user = {
  id: "1",
  email: "b@example.com",
  display_name: "B",
  role: "student",
  is_active: true,
  created_at: "",
};

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["student", "session"], { id: "A" });
  qc.setQueryData(["admin", "session"], { id: "ADM" });
  qc.setQueryData(["student", "artifact", "x"], { slide_last_index: 7 });
  qc.setQueryData(["student", "catalog"], { courses: [] });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, wrapper };
}

describe.each([
  ["student", useLogout, ["student", "session"]],
  ["admin", useAdminLogout, ["admin", "session"]],
] as const)("%s logout", (_name, hook, sessionKey) => {
  it("drops every cached query of the previous user on success", async () => {
    mockFetch({ status: 204, body: null });
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => hook(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(qc.getQueryData(["student", "artifact", "x"])).toBeUndefined();
    expect(qc.getQueryData(["student", "catalog"])).toBeUndefined();
    expect(qc.getQueryData([...sessionKey])).toBeNull();
  });

  it("does not pretend to have logged out when the request fails", async () => {
    mockFetch({ status: 500, body: { error: { code: "error", message: "boom" } } });
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => hook(), { wrapper });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isError).toBe(true));
    // session not cleared locally -> the guard does not show the signed-out UI
    expect(qc.getQueryData([...sessionKey])).not.toBeNull();
    // the previous user's cached data is still dropped
    expect(qc.getQueryData(["student", "artifact", "x"])).toBeUndefined();
    const toasts = useUIStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({ tone: "error", title: "Couldn’t log out" });
  });
});

describe.each([
  ["student", useLogin, ["student", "session"]],
  ["admin", useAdminLogin, ["admin", "session"]],
] as const)("%s login", (_name, hook, sessionKey) => {
  it("starts from an empty cache so nothing of the previous user leaks", async () => {
    mockFetch({ status: 200, body: { user } });
    const { qc, wrapper } = setup();
    const { result } = renderHook(() => hook(), { wrapper });
    act(() => result.current.mutate({ email: "b@example.com", password: "pw" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(qc.getQueryData(["student", "artifact", "x"])).toBeUndefined();
    expect(qc.getQueryData([...sessionKey])).toEqual(user);
  });
});
