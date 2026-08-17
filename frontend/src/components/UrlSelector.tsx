import { useEffect, useRef, useState } from "react";
import type { UrlScanResult } from "../types/api";
import "./url-selector.css";

interface UrlSelectorProps {
  results: UrlScanResult[];
  activeUrl: string | null;
  onSelect: (url: string) => void;
}

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname}${u.pathname.length > 46 ? u.pathname.slice(0, 46) + "…" : u.pathname}`;
  } catch {
    return url;
  }
}

function statusOf(r: UrlScanResult): "ok" | "failed" {
  return r.fetch_error ? "failed" : "ok";
}

/**
 * Shared dropdown for picking which scanned URL to view. Used by both the
 * Structured Data and Technical SEO tabs so the two stay visually identical
 * and don't wrap into a messy grid of chips when many URLs are scanned.
 */
export default function UrlSelector({ results, activeUrl, onSelect }: UrlSelectorProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  if (results.length === 0) return null;

  const active = results.find((r) => r.url === activeUrl) ?? results[0];
  const okCount = results.filter((r) => !r.fetch_error).length;
  const failedCount = results.length - okCount;

  return (
    <div className="url-select" ref={rootRef}>
      <button
        type="button"
        className={`url-select-trigger ${open ? "open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={`url-select-dot ${statusOf(active)}`} />
        <span className="url-select-label mono">{shortUrl(active.url)}</span>
        <span className="url-select-count">
          {results.length} URL{results.length === 1 ? "" : "s"}
          {failedCount > 0 ? ` · ${failedCount} failed` : ""}
        </span>
        <span className={`url-select-caret ${open ? "up" : ""}`}>▾</span>
      </button>

      {open && (
        <div className="url-select-menu" role="listbox">
          {results.map((r) => (
            <button
              type="button"
              key={r.url}
              role="option"
              aria-selected={r.url === activeUrl}
              className={`url-select-option ${r.url === activeUrl ? "active" : ""}`}
              onClick={() => {
                onSelect(r.url);
                setOpen(false);
              }}
            >
              <span className={`url-select-dot ${statusOf(r)}`} />
              <span className="url-select-option-text mono">{shortUrl(r.url)}</span>
              {r.fetch_error ? (
                <span className="url-select-option-err">{r.fetch_error_type ?? "error"}</span>
              ) : (
                <span className="url-select-option-code mono">{r.status_code}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}