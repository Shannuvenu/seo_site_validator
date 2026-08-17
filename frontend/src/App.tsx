import { useState, lazy, Suspense } from "react";

type Tab = "technical-seo" | "structured-data" | "data-layer" | "site-structure";

const TABS: { id: Tab; label: string }[] = [
  { id: "technical-seo", label: "Technical SEO" },
  { id: "structured-data", label: "Structured Data" },
  { id: "data-layer", label: "Data Layer" },
  { id: "site-structure", label: "Site Structure" },
];

// Lazy-load every page: only the active tab's JS (and its heavy deps, like
// CodeMirror inside SourceViewer) gets downloaded, instead of all four pages
// loading up front on first paint.
const TechnicalSeoPage = lazy(() => import("./pages/TechnicalSeoPage"));
const StructuredDataPage = lazy(() => import("./pages/StructuredDataPage"));
const DataLayerPage = lazy(() => import("./pages/DataLayerPage"));
const SiteStructurePage = lazy(() => import("./pages/SiteStructurePage"));

export default function App() {
  const [tab, setTab] = useState<Tab>("structured-data");

  return (
    <div className="app">
      <header className="app-header">
        <h1>SEO &amp; Structured Data Health Check</h1>
        <span className="sub">Deccan Herald · Prajavani</span>
      </header>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="app-content">
        <Suspense fallback={<div style={{ padding: 24 }}>Loading…</div>}>
          {tab === "technical-seo" && <TechnicalSeoPage />}
          {tab === "structured-data" && <StructuredDataPage />}
          {tab === "data-layer" && <DataLayerPage />}
          {tab === "site-structure" && <SiteStructurePage />}
        </Suspense>
      </main>
    </div>
  );
}