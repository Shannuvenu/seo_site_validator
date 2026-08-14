import { useState } from "react";
import TechnicalSeoPage from "./pages/TechnicalSeoPage";
import StructuredDataPage from "./pages/StructuredDataPage";
import DataLayerPage from "./pages/DataLayerPage";
import SiteStructurePage from "./pages/SiteStructurePage";

type Tab = "technical-seo" | "structured-data" | "data-layer" | "site-structure";

const TABS: { id: Tab; label: string }[] = [
  { id: "technical-seo", label: "Technical SEO" },
  { id: "structured-data", label: "Structured Data" },
  { id: "data-layer", label: "Data Layer" },
  { id: "site-structure", label: "Site Structure" },
];

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
        {tab === "technical-seo" && <TechnicalSeoPage />}
        {tab === "structured-data" && <StructuredDataPage />}
        {tab === "data-layer" && <DataLayerPage />}
        {tab === "site-structure" && <SiteStructurePage />}
      </main>
    </div>
  );
}
