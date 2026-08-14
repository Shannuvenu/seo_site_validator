/**
 * QA Monitor core: observes window.dataLayer + real user clicks, validates
 * events against the Prajavani spec, tracks sequences, and persists the QA log
 * to sessionStorage.
 *
 * Design rules:
 * - The monitor OBSERVES only. It never manufactures analytics events.
 * - dataLayer.push is wrapped once, preserving the original behavior and return
 *   value. Reassignment of window.dataLayer is detected and re-hooked.
 * - Re-running init() tears down the previous monitor (removes listeners,
 *   restores the original push) so events/sequences are never duplicated.
 * - The monitor is transport-agnostic (works pasted in console, as a
 *   bookmarklet, or as a userscript).
 */
import { EVENT_SCHEMAS, hasSchemaForEvent } from "./schemas";
import { normalizePayload, validateEvent } from "./validator";

export const MONITOR_VERSION = "1.0.0";
export const STORAGE_KEY = "pv.datalayer.qa.log.v1";

export type RowStatus = "WAITING" | "FIRED" | "NO EVENT" | "SYSTEM";

export interface ElementInfo {
  tag: string;
  id?: string;
  class?: string;
  text?: string;
  href?: string;
  role?: string;
  ariaLabel?: string;
  dataAttrs: Record<string, string>;
}

export interface QaRow {
  id: string;
  time: string; // ISO
  kind: "event" | "click" | "sequence" | "system";
  /** Display time (HH:MM:SS). */
  timeLabel: string;
  status: RowStatus;
  eventName?: string;
  variant?: string;
  check: string; // "PASS" | "FAIL" | "WARN" | "—"
  validationIssues: string[];
  /** Triggered-by element (for click association). */
  element?: ElementInfo | null;
  payload?: Record<string, unknown>;
  rawPayload?: unknown;
  fromGtag?: boolean;
  sequenceNote?: string;
  /** Source url when the row was created (survives navigation). */
  url?: string;
  payloadJson?: string;
}

export interface MonitorOptions {
  /** Sequence window in ms for trigger -> user_properties_update. */
  sequenceWindowMs?: number;
  /** Click -> event association window in ms. */
  clickEventWindowMs?: number;
  /** Max stored rows. */
  maxRows?: number;
  /** If false, clicks on elements that are unlikely to fire analytics are
   * still recorded but marked as informational (no NO EVENT failure). */
  markClickNoEventAsFailure?: boolean;
  /** Callback fired whenever the log changes (UI hook). */
  onLogChange?: (rows: QaRow[]) => void;
  onStatus?: (status: string) => void;
}

type ResolvedOptions = Required<
  Pick<
    MonitorOptions,
    "sequenceWindowMs" | "clickEventWindowMs" | "maxRows" | "markClickNoEventAsFailure"
  >
> &
  Pick<MonitorOptions, "onLogChange" | "onStatus">;

interface SequenceTracker {
  triggerEvent: string;
  triggerTime: number;
  triggeredBy: string;
  timer: ReturnType<typeof setTimeout> | null;
}

interface ClickTracker {
  element: ElementInfo;
  time: number;
  timer: ReturnType<typeof setTimeout> | null;
  matched: boolean;
}

const TRIGGER_EVENTS = ["page_view", "purchase", "sign_up", "login", "logout"];

function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour12: false });
}

/** Extract element info from a click target (never throws). */
export function elementInfo(el: EventTarget | null): ElementInfo | null {
  if (!el || !(el instanceof Element)) return null;
  const info: ElementInfo = {
    tag: el.tagName.toLowerCase(),
    dataAttrs: {},
  };
  const id = el.getAttribute("id");
  if (id) info.id = id;
  const cls = el.getAttribute("class");
  if (cls) info.class = cls.split(/\s+/).filter(Boolean).slice(0, 8).join(" ");
  const href = el.getAttribute("href");
  if (href) info.href = href;
  const role = el.getAttribute("role");
  if (role) info.role = role;
  const aria = el.getAttribute("aria-label");
  if (aria) info.ariaLabel = aria;
  const text = (el.textContent || "").replace(/\s+/g, " ").trim();
  if (text && text.length <= 120) info.text = text;
  for (const attr of Array.from(el.attributes)) {
    if (attr.name.startsWith("data-")) {
      info.dataAttrs[attr.name] = attr.value;
    }
  }
  return info;
}

/** Resolve the nearest meaningful interactive ancestor of a click target. */
function interactiveAncestor(el: Element): Element {
  const sel = [
    "a", "button", "input", "textarea", "select", "label", "summary",
    '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
    "[onclick]", "[data-testid]", "[aria-label]", "[title]",
  ].join(",");
  let cur: Element | null = el;
  while (cur && cur !== document.body && cur !== document.documentElement) {
    if (cur.matches && cur.matches(sel)) return cur;
    cur = cur.parentElement;
  }
  return el;
}

