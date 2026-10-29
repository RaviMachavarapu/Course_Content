/**
 * NotebookLM Studio requests in the format the web app sends today.
 *
 * The pinned notebooklm-mcp-server@4.0.2 still builds the pre-2026-10 request
 * shapes, which Google now rejects with [3] INVALID_ARGUMENT. Every layout and
 * code below was recorded from the live web app on 2026-10-22; see
 * docs/spikes/notebooklm-2026-10-capture.md. Nothing here is inferred: an
 * option or value that wasn't observed is not supported.
 *
 * Session: the connector keeps the Google cookies fresh in auth.json; this
 * module reads that file on every call and never writes it.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const ORIGIN = "https://notebook.google.com";
const BATCH_PATH = "/_/LabsTailwindUi/data/batchexecute";
const AUTH_PATH = path.join(os.homedir(), ".notebooklm-mcp", "auth.json");
export const UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36";

// First RPC parameter the web app sends with Studio requests.
const CLIENT_OPTIONS = [
  2,
  null,
  null,
  [1, null, null, null, null, null, null, null, null, null, [1]],
  [[1, 4, 8, 10, 14, 2, 3, 6]],
];

export class StudioError extends Error {
  constructor(message, { code = null, auth = false } = {}) {
    super(message);
    this.code = code;
    this.auth = auth;
  }
}

// The signed-in account's long-lived session cookie: it changes only on a new
// sign-in, not when Google rotates SIDCC & co.
let signedInAs = null;

function savedCookies() {
  let jar;
  try {
    const raw = JSON.parse(fs.readFileSync(AUTH_PATH, "utf-8")).cookies;
    jar = new Map(raw.split("; ").map((kv) => [kv.slice(0, kv.indexOf("=")), kv.slice(kv.indexOf("=") + 1)]));
  } catch {
    throw new StudioError("no saved Google session (auth.json)", { auth: true });
  }
  const session = jar.get("SID") ?? jar.get("__Secure-1PSID") ?? null;
  if (signedInAs !== null && session !== signedInAs) resetSession(); // a new sign-in
  signedInAs = session;
  return jar;
}

// auth.json drops cookie domains. These are host-only for notebook.google.com
// (OSID) or accounts.google.com (LSID); sent to lh3.google.com they clash with
// its own session and it loops back to sign-in (verified live 2026-10-22).
const HOST_ONLY = { OSID: "notebook.google.com", "__Secure-OSID": "notebook.google.com", LSID: "accounts.google.com" };

// SIDCC & co. rotate on every Google response; the connector never stores the
// new values, so keep them here (in memory only — the connector owns auth.json).
const refreshed = new Map();

export function remember(res) {
  for (const sc of res.headers.getSetCookie()) {
    const [pair, ...attrs] = sc.split(";").map((part) => part.trim());
    const domain = attrs.find((a) => /^domain=/i.test(a))?.slice(7).replace(/^\./, "");
    if (domain && /(^|\.)google\.com$/.test(domain)) {
      refreshed.set(pair.slice(0, pair.indexOf("=")), pair.slice(pair.indexOf("=") + 1));
    }
  }
}

export function cookieHeader(host) {
  const jar = savedCookies();
  for (const [k, v] of refreshed) jar.set(k, v);
  return [...jar]
    .filter(([k]) => !HOST_ONLY[k] || HOST_ONLY[k] === host)
    .map(([k, v]) => `${k}=${v}`)
    .join("; ");
}

let tokens = null; // { at, sid, bl, fetchedAt }

/** Forget the in-memory session state (rotated cookies, page token): after a
 * re-sign-in they belong to the old session and would be mixed into requests. */
export function resetSession() {
  refreshed.clear();
  tokens = null;
}

async function pageTokens(force = false) {
  if (!force && tokens && Date.now() - tokens.fetchedAt < 10 * 60 * 1000) return tokens;
  const res = await fetch(ORIGIN + "/", {
    headers: { Cookie: cookieHeader("notebook.google.com"), "User-Agent": UA },
    redirect: "manual",
  });
  remember(res);
  const html = res.status === 200 ? await res.text() : "";
  const at = html.match(/"SNlM0e"\s*:\s*"([^"]+)"/)?.[1];
  if (!at) {
    tokens = null;
    throw new StudioError(`NotebookLM session rejected (HTTP ${res.status})`, { auth: true });
  }
  tokens = {
    at,
    sid: html.match(/"FdrFJe"\s*:\s*"([^"]+)"/)?.[1] ?? "",
    bl: html.match(/"cfb2h"\s*:\s*"([^"]+)"/)?.[1] ?? "",
    fetchedAt: Date.now(),
  };
  return tokens;
}

