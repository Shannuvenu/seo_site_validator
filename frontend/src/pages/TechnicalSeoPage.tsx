import { useMemo, useState } from "react";
import type { ScanResponse, TechnicalSeoResult, UrlScanResult } from "../types/api";
import UrlInputBar from "../components/UrlInputBar";
import UrlSelector from "../components/UrlSelector";
import { api } from "../services/api";
import "./technical-seo.css";

interface TechnicalSeoPageProps {}

export default function TechnicalSeoPage(_props: TechnicalSeoPageProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeUrl, setActiveUrl] = useState<string | null>(null);

  const active: UrlScanResult | undefined = useMemo(
    () => result?.results.find((r) => r.url === activeUrl),
    [result, activeUrl],
  );

  const handleSubmit = async (urlsToScan: string[]) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.scan(urlsToScan, false);
      setResult(res);
      setActiveUrl(res.results[0]?.url ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <UrlInputBar onSubmit={handleSubmit} loading={loading} submitLabel="Run Technical SEO" />

      {loading && (
        <div className="loading-row">
          <span className="spinner" /> Scanning…
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      {result && (
        <UrlSelector results={result.results} activeUrl={activeUrl} onSelect={setActiveUrl} />
      )}

      {active?.fetch_error && (
        <div className="error-box">
          <strong>FETCH ERROR</strong> ({active.fetch_error_type}): {active.fetch_error}
        </div>
      )}

      {active?.technical_seo && <TechReport data={active.technical_seo} />}
    </div>
  );
}

function TechReport({ data }: { data: TechnicalSeoResult }) {
  return (
    <div className="tech-grid">
      <div className="card">
        <div className="card-title">Document</div>
        <KvRow k="HTTP status" v={String(data.status_code)} />
        <KvRow k="Final URL" v={data.final_url} mono />
        <KvRow k="Content type" v={data.content_type} />
        <KvRow k="Fetch time" v={`${data.fetch_duration_ms.toFixed(0)} ms`} />
        <KvRow k="Title" v={data.title ?? "—"} />
        <KvRow k="Title length" v={data.title_length != null ? String(data.title_length) : "—"} />
        <KvRow k="Meta description" v={data.meta_description ?? "—"} />
        <KvRow k="Canonical" v={data.canonical ?? "—"} mono />
        <KvRow k="Robots" v={data.robots_meta ?? "index, follow (default)"} mono />
        <KvRow k="Viewport" v={data.viewport ?? "—"} />
      </div>

      <div className="card">
        <div className="card-title">Structure</div>
        <KvRow k="H1" v={data.h1.length ? data.h1[0] : "—"} />
        <KvRow k="H1 count" v={String(data.h1.length)} />
        <KvRow k="H2 count" v={String(data.h2.length)} />
        <KvRow k="H3 count" v={String(data.h3.length)} />
        <KvRow k="Images" v={String(data.image_count)} />
        <KvRow k="Missing alt" v={String(data.images_missing_alt)} />
        <KvRow k="Links" v={String(data.link_count)} />
        <KvRow k="Internal links" v={String(data.internal_links)} />
        <KvRow k="External links" v={String(data.external_links)} />
        <KvRow k="Broken anchors" v={String(data.broken_anchors)} />
        <KvRow k="JSON-LD blocks" v={String(data.structured_data_blocks)} />
      </div>

      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-title">Findings</div>
        <table className="findings-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Check</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {data.findings.map((f, i) => (
              <tr key={i}>
                <td>
                  <span className={`badge ${f.severity === "ERROR" ? "error" : f.severity === "WARNING" ? "warning" : "info"}`}>
                    {f.severity}
                  </span>
                </td>
                <td>{f.name}</td>
                <td>{f.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {Object.keys(data.og_tags).length > 0 && (
        <div className="card" style={{ gridColumn: "1 / -1" }}>
          <div className="card-title">Open Graph</div>
          <div className="tag-grid">
            {Object.entries(data.og_tags).map(([k, v]) => (
              <KvRow key={k} k={k} v={v} mono />
            ))}
          </div>
        </div>
      )}

      {Object.keys(data.twitter_tags).length > 0 && (
        <div className="card" style={{ gridColumn: "1 / -1" }}>
          <div className="card-title">Twitter</div>
          <div className="tag-grid">
            {Object.entries(data.twitter_tags).map(([k, v]) => (
              <KvRow key={k} k={k} v={v} mono />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function KvRow({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="kv-row">
      <span className="kv-key">{k}</span>
      <span className={`kv-val ${mono ? "mono" : ""}`}>{v}</span>
    </div>
  );
}


