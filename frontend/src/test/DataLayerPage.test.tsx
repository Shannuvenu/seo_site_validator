import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DataLayerPage from "../pages/DataLayerPage";

const statusWithEvents = {
  session_id: "abc123",
  status: "capturing",
  url: "https://www.deccanherald.com/",
  current_url: "https://www.deccanherald.com/india",
  page_title: "India | Deccan Herald",
  data_layer_found: true,
  instrumented: true,
  event_count: 5,
  events: [
    {
      seq: 1,
      type: "dataLayer",
      url: "https://www.deccanherald.com/india",
      page_title: "India | Deccan Herald",
      timestamp: "2026-08-11T10:30:01.000Z",
      data: { event: "page_view", page_type: "article", article_id: "4100792" },
    },
    {
      seq: 2,
      type: "interaction",
      url: "https://www.deccanherald.com/india",
      page_title: "India | Deccan Herald",
      timestamp: "2026-08-11T10:30:02.000Z",
      data: {
        action: "click",
        description: 'User clicked "Login"',
        element: { tag: "button", text: "Login", id: "login-btn", "aria-label": "Login to account" },
      },
    },
    {
      seq: 3,
      type: "interaction",
      url: "https://www.deccanherald.com/india",
      page_title: "India | Deccan Herald",
      timestamp: "2026-08-11T10:30:03.000Z",
      data: { action: "scroll", description: "User scrolled to 75%", scroll_percent: 75, scroll_y: 4200 },
    },
    {
      seq: 4,
      type: "navigation",
      url: "https://www.deccanherald.com/india",
      page_title: "India | Deccan Herald",
      timestamp: "2026-08-11T10:30:04.000Z",
      data: {
        action: "navigation",
        from_url: "https://www.deccanherald.com/",
        to_url: "https://www.deccanherald.com/india",
      },
    },
    {
      seq: 5,
      type: "interaction",
      url: "https://www.deccanherald.com/india",
      page_title: "India | Deccan Herald",
      timestamp: "2026-08-11T10:30:05.000Z",
      data: { action: "pointer", description: 'User pressed "Menu area"', element: { tag: "div", text: "Menu area" } },
    },
  ],
  message: "capturing",
};

const HISTORY_KEY = "dataLayerHistory";

