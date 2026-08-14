/**
 * Build the self-contained "paste into console" bundle for the DataLayer QA
 * Monitor. Uses esbuild (already a devDependency via Vite) to bundle the QA
 * modules into a single IIFE with the CSS inlined, and writes:
 *   - dist-qa/prajavani-datalayer-qa-monitor.js   (console paste)
 *   - dist-qa/bookmarklet.js                      (bookmarklet href)
 *   - dist-qa/prajavani-datalayer-qa-monitor.user.js (Tampermonkey)
 */
import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "dist-qa");
mkdirSync(outDir, { recursive: true });

const entry = join(__dirname, "..", "src", "qa", "console-entry.ts");

await build({
  entryPoints: [entry],
  bundle: true,
  outfile: join(outDir, "prajavani-datalayer-qa-monitor.js"),
  format: "iife",
  globalName: "PrajavaniQA",
  target: "es2019",
  minify: false,
  loader: { ".css": "text" },
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
});

// Read the IIFE bundle, extract the globalName object usage.
const bundle = readFileSync(join(outDir, "prajavani-datalayer-qa-monitor.js"), "utf8");

// Bookmarklet: run the bundle, then boot the panel. Browsers accept unencoded
// JS in javascript: URLs.
const bookmarklet = `javascript:(function(){${bundle}\nif (typeof PrajavaniQA !== "undefined" && PrajavaniQA.initQaMonitor) { PrajavaniQA.initQaMonitor(); }})();`;
writeFileSync(join(outDir, "bookmarklet.js"), bookmarklet);

// Userscript wrapper.
const userscript = `// ==UserScript==
// @name         Prajavani DataLayer QA Monitor
// @namespace    prajavani.net
// @version      1.0.0
// @description  Observe + validate prajavani.net dataLayer events against the Paywall Data Layer spec (QA tool)
// @match        https://prajavani.net/*
// @match        https://www.prajavani.net/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function () {
  "use strict";
  if (window.__PRAJAVANI_QA_BOOTED__) return;
  window.__PRAJAVANI_QA_BOOTED__ = true;

${bundle
  .split("\n")
  .map((l) => "  " + l)
  .join("\n")}

  // Boot after DOM is ready.
  function boot() {
    try {
      if (typeof PrajavaniQA !== "undefined" && PrajavaniQA.initQaMonitor) {
        PrajavaniQA.initQaMonitor();
      }
    } catch (e) {
      console.error("[PrajavaniQA] boot failed", e);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
`;
writeFileSync(join(outDir, "prajavani-datalayer-qa-monitor.user.js"), userscript);

console.log("QA monitor bundles written to", outDir);