export class QaMonitor {
  rows: QaRow[] = [];
  options: ResolvedOptions;
  private originalPush: unknown = null;
  private hookedArray: unknown = null;
  private rearmTimer: ReturnType<typeof setInterval> | null = null;
  private clickHandler: ((e: MouseEvent) => void) | null = null;
  private pendingClicks: ClickTracker[] = [];
  private sequence: SequenceTracker | null = null;
  private eventListener: ((e: Event) => void) | null = null;
  private destroyed = false;

  constructor(options: MonitorOptions = {}) {
    this.options = {
      sequenceWindowMs: options.sequenceWindowMs ?? 2500,
      clickEventWindowMs: options.clickEventWindowMs ?? 1200,
      maxRows: options.maxRows ?? 1000,
      markClickNoEventAsFailure: options.markClickNoEventAsFailure ?? true,
      onLogChange: options.onLogChange,
      onStatus: options.onStatus,
    };
  }

  /* ---------------- lifecycle ---------------- */

  start(): void {
    if (this.destroyed) return;
    this.addSystemRow(`Monitor v${MONITOR_VERSION} started`);
    this.hookDataLayer();
    this.installClickListener();
    this.installEventListener();
    this.rearmTimer = setInterval(() => this.hookDataLayer(), 250);
    this.emitLog();
    this.emitStatus("Monitoring window.dataLayer — interact with the site.");
  }

  destroy(): void {
    this.destroyed = true;
    if (this.rearmTimer) clearInterval(this.rearmTimer);
    if (this.sequence?.timer) clearTimeout(this.sequence.timer);
    for (const c of this.pendingClicks) if (c.timer) clearTimeout(c.timer);
    this.pendingClicks = [];
    if (this.clickHandler) {
      document.removeEventListener("click", this.clickHandler, true);
      this.clickHandler = null;
    }
    if (this.eventListener) {
      window.removeEventListener("dataLayerPush", this.eventListener);
      this.eventListener = null;
    }
    this.restorePush();
  }

  private restorePush(): void {
    if (this.hookedArray && this.originalPush) {
      try {
        const arr = this.hookedArray as { push?: unknown };
        const orig = (arr as { __qaOriginalPush?: unknown }).__qaOriginalPush;
        if (typeof orig === "function") {
          arr.push = orig as typeof arr.push;
        } else {
          arr.push = this.originalPush as typeof arr.push;
        }
        delete (arr as { __qaHooked?: unknown }).__qaHooked;
        delete (arr as { __qaOriginalPush?: unknown }).__qaOriginalPush;
      } catch {
        /* noop */
      }
    }
    this.hookedArray = null;
    this.originalPush = null;
  }

  /* ---------------- dataLayer hooking ---------------- */

  private hookDataLayer(): void {
    const dl = (window as unknown as Record<string, unknown>).dataLayer;
    if (!Array.isArray(dl)) return;
    // Already hooked by us? Verify it's still our wrapper.
    if (dl === this.hookedArray && (dl as { __qaHooked?: boolean }).__qaHooked) return;
    // If a previous monitor left this array hooked, restore the original push
    // first so we don't stack wrappers (and never double-observe).
    const prev = dl as { __qaHooked?: boolean; push?: unknown };
    if (prev.__qaHooked && prev.push && dl !== this.hookedArray) {
      try {
        const arr = dl as { push?: unknown };
        const orig = (dl as unknown as { __qaOriginalPush?: unknown }).__qaOriginalPush;
        if (typeof orig === "function") arr.push = orig as typeof arr.push;
      } catch {
        /* noop */
      }
    }
    this.originalPush = dl.push;
    this.hookedArray = dl;
    // Store the original push on the array so a later monitor can restore it.
    try {
      Object.defineProperty(dl, "__qaOriginalPush", {
        value: this.originalPush,
        enumerable: false,
        configurable: true,
        writable: true,
      });
    } catch {
      (dl as { __qaOriginalPush?: unknown }).__qaOriginalPush = this.originalPush;
    }
    try {
      Object.defineProperty(dl, "__qaHooked", { value: true, enumerable: false });
    } catch {
      (dl as { __qaHooked?: boolean }).__qaHooked = true;
    }
    const original = dl.push.bind(dl);
    dl.push = (...args: unknown[]) => {
      const ret = original(...args);
      try {
        for (const arg of args) this.observePush(arg);
      } catch {
        /* never break the site's push */
      }
      return ret;
    };
    // Snapshot existing events so the QA log starts complete, but track which
    // items we've already seen so re-hooking after a reinit never duplicates.
    const seen = (dl as { __qaSeen?: Set<unknown> }).__qaSeen ?? new Set<unknown>();
    try {
      Object.defineProperty(dl, "__qaSeen", { value: seen, enumerable: false });
    } catch {
      (dl as { __qaSeen?: Set<unknown> }).__qaSeen = seen;
    }
    for (const item of dl as unknown[]) {
      if (seen.has(item)) continue;
      seen.add(item);
      this.observePush(item);
    }
  }

