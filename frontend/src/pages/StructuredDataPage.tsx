/** Two-panel Structured Data layout: ORIGINAL HTML SOURCE | DETECTED. */
import { useMemo, useState } from "react";
import type { ScanResponse, SourceLocation, UrlScanResult, ValidationFinding } from "../types/api";
import UrlInputBar from "../components/UrlInputBar";
import SourceViewer from "../components/SourceViewer";
import { api } from "../services/api";
import "./structured-data.css";

interface StructuredDataPageProps {}

/** Strip the official validator's <i>…</i> emphasis tags for plain display. */
function plainMessage(msg: string): string {
  return msg.replace(/<\/?i>/g, "").replace(/\s+/g, " ").trim();
}

function FindingRow({
  finding,
  onNavigate,
}: {
  finding: ValidationFinding;
  onNavigate: (f: ValidationFinding) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="finding-wrap">
      <button
        className="finding-row"
        onClick={() => onNavigate(finding)}
        title="Click to jump to the exact source location"
      >
        <span className={`badge ${finding.severity === "ERROR" ? "error" : finding.severity === "WARNING" ? "warning" : "info"}`}>
          {finding.severity}
        </span>
        <span className="finding-message">{plainMessage(finding.message)}</span>
        {finding.json_path && <span className="finding-path mono">{finding.json_path}</span>}
        {finding.source?.html_line ? (
          <span className="finding-line mono">line {finding.source.html_line}</span>
        ) : null}
        <span className="finding-caret" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="finding-detail">
          {finding.error_code && (
            <div><span className="faint">Code: </span><span className="mono">{finding.error_code}</span></div>
          )}
          {finding.property && (
            <div><span className="faint">Property: </span><span className="mono">{finding.property}</span></div>
          )}
          {finding.json_path && (
            <div><span className="faint">JSON-LD path: </span><span className="mono">{finding.json_path}</span></div>
          )}
          {finding.expected && (
            <div><span className="faint">Expected: </span><span>{finding.expected}</span></div>
          )}
          {finding.actual !== undefined && finding.actual !== null && (
            <div><span className="faint">Actual: </span><span className="mono">{String(finding.actual)}</span></div>
          )}
          {finding.source && (
            <div>
              <span className="faint">Source: </span>
              <span className="mono">
                line {finding.source.html_line}, col {finding.source.html_column}
                {finding.source.block_index !== undefined && finding.source.block_index !== null
                  ? ` · block ${finding.source.block_index}`
                  : ""}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ItemCard({
  item,
  findings,
  onNavigate,
}: {
  item: { type: string; index: number; errors: number; warnings: number; infos: number; properties: string[] };
  findings: ValidationFinding[];
  onNavigate: (f: ValidationFinding) => void;
}) {
  const [open, setOpen] = useState(true);
  const itemFindings = findings.filter(
    (f) => f.item_type === item.type && f.item_index === item.index,
  );
  return (
    <div className="item-card">
      <div className="item-card-header" onClick={() => setOpen(!open)}>
        <span className="item-type">{item.type}</span>
        <span className={`badge ${item.errors ? "error" : item.warnings ? "warning" : "pass"}`}>
          {item.errors} ERROR{item.errors === 1 ? "" : "S"}
        </span>
        <span className="badge warning">{item.warnings} WARNING{item.warnings === 1 ? "" : "S"}</span>
        <span className="badge info">1 ITEM</span>
      </div>
      {open && (
        <div className="item-body">
          {item.properties.length > 0 && (
            <div className="item-properties">
              <span className="faint" style={{ fontSize: 11 }}>Properties: </span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                {item.properties.join(", ")}
              </span>
            </div>
          )}
          {itemFindings.length > 0 && (
            <div className="item-findings">
              {itemFindings.map((f) => (
                <FindingRow key={f.id} finding={f} onNavigate={onNavigate} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function StructuredDataPage(_props: StructuredDataPageProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeUrl, setActiveUrl] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<SourceLocation | null>(null);
  const [activeFinding, setActiveFinding] = useState<ValidationFinding | null>(null);

  const activeResult: UrlScanResult | undefined = useMemo(() => {
    if (!result || !activeUrl) return undefined;
    return result.results.find((r) => r.url === activeUrl);
  }, [result, activeUrl]);

  const handleSubmit = async (urlsToScan: string[]) => {
    setLoading(true);
    setError(null);
    setHighlight(null);
    setActiveFinding(null);
    try {
      const res = await api.validateStructuredData(urlsToScan);
      setResult(res);
      setActiveUrl(res.results[0]?.url ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const navigateToFinding = (finding: ValidationFinding) => {
    const loc = finding.source ?? null;
    setActiveFinding(finding);
    setHighlight(loc);
  };

  const sd = activeResult?.structured_data;

  return (
    <div className="sd-page">
      <UrlInputBar onSubmit={handleSubmit} loading={loading} submitLabel="Run Validation" />

      {loading && (
        <div className="loading-row">
          <span className="spinner" /> Fetching and validating…
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      {result && (
        <div className="sd-url-selector mono">
          {result.results.map((r) => (
            <button
              key={r.url}
              className={`url-chip ${r.url === activeUrl ? "active" : ""} ${
                r.fetch_error ? "failed" : ""
              }`}
              onClick={() => {
                setActiveUrl(r.url);
                setHighlight(null);
                setActiveFinding(null);
              }}
            >
              {r.fetch_error ? "⚠" : r.status_code === 200 ? "✓" : "✗"} {shortUrl(r.url)}
              {r.fetch_error && <span className="chip-err"> {r.fetch_error_type}</span>}
            </button>
          ))}
        </div>
      )}

      {activeResult && !activeResult.fetch_error && sd && (
        <div className="sd-layout">
          <div className="sd-source-panel">
            <div className="panel-title">
              ORIGINAL HTML SOURCE
              <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>
                {activeResult.html_size
                  ? ` · ${(activeResult.html_size / 1024).toFixed(0)} KB · ${(activeResult.html || "").split("\n").length} lines`
                  : ""}
              </span>
            </div>
            <SourceViewer
              html={activeResult.html || ""}
              highlight={highlight}
              onClearHighlight={() => setHighlight(null)}
            />
          </div>
          <div className="sd-detected-panel">
            <div className="panel-title">DETECTED</div>
            <div className="summary-row">
              <span className={`badge ${sd.error_count ? "error" : "pass"}`}>{sd.error_count} ERROR{sd.error_count === 1 ? "" : "S"}</span>
              <span className={`badge ${sd.warning_count ? "warning" : "pass"}`}>{sd.warning_count} WARNING{sd.warning_count === 1 ? "" : "S"}</span>
              <span className="badge info">{sd.item_count} ITEM{sd.item_count === 1 ? "" : "S"}</span>
            </div>
            <div className="item-list">
              {sd.items.map((item) => (
                <ItemCard key={`${item.block_index}-${item.type}-${item.index}`} item={item} findings={sd.findings} onNavigate={navigateToFinding} />
              ))}
            </div>
            {sd.blocks.some((b) => b.malformed) && (
              <div className="malformed-box">
                {sd.blocks
                  .filter((b) => b.malformed)
                  .map((b) => (
                    <div key={b.index} className="error-box">
                      Block #{b.index}: {b.error} — {b.error_detail}
                    </div>
                  ))}
              </div>
            )}
            {activeFinding && highlight && (
              <div className="active-finding">
                <div className="active-finding-title">Active finding</div>
                <div className="mono">
                  {plainMessage(activeFinding.message)}
                  <br />
                  <span className="faint">
                    {activeFinding.json_path} · line {highlight.html_line}, col {highlight.html_column}
                    {highlight.json_path ? ` · ${highlight.json_path}` : ""}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {activeResult?.fetch_error && (
        <div className="error-box">
          <strong>FETCH ERROR</strong> ({activeResult.fetch_error_type}): {activeResult.fetch_error}
        </div>
      )}

      {result && !loading && result.results.every((r) => !r.structured_data && !r.fetch_error) && (
        <div className="muted" style={{ padding: 20 }}>
          No structured data found on these pages.
        </div>
      )}
    </div>
  );
}

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname}${u.pathname.length > 40 ? u.pathname.slice(0, 40) + "…" : u.pathname}`;
  } catch {
    return url;
  }
}
