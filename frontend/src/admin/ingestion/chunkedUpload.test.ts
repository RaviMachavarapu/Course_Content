import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setCsrfFailureHandler, setSessionEndedHandler } from "@/lib/api";
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
      { status: 200, body: { received_bytes: 0, status: "receiving" } }, // status check
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
    expect(calls[4]!.method).toBe("PUT");

    expect(await settled).toBe("rejected");
    expect(calls).toHaveLength(6);
    expect(calls[5]!.method).toBe("GET");
    expect(calls[5]!.url).toBe("/api/admin/uploads/u1");
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

  it("reports a lost upload (409 upload_lost) once, with its code, without retrying", async () => {
    const calls = stubFetch([
      START,
      {
        status: 409,
        body: {
          error: { code: "upload_lost", message: "a.pdf was lost on the server; upload it again" },
        },
      },
    ]);
    const err = await uploadPdf(pdf(10), vi.fn()).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("upload_lost");
    expect((err as ApiError).message).toBe("a.pdf was lost on the server; upload it again");
    expect(calls).toHaveLength(2);
  });

  it("treats a finished upload as success when the final chunk's response was lost", async () => {
    const calls = stubFetch([
      START,
      new TypeError("network"), // committed on the server, response lost
      {
        status: 409,
        body: { error: { code: "not_receiving", message: "Upload is already finished" } },
      },
      { status: 200, body: { received_bytes: 10, status: "complete" } },
    ]);
    const p = uploadPdf(pdf(10), vi.fn());
    await vi.advanceTimersByTimeAsync(1000);
    await expect(p).resolves.toBe("u1");
    expect(calls.map((c) => c.method)).toEqual(["POST", "PUT", "PUT", "GET"]);
  });

  it("still fails when the status check shows the upload did not complete", async () => {
    stubFetch([
      START,
      {
        status: 409,
        body: { error: { code: "not_receiving", message: "Upload is already finished" } },
      },
      { status: 200, body: { received_bytes: 4, status: "receiving" } },
    ]);
    await expect(uploadPdf(pdf(10), vi.fn())).rejects.toThrow("Upload is already finished");
  });

  it("succeeds when retries run out but the server has the whole file", async () => {
    stubFetch([
      START,
      { status: 502 },
      { status: 502 },
      { status: 502 },
      { status: 502 },
      { status: 200, body: { received_bytes: 10, status: "complete" } },
    ]);
    const p = uploadPdf(pdf(10), vi.fn());
    await vi.advanceTimersByTimeAsync(7000);
    await expect(p).resolves.toBe("u1");
  });

  it("reports the new upload as soon as the server starts it", async () => {
    stubFetch([START, { status: 200, body: { received_bytes: 10 } }]);
    const onStarted = vi.fn();
    await uploadPdf(pdf(10), vi.fn(), undefined, { onStarted });
    expect(onStarted).toHaveBeenCalledWith({ upload_id: "u1", chunk_size: CHUNK });
  });

  it("resumes an earlier upload from the server's received_bytes", async () => {
    const size = 2 * CHUNK;
    const calls = stubFetch([
      { status: 200, body: { received_bytes: CHUNK, status: "receiving" } },
      { status: 200, body: { received_bytes: size } },
    ]);
    const progress = vi.fn();
    const onStarted = vi.fn();
    const id = await uploadPdf(pdf(size), progress, undefined, {
      resume: { upload_id: "u1", chunk_size: CHUNK },
      onStarted,
    });
    expect(id).toBe("u1");
    expect(calls.map((c) => [c.method, c.url.split("?")[0]])).toEqual([
      ["GET", "/api/admin/uploads/u1"],
      ["PUT", "/api/admin/uploads/u1"],
    ]);
    expect(offsetOf(calls[1]!)).toBe(CHUNK);
    expect(progress).toHaveBeenNthCalledWith(1, CHUNK, size);
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("a resumed upload the server already has whole sends nothing more", async () => {
    const calls = stubFetch([{ status: 200, body: { received_bytes: 10, status: "complete" } }]);
    await expect(
      uploadPdf(pdf(10), vi.fn(), undefined, { resume: { upload_id: "u1", chunk_size: CHUNK } }),
    ).resolves.toBe("u1");
    expect(calls).toHaveLength(1);
  });

  it.each([
    ["gone (404)", { status: 404, body: { error: { code: "not_found", message: "x" } } }],
    ["already used", { status: 200, body: { received_bytes: 10, status: "claimed" } }],
  ])("starts a fresh upload when the earlier one is %s", async (_label, reply) => {
    const calls = stubFetch([
      reply,
      { status: 201, body: { upload_id: "u2", chunk_size: CHUNK } },
      { status: 200, body: { received_bytes: 10 } },
    ]);
    const onStarted = vi.fn();
    await expect(
      uploadPdf(pdf(10), vi.fn(), undefined, {
        resume: { upload_id: "u1", chunk_size: CHUNK },
        onStarted,
      }),
    ).resolves.toBe("u2");
    expect(calls.map((c) => c.method)).toEqual(["GET", "POST", "PUT"]);
    expect(offsetOf(calls[2]!)).toBe(0);
    expect(onStarted).toHaveBeenCalledWith({ upload_id: "u2", chunk_size: CHUNK });
  });

  it("reports an expired CSRF token so the app can send the admin to sign in", async () => {
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    stubFetch([
      START,
      {
        status: 403,
        body: { error: { code: "csrf_failed", message: "Missing or invalid CSRF token" } },
      },
    ]);
    await expect(uploadPdf(pdf(10), vi.fn())).rejects.toThrow(/session ended/i);
    expect(handler).toHaveBeenCalledWith("/api/admin/uploads/u1");
    setCsrfFailureHandler(null);
  });

  it("reports a session that ended mid-upload (401) instead of a bare error", async () => {
    const handler = vi.fn();
    setSessionEndedHandler(handler);
    stubFetch([
      START,
      { status: 401, body: { error: { code: "unauthorized", message: "Not authenticated" } } },
    ]);
    await expect(uploadPdf(pdf(10), vi.fn())).rejects.toThrow(/session ended/i);
    expect(handler).toHaveBeenCalledWith("/api/admin/uploads/u1");
    setSessionEndedHandler(null);
  });

  it("refreshes an expired CSRF token via /me and resends the chunk once", async () => {
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    const calls = stubFetch([
      START,
      { status: 403, body: { error: { code: "csrf_failed", message: "x" } } },
      { status: 200, body: { user: {} } },
      { status: 200, body: { received_bytes: 10 } },
    ]);
    await expect(uploadPdf(pdf(10), vi.fn())).resolves.toBe("u1");
    expect(calls.map((c) => [c.method, c.url.split("?")[0]])).toEqual([
      ["POST", "/api/admin/uploads"],
      ["PUT", "/api/admin/uploads/u1"],
      ["GET", "/api/admin/auth/me"],
      ["PUT", "/api/admin/uploads/u1"],
    ]);
    expect(handler).not.toHaveBeenCalled();
    setCsrfFailureHandler(null);
  });
});
