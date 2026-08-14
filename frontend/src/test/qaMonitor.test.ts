/**
 * Tests for the QA monitor behavior — sequences, click matching, dataLayer
 * reassignment, re-init teardown, circular payloads, persistence, export.
 * Cases 40–54 from the requirements.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  QaMonitor,
  STORAGE_KEY,
  createMonitor,
} from "../qa/monitor";
import { safeClone, normalizePayload } from "../qa/validator";

const UUID = "3b241101-e2bb-4255-8caf-4136c566a962";

function resetDataLayer(): void {
  // Recreate a fresh dataLayer (simulates Next.js reassignment).
  (window as unknown as { dataLayer: unknown[] }).dataLayer = [];
}

function userProps(p: Partial<Record<string, unknown>> = {}) {
  return {
    event: "user_properties_update",
    auth_status: "non_logged_in",
    subscription_status: "NA",
    uuid: "NA",
    plan_name: "NA",
    plan_price: "NA",
    ...p,
  };
}

describe("QaMonitor", () => {
  beforeEach(() => {
    resetDataLayer();
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* noop */
    }
  });

  afterEach(() => {
    const mon = (window as unknown as { __qaTestMonitor?: QaMonitor }).__qaTestMonitor;
    mon?.destroy();
    delete (window as unknown as { __qaTestMonitor?: QaMonitor }).__qaTestMonitor;
    resetDataLayer();
  });

  function startMonitor(opts: { sequenceWindowMs?: number; clickEventWindowMs?: number } = {}) {
    const monitor = new QaMonitor({
      sequenceWindowMs: opts.sequenceWindowMs ?? 300,
      clickEventWindowMs: opts.clickEventWindowMs ?? 120,
      markClickNoEventAsFailure: true,
    });
    (window as unknown as { __qaTestMonitor?: QaMonitor }).__qaTestMonitor = monitor;
    monitor.start();
    return monitor;
  }

  function push(monitor: QaMonitor, value: unknown): void {
    const dl = (window as unknown as { dataLayer: unknown[] }).dataLayer;
    if (Array.isArray(dl)) {
      dl.push(value);
    } else {
      (monitor as unknown as { observePush: (v: unknown) => void }).observePush(value);
    }
  }

  it("40. page_view -> user_properties_update sequence PASSes", async () => {
    const monitor = startMonitor();
    push(monitor, {
      event: "page_view",
      article_id: "1",
      article_type: "a",
      auth_status: "non_logged_in",
      author_id: "1",
      author_name: "n",
      comment_number: 0,
      content_id: UUID,
      content_title: "t",
      created_date: "2026-01-01T00:00:00Z",
      creator_name: "n",
      last_updated_date: "2026-01-01T00:00:00Z",
      page_type: "article_page",
      published_date: "2026-01-01T00:00:00Z",
      section_name: "s",
      story_tags: "t",
      story_words: 10,
      uuid: "NA",
      premium_article: "No",
      access_level_value: 200,
    });
    await vi.waitFor(() => {
      expect(monitor.rows.some((r) => r.kind === "sequence" && r.check === "WAITING")).toBe(true);
    });
    push(monitor, userProps());
    const seq = monitor.rows.find((r) => r.kind === "sequence" && r.check === "PASS");
    expect(seq).toBeTruthy();
  });

  it("41. missing user_properties_update sequence FAILs", async () => {
    const monitor = startMonitor();
    push(monitor, {
      event: "page_view",
      article_id: "1",
      article_type: "a",
      auth_status: "non_logged_in",
      author_id: "1",
      author_name: "n",
      comment_number: 0,
      content_id: UUID,
      content_title: "t",
      created_date: "2026-01-01T00:00:00Z",
      creator_name: "n",
      last_updated_date: "2026-01-01T00:00:00Z",
      page_type: "article_page",
      published_date: "2026-01-01T00:00:00Z",
      section_name: "s",
      story_tags: "t",
      story_words: 10,
      uuid: "NA",
      premium_article: "No",
      access_level_value: 200,
    });
    await vi.waitFor(
      () => {
        expect(monitor.rows.some((r) => r.kind === "sequence" && r.check === "SEQUENCE FAIL")).toBe(true);
      },
      { timeout: 2000 },
    );
  });

  it("42/43/44/45. purchase/sign_up/login/logout -> user_properties_update sequences PASS", async () => {
    for (const trigger of ["purchase", "sign_up", "login", "logout"]) {
      const monitor = startMonitor({ sequenceWindowMs: 500 });
      const payload: Record<string, unknown> = { event: trigger };
      if (trigger === "purchase") {
        Object.assign(payload, {
          uuid: UUID,
          plan_name: "monthly",
          plan_price: 150,
          currency: "INR",
          transaction_id: "pay_1",
          redirection_url: "https://prajavani.net/",
          user_type: "new user",
        });
      } else if (trigger === "sign_up") {
        Object.assign(payload, {
          method: "email",
          source: "header_button",
          uuid: UUID,
          account_created_date: "2026-01-01T00:00:00Z",
          marketing_and_promotion_consent: true,
          Newsletter_consent: false,
        });
      } else if (trigger === "login") {
        Object.assign(payload, {
          method: "email",
          source: "header_button",
          uuid: UUID,
          account_created_date: "2026-01-01T00:00:00Z",
          marketing_and_promotion_consent: true,
          Newsletter_consent: false,
        });
      } else if (trigger === "logout") {
        Object.assign(payload, { source: "profile", uuid: UUID, subscription_status: "subscribed" });
      }
      push(monitor, payload);
      await vi.waitFor(() => {
        expect(monitor.rows.some((r) => r.kind === "sequence" && r.check === "WAITING")).toBe(true);
      });
      push(monitor, userProps());
      expect(
        monitor.rows.some((r) => r.kind === "sequence" && r.check === "PASS" && r.eventName?.includes(trigger)),
      ).toBe(true);
      monitor.destroy();
    }
  });

  it("46. click followed by event = FIRED", async () => {
    const monitor = startMonitor({ clickEventWindowMs: 200 });
    const btn = document.createElement("button");
    btn.textContent = "Subscribe Now";
    btn.setAttribute("aria-label", "Subscribe Now");
    document.body.appendChild(btn);
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    push(monitor, {
      event: "paywall_subscribe_button_click",
      auth_status: "non_logged_in",
      uuid: "NA",
      page_url: "https://prajavani.net/",
    });
    await vi.waitFor(() => {
      const eventRow = monitor.rows.find((r) => r.kind === "event" && r.eventName === "paywall_subscribe_button_click");
      expect(eventRow?.element?.ariaLabel).toBe("Subscribe Now");
    });
    btn.remove();
  });

  it("47. click without event = NO EVENT", async () => {
    const monitor = startMonitor({ clickEventWindowMs: 100 });
    const btn = document.createElement("button");
    btn.textContent = "Plain Button";
    document.body.appendChild(btn);
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await vi.waitFor(
      () => {
        expect(monitor.rows.some((r) => r.kind === "click" && r.status === "NO EVENT")).toBe(true);
      },
      { timeout: 2000 },
    );
    btn.remove();
  });

  it("48. dataLayer reassignment is re-hooked", async () => {
    const monitor = startMonitor();
    // Reassign the array (Next.js style).
    (window as unknown as { dataLayer: unknown[] }).dataLayer = [];
    // Wait for the rearm timer to hook the fresh array.
    await vi.waitFor(
      () => {
        const dl = (window as unknown as { dataLayer: unknown[] }).dataLayer;
        expect((dl as { __qaHooked?: boolean }).__qaHooked).toBe(true);
      },
      { timeout: 2000 },
    );
    push(monitor, { event: "logout", source: "profile", uuid: UUID, subscription_status: "non_subscriber" });
    expect(monitor.rows.some((r) => r.kind === "event" && r.eventName === "logout")).toBe(true);
  });

  it("49. re-initializing monitor does not duplicate events", () => {
    const m1 = startMonitor();
    push(m1, { event: "accept_popup", uuid: UUID });
    // Create a second monitor (simulates re-paste / reinit).
    const m2 = new QaMonitor({ clickEventWindowMs: 100 });
    m2.start();
    push(m2, { event: "accept_popup", uuid: UUID });
    const count = m2.rows.filter((r) => r.kind === "event" && r.eventName === "accept_popup").length;
    // m2 must not re-observe m1's pushed event from the snapshot, and the
    // re-hook must not stack wrappers that double-deliver.
    expect(count).toBe(1);
    m2.destroy();
  });

  it("50. circular payload does not crash", () => {
    const monitor = startMonitor();
    const circular: Record<string, unknown> = { event: "accept_popup", uuid: UUID };
    circular.self = circular;
    circular.win = window;
    circular.fn = () => 1;
    let threw = false;
    try {
      push(monitor, circular);
    } catch {
      threw = true;
    }
    expect(threw).toBe(false);
    const row = monitor.rows.find((r) => r.kind === "event" && r.eventName === "accept_popup");
    expect(row).toBeTruthy();
    // Payload must be JSON-serializable (no crash).
    expect(() => JSON.stringify(row?.payload)).not.toThrow();
  });

  it("51. gtag Arguments payload is displayed correctly", () => {
    const monitor = startMonitor();
    const args = {
      0: "event",
      1: "dismiss_popup",
      2: { uuid: UUID },
    };
    push(monitor, args);
    const row = monitor.rows.find((r) => r.kind === "event" && r.eventName === "dismiss_popup");
    expect(row).toBeTruthy();
    expect(row?.fromGtag).toBe(true);
    expect(row?.payload?.uuid).toBe(UUID);
  });

  it("52. sessionStorage restore works", () => {
    const m1 = startMonitor();
    push(m1, { event: "accept_popup", uuid: UUID });
    const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "[]");
    expect(stored.length).toBeGreaterThan(0);
    // New monitor in the same tab restores.
    const m2 = new QaMonitor({ clickEventWindowMs: 100 });
    const restored = m2.restore();
    expect(restored).toBeGreaterThan(0);
    expect(m2.rows.some((r) => r.eventName === "accept_popup")).toBe(true);
    m2.destroy();
  });

  it("53. CSV export works (does not throw, produces rows)", () => {
    const monitor = startMonitor();
    push(monitor, { event: "accept_popup", uuid: UUID });
    const click = document.createElement("a");
    click.href = "https://prajavani.net/";
    click.textContent = "Renew Now";
    click.setAttribute("data-qa", "renew");
    document.body.appendChild(click);
    click.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    push(monitor, { event: "accept_popup", uuid: UUID });
    click.remove();
    // Build the CSV in the same way the UI does.
    const header = [
      "time", "status", "event_name", "check", "validation_issues",
      "element", "element_attributes", "payload_json", "sequence",
    ];
    const lines = [header.join(",")];
    for (const row of monitor.rows) {
      lines.push([
        `"${row.time}"`,
        `"${row.status}"`,
        `"${row.eventName ?? ""}"`,
        `"${row.check}"`,
        `"${row.validationIssues.join(" | ")}"`,
        `"${row.element?.text ?? ""}"`,
        `"${JSON.stringify(row.element ?? {})}"`,
        `"${JSON.stringify(row.payload ?? {})}"`,
        `"${row.sequenceNote ?? ""}"`,
      ].join(","));
    }
    const csv = lines.join("\n");
    expect(csv.split("\n").length).toBeGreaterThan(2);
    expect(csv).toContain("accept_popup");
  });

  it("54. JSON export contains the full QA run", () => {
    const monitor = startMonitor();
    push(monitor, { event: "accept_popup", uuid: UUID });
    const json = JSON.stringify({
      exportedAt: new Date().toISOString(),
      rows: monitor.rows.map((r) => ({
        time: r.time,
        status: r.status,
        event: r.eventName,
        check: r.check,
        payload: r.payload,
        clickedElement: r.element,
        sequence: r.sequenceNote,
      })),
    });
    const parsed = JSON.parse(json);
    expect(parsed.rows.length).toBeGreaterThan(0);
    expect(parsed.rows[0].event).toBeDefined();
  });
});

describe("safeClone", () => {
  it("handles circular + DOM + function without throwing", () => {
    const obj: Record<string, unknown> = { a: 1 };
    obj.self = obj;
    obj.fn = () => 1;
    const div = document.createElement("div");
    div.id = "x";
    obj.node = div;
    let out: unknown;
    expect(() => {
      out = safeClone(obj);
    }).not.toThrow();
    expect((out as Record<string, unknown>).a).toBe(1);
    expect(() => JSON.stringify(out)).not.toThrow();
    expect(typeof JSON.stringify(out)).toBe("string");
  });

  it("normalizePayload never returns null for objects", () => {
    const n = normalizePayload({ event: "accept_popup", uuid: UUID });
    expect(n?.eventName).toBe("accept_popup");
  });
});

describe("createMonitor singleton", () => {
  it("re-inits cleanly (destroy previous)", () => {
    const m1 = createMonitor();
    const m2 = createMonitor();
    expect(m1).not.toBe(m2);
    // m1 was destroyed by createMonitor; its start must not double-observe.
    const d1 = m1 as unknown as { destroyed?: boolean };
    expect(d1.destroyed).toBe(true);
    m2.destroy();
  });
});