describe("DataLayerPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("renders URL input and action buttons — no custom script UI", () => {
    render(<DataLayerPage />);
    expect(screen.getByPlaceholderText(/https:\/\/www\.deccanherald\.com/)).toBeInTheDocument();
    expect(screen.getByText("Start Capture")).toBeInTheDocument();
    expect(screen.getByText("Dump Events")).toBeInTheDocument();
    expect(screen.getByText("Clear History")).toBeInTheDocument();
    expect(screen.getByText("Close Browser")).toBeInTheDocument();
    expect(screen.getByText("Export JSON")).toBeInTheDocument();
    // Custom script editor + Execute button removed.
    expect(screen.queryByText(/JavaScript logger script/)).not.toBeInTheDocument();
    expect(screen.queryByText(/run custom JavaScript/)).not.toBeInTheDocument();
    expect(screen.queryByText("Execute Script")).not.toBeInTheDocument();
    expect(screen.queryByText("Execute")).not.toBeInTheDocument();
  });

  it("shows 0 events empty state before a session starts", () => {
    render(<DataLayerPage />);
    expect(screen.getByText(/Start a capture session to see events here/)).toBeInTheDocument();
    expect(screen.getByText("0 events captured")).toBeInTheDocument();
  });

  it("starts capture, renders human-friendly rows, and expands an event", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (url.endsWith("/api/data-layer/start")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ session_id: "abc123", url: body.url, status: "capturing" }),
        });
      }
      if (url.includes("/api/data-layer/events")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => statusWithEvents });
      }
      if (url.endsWith("/api/data-layer/clear")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, message: "Cleared", session_id: "abc123" }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<DataLayerPage />);

    await user.type(
      screen.getByPlaceholderText(/https:\/\/www\.deccanherald\.com/),
      "https://www.deccanherald.com/india",
    );
    fireEvent.click(screen.getByText("Start Capture"));
    await waitFor(() => {
      expect(screen.getByText("Capturing")).toBeInTheDocument();
      expect(screen.getByText("page_view")).toBeInTheDocument();
    });

    // Human-friendly descriptions render.
    expect(screen.getByText(/User clicked "Login"/)).toBeInTheDocument();
    expect(screen.getByText(/User scrolled to 75%/)).toBeInTheDocument();

    // Distinct types visible.
    expect(screen.getAllByText("USER INTERACTION").length).toBeGreaterThan(0);
    expect(screen.getAllByText("DATA LAYER").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NAVIGATION").length).toBeGreaterThan(0);

    // Search for "login" finds the click row (description + element text).
    const search = screen.getByPlaceholderText(/Search events/);
    await user.type(search, "login");
    expect(screen.queryByText("page_view")).not.toBeInTheDocument();
    expect(screen.getByText(/User clicked "Login"/)).toBeInTheDocument();

    // Clear search, expand the dataLayer event -> full JSON.
    await user.clear(search);
    fireEvent.click(screen.getByText("page_view"));
    await waitFor(() => {
      expect(screen.getByText('"article_id"')).toBeInTheDocument();
      expect(screen.getByText('"4100792"')).toBeInTheDocument();
    });

    // App history persisted to localStorage.
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    expect(stored.length).toBe(5);

    // Clear History resets timeline + storage.
    fireEvent.click(screen.getByText("Clear History"));
    await waitFor(() => {
      expect(screen.getAllByText("0 events captured").length).toBeGreaterThan(0);
    });
    expect(localStorage.getItem(HISTORY_KEY)).toBeNull();
  }, 20000);

  it("deduplicates identical events from repeated polls", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/data-layer/events")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => statusWithEvents });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    const { unmount } = render(<DataLayerPage />);
    await user.type(
      screen.getByPlaceholderText(/https:\/\/www\.deccanherald\.com/),
      "https://www.deccanherald.com/india",
    );
    fireEvent.click(screen.getByText("Start Capture"));
    await waitFor(() => {
      expect(screen.getByText(/5 events captured/)).toBeInTheDocument();
    });

    // The same backend payload arrives again (poll) — must not duplicate.
    unmount();
    render(<DataLayerPage />);
    fireEvent.click(screen.getByText("Start Capture"));
    await waitFor(() => {
      expect(screen.getByText(/5 events captured/)).toBeInTheDocument();
    });
    // No duplicate rows.
    expect(screen.getAllByText(/User clicked "Login"/)).toHaveLength(1);
  }, 20000);

  it("restores history from localStorage on refresh", async () => {
    // Pre-seed application history.
    localStorage.setItem(HISTORY_KEY, JSON.stringify(statusWithEvents.events));
    render(<DataLayerPage />);
    // Previous history visible even without a session.
    expect(screen.getByText(/User clicked "Login"/)).toBeInTheDocument();
    expect(screen.getByText("page_view")).toBeInTheDocument();
  });

  it("shows the page column, pointer filter, and View Source modal", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/data-layer/start")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ session_id: "abc123", url: "https://www.deccanherald.com/india", status: "capturing" }),
        });
      }
      if (url.includes("/api/data-layer/events")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => statusWithEvents });
      }
      if (url.includes("/api/data-layer/source")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            url: "https://www.deccanherald.com/india",
            html: "<html><head><title>India</title></head><body>page body</body></html>",
            html_size: 60,
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<DataLayerPage />);
    await user.type(
      screen.getByPlaceholderText(/https:\/\/www\.deccanherald\.com/),
      "https://www.deccanherald.com/india",
    );
    fireEvent.click(screen.getByText("Start Capture"));
    await waitFor(() => {
      expect(screen.getByText(/5 events captured/)).toBeInTheDocument();
    });

    // Page column shows the event's page title.
    expect(screen.getAllByText("India | Deccan Herald").length).toBeGreaterThan(0);

    // Pointer filter reveals the pointer interaction.
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "pointer" } });
    expect(screen.getByText(/User pressed "Menu area"/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "all" } });

    // Expand an event -> View Source button opens the modal.
    fireEvent.click(screen.getByText("page_view"));
    await waitFor(() => {
      expect(screen.getByText("View Source")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("View Source"));
    await waitFor(() => {
      expect(screen.getAllByText(/India/).length).toBeGreaterThan(0);
      expect(screen.getByText("Close")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("Close"));
    await waitFor(() => {
      expect(screen.queryByText("Close")).not.toBeInTheDocument();
    });
  }, 20000);
});
