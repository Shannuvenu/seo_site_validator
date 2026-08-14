/** API client for the FastAPI backend. */
import type {
  DataLayerClickResponse,
  DataLayerExportResponse,
  DataLayerSourceResponse,
  DataLayerStartResponse,
  DataLayerStatusResponse,
  ScanResponse,
  SiteStructureResult,
} from "../types/api";

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

  // ---- Data Layer (persistent browser session) ----
  dataLayerStart: (url: string, opts?: { navigationPauseMs?: number; clickText?: string; clickSelector?: string; headless?: boolean }) =>
    post<DataLayerStartResponse>("/data-layer/start", {
      url,
      navigation_pause_ms: opts?.navigationPauseMs ?? 2500,
      click_text: opts?.clickText,
      click_selector: opts?.clickSelector,
      headless: opts?.headless ?? true,
    }),

  dataLayerClick: (sessionId: string, text: string) =>
    post<DataLayerClickResponse>("/data-layer/click", { session_id: sessionId, text }),

  dataLayerStatus: (sessionId: string) =>
    get<DataLayerStatusResponse>(`/data-layer/status?session_id=${encodeURIComponent(sessionId)}`),

  dataLayerEvents: (sessionId: string) =>
    get<DataLayerStatusResponse>(`/data-layer/events?session_id=${encodeURIComponent(sessionId)}`),

  dataLayerClear: (sessionId: string) =>
    post<{ ok: boolean; message: string; session_id: string }>("/data-layer/clear", { session_id: sessionId }),

  dataLayerExport: (sessionId: string) =>
    post<DataLayerExportResponse>("/data-layer/export", { session_id: sessionId }),

  dataLayerSource: (sessionId: string) =>
    get<DataLayerSourceResponse>(`/data-layer/source?session_id=${encodeURIComponent(sessionId)}`),

  dataLayerClose: (sessionId: string) =>
    post<{ ok: boolean; message: string; session_id: string }>("/data-layer/close", { session_id: sessionId }),

  siteStructure: (site = "deccanherald") =>
    get<SiteStructureResult>(`/site-structure/config?site=${encodeURIComponent(site)}`),
};
