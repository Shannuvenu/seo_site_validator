/**
 * DataLayer QA Monitor — prajavani.net
 *
 * Floating draggable QA panel. Pure DOM (framework-free) so it can be pasted
 * into the DevTools console, run as a bookmarklet, or installed as a
 * Tampermonkey userscript. It renders the QaMonitor log, validates events
 * against the Prajavani Paywall spec, shows PASS / FAIL / WARN / NO EVENT /
 * SEQUENCE FAIL, and exports CSV / JSON.
 */
import { QaMonitor, QaRow, createMonitor, STORAGE_KEY } from "./monitor";
import { EVENT_SCHEMAS } from "./schemas";

export interface QaUiOptions {
  sequenceWindowMs?: number;
  clickEventWindowMs?: number;
  markClickNoEventAsFailure?: boolean;
  maxRows?: number;
  /** Auto-start when the panel is created. */
  autoStart?: boolean;
}

const PANEL_ID = "pv-datalayer-qa-monitor";

/* ---------------- helpers ---------------- */

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusClass(status: string): string {
  switch (status) {
    case "FIRED":
      return "pvqa-pass";
    case "NO EVENT":
      return "pvqa-noevent";
    case "WAITING":
      return "pvqa-wait";
    case "SYSTEM":
      return "pvqa-system";
    default:
      return "";
  }
}

function checkClass(check: string): string {
  if (check === "PASS") return "pvqa-pass";
  if (check === "FAIL" || check === "SEQUENCE FAIL") return "pvqa-noevent";
  if (check === "WARN") return "pvqa-warn";
  if (check === "—") return "pvqa-unchecked";
  return "";
}

