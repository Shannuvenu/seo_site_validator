/** Structured Data page: source viewer + Schema.org validation + a Google
 * Search Console-style eligibility report, kept clearly separate from
 * Schema.org validity (a Schema.org-valid item is not automatically Google
 * Search eligible). */
import { useMemo, useState } from "react";
import type {
  GoogleFinding,
  GoogleItemResult,
  ScanResponse,
  SourceLocation,
  StructuredDataResult,
  UrlScanResult,
  ValidationFinding,
} from "../types/api";
import UrlInputBar from "../components/UrlInputBar";
import UrlSelector from "../components/UrlSelector";
import SourceViewer from "../components/SourceViewer";
import { api } from "../services/api";
import "./structured-data.css";

interface StructuredDataPageProps {}

type NavigateTarget = { source: SourceLocation | null; message: string; path?: string | null };

/** Strip the official validator's <i>…</i> emphasis tags for plain display. */
function plainMessage(msg: string): string {
  return msg.replace(/<\/?i>/g, "").replace(/\s+/g, " ").trim();
}

function FindingRow({
  id,
  severity,
  message,
  code,
  property,
  jsonPath,
  expected,
  actual,
  source,
  categoryLabel,
  heuristic,
  onNavigate,
}: {
  id: string;
  severity: "ERROR" | "WARNING" | "INFO";
  message: string;
  code?: string | null;
  property?: string | null;
  jsonPath?: string | null;
  expected?: string | null;
  actual?: string | null;
  source?: SourceLocation | null;
  categoryLabel?: string;
  heuristic?: boolean;
  onNavigate: (t: NavigateTarget) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="finding-wrap" key={id}>
      <button
        className="finding-row"
        onClick={() => onNavigate({ source: source ?? null, message, path: jsonPath })}
        title="Click to jump to the exact source location"
      >
        <span className={`badge ${severity === "ERROR" ? "error" : severity === "WARNING" ? "warning" : "info"}`}>
          {severity}
        </span>
        {categoryLabel && <span className="category-tag">{categoryLabel}</span>}
        <span className="finding-message">{plainMessage(message)}</span>
        {jsonPath && <span className="finding-path mono">{jsonPath}</span>}
        {source?.html_line ? <span className="finding-line mono">line {source.html_line}</span> : null}
        <span
          className="finding-caret"
          onClick={(e) => {
            e.stopPropagation();
            setOpen(!open);
          }}
        >
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="finding-detail">
          {code && (
            <div>
              <span className="faint">Code: </span>
              <span className="mono">{code}</span>
            </div>
          )}
          {property && (
            <div>
              <span className="faint">Property: </span>
              <span className="mono">{property}</span>
            </div>
          )}
          {jsonPath && (
            <div>
              <span className="faint">JSON-LD path: </span>
              <span className="mono">{jsonPath}</span>
            </div>
          )}
          {expected && (
            <div>
              <span className="faint">Expected: </span>
              <span>{expected}</span>
            </div>
          )}
          {actual !== undefined && actual !== null && (
            <div>
              <span className="faint">Actual: </span>
              <span className="mono">{String(actual)}</span>
            </div>
          )}
          {heuristic && (
            <div className="faint">
              This check is a project-level heuristic, not a rule lifted verbatim from Google's
              documentation.
            </div>
          )}
          {source && (
            <div>
              <span className="faint">Source: </span>
              <span className="mono">
                line {source.html_line}, col {source.html_column}
                {source.block_index !== undefined && source.block_index !== null
                  ? ` · block ${source.block_index}`
                  : ""}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GoogleStatusBadge({ item }: { item: GoogleItemResult | undefined }) {
  if (!item) return null;
  if (item.support_status === "DEPRECATED") {
    return <span className="badge warning">GOOGLE: DEPRECATED</span>;
  }
  if (item.support_status === "NOT_SUPPORTED") {
    return <span className="badge info">NOT A GOOGLE FEATURE</span>;
  }
  if (item.support_status === "UNKNOWN") {
    return <span className="badge info">GOOGLE: UNKNOWN</span>;
  }
  // SUPPORTED
  if (item.eligible) {
    return <span className="badge pass">GOOGLE ELIGIBLE{item.rich_result_type ? ` · ${item.rich_result_type}` : ""}</span>;
  }
  return <span className="badge error">GOOGLE INELIGIBLE{item.rich_result_type ? ` · ${item.rich_result_type}` : ""}</span>;
}

function ItemCard({
  item,
  findings,
  googleItem,
  extraGoogleItems,
  googleFindings,
  onNavigate,
}: {
  item: { type: string; index: number; errors: number; warnings: number; infos: number; properties: string[] };
  findings: ValidationFinding[];
  googleItem: GoogleItemResult | undefined;
  /** Additional Google Search features detected on the SAME item (e.g.
   * "Paywalled content" markup nested inside an Article) that don't have
   * their own DetectedItem — see google.items entries whose item_type
   * differs from this item's own Schema.org type but share its
   * block_index/item_index. */
  extraGoogleItems?: GoogleItemResult[];
  googleFindings: GoogleFinding[];
  onNavigate: (t: NavigateTarget) => void;
}) {
  const [open, setOpen] = useState(true);
  const itemFindings = findings.filter((f) => f.item_type === item.type && f.item_index === item.index);
  const itemGoogleFindings = googleFindings.filter(
    (f) => f.item_type === item.type && f.item_index === item.index,
  );

  return (
    <div className="item-card">
      <div className="item-card-header" onClick={() => setOpen(!open)}>
        <span className="item-type">{item.type}</span>
        <span className={`badge ${item.errors ? "error" : item.warnings ? "warning" : "pass"}`}>
          SCHEMA {item.errors} ERROR{item.errors === 1 ? "" : "S"}
        </span>
        <GoogleStatusBadge item={googleItem} />
        {(extraGoogleItems ?? []).map((g) => (
          <GoogleStatusBadge key={`${g.item_type}-${g.rich_result_type}`} item={g} />
        ))}
      </div>
      {open && (
        <div className="item-body">
          {item.properties.length > 0 && (
            <div className="item-properties">
              <span className="faint" style={{ fontSize: 11 }}>
                Properties:{" "}
              </span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                {item.properties.join(", ")}
              </span>
            </div>
          )}

          {googleItem?.deprecated_message && (
            <div className="deprecated-note">{googleItem.deprecated_message}</div>
          )}
          {googleItem?.note && !googleItem.deprecated_message && (
            <div className="deprecated-note">{googleItem.note}</div>
          )}

          {itemFindings.length > 0 && (
            <div className="item-findings">
              <div className="finding-group-label">Schema.org</div>
              {itemFindings.map((f) => (
                <FindingRow
                  key={f.id}
                  id={f.id}
                  severity={f.severity}
                  message={f.message}
                  code={f.error_code}
                  property={f.property}
                  jsonPath={f.json_path}
                  expected={f.expected}
                  actual={f.actual}
                  source={f.source}
                  categoryLabel="SCHEMA_ERROR"
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          )}

          {itemGoogleFindings.length > 0 && (
            <div className="item-findings">
              <div className="finding-group-label">Google Search</div>
              {itemGoogleFindings.map((f) => (
                <FindingRow
                  key={f.id}
                  id={f.id}
                  severity={f.severity}
                  message={f.message}
                  code={f.code}
                  property={f.property ?? undefined}
                  jsonPath={f.json_path}
                  source={f.source}
                  categoryLabel={f.category}
                  heuristic={f.heuristic}
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Groups findings by message so the overview can show "N items affected". */
function groupByMessage<T extends { message: string; id: string }>(findings: T[]): { message: string; count: number; sample: T }[] {
  const map = new Map<string, { message: string; count: number; sample: T }>();
  for (const f of findings) {
    const key = plainMessage(f.message);
    const existing = map.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      map.set(key, { message: key, count: 1, sample: f });
    }
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count);
}

function GoogleOverview({ sd }: { sd: StructuredDataResult }) {
  const g = sd.google;
  const invalidGroups = groupByMessage(sd.findings.filter((f) => f.severity === "ERROR"));
  const improveGroups = groupByMessage(sd.findings.filter((f) => f.severity === "WARNING"));
  const googleErrorGroups = groupByMessage(g.findings.filter((f) => f.severity === "ERROR"));
  const googleWarningGroups = groupByMessage(g.findings.filter((f) => f.severity === "WARNING"));
  const unparsable = sd.blocks.filter((b) => b.malformed);

  return (
    <div className="gsc-overview">
      <div className="gsc-section-title">OVERVIEW</div>
      <div className="gsc-overview-grid">
        <div className="gsc-stat pass">
          <div className="gsc-stat-value">{sd.item_count - sd.items.filter((i) => i.errors > 0).length}</div>
          <div className="gsc-stat-label">Valid items</div>
        </div>
        <div className="gsc-stat error">
          <div className="gsc-stat-value">{sd.items.filter((i) => i.errors > 0).length}</div>
          <div className="gsc-stat-label">Invalid items</div>
        </div>
        <div className="gsc-stat warning">
          <div className="gsc-stat-value">{sd.items.filter((i) => i.warnings > 0).length}</div>
          <div className="gsc-stat-label">Warnings</div>
        </div>
        <div className="gsc-stat error">
          <div className="gsc-stat-value">{unparsable.length}</div>
          <div className="gsc-stat-label">Unparsable structured data</div>
        </div>
        <div className="gsc-stat info">
          <div className="gsc-stat-value">{g.not_supported_count + g.deprecated_count + g.unknown_count}</div>
          <div className="gsc-stat-label">Unsupported / unknown types</div>
        </div>
        <div className="gsc-stat pass">
          <div className="gsc-stat-value">{g.eligible_count}</div>
          <div className="gsc-stat-label">Google Search eligible</div>
        </div>
      </div>

      {(invalidGroups.length > 0 || googleErrorGroups.length > 0) && (
        <>
          <div className="gsc-section-title">WHY ITEMS ARE INVALID</div>
          {invalidGroups.map((g2) => (
            <div className="gsc-issue-row" key={`schema-${g2.message}`}>
              <span className="badge error">SCHEMA_ERROR</span>
              <span className="gsc-issue-message">{g2.message}</span>
              <span className="gsc-issue-count">{g2.count} item{g2.count === 1 ? "" : "s"}</span>
            </div>
          ))}
          {googleErrorGroups.map((g2) => (
            <div className="gsc-issue-row" key={`google-err-${g2.message}`}>
              <span className="badge error">GOOGLE_SEARCH_ERROR</span>
              <span className="gsc-issue-message">{g2.message}</span>
              <span className="gsc-issue-count">{g2.count} item{g2.count === 1 ? "" : "s"}</span>
            </div>
          ))}
        </>
      )}

      {(improveGroups.length > 0 || googleWarningGroups.length > 0) && (
        <>
          <div className="gsc-section-title">IMPROVE ITEM APPEARANCE</div>
          {improveGroups.map((g2) => (
            <div className="gsc-issue-row" key={`schema-w-${g2.message}`}>
              <span className="badge warning">SCHEMA_WARNING</span>
              <span className="gsc-issue-message">{g2.message}</span>
              <span className="gsc-issue-count">{g2.count} item{g2.count === 1 ? "" : "s"}</span>
            </div>
          ))}
          {googleWarningGroups.map((g2) => (
            <div className="gsc-issue-row" key={`google-w-${g2.message}`}>
              <span className="badge warning">GOOGLE_SEARCH_WARNING</span>
              <span className="gsc-issue-message">{g2.message}</span>
              <span className="gsc-issue-count">{g2.count} item{g2.count === 1 ? "" : "s"}</span>
            </div>
          ))}
        </>
      )}

      {unparsable.length > 0 && (
        <>
          <div className="gsc-section-title">UNPARSABLE STRUCTURED DATA</div>
          {unparsable.map((b) => (
            <div className="gsc-issue-row" key={`block-${b.index}`}>
              <span className="badge error">PARSING_ERROR</span>
              <span className="gsc-issue-message">
                Block #{b.index}: {b.error} — {b.error_detail}
              </span>
            </div>
          ))}
        </>
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
  const [activeFinding, setActiveFinding] = useState<NavigateTarget | null>(null);

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

  const navigateToFinding = (t: NavigateTarget) => {
    setActiveFinding(t);
    setHighlight(t.source ?? null);
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
        <UrlSelector
          results={result.results}
          activeUrl={activeUrl}
          onSelect={(url) => {
            setActiveUrl(url);
            setHighlight(null);
            setActiveFinding(null);
          }}
        />
      )}

      {sd && <GoogleOverview sd={sd} />}

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
            <div className="panel-title">ITEM DETAILS</div>
            <div className="summary-row">
              <span className={`badge ${sd.error_count ? "error" : "pass"}`}>
                {sd.error_count} SCHEMA ERROR{sd.error_count === 1 ? "" : "S"}
              </span>
              <span className={`badge ${sd.warning_count ? "warning" : "pass"}`}>
                {sd.warning_count} SCHEMA WARNING{sd.warning_count === 1 ? "" : "S"}
              </span>
              <span className={`badge ${sd.google.error_count ? "error" : "pass"}`}>
                {sd.google.error_count} GOOGLE ERROR{sd.google.error_count === 1 ? "" : "S"}
              </span>
              <span className="badge info">
                {sd.item_count} ITEM{sd.item_count === 1 ? "" : "S"}
              </span>
            </div>
            <div className="item-list">
              {sd.items.map((item) => {
                const gItem = sd.google.items.find(
                  (g) => g.item_type === item.type && g.item_index === item.index && g.block_index === item.block_index,
                );
                // Extra Google features detected on this same node that
                // aren't a match for the node's own Schema.org type (e.g.
                // "Paywalled content" on an Article/NewsArticle) — see
                // GoogleSearchValidator._check_paywalled_content.
                const extraGItems = sd.google.items.filter(
                  (g) =>
                    g.item_index === item.index &&
                    g.block_index === item.block_index &&
                    g.item_type !== item.type,
                );
                return (
                  <ItemCard
                    key={`${item.block_index}-${item.type}-${item.index}`}
                    item={item}
                    findings={sd.findings}
                    googleItem={gItem}
                    extraGoogleItems={extraGItems}
                    googleFindings={sd.google.findings}
                    onNavigate={navigateToFinding}
                  />
                );
              })}
            </div>
            {activeFinding && highlight && (
              <div className="active-finding">
                <div className="active-finding-title">Active finding</div>
                <div className="mono">
                  {plainMessage(activeFinding.message)}
                  <br />
                  <span className="faint">
                    {activeFinding.path} · line {highlight.html_line}, col {highlight.html_column}
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
