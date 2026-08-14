import { readFileSync } from "node:fs";

const p = readFileSync("dist-qa/bookmarklet.js", "utf-8");
console.log("len:", p.length);
console.log("prefix:", p.slice(0, 80));
console.log("has initQaMonitor:", p.includes("initQaMonitor"));
const code = p.replace(/^javascript:/, "");
try {
  new Function(code);
  console.log("bookmarklet JS syntax: OK");
} catch (e) {
  console.log("bookmarklet JS syntax: FAIL", e.message);
}
const u = readFileSync("dist-qa/prajavani-datalayer-qa-monitor.user.js", "utf-8");
console.log("userscript has @match prajavani.net:", u.includes("@match"));
console.log("userscript has initQaMonitor:", u.includes("initQaMonitor"));