  private observePush(value: unknown): void {
    // Track every observed raw item on the hooked array so re-hooking after a
    // reinit never re-observes already-seen pushes (no duplicate rows).
    const dl = (window as unknown as Record<string, unknown>).dataLayer;
    if (Array.isArray(dl)) {
      const seen = (dl as { __qaSeen?: Set<unknown> }).__qaSeen;
      if (seen) seen.add(value);
    }
    const normalized = normalizePayload(value);
    if (!normalized) return;
    const result = validateEvent(normalized);
    const schemas = (window as unknown as { __qaSchemas?: typeof EVENT_SCHEMAS })
      .__qaSchemas ?? EVENT_SCHEMAS;
    const variants = schemas.filter((s) => s.event === normalized.eventName);
    const variant = variants.length ? variants.map((v) => v.variant).filter(Boolean).join(" / ") : undefined;
    const row: QaRow = {
      id: uid(),
      time: new Date().toISOString(),
      timeLabel: fmtTime(new Date().toISOString()),
      kind: "event",
      status: "FIRED",
      eventName: normalized.eventName,
      variant,
      check: result.uncovered ? "—" : result.status,
      validationIssues: result.issues.map((i) => `${i.field}: ${i.reason}`),
      payload: normalized.payload,
      rawPayload: value,
      fromGtag: normalized.fromGtag,
      url: location.href,
    };
    this.addRow(row);

    // Sequence: triggers expect a user_properties_update follow-up.
    if (TRIGGER_EVENTS.includes(normalized.eventName)) {
      this.expectUserPropertiesUpdate(normalized.eventName);
    }
    if (normalized.eventName === "user_properties_update") {
      this.resolveSequence();
    }

    // Click association: any event fired within the click window is attributed.
    const now = Date.now();
    for (const click of this.pendingClicks) {
      if (now - click.time <= this.options.clickEventWindowMs && !click.matched) {
        click.matched = true;
        row.element = click.element;
        if (click.timer) clearTimeout(click.timer);
        this.updateRow(row.id, { status: "FIRED", element: click.element });
        this.emitLog();
      }
    }
  }

  /* ---------------- click tracking ---------------- */

  private installClickListener(): void {
    this.clickHandler = (e: MouseEvent) => {
      const el = interactiveAncestor(e.target as Element);
      const info = elementInfo(el);
      if (!info) return;
      const tracker: ClickTracker = {
        element: info,
        time: Date.now(),
        matched: false,
        timer: null,
      };
      tracker.timer = setTimeout(() => {
        if (!tracker.matched) {
          // No event fired within the window.
          const clickRow: QaRow = {
            id: uid(),
            time: new Date().toISOString(),
            timeLabel: fmtTime(new Date().toISOString()),
            kind: "click",
            status: "NO EVENT",
            check: "NO EVENT",
            validationIssues: [],
            element: info,
            url: location.href,
          };
          if (!this.options.markClickNoEventAsFailure) {
            clickRow.check = "—";
            clickRow.status = "SYSTEM";
            clickRow.validationIssues = ["click observed; element not expected to fire analytics (informational)"];
          } else {
            clickRow.validationIssues = [
              `no dataLayer event fired within ${this.options.clickEventWindowMs}ms of clicking`,
            ];
          }
          this.addRow(clickRow);
        }
        const idx = this.pendingClicks.indexOf(tracker);
        if (idx >= 0) this.pendingClicks.splice(idx, 1);
      }, this.options.clickEventWindowMs);
      this.pendingClicks.push(tracker);
      // Keep pending clicks bounded.
      if (this.pendingClicks.length > 50) {
        const dropped = this.pendingClicks.shift();
        if (dropped?.timer) clearTimeout(dropped.timer);
      }
    };
    document.addEventListener("click", this.clickHandler, true);
  }

  /* ---------------- sequence validation ---------------- */