/** One batchexecute RPC; returns the decoded result (or null). */
export async function rpc(rpcId, params, sourcePath, retried = false) {
  const t = await pageTokens(retried);
  const fReq = JSON.stringify([[[rpcId, JSON.stringify(params), null, "generic"]]]);
  const qs = new URLSearchParams({
    rpcids: rpcId,
    "source-path": sourcePath,
    bl: t.bl,
    hl: "en",
    rt: "c",
    "f.sid": t.sid,
  });
  const res = await fetch(`${ORIGIN}${BATCH_PATH}?${qs}`, {
    method: "POST",
    headers: {
      Cookie: cookieHeader("notebook.google.com"),
      "User-Agent": UA,
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      Origin: ORIGIN,
      Referer: `${ORIGIN}/`,
      "X-Same-Domain": "1",
    },
    body: `f.req=${encodeURIComponent(fReq)}&at=${encodeURIComponent(t.at)}&`,
  });
  remember(res);
  const text = await res.text();
  if (res.status === 401 || res.status === 403) {
    if (!retried) return rpc(rpcId, params, sourcePath, true);
    throw new StudioError(`NotebookLM rejected the session (HTTP ${res.status})`, { auth: true });
  }
  for (const line of text.split("\n")) {
    if (!line.startsWith("[")) continue;
    let rows;
    try {
      rows = JSON.parse(line);
    } catch {
      continue;
    }
    for (const row of rows) {
      if (!Array.isArray(row) || row[0] !== "wrb.fr" || row[1] !== rpcId) continue;
      if (typeof row[2] === "string") return JSON.parse(row[2]);
      const code = Array.isArray(row[5]) ? row[5][0] : null;
      if (code === 16 && !retried) return rpc(rpcId, params, sourcePath, true);
      throw new StudioError(`NotebookLM rejected ${rpcId} (error [${code}])`, {
        code,
        auth: code === 16,
      });
    }
  }
  throw new StudioError(`no ${rpcId} result in NotebookLM's reply (HTTP ${res.status})`);
}

// -- option codes (all observed) ------------------------------------------------

const AUDIO_FORMAT = { deep_dive: 1, brief: 2, critique: 3, debate: 4 };
const AUDIO_LENGTH = { short: 1, default: 2, long: 3 };
const SLIDE_FORMAT = { detailed: 1, presenter: 2 };
const SLIDE_LENGTH = { short: 2, default: 3 };
const QUANTITY = { fewer: 1, standard: 2, more: 3 };
const DIFFICULTY = { easy: 1, medium: 2, hard: 3 };
const ORIENTATION = { landscape: 1, portrait: 2, square: 3 };
const DETAIL = { concise: 1, standard: 2, detailed: 3 };
const STYLE = {
  auto: 1,
  sketch_note: 2,
  professional: 3,
  bento_grid: 4,
  editorial: 5,
  instructional: 6,
  bricks: 7,
  clay: 8,
  anime: 9,
  kawaii: 10,
  scientific: 11,
};

