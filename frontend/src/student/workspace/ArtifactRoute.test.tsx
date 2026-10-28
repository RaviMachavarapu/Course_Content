import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { ArtifactRoute } from "./ArtifactRoute";
import type { WorkspaceContext } from "./WorkspaceLayout";

afterEach(() => vi.unstubAllGlobals());

const course: WorkspaceContext["course"] = {
  id: "c1",
  slug: "nn",
  title: "NN",
  description: "",
  percent_complete: 0,
  current_module_index: 0,
  modules: [0, 1].map((i) => ({
    index: i,
    id: `m${i}`,
    title: `Unit ${i}`,
    percent_complete: 0,
    artifacts: [
      { id: i === 0 ? "FA" : "FB", type: "flashcards" as const, completed: false },
      { id: i === 0 ? "SA" : "SB", type: "slide_deck" as const, completed: false },
    ],
  })),
};

function artifact(id: string) {
  const isSlides = id.startsWith("S");
  return {
    id,
    type: isSlides ? "slide_deck" : "flashcards",
    module_id: "m",
    module_index: 0,
    course_slug: "nn",
    revision: 1,
    content_json: isSlides
      ? { slides: [] }
      : {
          cards: [
            { front: `${id}-Q0`, back: "A0" },
            { front: `${id}-Q1`, back: "A1" },
          ],
        },
    content_html: null,
    media: isSlides
      ? [0, 1, 2].map((p) => ({ kind: "slide_png", url: `/m/${id}/${p}.png`, page_index: p }))
      : [],
    completed: false,
    slide_last_index: isSlides && id === "SB" ? 1 : null,
    audio_position_seconds: null,
    flashcard_ratings: {},
  };
}

function installFetch() {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const id = url.match(/artifacts\/([A-Z]+)/)?.[1] ?? "";
    const body =
      method === "PUT"
        ? {
            completed: true,
            slide_last_index: null,
            audio_position_seconds: null,
            course_percent_complete: 0,
          }
        : artifact(id);
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: "200",
      json: () => Promise.resolve(body),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function progressPuts(fn: ReturnType<typeof vi.fn>, id: string) {
  return fn.mock.calls
    .filter(
      (c) =>
        (c[1] as RequestInit | undefined)?.method === "PUT" &&
        String(c[0]).includes(`/artifacts/${id}/progress`),
    )
    .map((c) => JSON.parse((c[1] as RequestInit).body as string) as Record<string, unknown>);
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/learn/:slug"
            element={
              <>
                <Link to="/learn/nn/1/flashcards">go-fb</Link>
                <Link to="/learn/nn/1/slide_deck">go-sb</Link>
                <Outlet context={{ course } satisfies WorkspaceContext} />
              </>
            }
          >
            <Route path=":moduleIndex/:type" element={<ArtifactRoute />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ArtifactRoute switching modules (same type)", () => {
  it("does not carry flashcard progress into the next module's deck", async () => {
    const fetchMock = installFetch();
    renderAt("/learn/nn/0/flashcards");
    await screen.findByText("FA-Q0");
    await userEvent.click(screen.getByTestId("btn-fc3"));
    await waitFor(() => expect(progressPuts(fetchMock, "FA")).toContainEqual({ completed: true }));

    await userEvent.click(screen.getByText("go-fb"));
    await screen.findByText("FB-Q0");
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(progressPuts(fetchMock, "FB")).toEqual([]);
  });

  it("resumes the next deck at its own saved slide and never marks it complete", async () => {
    const fetchMock = installFetch();
    renderAt("/learn/nn/0/slide_deck");
    await screen.findByText("Slide 1 of 3");
    await userEvent.click(screen.getByTestId("btn-sd2"));
    await userEvent.click(screen.getByTestId("btn-sd2"));
    expect(screen.getByText("Slide 3 of 3")).toBeInTheDocument();

    await userEvent.click(screen.getByText("go-sb"));
    expect(await screen.findByText("Slide 2 of 3")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 600));
    expect(progressPuts(fetchMock, "SB").some((b) => b.completed)).toBe(false);
  });
});
