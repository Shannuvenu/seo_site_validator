/**
 * DataLayer QA Monitor — prajavani.net
 * Option A: paste this file's content into the browser DevTools Console.
 *
 * After pasting, call:  initQaMonitor()
 * To tear down:         destroyQaMonitor()
 *
 * This entry point is self-contained: it inlines the panel CSS and bundles the
 * monitor/validator/schemas so it works without a bundler.
 */
import { initQaMonitor, destroyQaMonitor, ensureQaStyles } from "./qa-monitor";
import { QaUiOptions } from "./qa-monitor";
// Vite imports CSS as a string when queried with ?inline.
import css from "./qa-monitor.css?inline";

declare global {
  interface Window {
    initQaMonitor?: (opts?: QaUiOptions) => unknown;
    destroyQaMonitor?: () => void;
  }
}

export function bootQaMonitor(options: QaUiOptions = {}): void {
  ensureQaStyles(css);
  initQaMonitor(options);
}

// Expose a tiny global API for the console.
window.initQaMonitor = (opts?: QaUiOptions) => {
  ensureQaStyles(css);
  return initQaMonitor(opts);
};
window.destroyQaMonitor = () => {
  destroyQaMonitor();
};

// Auto-boot for the userscript/bookmarklet path when window.__QA_BOOT is set.
if (typeof window !== "undefined" && (window as unknown as { __QA_BOOT?: boolean }).__QA_BOOT) {
  bootQaMonitor();
}