// Document-report templates, sent verbatim exactly as the web app sends them.
const REPORT_TEMPLATES = {
  briefing_doc: [
    "Briefing Doc",
    "Key insights and important quotes",
    "Create a comprehensive briefing document that synthesizes the main themes and ideas from the sources. Start with a concise Executive Summary that presents the most critical takeaways upfront. The body of the document must provide a detailed and thorough examination of the main themes, evidence, and conclusions found in the sources. This analysis should be structured logically with headings and bullet points to ensure clarity. The tone must be objective and incisive.",
  ],
  study_guide: [
    "Study Guide",
    "Quiz with answer key plus glossary",
    "You are a highly capable research assistant and tutor. Create a detailed study guide designed to review understanding of the sources. Create a quiz with ten short-answer questions (2-3 sentences each) and include a separate answer key. Suggest five essay format questions, but do not supply answers. Also conclude with a comprehensive glossary of key terms with definitions.",
  ],
  blog_post: [
    "Blog Post",
    "Informational article in the style of a blog post",
    "Act as a thoughtful writer and synthesizer of ideas, tasked with creating an engaging and readable blog post for a popular online publishing platform known for its clean aesthetic and insightful content. Your goal is to distill the top most surprising, counter-intuitive, or impactful takeaways from the provided source materials into a compelling listicle. The writing style should be clean, accessible, and highly scannable, employing a conversational yet intelligent tone. Craft a compelling, click-worthy headline. Begin the article with a short introduction that hooks the reader by establishing a relatable problem or curiosity, then present each of the takeaway points as a distinct section with a clear, bolded subheading. Within each section, use short paragraphs to explain the concept clearly, and don't just summarize; offer a brief analysis or a reflection on why this point is so interesting or important, and if a powerful quote exists in the sources, feature it in a blockquote for emphasis. Conclude the post with a brief, forward-looking summary that leaves the reader with a final thought-provoking question or a powerful takeaway to ponder.",
  ],
};
const CUSTOM_REPORT = ["Create your own", "Craft reports your way by specifying structure, style, tone and more"];

function code(table, value, name) {
  if (!(value in table)) throw new StudioError(`unsupported ${name}: ${JSON.stringify(value)}`);
  return table[value];
}

/** spec[slot] = value, padding the gaps with nulls like the web app does. */
function specWith(type, sourceIds, slot, value) {
  const spec = [null, null, type, [sourceIds.map((id) => [id])]];
  while (spec.length < slot) spec.push(null);
  spec[slot] = value;
  return spec;
}

/** Build STUDIO_GENERATE's third parameter for one artifact kind. */
export function buildSpec(kind, sourceIds, focus, o) {
  const S = sourceIds.map((id) => [id]);
  const text = focus || null;
  switch (kind) {
    case "audio_overview": {
      const format = code(AUDIO_FORMAT, o.format, "audio format");
      // Brief has no length control; Critique/Debate offer Short and Default only.
      const length = o.format === "brief" ? null : code(AUDIO_LENGTH, o.length, "audio length");
      if (o.format !== "deep_dive" && o.length === "long") {
        throw new StudioError(`audio length "long" is not offered for ${o.format}`);
      }
      return specWith(1, sourceIds, 6, [null, [text, length, null, S, o.language, null, format]]);
    }
    case "slide_deck": {
      const block = [
        [text, o.language, code(SLIDE_FORMAT, o.format, "slide format"), code(SLIDE_LENGTH, o.length, "slide length")],
      ];
      return specWith(8, sourceIds, 16, block);
    }
    case "report": {
      if (o.format === "interactive") return specWith(11, sourceIds, 34, [null, [null, o.language]]);
      if (o.format !== "document") throw new StudioError(`unsupported report format: ${o.format}`);
      if (o.template === "custom") {
        if (!text) throw new StudioError('report template "custom" needs a description');
        return specWith(2, sourceIds, 7, [null, [...CUSTOM_REPORT, null, S, o.language, text, 2]]);
      }
      const [title, description, prompt] = REPORT_TEMPLATES[o.template] ?? [];
      if (!title) throw new StudioError(`unsupported report template: ${o.template}`);
      return specWith(2, sourceIds, 7, [null, [title, description, null, S, o.language, prompt]]);
    }
    case "flashcards": {
      const images = o.images === "text_only" ? [1] : [];
      return specWith(4, sourceIds, 9, [
        null,
        [1, null, text, o.language, null, null, [code(QUANTITY, o.quantity, "quantity"), code(DIFFICULTY, o.difficulty, "difficulty"), images]],
      ]);
    }
    case "quiz":
      return specWith(4, sourceIds, 9, [
        null,
        [2, null, text, o.language, null, null, null, [code(QUANTITY, o.quantity, "quantity"), code(DIFFICULTY, o.difficulty, "difficulty")]],
      ]);
    case "infographic":
      return specWith(7, sourceIds, 14, [
        [text, o.language, null, code(ORIENTATION, o.orientation, "orientation"), code(DETAIL, o.detail, "detail"), code(STYLE, o.style, "style")],
      ]);
    default:
      throw new StudioError(`unsupported artifact kind: ${kind}`);
  }
}

