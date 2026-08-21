/** API client for the FastAPI backend. */
import type { ScanResponse, SiteStructureResult } from "../types/api";

const BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  scan: (urls: string[], includeHtml = true, timeoutSeconds?: number) =>
    post<ScanResponse>("/scan", { urls, include_html: includeHtml, timeout_seconds: timeoutSeconds }),

  validateStructuredData: (urls: string[], includeHtml = true) =>
    post<ScanResponse>("/structured-data/validate", { urls, include_html: includeHtml }),

  validateHtml: (html: string) =>
    post<{ structured_data: ScanResponse["results"][0]["structured_data"] }>("/structured-data/validate-html", { html }),

  // Kept for internal/backend tooling use; not surfaced as a UI tab.
  siteStructure: (site = "deccanherald") =>
    get<SiteStructureResult>(`/site-structure/config?site=${encodeURIComponent(site)}`),
};
