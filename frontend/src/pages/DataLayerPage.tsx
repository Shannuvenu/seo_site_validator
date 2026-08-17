import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  DataLayerRecord,
  DataLayerStatusResponse,
  SourceLocation,
} from "../types/api";
import { api } from "../services/api";
import SourceViewer from "../components/SourceViewer";
import { normalizePayload, validateEvent } from "../qa/validator";
import "./data-layer.css";
import { schemasForEvent } from "../qa/schemas";
import type { ValidationIssue } from "../qa/schemas";

/**
 * Reorder a dataLayer payload's keys to match the Excel spec's field order
 * (schemas.ts's field object key order mirrors the sheet, e.g. for
 * page_view: article_id, article_type, auth_status, author_id, ... event,
 * ... premium_article, access_level_value). Any payload keys not in the
 * spec are appended at the end, unchanged — nothing is dropped or invented.
 */
function reorderForDisplay(eventName: string, payload: Record<string, unknown>): Record<string, unknown> {
  const schemas = schemasForEvent(eventName);
  if (schemas.length === 0) return payload;
  const order: string[] = [];
  const seen = new Set<string>();
  for (const schema of schemas) {
    for (const key of Object.keys(schema.fields)) {
      if (!seen.has(key)) {
        seen.add(key);
        order.push(key);
      }
    }
  }
  const out: Record<string, unknown> = {};
  for (const key of order) {
    if (key in payload) out[key] = payload[key];
  }
  for (const key of Object.keys(payload)) {
    if (!seen.has(key)) out[key] = payload[key];
  }
  return out;
}

/** Ported 1:1 from qa/monitor.ts (QaMonitor) — same constants, same rule,
 * but evaluated post-hoc over the backend's timestamped/ordered event log
 * instead of live setTimeout, because QaMonitor's own click/document
 * listeners cannot see the target page (it runs in a separate Chromium
 * process owned by Playwright, not in this React tab). */
const CLICK_EVENT_WINDOW_MS = 1200;
const SEQUENCE_WINDOW_MS = 2500;
const TRIGGER_EVENTS = ["page_view", "purchase", "sign_up", "login", "logout"];

export type CheckKind = "PASS" | "FAIL" | "NO_EVENT" | "SEQUENCE_FAIL" | "UNCHECKED";

export interface CheckResult {
  kind: CheckKind;
  label: string; // "PASS" | "❌ N issues" | "NO EVENT" | "SEQUENCE FAIL" | "—"
  variant?: string;
  issues: ValidationIssue[];
  payload?: Record<string, unknown>;
  // NO EVENT extras
  clickedElement?: Record<string, unknown>;
  noEventReason?: string;
  // SEQUENCE FAIL extras
  trigger?: string;
  expectedFollowUp?: string;
  windowMs?: number;
  actualGapMs?: number;
}

function tsMs(rec: DataLayerRecord): number {
  const t = rec.timestamp ? Date.parse(rec.timestamp) : NaN;
  return isNaN(t) ? 0 : t;
}

/**
 * Compute a Check result for every row, in one linear pass over the ordered
 * (already deduped, already seq-sorted) events array:
 *  - dataLayer rows -> validateEvent() from the existing QA validator (PASS /
 *    ❌ N issues / — for uncovered events), payload = the exact pushed object.
 *  - interaction/click rows -> NO EVENT if no dataLayer push landed within
 *    CLICK_EVENT_WINDOW_MS after the click timestamp.
 *  - trigger dataLayer events (page_view/purchase/sign_up/login/logout) ->
 *    SEQUENCE FAIL if no "user_properties_update" dataLayer push lands within
 *    SEQUENCE_WINDOW_MS.
 * Nothing here invents schemas or fields — PASS/FAIL/issues come straight
 * from qa/schemas.ts + qa/validator.ts.
 */