/** The full STUDIO_GENERATE parameter list. */
export function buildParams(notebookId, sourceIds, kind, focus, options) {
  const params = [CLIENT_OPTIONS, notebookId, buildSpec(kind, sourceIds, focus, options)];
  // "Review slide outline" is a top-level flag after the spec, not part of it.
  if (kind === "slide_deck" && options.review_outline) params.push(null, null, [1]);
  return params;
}

export async function createArtifact(notebookId, sourceIds, kind, focus, options) {
  const params = buildParams(notebookId, sourceIds, kind, focus, options);
  const result = await rpc("R7cb6c", params, `/notebook/${notebookId}`);
  const artifactId = Array.isArray(result?.[0]) ? result[0][0] : null;
  if (!artifactId) throw new StudioError(`STUDIO_GENERATE returned no artifact: ${JSON.stringify(result).slice(0, 300)}`);
  return artifactId;
}

/** Outline review: feedback revises the draft outline; no feedback builds the deck. */
export async function outlineAction(notebookId, artifactId, feedback) {
  const params = feedback ? [CLIENT_OPTIONS, artifactId, null, [[feedback]]] : [CLIENT_OPTIONS, artifactId];
  await rpc("hRBcub", params, `/notebook/${notebookId}`);
}

// -- media ---------------------------------------------------------------------

const ALLOWED_HOSTS = [/\.googleusercontent\.com$/, /\.google\.com$/, /\.googlevideo\.com$/];
const COOKIE_HOSTS = /(^|\.)google\.com$/;

/**
 * Download NotebookLM media (slide PNG/PDF/PPTX, infographic PNG, audio).
 * Redirects are followed by hand so the Google cookies reach the *.google.com
 * hops (lh3.google.com needs them); a client that drops them gets a sign-in page.
 */
export async function download(url) {
  let current = new URL(url);
  for (let hop = 0; hop < 10; hop += 1) {
    if (current.protocol !== "https:" || !ALLOWED_HOSTS.some((re) => re.test(current.hostname))) {
      throw new StudioError(`refusing to fetch ${current.hostname}`);
    }
    const headers = { "User-Agent": UA };
    if (COOKIE_HOSTS.test(current.hostname)) headers.Cookie = cookieHeader(current.hostname);
    const res = await fetch(current, { headers, redirect: "manual" });
    remember(res);
    if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
      current = new URL(res.headers.get("location"), current);
      continue;
    }
    if (!res.ok) throw new StudioError(`media download failed (HTTP ${res.status})`);
    const type = res.headers.get("content-type") || "application/octet-stream";
    if (type.startsWith("text/html")) {
      throw new StudioError("media download returned a web page, not a file (session rejected?)", { auth: true });
    }
    const size = Number(res.headers.get("content-length"));
    if (/\.googlevideo\.com$/.test(current.hostname) && size > 0) {
      await res.body?.cancel();
      return { type, data: await rangedDownload(current, headers, size) };
    }
    return { type, data: Buffer.from(await res.arrayBuffer()) };
  }
  throw new StudioError("too many redirects downloading media");
}

const RANGE_CHUNK = 1024 * 1024;

// googlevideo throttles a plain GET to playback speed (~32 KB/s: a 22 MB Audio
// Overview took 11+ minutes), but serves byte ranges at full speed (1 MB in
// ~0.3s, measured live 2026-10-23).
async function rangedDownload(url, headers, size) {
  const parts = [];
  for (let start = 0; start < size; start += RANGE_CHUNK) {
    const end = Math.min(start + RANGE_CHUNK, size) - 1;
    const res = await fetch(url, { headers: { ...headers, Range: `bytes=${start}-${end}` } });
    if (res.status !== 206) throw new StudioError(`media range download failed (HTTP ${res.status})`);
    parts.push(Buffer.from(await res.arrayBuffer()));
  }
  const data = Buffer.concat(parts);
  if (data.length !== size) throw new StudioError(`media download incomplete (${data.length} of ${size} bytes)`);
  return data;
}
