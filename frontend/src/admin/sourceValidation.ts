/** Client mirror of backend `app/services/ingestion.py`. */

const YOUTUBE = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"]);
const DRIVE = new Set(["drive.google.com", "docs.google.com"]);

export type SourceKind = "youtube" | "drive" | "pdf" | "web";

export function classifySource(url: string): SourceKind | null {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  const host = parsed.hostname.toLowerCase();
  if (YOUTUBE.has(host)) return "youtube";
  if (DRIVE.has(host)) return "drive";
  if (parsed.pathname.toLowerCase().endsWith(".pdf")) return "pdf";
  return "web";
}

export function sourceUrlError(url: string): string | null {
  if (!url.trim()) return null; // the link is optional; the page checks for at least one source
  if (classifySource(url) === null) {
    return "Enter a valid http(s) URL — YouTube, Google Drive, a .pdf link, or a web page";
  }
  return null;
}