function computeChecks(events: DataLayerRecord[]): Map<number, CheckResult> {
  const out = new Map<number, CheckResult>();
  const dataLayerRows = events.filter((e) => e.type === "dataLayer");

  for (const e of events) {
    if (e.type === "dataLayer") {
      const normalized = normalizePayload(e.data);
      if (!normalized) {
        out.set(e.seq, { kind: "UNCHECKED", label: "—", issues: [], payload: e.data as Record<string, unknown> });
        continue;
      }
      const result = validateEvent(normalized);
      if (result.uncovered) {
        out.set(e.seq, { kind: "UNCHECKED", label: "—", issues: [], payload: normalized.payload });
      } else if (result.status === "PASS") {
        out.set(e.seq, { kind: "PASS", label: "PASS", issues: result.issues, payload: normalized.payload });
      } else {
        const failCount = result.issues.filter((i) => i.severity === "FAIL").length || result.issues.length;
        out.set(e.seq, {
          kind: "FAIL",
          label: `❌ ${failCount} issue${failCount === 1 ? "" : "s"}`,
          issues: result.issues,
          payload: normalized.payload,
        });
      }

      // Sequence check: trigger event must be followed by user_properties_update.
      const eventName = String(normalized.payload.event ?? "");
      if (TRIGGER_EVENTS.includes(eventName)) {
        const triggerMs = tsMs(e);
        const followUp = dataLayerRows.find((d) => {
          if (d.seq === e.seq) return false;
          const dp = normalizePayload(d.data);
          const name = dp ? String(dp.payload.event ?? "") : "";
          const dt = tsMs(d);
          return name === "user_properties_update" && dt >= triggerMs && dt - triggerMs <= SEQUENCE_WINDOW_MS;
        });
        if (!followUp) {
          const prev = out.get(e.seq)!;
          out.set(e.seq, {
            ...prev,
            kind: "SEQUENCE_FAIL",
            label: "SEQUENCE FAIL",
            trigger: eventName,
            expectedFollowUp: "user_properties_update",
            windowMs: SEQUENCE_WINDOW_MS,
            actualGapMs: undefined,
          });
        }
      }
    } else if (e.type === "interaction") {
      const action = String((e.data as Record<string, unknown>)?.action ?? "");
      if (action !== "click") continue;
      const clickMs = tsMs(e);
      const matched = dataLayerRows.some((d) => {
        const dt = tsMs(d);
        return dt >= clickMs && dt - clickMs <= CLICK_EVENT_WINDOW_MS;
      });
      if (!matched) {
        out.set(e.seq, {
          kind: "NO_EVENT",
          label: "NO EVENT",
          issues: [],
          clickedElement: (e.data as Record<string, unknown>)?.element as Record<string, unknown> | undefined,
          noEventReason: `no dataLayer event fired within ${CLICK_EVENT_WINDOW_MS}ms of this click`,
        });
      }
    }
  }
  return out;
}

export interface SessionStatus {
  authStatus: "logged_in" | "non_logged_in" | "unknown";
  subscriptionStatus: string;
  planName?: string;
  planPrice?: string | number;
  source: string; // event name this was derived from, or "none"
  updatedAt?: string | null;
}

/**
 * Derive "is this session currently logged in / subscribed" from the
 * captured dataLayer stream — no new capture, purely reading what the
 * existing observer already recorded.
 *
 * user_properties_update is the spec's authoritative source for
 * auth_status/subscription_status, so the MOST RECENT one wins. Before the
 * first user_properties_update fires (e.g. right after Start Capture), fall
 * back to the most recent event that happens to carry auth_status
 * (page_view / login / logout), so the indicator isn't blank while QA is
 * still on the first page.
 */
function computeSessionStatus(events: DataLayerRecord[]): SessionStatus {
  const dataLayerRows = events.filter((e) => e.type === "dataLayer");

  for (let i = dataLayerRows.length - 1; i >= 0; i--) {
    const rec = dataLayerRows[i];
    const d = rec.data as Record<string, unknown>;
    if (String(d.event ?? "") === "user_properties_update") {
      return {
        authStatus: (d.auth_status as SessionStatus["authStatus"]) ?? "unknown",
        subscriptionStatus: String(d.subscription_status ?? "unknown"),
        planName: d.plan_name != null ? String(d.plan_name) : undefined,
        planPrice: d.plan_price as string | number | undefined,
        source: "user_properties_update",
        updatedAt: rec.timestamp,
      };
    }
  }

  for (let i = dataLayerRows.length - 1; i >= 0; i--) {
    const rec = dataLayerRows[i];
    const d = rec.data as Record<string, unknown>;
    if (typeof d.auth_status === "string") {
      return {
        authStatus: d.auth_status as SessionStatus["authStatus"],
        subscriptionStatus: String(d.subscription_status ?? "unknown"),
        planName: d.plan_name != null ? String(d.plan_name) : undefined,
        planPrice: d.plan_price as string | number | undefined,
        source: String(d.event ?? "unknown"),
        updatedAt: rec.timestamp,
      };
    }
  }

  return { authStatus: "unknown", subscriptionStatus: "unknown", source: "none", updatedAt: null };
}

/** Application-side persistent history key (NOT the target-page transport). */
const HISTORY_KEY = "dataLayerHistory";
const HISTORY_MAX = 500;

type BrowserStatus = "not_started" | "starting" | "open" | "capturing" | "error" | "closed";

interface StatusMeta {
  label: string;
  className: string;
  dot: string;
}

const STATUS_META: Record<BrowserStatus, StatusMeta> = {
  not_started: { label: "Not started", className: "status-idle", dot: "○" },
  starting: { label: "Starting browser", className: "status-starting", dot: "●" },
  open: { label: "Opening page", className: "status-starting", dot: "●" },
  capturing: { label: "Capturing", className: "status-capturing", dot: "●" },
  error: { label: "Error", className: "status-error", dot: "●" },
  closed: { label: "Browser session closed", className: "status-idle", dot: "○" },
};

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return (
    d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0")
  );
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString([], { hour12: false });
}

