import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { StudentArtifact } from "./api";
import { useArtifactProgress } from "./useWorkspace";

afterEach(() => vi.unstubAllGlobals());

function setup(result: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "200",
        json: () => Promise.resolve(result),
      } as Response),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["student", "artifact", "a1"], {
    id: "a1",
    slide_last_index: null,
    audio_position_seconds: null,
    completed: false,
  });
  qc.setQueryData(["student", "me", "listening"], { items: [] });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, wrapper };
}

describe("useArtifactProgress", () => {
  it("writes saved positions back into the cached artifact", async () => {
    const { qc, wrapper } = setup({
      completed: false,
      slide_last_index: null,
      audio_position_seconds: 600,
      course_percent_complete: 10,
    });
    const { result } = renderHook(() => useArtifactProgress("a1", "nn"), { wrapper });
    act(() => result.current.mutate({ audio_position_seconds: 600 }));
    await waitFor(() =>
      expect(qc.getQueryData<StudentArtifact>(["student", "artifact", "a1"])).toMatchObject({
        audio_position_seconds: 600,
        slide_last_index: null,
      }),
    );
    // MyListening / Progress pages see the new position on next view
    expect(qc.getQueryState(["student", "me", "listening"])?.isInvalidated).toBe(true);
  });
});
