import { useEffect, useState } from "react";
import type { SiteNode, SiteStructureResult } from "../types/api";
import { api } from "../services/api";
import "./site-structure.css";

function TreeNode({ node, depth }: { node: SiteNode; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const hasChildren = node.children.length > 0;
  return (
    <div className="tree-node">
      <div
        className="tree-row"
        style={{ paddingLeft: depth * 18 + 6 }}
        onClick={() => hasChildren && setOpen(!open)}
      >
        <span className="tree-caret">{hasChildren ? (open ? "▾" : "▸") : "·"}</span>
        <span className="tree-name">{node.name}</span>
        {node.slug && <span className="tree-slug mono">{node.slug}</span>}
        <span className="tree-id mono faint">{node.section_id}</span>
        {node.collection_type && <span className="badge info">{node.collection_type}</span>}
      </div>
      {open &&
        hasChildren &&
        node.children.map((c) => <TreeNode key={c.section_id} node={c} depth={depth + 1} />)}
    </div>
  );
}

export default function SiteStructurePage() {
  const [site, setSite] = useState("deccanherald");
  const [result, setResult] = useState<SiteStructureResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (siteName: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.siteStructure(siteName);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(site);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="url-bar">
        <select
          className="btn"
          value={site}
          onChange={(e) => {
            setSite(e.target.value);
            load(e.target.value);
          }}
          style={{ appearance: "auto", padding: "8px 12px" }}
        >
          <option value="deccanherald">Deccan Herald</option>
          <option value="prajavani">Prajavani</option>
        </select>
        <span className="muted" style={{ fontSize: 12 }}>
          Quintype config API · section hierarchy
        </span>
      </div>

      {loading && (
        <div className="loading-row">
          <span className="spinner" /> Fetching section tree…
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      {result?.error && <div className="error-box">{result.error}</div>}

      {result && !result.error && (
        <div className="ss-report">
          <div className="summary-row">
            <span className="badge info">{result.node_count} sections</span>
            <span className="badge info">{result.site}</span>
            <span className="faint mono" style={{ fontSize: 11 }}>
              {result.config_url}
            </span>
          </div>
          {result.root && <TreeNode node={result.root} depth={0} />}
        </div>
      )}
    </div>
  );
}
