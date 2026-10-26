import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { uploadPdf } from "./chunkedUpload";

const MB = 1024 * 1024;
const CHUNK = 8 * MB;

type Reply = { status: number; body?: unknown } | Error;

interface Call {
  url: string;
  method: string;
  init: RequestInit;
}

function stubFetch(replies: Reply[]): Call[] {
  const calls: Call[] = [];
  const queue = [...replies];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: (init.method ?? "GET").toUpperCase(), init });
      const r = queue.shift();
      if (!r) return Promise.reject(new Error("unexpected fetch"));
      if (r instanceof Error) return Promise.reject(r);
      return Promise.resolve({
        ok: r.status < 400,
        status: r.status,
        statusText: String(r.status),
        json: () => Promise.resolve(r.body ?? null),
      } as Response);
    }),
  );
  return calls;
}

function pdf(size: number, name = "a.pdf"): File {
  return new File([new Uint8Array(size)], name, { type: "application/pdf" });
}

const START = { status: 201, body: { upload_id: "u1", chunk_size: CHUNK } };

function offsetOf(call: Call): number {
  return Number(new URL(call.url, "http://x").searchParams.get("offset"));
}

beforeEach(() => {
  vi.useFakeTimers();
  document.cookie = "sdp_csrf=tok%3D1";
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("uploadPdf", () => {
  it("starts an upload then PUTs 8 MB slices at the right offsets", async () => {
    const size = 2 * CHUNK + 100;
    const calls = stubFetch([
      START,
      { status: 200, body: { received_bytes: CHUNK } },
      { status: 200, body: { received_bytes: 2 * CHUNK } },
      { status: 200, body: { received_bytes: size } },
    ]);
    const progress = vi.fn();

    const id = await uploadPdf(pdf(size), progress);

    expect(id).toBe("u1");
    expect(calls[0]!.url).toBe("/api/admin/uploads");
    expect(calls[0]!.method).toBe("POST");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({
      file_name: "a.pdf",
      size_bytes: size,
    });
    const puts = calls.slice(1);
    expect(puts.map(offsetOf)).toEqual([0, CHUNK, 2 * CHUNK]);
    expect(puts.map((c) => (c.init.body as Blob).size)).toEqual([CHUNK, CHUNK, 100]);
    for (const p of puts) {
      expect(p.url).toContain("/api/admin/uploads/u1?offset=");
      expect(p.method).toBe("PUT");
      expect(p.init.credentials).toBe("include");
      const h = p.init.headers as Record<string, string>;
      expect(h["X-CSRF-Token"]).toBe("tok=1");
      expect(h["Content-Type"]).toBe("application/octet-stream");
    }
    expect(progress).toHaveBeenLastCalledWith(size, size);
    expect(progress).toHaveBeenCalledWith(CHUNK, size);
  });

  it("resumes from received_bytes after a 409 offset mismatch", async () => {
    const size = 2 * CHUNK;
    const calls = stubFetch([
      START,
      { status: 409, body: { code: "offset_mismatch", received_bytes: CHUNK } },
      { status: 200, body: { received_bytes: size } },
    ]);

    await uploadPdf(pdf(size), vi.fn());

    expect(calls.slice(1).map(offsetOf)).toEqual([0, CHUNK]);
  });

  it("retries a failing chunk three times (1s, 2s, 4s) then rejects", async () => {
    const calls = stubFetch([
      START,
      { status: 500 },
      new TypeError("network"),
      { status: 502 },
      { status: 500 },
    ]);
    const settled = uploadPdf(pdf(10), vi.fn()).then(
      () => "resolved",
      () => "rejected",
    );

    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(999);
    expect(calls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(2000);
    expect(calls).toHaveLength(4);
    await vi.advanceTimersByTimeAsync(4000);
    expect(calls).toHaveLength(5);

    expect(await settled).toBe("rejected");
    expect(calls).toHaveLength(5);
  });

  it("recovers when a retry succeeds", async () => {
    const calls = stubFetch([
      START,
      { status: 503 },
      { status: 200, body: { received_bytes: 10 } },
    ]);
    const p = uploadPdf(pdf(10), vi.fn());
    await vi.advanceTimersByTimeAsync(1000);
    await expect(p).resolves.toBe("u1");
    expect(calls).toHaveLength(3);
  });

  it("surfaces the server's message for a non-PDF without retrying", async () => {
    const calls = stubFetch([
      START,
      { status: 422, body: { error: { code: "not_pdf", message: "a.pdf is not a PDF" } } },
    ]);
    await expect(uploadPdf(pdf(10), vi.fn())).rejects.toThrow("a.pdf is not a PDF");
    expect(calls).toHaveLength(2);
  });
});