  private expectUserPropertiesUpdate(triggerEvent: string): void {
    if (this.sequence) {
      // A new trigger supersedes a pending one; fail the old with SEQUENCE FAIL.
      this.failSequence("superseded by another trigger event");
    }
    const st: SequenceTracker = {
      triggerEvent,
      triggerTime: Date.now(),
      triggeredBy: "dataLayer.push",
      timer: null,
    };
    st.timer = setTimeout(() => {
      this.failSequence("no user_properties_update within the sequence window");
    }, this.options.sequenceWindowMs);
    this.sequence = st;
    this.addRow({
      id: uid(),
      time: new Date().toISOString(),
      timeLabel: fmtTime(new Date().toISOString()),
      kind: "sequence",
      status: "WAITING",
      check: "WAITING",
      eventName: `sequence: ${triggerEvent} → user_properties_update`,
      sequenceNote: `waiting up to ${this.options.sequenceWindowMs}ms for user_properties_update`,
      validationIssues: [],
      url: location.href,
    });
  }

  private resolveSequence(): void {
    if (!this.sequence) return;
    const st = this.sequence;
    this.sequence = null;
    if (st.timer) clearTimeout(st.timer);
    this.addRow({
      id: uid(),
      time: new Date().toISOString(),
      timeLabel: fmtTime(new Date().toISOString()),
      kind: "sequence",
      status: "FIRED",
      check: "PASS",
      eventName: `sequence: ${st.triggerEvent} → user_properties_update`,
      sequenceNote: `follow-up arrived within ${Date.now() - st.triggerTime}ms (window ${this.options.sequenceWindowMs}ms)`,
      validationIssues: [],
      url: location.href,
    });
  }

  private failSequence(reason: string): void {
    if (!this.sequence) return;
    const st = this.sequence;
    this.sequence = null;
    if (st.timer) clearTimeout(st.timer);
    this.addRow({
      id: uid(),
      time: new Date().toISOString(),
      timeLabel: fmtTime(new Date().toISOString()),
      kind: "sequence",
      status: "NO EVENT",
      check: "SEQUENCE FAIL",
      eventName: `sequence: ${st.triggerEvent} → user_properties_update`,
      sequenceNote: reason,
      validationIssues: [reason],
      url: location.href,
    });
  }

  /* ---------------- cross-monitor / page events ---------------- */

  private installEventListener(): void {
    // Allow OTHER code (e.g. the production page) to notify the monitor of
    // pushes it intercepts, without breaking anything.
    this.eventListener = (e: Event) => {
      const custom = e as CustomEvent;
      if (custom.detail && typeof custom.detail === "object") {
        const v = (custom.detail as { value?: unknown }).value;
        if (v !== undefined) this.observePush(v);
      }
    };
    window.addEventListener("dataLayerPush", this.eventListener);
  }

  /* ---------------- persistence ---------------- */

  private addRow(row: QaRow): void {
    this.rows.push(row);
    if (this.rows.length > this.options.maxRows) {
      this.rows = this.rows.slice(-this.options.maxRows);
    }
    this.emitLog();
  }

  private updateRow(id: string, patch: Partial<QaRow>): void {
    const row = this.rows.find((r) => r.id === id);
    if (row) Object.assign(row, patch);
  }

  private emitLog(): void {
    this.options.onLogChange?.(this.rows.slice());
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(this.rows));
    } catch {
      /* storage full / blocked */
    }
  }

  private emitStatus(msg: string): void {
    this.options.onStatus?.(msg);
  }

  addSystemRow(message: string): void {
    this.addRow({
      id: uid(),
      time: new Date().toISOString(),
      timeLabel: fmtTime(new Date().toISOString()),
      kind: "system",
      status: "SYSTEM",
      check: "SYSTEM",
      eventName: "system",
      validationIssues: [],
      sequenceNote: message,
      url: location.href,
    });
  }

  clear(): void {
    this.rows = [];
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* noop */
    }
    this.addSystemRow("QA log cleared");
    this.emitLog();
  }

  /** Restore rows persisted by a previous monitor instance in this tab. */
  restore(): number {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return 0;
      const parsed = JSON.parse(raw) as QaRow[];
      if (!Array.isArray(parsed)) return 0;
      this.rows = parsed.slice(-this.options.maxRows);
      this.emitLog();
      return parsed.length;
    } catch {
      return 0;
    }
  }
}

/** Singleton accessor; ensures only one live monitor per tab. */
let activeMonitor: QaMonitor | null = null;

export function getActiveMonitor(): QaMonitor | null {
  return activeMonitor;
}

export function createMonitor(options: MonitorOptions = {}): QaMonitor {
  if (activeMonitor) {
    activeMonitor.destroy();
  }
  activeMonitor = new QaMonitor(options);
  return activeMonitor;
}

/** True if any schema is defined for an event (used for the CHECK: — column). */
export function isKnownEvent(eventName: string): boolean {
  return hasSchemaForEvent(eventName);
}