function shortUrl(url: string, max = 60): string {
  try {
    const u = new URL(url);
    const path = u.pathname === "/" ? "" : u.pathname;
    const full = u.hostname + path;
    return full.length > max ? full.slice(0, max) + "…" : full;
  } catch {
    return url.length > max ? url.slice(0, max) + "…" : url;
  }
}

/** Stable identity for one real event (used for dedup across polling paths). */
function eventKey(rec: DataLayerRecord): string {
  const d = rec.data as Record<string, unknown>;
  const s = JSON.stringify(d ?? {});
  return `${rec.type}|${rec.timestamp ?? ""}|${rec.url}|${s}`;
}

/**
 * Locate the character offset of a JSON pointer (e.g. "0.author[0].name") in a
 * serialized JSON-LD-ish block. Walks key-by-key so arrays and repeated keys
 * resolve to the exact occurrence.
 */
function findJsonPathOffset(text: string, path: string): { start: number; end: number } | null {
  if (!path) return null;
  const segs = path.split(/\.|\[|\]/).filter(Boolean);
  let cursor = 0;
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    const escaped = seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`"${escaped}"\\s*:`);
    const from = text.indexOf('"', cursor);
    const m = re.exec(text.slice(from));
    if (!m) return null;
    cursor = from + m.index + m[0].length;
    // Skip the value for non-final segments so the NEXT key is searched after
    // this key's value, not inside it.
    if (i < segs.length - 1) {
      let depth = 0;
      let inStr = false;
      let esc = false;
      while (cursor < text.length) {
        const c = text[cursor];
        if (inStr) {
          if (esc) esc = false;
          else if (c === "\\") esc = true;
          else if (c === '"') inStr = false;
        } else {
          if (c === '"') inStr = true;
          else if (c === "{" || c === "[") depth++;
          else if (c === "}" || c === "]") {
            depth--;
            if (depth <= 0) {
              cursor++;
              break;
            }
          }
        }
        cursor++;
      }
    }
  }
  const start = text.lastIndexOf('"', cursor - 1);
  const keyStart = text.lastIndexOf('"', start - 1) + 1;
  return { start: keyStart, end: cursor };
}

function recordTypeLabel(rec: DataLayerRecord): string {
  if (rec.type === "dataLayer") return "DATA LAYER";
  if (rec.type === "interaction") return "USER INTERACTION";
  if (rec.type === "navigation") return "NAVIGATION";
  return "PAGE";
}

/** Human-friendly summary: description when present, else a sensible default. */
function recordSummary(rec: DataLayerRecord): { title: string; sub?: string } {
  const d = rec.data as Record<string, unknown>;
  if (rec.type === "dataLayer") {
    const ev = d.event ?? d.eventName ?? d.event_name;
    let sub = rec.data && Object.keys(d).length ? `${Object.keys(d).length} key(s)` : "";
    // page_view (Premium Article) — surface the key fields inline, without
    // needing to click the row, per the "show event parameters" requirement.
    if (ev === "page_view" && (d.premium_article !== undefined || d.access_level_value !== undefined)) {
      const bits = [
        d.section_name ? `section: ${d.section_name}` : null,
        d.author_name ? `by ${d.author_name}` : null,
        d.premium_article !== undefined ? `premium: ${d.premium_article}` : null,
        d.access_level_value !== undefined ? `access_level: ${d.access_level_value}` : null,
        d.auth_status ? `auth: ${d.auth_status}` : null,
      ].filter(Boolean);
      if (bits.length) sub = bits.join(" · ");
    }
    return { title: String(ev ?? "(unnamed dataLayer push)"), sub };
  }
  if (rec.type === "interaction") {
    const action = String(d.action ?? "interaction");
    const el = (d.element ?? {}) as Record<string, unknown>;
    const elText = el.text ?? el["aria-label"] ?? el.title ?? el.id;
    const tag = el.tag ? String(el.tag) : "";
    const href = el.href ? String(el.href) : "";
    const parts = [
      tag ? `<${tag}>` : null,
      elText ? `"${String(elText)}"` : null,
      href ? `→ ${shortUrl(href, 40)}` : null,
      d.in_frame ? "(inside embedded frame)" : null,
    ].filter(Boolean);
    const clickSub = parts.length ? parts.join(" ") : typeof d.description === "string" ? d.description : undefined;
    return { title: action.toUpperCase(), sub: clickSub };
  }
  if (rec.type === "navigation") {
    const from = String(d.from_url ?? "");
    const to = String(d.to_url ?? rec.url);
    return { title: "NAVIGATION", sub: `${shortUrl(from, 40)} → ${shortUrl(to, 40)}` };
  }
  return { title: String(d.action ?? rec.type), sub: String(d.event ?? "") };
}

