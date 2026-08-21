import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";

const sampleScan = {
  scan_id: "t1",
  results: [
    {
      url: "https://www.deccanherald.com/test",
      final_url: "https://www.deccanherald.com/test",
      status_code: 200,
      content_type: "text/html",
      fetch_duration_ms: 100,
      html_size: 5000,
      html:
        "<!DOCTYPE html>\n<html><head>\n" +
        '<script type="application/ld+json">\n' +
        '{"@type":"NewsArticle","headline":"X","badProp":1}\n' +
        "</script>\n</head><body></body></html>\n",
      technical_seo: null,
      structured_data: {
        status: "FAIL",
        item_count: 1,
        error_count: 1,
        warning_count: 0,
        info_count: 0,
        blocks: [
          {
            index: 0,
            parsed: true,
            malformed: false,
            entities: [
              {
                type: "NewsArticle",
                index: 0,
                block_index: 0,
                json_path: "0",
                errors: 1,
                warnings: 0,
                infos: 0,
                status: "FAIL",
                properties: ["headline", "badProp"],
                source_start_line: 3,
                source_end_line: 3,
              },
            ],
            html_start_line: 3,
            html_end_line: 3,
            text_start_line: 3,
          },
        ],
        items: [
          {
            type: "NewsArticle",
            index: 0,
            block_index: 0,
            json_path: "0",
            errors: 1,
            warnings: 0,
            infos: 0,
            status: "FAIL",
            properties: ["headline", "badProp"],
            source_start_line: 3,
            source_end_line: 3,
          },
        ],
        findings: [
          {
            id: "f1",
            severity: "ERROR",
            error_code: "UNKNOWN_FIELD",
            message: "The property <i>badProp</i> is not recognised by the schema (e.g. schema.org) for an object of type <i>NewsArticle</i>.",
            item_type: "NewsArticle",
            item_index: 0,
            block_index: 0,
            json_path: "0.badProp",
            property: "badProp",
            expected: "a property of the type or one of its parent types",
            actual: "badProp",
            source: {
              html_line: 3,
              html_column: 12,
              start_offset: 60,
              end_offset: 70,
              json_path: "badProp",
              json_line: 2,
              json_column: 3,
              block_index: 0,
            },
          },
        ],
        google: {
          items: [],
          findings: [],
          supported_count: 0,
          not_supported_count: 0,
          deprecated_count: 0,
          unknown_count: 1,
          eligible_count: 0,
          error_count: 0,
          warning_count: 0,
        },
      },
    },
  ],
};

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders only the two tabs", () => {
    render(<App />);
    expect(screen.getByText("Technical SEO")).toBeInTheDocument();
    expect(screen.getByText("Structured Data")).toBeInTheDocument();
    expect(screen.queryByText("Data Layer")).not.toBeInTheDocument();
    expect(screen.queryByText("Site Structure")).not.toBeInTheDocument();
  });

  it("switches tabs", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Technical SEO"));
    expect(screen.getByPlaceholderText(/Paste up to 15 URLs/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Structured Data"));
    await waitFor(() => {
      expect(screen.getByText("Run Validation")).toBeInTheDocument();
    });
  });

  it("submits a URL and renders detected items with source navigation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => sampleScan,
      }),
    );
    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByPlaceholderText(/Paste up to 15 URLs/);
    await user.type(input, "https://www.deccanherald.com/test");
    fireEvent.click(screen.getByText("Run Validation"));

    await waitFor(() => {
      expect(screen.getByText("ITEM DETAILS")).toBeInTheDocument();
      expect(screen.getByText("NewsArticle")).toBeInTheDocument();
    });

    // error summary
    expect(screen.getAllByText(/1 SCHEMA ERROR/).length).toBeGreaterThan(0);

    // click the finding -> navigates (highlight state changes; SourceViewer mounts)
    fireEvent.click(screen.getByText(/not recognised by the schema/));
    await waitFor(() => {
      expect(screen.getByText(/line 3, col 12/)).toBeInTheDocument();
    });
  });
});
