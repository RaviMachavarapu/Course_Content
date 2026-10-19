import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AudioPlayer } from "./AudioPlayer";

let playSpy: ReturnType<typeof vi.spyOn>;
let pauseSpy: ReturnType<typeof vi.spyOn>;

beforeAll(() => {
  playSpy = vi
    .spyOn(window.HTMLMediaElement.prototype, "play")
    .mockImplementation(() => Promise.resolve());
  pauseSpy = vi.spyOn(window.HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterAll(() => {
  playSpy.mockRestore();
  pauseSpy.mockRestore();
});
afterEach(() => vi.unstubAllGlobals());

const ARTIFACT = {
  id: "a-audio",
  type: "audio_overview",
  module_id: "m1",
  module_index: 0,
  course_slug: "nn",
  revision: 1,
  content_json: {
    duration_seconds: 180,
    voice: null,
    transcript: [
      { t: 0, text: "Welcome to the overview." },
      { t: 12, text: "Neurons combine inputs." },
      { t: 40, text: "Depth builds abstractions." },
    ],
  },
  content_html: null,
  media: [{ kind: "audio_mp3", url: "/api/media/audio.mp3", page_index: null }],
  completed: false,
  slide_last_index: null,
  audio_position_seconds: 12,
  flashcard_ratings: {},
};

function installFetch() {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/progress") && method === "PUT") {
      body = { completed: false, slide_last_index: null, audio_position_seconds: 12, course_percent_complete: 0 };
      status = 200;
    } else if (url.includes("/api/student/artifacts/")) {
      body = ARTIFACT;
      status = 200;
    }
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(body),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderPlayer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/learn/nn/0/audio_overview"]}>
        <Routes>
          <Route
            path="/learn/nn/0/audio_overview"
            element={
              <AudioPlayer artifactId="a-audio" slug="nn" nextHref="/learn/nn/0/slide_deck" />
            }
          />
          <Route path="/learn/nn/0/slide_deck" element={<div>NEXT LESSON</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AudioPlayer", () => {
  it("renders controls and shows total duration from content_json", async () => {
    installFetch();
    renderPlayer();
    expect(await screen.findByTestId("btn-au1")).toBeInTheDocument();
    expect(screen.getByTestId("btn-au5")).toHaveTextContent("1x");
    expect(screen.getByText("3:00")).toBeInTheDocument(); // 180s total
  });

  it("resumes from audio_position_seconds on loadedmetadata", async () => {
    installFetch();
    const { container } = renderPlayer();
    await screen.findByTestId("btn-au1");
    const audio = container.querySelector("audio")!;
    fireEvent.loadedMetadata(audio);
    expect(Math.round(audio.currentTime)).toBe(12);
  });

  it("cycles speed and toggles the transcript", async () => {
    installFetch();
    renderPlayer();
    await screen.findByTestId("btn-au1");

    await userEvent.click(screen.getByTestId("btn-au5"));
    expect(screen.getByTestId("btn-au5")).toHaveTextContent("1.25x");

    await userEvent.click(screen.getByTestId("btn-au7"));
    expect(screen.getByTestId("transcript-panel")).toBeInTheDocument();
    expect(screen.getByText("Neurons combine inputs.")).toBeInTheDocument();
  });

  it("Play calls the media element and Next Lesson navigates", async () => {
    installFetch();
    renderPlayer();
    await screen.findByTestId("btn-au1");

    await userEvent.click(screen.getByTestId("btn-au1"));
    expect(playSpy).toHaveBeenCalled();

    await userEvent.click(screen.getByTestId("btn-au8"));
    expect(await screen.findByText("NEXT LESSON")).toBeInTheDocument();
  });

  it("marks completed when playback ends", async () => {
    const fetchMock = installFetch();
    const { container } = renderPlayer();
    await screen.findByTestId("btn-au1");
    const audio = container.querySelector("audio")!;

    fireEvent.ended(audio);
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "PUT" &&
          String(c[0]).includes("/progress") &&
          (JSON.parse((c[1] as RequestInit).body as string) as { completed?: boolean }).completed,
      );
      expect(put).toBeDefined();
    });
  });
});