/** Expandable JSON viewer for a single record's data. */
function JsonTree({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const [open, setOpen] = useState(depth < 1);
  const isObj = value !== null && typeof value === "object";

  if (!isObj) {
    return <span className="json-scalar">{JSON.stringify(value)}</span>;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  return (
    <div className="json-tree" style={{ paddingLeft: depth > 0 ? 14 : 0 }}>
      <span className="json-toggle" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {Array.isArray(value) ? `[${entries.length}]` : `{${entries.length}}`}
      </span>
      {open && (
        <div className="json-children">
          {entries.map(([k, v]) => (
            <div key={k} className="json-entry">
              <span className="json-key">"{k}"</span>
              <span className="json-colon">: </span>
              <JsonTree value={v} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type FilterKey =
  | "all"
  | "dataLayer"
  | "interaction"
  | "navigation"
  | "click"
  | "scroll"
  | "page_load"
  | "input"
  | "submit"
  | "pointer";

function matchesFilter(rec: DataLayerRecord, filter: FilterKey): boolean {
  if (filter === "all") return true;
  if (filter === "dataLayer") return rec.type === "dataLayer";
  if (filter === "interaction") return rec.type === "interaction";
  if (filter === "navigation") return rec.type === "navigation";
  const action = String((rec.data as Record<string, unknown>)?.action ?? "");
  return rec.type === "interaction" && action === filter;
}

function checkBadgeClass(kind: CheckKind): string {
  if (kind === "PASS") return "badge pass";
  if (kind === "FAIL") return "badge fail";
  if (kind === "NO_EVENT") return "badge warning";
  if (kind === "SEQUENCE_FAIL") return "badge fail";
  return "badge neutral";
}

function EventRow({
  event,
  expanded,
  onToggle,
  onViewSource,
  check,
  onCheckClick,
}: {
  event: DataLayerRecord;
  expanded: boolean;
  onToggle: () => void;
  onViewSource: (e: React.MouseEvent) => void;
  check?: CheckResult;
  onCheckClick: (e: React.MouseEvent) => void;
}) {
  const { title, sub } = recordSummary(event);
  const copyJson = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(JSON.stringify(event.data, null, 2));
  };
  const typeClass =
    event.type === "dataLayer"
      ? "type-datalayer"
      : event.type === "navigation"
        ? "type-navigation"
        : "type-interaction";
  const jsonPath = String(
    (event.data as Record<string, unknown>)?.json_path ??
      (event.data as Record<string, unknown>)?.jsonPath ??
      "",
  );
  return (
    <div className={`dl-row ${expanded ? "expanded" : ""}`}>
      <div className="dl-row-main" onClick={onToggle}>
        <span className="dl-seq mono">{event.seq}</span>
        <span className="dl-time mono">{formatTime(event.timestamp)}</span>
        <span className={`dl-type ${typeClass}`}>{recordTypeLabel(event)}</span>
        <span className="dl-event-name mono dl-event-name-wide" title={title}>
          {title}
          {sub ? <span className="dl-event-sub"> — {sub}</span> : null}
        </span>
        <span className="dl-page mono" title={event.page_title ?? undefined}>
          {event.page_title ? shortUrl(event.page_title, 30) : ""}
        </span>
        <span className="dl-url mono">{shortUrl(event.url)}</span>
        <span className="dl-check">
          {check ? (
            <button type="button" className={checkBadgeClass(check.kind)} onClick={onCheckClick}>
              {check.label}
            </button>
          ) : (
            <span className="badge neutral">—</span>
          )}
        </span>
        <span className="dl-caret">{expanded ? "▾" : "▸"}</span>
      </div>
      {expanded && (
        <div className="dl-row-detail">
          <div className="dl-detail-meta">
            <div>
              <span className="faint">type: </span>
              <span className="mono">{recordTypeLabel(event)}</span>
              <span className="faint"> · seq: </span>
              <span className="mono">{event.seq}</span>
            </div>
            <div>
              <span className="faint">URL: </span>
              <span className="mono">{event.url}</span>
            </div>
            {event.page_title && (
              <div>
                <span className="faint">Page: </span>
                <span className="mono">{event.page_title}</span>
              </div>
            )}
            {jsonPath && (
              <div>
                <span className="faint">JSON-LD path: </span>
                <span className="mono">{jsonPath}</span>
              </div>
            )}
            <div>
              <span className="faint">Time: </span>
              <span className="mono">{formatDateTime(event.timestamp)}</span>
            </div>
          </div>
          <div className="dl-detail-data">
            <div className="dl-detail-data-header">
              <span className="faint">Complete JSON:</span>
              <div className="dl-detail-btns">
                <button className="btn btn-small" onClick={onViewSource}>
                  View Source
                </button>
                <button className="btn btn-small" onClick={copyJson}>
                  Copy JSON
                </button>
              </div>
            </div>
            <JsonTree
              value={
                event.type === "dataLayer"
                  ? reorderForDisplay(String((event.data as Record<string, unknown>)?.event ?? ""), event.data as Record<string, unknown>)
                  : event.data
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ---- application-side localStorage history (persistent UI history/cache) ----
function loadHistory(): DataLayerRecord[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? (arr as DataLayerRecord[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(events: DataLayerRecord[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(events.slice(-HISTORY_MAX)));
  } catch {
    /* storage full / unavailable — history is a best-effort cache */
  }
}

/** Modal: live page source with the event's JSON path highlighted. */
function SourceModal({
  url,
  html,
  jsonPath,
  onClose,
}: {
  url: string;
  html: string;
  jsonPath: string;
  onClose: () => void;
}) {
  const [highlight, setHighlight] = useState<SourceLocation | null>(null);
  useEffect(() => {
    const loc = findJsonPathOffset(html, jsonPath);
    setHighlight(
      loc
        ? { html_line: 1, html_column: 0, start_offset: loc.start, end_offset: loc.end, json_path: jsonPath }
        : null,
    );
  }, [html, jsonPath]);
  return (
    <div className="dl-modal-backdrop" onClick={onClose}>
      <div className="dl-modal" onClick={(e) => e.stopPropagation()}>
        <div className="dl-modal-head">
          <span className="mono">{url}</span>
          <span className="dl-modal-path faint">{jsonPath || "page source"}</span>
          <button className="btn btn-small" onClick={onClose}>
            Close
          </button>
        </div>
        <SourceViewer
          html={html}
          highlight={highlight}
          onClearHighlight={() => setHighlight(null)}
          height="100%"
        />
        {!highlight && (
          <div className="dl-modal-note muted">JSON path "{jsonPath}" not found in the current page source.</div>
        )}
      </div>
    </div>
  );
}

export default function DataLayerPage() {
  const [url, setUrl] = useState("");
  // Default FALSE (= visible browser window). Headless mode has no window
  // for QA to click in at all — that is why clicks were never captured:
  // you were clicking in your own separate Chrome, not the instrumented one.
  const [headless, setHeadless] = useState(false);
  const [checkModal, setCheckModal] = useState<{ event: DataLayerRecord; check: CheckResult } | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [browserStatus, setBrowserStatus] = useState<BrowserStatus>("not_started");
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [currentUrl, setCurrentUrl] = useState("");
  const [dataLayerFound, setDataLayerFound] = useState(false);
  const [instrumented, setInstrumented] = useState(false);
  const [pageTitle, setPageTitle] = useState<string | null>(null);
  const [events, setEvents] = useState<DataLayerRecord[]>(() => loadHistory());
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [clickText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const [sourceModal, setSourceModal] = useState<{
    url: string;
    html: string;
    jsonPath: string;
  } | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);

  const handleViewSource = useCallback(
    async (e: React.MouseEvent, rec: DataLayerRecord) => {
      e.stopPropagation();
      if (!sessionId) return;
      setSourceLoading(true);
      setError(null);
      try {
        const res = await api.dataLayerSource(sessionId);
        const jsonPath = String(
          (rec.data as Record<string, unknown>)?.json_path ??
            (rec.data as Record<string, unknown>)?.jsonPath ??
            "",
        );
        setSourceModal({ url: res.url, html: res.html, jsonPath });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSourceLoading(false);
      }
    },
    [sessionId],
  );

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Merge new backend events into the timeline + app history with dedup.
  const mergeEvents = useCallback((incoming: DataLayerRecord[]) => {
    setEvents((prev) => {
      const seen = seenRef.current;
      const merged = [...prev];
      let changed = false;
      for (const rec of incoming) {
        const key = eventKey(rec);
        if (seen.has(key)) continue;
        seen.add(key);
        merged.push(rec);
        changed = true;
      }
      if (!changed) return prev;
      const sorted = merged.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
      saveHistory(sorted);
      return sorted;
    });
  }, []);

  const applyStatus = useCallback(
    (st: DataLayerStatusResponse) => {
      setBrowserStatus((st.status as BrowserStatus) || "not_started");
      setStatusMsg(st.message ?? null);
      setCurrentUrl(st.current_url || st.url);
      setDataLayerFound(st.data_layer_found);
      setInstrumented(st.instrumented);
      setPageTitle(st.page_title ?? null);
      mergeEvents(st.events ?? []);
      if (st.error) setError(st.error);
    },
    [mergeEvents],
  );

  const poll = useCallback(async () => {
    if (!sessionId) return;
    try {
      const st = await api.dataLayerEvents(sessionId);
      applyStatus(st);
    } catch {
      /* transient — keep polling */
    }
  }, [sessionId, applyStatus]);

  useEffect(() => {
    if (browserStatus === "capturing" || browserStatus === "open") {
      stopPolling();
      pollRef.current = setInterval(poll, 1500);
      poll();
    } else {
      stopPolling();
    }
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, browserStatus]);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const handleStart = async () => {
    if (!url.trim()) {
      setError("Enter a URL first.");
      return;
    }
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.dataLayerStart(url.trim(), {
        navigationPauseMs: 2500,
        clickText: clickText.trim() || undefined,
        headless,
      });
      setSessionId(res.session_id);
      setBrowserStatus("starting");
      setStatusMsg("Browser connected — instrumentation active.");
      setCurrentUrl(url.trim());
      const st = await api.dataLayerEvents(res.session_id);
      applyStatus(st);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBrowserStatus("error");
    } finally {
      setLoading(false);
    }
  };

  const handleClick = async () => {
    if (!sessionId) {
      setError("Start Capture first.");
      return;
    }
    const text = clickText.trim();
    if (!text) {
      setError("Enter click element text first.");
      return;
    }
    setBusyAction("Clicking");
    setError(null);
    try {
      const res = await api.dataLayerClick(sessionId, text);
      setNotice(res.message);
      if (!res.clicked) setError(res.message);
      await poll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const handleDump = async () => {
    if (!sessionId) {
      setError("Start Capture first.");
      return;
    }
    setBusyAction("Dumping");
    setError(null);
    try {
      await poll();
      setNotice("Events refreshed from the browser session.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const handleClear = async () => {
    if (!sessionId) return;
    setBusyAction("Clearing");
    setError(null);
    try {
      await api.dataLayerClear(sessionId);
      // Clear app history + dedup set, then reset UI.
      try {
        localStorage.removeItem(HISTORY_KEY);
      } catch {
        /* ignore */
      }
      seenRef.current = new Set();
      setEvents([]);
      setExpanded(new Set());
      setNotice("History cleared — still capturing new events.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const handleExport = async () => {
    if (!sessionId) return;
    setBusyAction("Exporting");
    setError(null);
    try {
      const payload = await api.dataLayerExport(sessionId);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `data-layer-session-${payload.session_id}-${new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[:T]/g, "-")}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      setNotice(`Exported ${payload.events.length} events from the full session.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const handleCopyAll = () => {
    navigator.clipboard?.writeText(JSON.stringify(events, null, 2));
    setNotice("Copied all events to clipboard.");
  };

  const handleClose = async () => {
    if (!sessionId) return;
    setBusyAction("Closing");
    setError(null);
    try {
      const res = await api.dataLayerClose(sessionId);
      stopPolling();
      setSessionId(null);
      setBrowserStatus("closed");
      setStatusMsg(res.message || "Browser session closed.");
      // Keep app history visible after closing (persistent by design).
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyAction(null);
    }
  };

  const checks = useMemo(() => computeChecks(events), [events]);
  const sessionStatus = useMemo(() => computeSessionStatus(events), [events]);

  const filteredEvents = useMemo(() => {
    const q = search.trim().toLowerCase();
    return events.filter((e) => {
      if (!matchesFilter(e, filter)) return false;
      if (!q) return true;
      const { title, sub } = recordSummary(e);
      const hay = [
        title,
        sub ?? "",
        e.type,
        e.url,
        String((e.data as Record<string, unknown>)?.action ?? ""),
        String((e.data as Record<string, unknown>)?.description ?? ""),
        String((e.data as Record<string, unknown>)?.label ?? ""),
        JSON.stringify(e.data),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [events, search, filter]);

  const toggleExpanded = (seq: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  const meta = STATUS_META[browserStatus];
  const browserLive = browserStatus === "capturing" || browserStatus === "open";
  const dataLayerCount = useMemo(() => events.filter((e) => e.type === "dataLayer").length, [events]);
  const interactionCount = useMemo(
    () => events.filter((e) => e.type === "interaction").length,
    [events],
  );
  const navigationCount = useMemo(
    () => events.filter((e) => e.type === "navigation").length,
    [events],
  );

  return (
    <div className="dl-page">
      <div className="dl-intro">
        <div className="dl-intro-title">Data Layer &amp; Interaction Monitor</div>
        <div className="muted">
          Monitors a real Chrome session, automatically instruments{" "}
          <code>window.dataLayer</code>, and records what you do — clicks, scrolls,
          navigation — as <strong>user interactions</strong>, separate from real{" "}
          <strong>dataLayer events</strong>.
        </div>
      </div>

      <div className="dl-controls">
        <div className="url-bar">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.deccanherald.com/..."
            disabled={!!sessionId}
          />
          <button className="btn btn-primary" onClick={handleStart} disabled={loading || !!sessionId}>
            {loading ? "Starting…" : "Start Capture"}
          </button>
        </div>
        <label className="dl-headless-toggle" style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, fontSize: 12 }}>
          <input
            type="checkbox"
            checked={headless}
            onChange={(e) => setHeadless(e.target.checked)}
            disabled={!!sessionId}
          />
          <span className="faint">
            Run headless (no visible window). <strong>Uncheck this to click around yourself</strong> — a real
            browser window will open and you must click INSIDE that window, not your own Chrome.
          </span>
        </label>

        <div className="dl-actions">
          <button className="btn" onClick={handleDump} disabled={!sessionId || !!busyAction}>
            Dump Events
          </button>
          <button className="btn" onClick={handleClear} disabled={!sessionId || !!busyAction}>
            Clear History
          </button>
          <button className="btn" onClick={handleExport} disabled={!sessionId || events.length === 0}>
            Export JSON
          </button>
          <button className="btn" onClick={handleClose} disabled={!sessionId}>
            Close Browser
          </button>
        </div>
      </div>

      <div className="dl-status card">
        <div className="card-title">Browser Status</div>
        <div className="dl-status-row">
          <span className={`status-dot ${meta.className}`}>{meta.dot}</span>
          <span className={`status-label ${meta.className}`}>{meta.label}</span>
          {browserLive && <span className="badge pass">live</span>}
        </div>
        {currentUrl && (
          <div className="dl-status-line">
            <span className="faint">Current URL: </span>
            <span className="mono">{shortUrl(currentUrl, 90)}</span>
          </div>
        )}
        {pageTitle && (
          <div className="dl-status-line">
            <span className="faint">Page title: </span>
            <span>{pageTitle}</span>
          </div>
        )}
        <div className="dl-status-line">
          <span className="faint">Events captured: </span>
          <span className="mono dl-event-count">{events.length}</span>
          {browserLive && <span className="dl-live-dot" title="Polling live" />}
        </div>
        <div className="dl-status-line">
          <span className="faint">Data Layer: </span>
          <span className={`badge ${dataLayerFound ? "pass" : "warning"}`}>
            {dataLayerFound ? "detected: YES" : "not detected"}
          </span>
          <span className="faint">Capture: </span>
          <span className={`badge ${instrumented ? "pass" : "warning"}`}>
            {instrumented ? "Listening" : "Stopped"}
          </span>
        </div>
        {statusMsg && (
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            {statusMsg}
          </div>
        )}
      </div>

      <div className="dl-status card">
        <div className="card-title">Session Status (Auth / Subscription)</div>
        <div className="dl-status-row">
          <span className="faint">Logged in: </span>
          <span
            className={`badge ${
              sessionStatus.authStatus === "logged_in"
                ? "pass"
                : sessionStatus.authStatus === "non_logged_in"
                  ? "neutral"
                  : "warning"
            }`}
          >
            {sessionStatus.authStatus === "logged_in"
              ? "Yes — logged in"
              : sessionStatus.authStatus === "non_logged_in"
                ? "No — not logged in"
                : "Unknown (no event yet)"}
          </span>
        </div>
        <div className="dl-status-row">
          <span className="faint">Subscribed: </span>
          <span
            className={`badge ${
              sessionStatus.subscriptionStatus === "subscriber" || sessionStatus.subscriptionStatus === "subscribed"
                ? "pass"
                : sessionStatus.subscriptionStatus === "non_subscriber" || sessionStatus.subscriptionStatus === "NA"
                  ? "neutral"
                  : "warning"
            }`}
          >
            {sessionStatus.subscriptionStatus === "subscriber" || sessionStatus.subscriptionStatus === "subscribed"
              ? `Yes — subscriber${sessionStatus.planName ? ` (${sessionStatus.planName})` : ""}`
              : sessionStatus.subscriptionStatus === "non_subscriber"
                ? "No — non-subscriber"
                : sessionStatus.subscriptionStatus === "NA"
                  ? "N/A (not logged in)"
                  : "Unknown (no event yet)"}
          </span>
        </div>
        {sessionStatus.source !== "none" && (
          <div className="dl-status-line">
            <span className="faint">Derived from: </span>
            <span className="mono">{sessionStatus.source}</span>
            <span className="faint"> at </span>
            <span className="mono">{formatTime(sessionStatus.updatedAt)}</span>
          </div>
        )}
      </div>

      <div className="dl-events-section">
        <div className="card-title">Activity History</div>
        <div className="dl-events-toolbar">
          <input
            className="dl-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search events (event, action, URL, element text, JSON)…"
          />
          <select
            className="btn dl-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value as FilterKey)}
          >
            <option value="all">All Events</option>
            <option value="dataLayer">Data Layer</option>
            <option value="interaction">User Interaction</option>
            <option value="navigation">Navigation</option>
            <option value="click">Click</option>
            <option value="scroll">Scroll</option>
            <option value="page_load">Page Load</option>
            <option value="input">Input</option>
            <option value="submit">Submit</option>
            <option value="pointer">Pointer</option>
          </select>
          <button className="btn btn-small" onClick={handleCopyAll} disabled={events.length === 0}>
            Copy All Events
          </button>
        </div>
        <div className="dl-count-line muted">
          {events.length} event{events.length === 1 ? "" : "s"} captured
          {dataLayerCount > 0 ? ` · ${dataLayerCount} dataLayer` : ""}
          {interactionCount > 0 ? ` · ${interactionCount} interaction${interactionCount === 1 ? "" : "s"}` : ""}
          {navigationCount > 0 ? ` · ${navigationCount} navigation${navigationCount === 1 ? "" : "s"}` : ""}
          {filteredEvents.length !== events.length ? ` · ${filteredEvents.length} shown` : ""}
        </div>

        {events.length === 0 ? (
          <div className="dl-empty muted">
            {browserLive ? (
              <>
                No events captured yet. Interact with the website in the browser — clicks,
                scrolls and dataLayer pushes will appear here automatically.
              </>
            ) : (
              <>Start a capture session to see events here.</>
            )}
          </div>
        ) : (
          <div className="dl-table">
            <div className="dl-table-head">
              <span className="dl-seq mono">#</span>
              <span className="dl-time mono">Time</span>
              <span className="dl-type">Type</span>
              <span className="dl-event-name mono">Event / Action</span>
              <span className="dl-page mono">Page</span>
              <span className="dl-url mono">URL</span>
              <span className="dl-check">Check</span>
              <span />
            </div>
            {filteredEvents.length === 0 ? (
              <div className="dl-empty muted">No events match the search / filter.</div>
            ) : (
              filteredEvents.map((e) => (
                <EventRow
                  key={eventKey(e)}
                  event={e}
                  expanded={expanded.has(e.seq)}
                  onToggle={() => toggleExpanded(e.seq)}
                  onViewSource={(ev) => handleViewSource(ev, e)}
                  check={checks.get(e.seq)}
                  onCheckClick={(ev) => {
                    ev.stopPropagation();
                    const c = checks.get(e.seq);
                    if (c) setCheckModal({ event: e, check: c });
                  }}
                />
              ))
            )}
          </div>
        )}
      </div>

      {sourceLoading && (
        <div className="dl-modal-backdrop">
          <div className="dl-modal loading">
            <span className="spinner" /> Loading page source…
          </div>
        </div>
      )}

      {sourceModal && (
        <SourceModal
          url={sourceModal.url}
          html={sourceModal.html}
          jsonPath={sourceModal.jsonPath}
          onClose={() => setSourceModal(null)}
        />
      )}

      {checkModal && <CheckDetailModal event={checkModal.event} check={checkModal.check} onClose={() => setCheckModal(null)} />}
    </div>
  );
}

/** Detail modal for a clicked Check result — reuses the existing dl-modal
 * chrome (same classes as SourceModal) so no second modal system is added. */
function CheckDetailModal({
  event,
  check,
  onClose,
}: {
  event: DataLayerRecord;
  check: CheckResult;
  onClose: () => void;
}) {
  const eventName = String((event.data as Record<string, unknown>)?.event ?? event.type);
  return (
    <div className="dl-modal-backdrop" onClick={onClose}>
      <div className="dl-modal" onClick={(e) => e.stopPropagation()}>
        <div className="dl-modal-head">
          <span className="mono">{eventName}</span>
          <span className={checkBadgeClass(check.kind)}>{check.label}</span>
          <button className="btn btn-small" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="dl-check-detail">
          {check.kind === "NO_EVENT" && (
            <>
              <div className="dl-detail-meta">
                <div>
                  <span className="faint">Reason: </span>
                  <span>{check.noEventReason}</span>
                </div>
              </div>
              <div className="dl-detail-data-header">
                <span className="faint">Clicked element:</span>
              </div>
              <JsonTree value={check.clickedElement ?? {}} />
            </>
          )}
          {check.kind === "SEQUENCE_FAIL" && (
            <div className="dl-detail-meta">
              <div>
                <span className="faint">Trigger event: </span>
                <span className="mono">{check.trigger}</span>
              </div>
              <div>
                <span className="faint">Expected follow-up: </span>
                <span className="mono">{check.expectedFollowUp}</span>
              </div>
              <div>
                <span className="faint">Window: </span>
                <span className="mono">{check.windowMs}ms</span>
              </div>
            </div>
          )}
          {(check.kind === "PASS" || check.kind === "FAIL") && check.issues.length > 0 && (
            <>
              <div className="dl-detail-data-header">
                <span className="faint">{check.issues.length} issue(s):</span>
              </div>
              <ul className="dl-issue-list">
                {check.issues.map((iss, i) => (
                  <li key={i}>
                    <span className="mono">"{iss.field}"</span>: {iss.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
          {check.payload && (
            <>
              <div className="dl-detail-data-header">
                <span className="faint">Payload:</span>
                <button
                  className="btn btn-small"
                  onClick={() => navigator.clipboard?.writeText(JSON.stringify(check.payload, null, 2))}
                >
                  Copy JSON
                </button>
              </div>
              <JsonTree
                value={
                  check.payload
                    ? reorderForDisplay(String(check.payload.event ?? eventName), check.payload)
                    : check.payload
                }
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