function csvCell(v: unknown): string {
  if (v === undefined || v === null) return "";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return '"' + String(s).replace(/"/g, '""') + '"';
}

function download(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function elementSummary(row: QaRow): string {
  if (!row.element) return "";
  const e = row.element;
  const parts = [e.tag, e.id ? `#${e.id}` : "", e.class ? `.${e.class.split(" ").join(".")}` : ""];
  return parts.join("") + (e.text ? ` "${e.text.slice(0, 40)}"` : "");
}

/* ---------------- panel ---------------- */

export class QaMonitorPanel {
  private monitor: QaMonitor;
  private root: HTMLDivElement;
  private header: HTMLDivElement;
  private body: HTMLDivElement;
  private tableBody: HTMLTableSectionElement;
  private searchInput: HTMLInputElement;
  private countLabel: HTMLSpanElement;
  private statusLabel: HTMLDivElement;
  private minimized = false;
  private filter = "all";
  private rows: QaRow[] = [];

  constructor(options: QaUiOptions = {}) {
    // Tear down any previous panel (single instance per tab).
    const existing = document.getElementById(PANEL_ID);
    if (existing) existing.remove();

    this.monitor = createMonitor({
      sequenceWindowMs: options.sequenceWindowMs,
      clickEventWindowMs: options.clickEventWindowMs,
      maxRows: options.maxRows,
      markClickNoEventAsFailure: options.markClickNoEventAsFailure,
      onLogChange: (rows) => {
        this.rows = rows;
        this.render();
      },
      onStatus: (msg) => {
        this.statusLabel.textContent = msg;
      },
    });

    this.root = el("div", "pvqa-root");
    this.root.id = PANEL_ID;

    this.header = el("div", "pvqa-header");
    this.header.textContent = "DataLayer QA Monitor — prajavani.net";
    this.header.title = "Drag to move";

    const btnMin = el("button", "pvqa-btn", "—");
    btnMin.title = "Minimize / restore";
    btnMin.addEventListener("click", () => this.toggleMinimize());

    const btnClear = el("button", "pvqa-btn", "Clear");
    btnClear.title = "Clear QA log (current session)";
    btnClear.addEventListener("click", () => this.monitor.clear());

    const btnCsv = el("button", "pvqa-btn", "Export CSV");
    btnCsv.addEventListener("click", () => this.exportCsv());

    const btnJson = el("button", "pvqa-btn", "Export JSON");
    btnJson.addEventListener("click", () => this.exportJson());

    this.header.appendChild(el("span", "pvqa-title", "DataLayer QA Monitor — prajavani.net"));
    const actions = el("div", "pvqa-actions");
    actions.append(btnMin, btnClear, btnCsv, btnJson);
    this.header.appendChild(actions);

    this.body = el("div", "pvqa-body");
    this.body.style.flex = "1";
    this.body.style.minHeight = "0";
    this.body.style.overflow = "hidden";

    // Toolbar
    const toolbar = el("div", "pvqa-toolbar");
    this.searchInput = el("input", "pvqa-search");
    this.searchInput.placeholder = "Search event / element / payload…";
    this.searchInput.addEventListener("input", () => this.render());
    const filterSelect = el("select", "pvqa-filter");
    ["all", "PASS", "FAIL", "WARN", "NO EVENT", "SEQUENCE", "—"].forEach((f) => {
      const opt = el("option", undefined, f);
      opt.value = f;
      filterSelect.appendChild(opt);
    });
    filterSelect.addEventListener("change", () => {
      this.filter = filterSelect.value;
      this.render();
    });
    this.countLabel = el("span", "pvqa-count", "0 events");
    toolbar.append(this.searchInput, filterSelect, this.countLabel);

    this.statusLabel = el("div", "pvqa-status", "Ready.");

    // Table
    const table = el("table", "pvqa-table");
    const thead = el("thead");
    const headRow = el("tr");
    ["Time", "Status", "Event", "Check", "Triggered by", "Payload"].forEach((h) =>
      headRow.appendChild(el("th", undefined, h)),
    );
    thead.appendChild(headRow);
    this.tableBody = el("tbody");
    table.append(thead, this.tableBody);
    const tableWrap = el("div", "pvqa-table-wrap");
    tableWrap.appendChild(table);

    this.body.append(toolbar, this.statusLabel, tableWrap);
    this.root.append(this.header, this.body);
    document.body.appendChild(this.root);

    this.makeDraggable();

    // Restore prior session history.
    const restored = this.monitor.restore();
    if (restored > 0) {
      this.statusLabel.textContent = `Restored ${restored} events from this browser session…`;
    }

    if (options.autoStart !== false) {
      this.monitor.start();
    }
  }

  private render(): void {
    const q = this.searchInput.value.trim().toLowerCase();
    const visible = this.rows.filter((row) => {
      if (this.filter !== "all") {
        if (this.filter === "SEQUENCE" && row.kind !== "sequence") return false;
        if (this.filter !== "SEQUENCE" && row.check !== this.filter && row.status !== this.filter) return false;
      }
      if (!q) return true;
      const hay = [
        row.eventName,
        row.check,
        row.status,
        row.variant,
        elementSummary(row),
        row.validationIssues.join(" "),
        row.sequenceNote,
        row.payloadJson ?? "",
        row.payload ? JSON.stringify(row.payload) : "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
    this.countLabel.textContent = `${visible.length} of ${this.rows.length}`;

    this.tableBody.textContent = "";
    for (const row of visible) {
      const tr = el("tr");
      const timeTd = el("td", "pvqa-mono", row.timeLabel);
      const statusTd = el("td");
      const statusBadge = el("span", `pvqa-badge ${statusClass(row.status)}`, row.status);
      statusTd.appendChild(statusBadge);
      const eventTd = el("td");
      eventTd.appendChild(el("span", "pvqa-eventname", row.eventName ?? row.kind));
      if (row.variant) eventTd.appendChild(el("div", "pvqa-variant", row.variant));
      if (row.sequenceNote) eventTd.appendChild(el("div", "pvqa-seqnote", row.sequenceNote));
      const checkTd = el("td");
      const checkBadge = el("span", `pvqa-badge ${checkClass(row.check)}`, row.check);
      if (row.validationIssues.length) checkBadge.title = row.validationIssues.join("\n");
      checkBadge.style.cursor = "pointer";
      checkBadge.addEventListener("click", () => this.showPayloadModal(row));
      checkTd.appendChild(checkBadge);
      const elTd = el("td", "pvqa-el", elementSummary(row));
      const payloadTd = el("td");
      const payloadBtn = el("button", "pvqa-btn pvqa-btn-small", row.kind === "event" ? "View" : "—");
      if (row.kind === "event" && row.payload) {
        payloadBtn.addEventListener("click", () => this.showPayloadModal(row));
      } else {
        payloadBtn.disabled = true;
      }
      payloadTd.appendChild(payloadBtn);
      tr.append(timeTd, statusTd, eventTd, checkTd, elTd, payloadTd);
      this.tableBody.appendChild(tr);
    }
  }

  private toggleMinimize(): void {
    this.minimized = !this.minimized;
    this.body.style.display = this.minimized ? "none" : "";
  }

  private showPayloadModal(row: QaRow): void {
    const backdrop = el("div", "pvqa-modal-backdrop");
    const modal = el("div", "pvqa-modal");
    const head = el("div", "pvqa-modal-head");
    head.appendChild(
      el("span", "pvqa-modal-title", `${row.eventName ?? row.kind} — ${row.check}`),
    );
    const btnCopy = el("button", "pvqa-btn", "Copy");
    btnCopy.addEventListener("click", () => {
      try {
        navigator.clipboard?.writeText(JSON.stringify(row.payload ?? {}, null, 2));
      } catch {
        /* noop */
      }
    });
    const btnClose = el("button", "pvqa-btn", "Close");
    btnClose.addEventListener("click", () => backdrop.remove());
    head.append(btnCopy, btnClose);
    modal.append(head);

    if (row.variant) {
      modal.appendChild(el("div", "pvqa-variant", `Schema/variant: ${row.variant}`));
    }

    if (row.validationIssues.length) {
      modal.appendChild(el("div", undefined, `${row.validationIssues.length} issue(s):`));
      const list = el("ul");
      for (const issue of row.validationIssues) {
        list.appendChild(el("li", undefined, issue));
      }
      modal.appendChild(list);
    }

    if (row.sequenceNote) {
      modal.appendChild(el("div", "pvqa-seqnote", row.sequenceNote));
    }

    if (row.element) {
      modal.appendChild(el("div", undefined, "Clicked element:"));
      const elPre = el("pre", "pvqa-modal-json");
      elPre.textContent = JSON.stringify(row.element, null, 2);
      modal.appendChild(elPre);
    }

    if (row.payload) {
      modal.appendChild(el("div", undefined, "Payload:"));
      const pre = el("pre", "pvqa-modal-json");
      pre.textContent = JSON.stringify(row.payload, null, 2);
      modal.appendChild(pre);
    } else if (!row.element) {
      modal.appendChild(el("div", undefined, "No payload captured for this row."));
    }

    backdrop.appendChild(modal);
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) backdrop.remove();
    });
    document.body.appendChild(backdrop);
  }

  private exportCsv(): void {
    const header = [
      "time", "status", "event_name", "check", "validation_issues",
      "element", "element_attributes", "payload_json", "sequence",
    ];
    const lines = [header.join(",")];
    for (const row of this.rows) {
      const attrs = row.element
        ? JSON.stringify({ ...row.element, dataAttrs: row.element.dataAttrs })
        : "";
      lines.push(
        [
          csvCell(row.time),
          csvCell(row.status),
          csvCell(row.eventName),
          csvCell(row.check),
          csvCell(row.validationIssues.join(" | ")),
          csvCell(elementSummary(row)),
          csvCell(attrs),
          csvCell(row.payloadJson ?? (row.payload ? JSON.stringify(row.payload) : "")),
          csvCell(row.sequenceNote),
        ].join(","),
      );
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    download(`prajavani-datalayer-qa-${stamp}.csv`, lines.join("\n"), "text/csv");
  }

  private exportJson(): void {
    const payload = {
      exportedAt: new Date().toISOString(),
      site: "prajavani.net",
      monitorVersion: "1.0.0",
      total: this.rows.length,
      rows: this.rows.map((r) => ({
        time: r.time,
        status: r.status,
        event: r.eventName,
        variant: r.variant,
        check: r.check,
        validationIssues: r.validationIssues,
        payload: r.payload,
        clickedElement: r.element,
        sequence: r.sequenceNote,
        url: r.url,
      })),
    };
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    download(
      `prajavani-datalayer-qa-${stamp}.json`,
      JSON.stringify(payload, null, 2),
      "application/json",
    );
  }

  private makeDraggable(): void {
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let origLeft = 0;
    let origTop = 0;
    this.header.addEventListener("mousedown", (e) => {
      if ((e.target as HTMLElement).closest(".pvqa-btn")) return;
      dragging = true;
      const rect = this.root.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      origLeft = rect.left;
      origTop = rect.top;
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      this.root.style.left = `${Math.max(0, origLeft + dx)}px`;
      this.root.style.top = `${Math.max(0, origTop + dy)}px`;
    });
    document.addEventListener("mouseup", () => {
      dragging = false;
    });
  }
}

/* ---------------- standalone entry ---------------- */

let panel: QaMonitorPanel | null = null;

export function initQaMonitor(options: QaUiOptions = {}): QaMonitorPanel {
  if (panel) {
    document.getElementById(PANEL_ID)?.remove();
  }
  panel = new QaMonitorPanel(options);
  // Expose the monitor on window so destroyQaMonitor / the console entry can
  // reach it and so re-running init tears the previous one down cleanly.
  (window as unknown as { __qaMonitor?: QaMonitor }).__qaMonitor = panel["monitor"];
  return panel;
}

export function destroyQaMonitor(): void {
  const active = (window as unknown as { __qaMonitor?: QaMonitor }).__qaMonitor;
  active?.destroy();
  document.getElementById(PANEL_ID)?.remove();
  panel = null;
}

export { EVENT_SCHEMAS, STORAGE_KEY };

/* ---------------- injected-stylesheet support ---------------- */

/**
 * Ensure the QA panel CSS is present. Called by the standalone entry points
 * (console paste / bookmarklet / userscript) because they can't rely on a
 * bundler injecting the stylesheet.
 */
export function ensureQaStyles(css: string): void {
  if (document.getElementById("pvqa-styles")) return;
  const style = document.createElement("style");
  style.id = "pvqa-styles";
  style.textContent = css;
  document.head.appendChild(style);
}
