import { useState, lazy, Suspense } from "react";

type Tab = "structured-data" | "technical-seo";

const TABS: { id: Tab; label: string }[] = [
  { id: "structured-data", label: "Structured Data" },
  { id: "technical-seo", label: "Technical SEO" },
];

// Lazy-load every page: only the active tab's JS (and its heavy deps, like
// CodeMirror inside SourceViewer) gets downloaded, instead of both pages
// loading up front on first paint.
const StructuredDataPage = lazy(() => import("./pages/StructuredDataPage"));
const TechnicalSeoPage = lazy(() => import("./pages/TechnicalSeoPage"));

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
          {tab === "structured-data" && <StructuredDataPage />}
          {tab === "technical-seo" && <TechnicalSeoPage />}
        </Suspense>
      </main>
    </div>
  );
}
