"""Data Layer inspection via a persistent real browser session (Playwright).

Architecture
------------
React  ->  FastAPI  ->  Playwright  ->  real Chromium page  ->  window.dataLayer
   ^                            ^
   |                            +-- observer injects automatically on every
   |                                navigation (no manual script paste needed)
   +-- backend session log is the AUTHORITATIVE event history

Two distinct capture streams
----------------------------
1. DATA LAYER EVENTS  — real ``window.dataLayer.push(...)`` calls. The observer
   hooks ``push`` BEFORE any page script runs (``add_init_script``), preserves
   the original ``push`` (site functionality is never broken), and records the
   EXACT object that was pushed — nothing is invented or modified.

2. USER INTERACTIONS — things the user does in the page (click / scroll /
   input / change / submit / navigation / page load). These are recorded
   separately and NEVER reported as dataLayer events. Each record carries
   ``kind: "interaction"`` plus rich element info (tag, text, id, class,
   href, role, aria-label...).

Every record is stamped with an ISO timestamp and the URL it happened on, and
is sent to the backend immediately over the page-side ``window.__dlCapture``
postMessage bridge. The backend keeps the complete chronological session log,
so events survive cross-origin navigation, redirects and reloads (page
localStorage is a best-effort mirror only).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATA_LAYER_MAX_EVENTS, DL_BEACON_URL
from ..models.schemas import DataLayerRecord
from .fetcher import validate_url


def _allow_localhost_debug() -> bool:
    """Allow localhost/loopback targets for the Data Layer browser.

    Only enabled for automated test fixtures via SEO_ALLOW_LOCALHOST_DEBUG=1.
    Production keeps SSRF protection on by default. Read live (not cached) so
    tests that set the env var after import still work.
    """
    return os.environ.get("SEO_ALLOW_LOCALHOST_DEBUG", "0") == "1"


def _beacon_url() -> str:
    """Public backend URL the monitored pages can beacon records to.

    Empty unless DL_BEACON_URL is configured — the observer then skips the
    beacon and the localStorage sweep remains the primary transport.
    """
    return (DL_BEACON_URL or "").strip().rstrip("/")


# ---------------------------------------------------------------------------
# Browser-side observer. Injected with add_init_script() so it runs BEFORE any
# page script: it captures existing dataLayer entries, hooks future push()
# calls, and observes real user interactions (click/scroll/input/change/
# submit/navigation). It never modifies pushed objects and never breaks the
# original push behavior.
#
# Transport: every record is persisted to localStorage IMMEDIATELY (this is
# what survives same-origin navigation) AND posted to the page via
# postMessage. The backend sweeps localStorage on a timer + on every
# navigation, so even if a click navigates away in the same tick the record
# written to localStorage before the unload is picked up. postMessage is a
# best-effort fast path only — Playwright does NOT deliver same-window
# postMessage to page.on("message"), so the backend must never depend on it.
# ---------------------------------------------------------------------------
OBSERVER_SCRIPT = r"""
(function () {
  // Per-document guard: popups start at about:blank (init script runs there),
  // then the document is REUSED and its URL changes to the real page (Chromium
  // does this for window.open with same-origin targets). A plain document flag
  // would then skip install on the real page, so we ALSO compare the URL the
  // observer last saw: if it changed, re-install everything fresh.
  var prevUrl = null;
  try { prevUrl = document.__dlObservedUrl || null; } catch (e) {}
  var urlChanged = !!(document.__dlObserverInstalled) && prevUrl !== null && prevUrl !== location.href;
  if (document.__dlObserverInstalled && !urlChanged) return;
  try { Object.defineProperty(document, '__dlObserverInstalled', { value: true }); } catch (e) { document.__dlObserverInstalled = true; }
  try { Object.defineProperty(document, '__dlObservedUrl', { value: location.href, writable: true, configurable: true }); } catch (e) { document.__dlObservedUrl = location.href; }
  // Reset per-document runtime state when the URL changed on a reused document.
  if (urlChanged) {
    try { document.__dlScrollState = null; } catch (e) {}
    try { document.__dlLoadReported = false; } catch (e) {}
    try { document.__dlListenersInstalled = false; } catch (e) {}
    if (document.__dlArmTimer) { try { clearInterval(document.__dlArmTimer); } catch (e) {} document.__dlArmTimer = null; }
  }

  // Only the top-level document reports page_load / scroll / navigation.
  // iframes (ads, embeds) each run this script too; their interactions would
  // just be noise for the manager's capture timeline.
  var isTop = true;
  try { isTop = window.self === window.top; } catch (e) { isTop = true; }

  var SEQ_KEY = '__dl_seq';
  var LS_KEY = '__dl_captured_events';
  var MAX_LS = 2000;
  var maxSeq = 0;

  // ---- safe deep clone: handles cycles, functions, DOM nodes, undefined ----
  function safeClone(v, depth, seen) {
    if (v === null || v === undefined) return v;
    var t = typeof v;
    if (t === 'string' || t === 'boolean') return v;
    if (t === 'number') return isFinite(v) ? v : String(v);
    if (t === 'function') return '[function]';
    if (t === 'symbol' || t === 'bigint') return String(v);
    if (depth > 12) return '[deep]';
    if (v instanceof Error) return { name: v.name, message: v.message };
    if (v instanceof Date) return v.toISOString();
    if (v instanceof Element || v instanceof Node) {
      return '<' + v.tagName + (v.id ? '#' + v.id : '') + '>';
    }
    if (seen.indexOf(v) !== -1) return '[circular]';
    seen = seen.concat([v]);
    if (Array.isArray(v)) {
      var out = [];
      for (var i = 0; i < v.length; i++) out.push(safeClone(v[i], depth + 1, seen));
      return out;
    }
    var o = {};
    try {
      var keys = Object.keys(v);
      for (var i = 0; i < keys.length; i++) {
        try { o[keys[i]] = safeClone(v[keys[i]], depth + 1, seen); } catch (e) { o[keys[i]] = '[unserializable]'; }
      }
    } catch (e) { /* cross-origin / proxied object */ }
    return o;
  }

  // ---- event log (in-page mirror; backend is authoritative) ----
  function readSeq() {
    try { var s = parseInt(localStorage.getItem(SEQ_KEY) || '0', 10); if (isFinite(s) && s > maxSeq) maxSeq = s; } catch (e) {}
    return maxSeq;
  }
  function nextSeq() { return ++maxSeq; }
  function persist(rec) {
    try {
      var raw = localStorage.getItem(LS_KEY);
      var arr = raw ? JSON.parse(raw) : [];
      arr.push(rec);
      if (arr.length > MAX_LS) arr = arr.slice(-MAX_LS);
      localStorage.setItem(LS_KEY, JSON.stringify(arr));
      localStorage.setItem(SEQ_KEY, String(maxSeq));
    } catch (e) {}
  }
  function emit(type, payload) {
    var rec = {
      seq: nextSeq(),
      type: type,          // 'dataLayer' | 'interaction' | 'navigation' | 'page'
      timestamp: new Date().toISOString(),
      url: location.href,
      data: payload || {}
    };
    try { if (document.title) rec.page_title = document.title; } catch (e) {}
    // localStorage FIRST — this is the transport that actually survives
    // navigation. postMessage is a best-effort fast path.
    persist(rec);
    try { window.postMessage({ __dlCapture: true, record: rec }, '*'); } catch (e) {}
    // Console bridge: Playwright's page.on("console") reliably delivers
    // same-page console messages (unlike postMessage, which Playwright does
    // NOT surface for same-window sends). This is a second fast path so a
    // click/scroll reaches the backend even if the sweep is delayed or the
    // page's localStorage is clobbered by site code. Prefix keeps it
    // distinguishable from real site console output.
    try {
      console.debug('__dl_capture__', JSON.stringify(rec));
    } catch (e) {}
    // Best-effort beacon for events right before a (possibly cross-origin)
    // navigation where localStorage becomes unreachable. Only fires when the
    // page can reach the backend without mixed-content blocking (HTTPS
    // backend); otherwise it silently no-ops.
    try {
      if (window.__dlBeaconUrl && navigator.sendBeacon) {
        var payload2 = JSON.stringify({ session_id: window.__dlSessionId || '', record: rec });
        navigator.sendBeacon(window.__dlBeaconUrl + '/api/data-layer/ingest', new Blob([payload2], { type: 'text/plain' }));
      }
    } catch (e) {}
    return rec;
  }

  // ---- dataLayer: snapshot existing entries ----
  function snapshotExisting() {
    var dl = window.dataLayer;
    if (!dl || !Array.isArray(dl)) return;
    for (var i = 0; i < dl.length; i++) {
      var item = dl[i];
      if (item && typeof item === 'object' && !item.__dlCaptured) {
        try { Object.defineProperty(item, '__dlCaptured', { value: true, enumerable: false }); } catch (e) {}
        emit('dataLayer', { source: 'existing', data: safeClone(item, 0, []) });
      }
    }
  }

  // ---- dataLayer: hook push so every future call is captured verbatim ----
  function hookPush() {
    var dl = window.dataLayer;
    if (!dl || !Array.isArray(dl) || dl.__dlHooked) return;
    try { Object.defineProperty(dl, '__dlHooked', { value: true, enumerable: false }); } catch (e) { dl.__dlHooked = true; }
    var original = dl.push;
    dl.push = function () {
      var args = Array.prototype.slice.call(arguments);
      var ret = original.apply(dl, arguments);
      for (var i = 0; i < args.length; i++) {
        var a = args[i];
        if (a && typeof a === 'object') {
          emit('dataLayer', { source: 'push', data: safeClone(a, 0, []) });
        } else {
          emit('dataLayer', { source: 'push', data: { value: safeClone(a, 0, []) } });
        }
      }
      return ret;
    };
  }

  // ---- observe user interactions ----
  function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }

  // Strip leading icon glyphs (icons like * / ► / ☰ / 🗞 etc.) so a label
  // like "* Epaper" resolves to "Epaper".
  function cleanLabel(s) {
    s = norm(String(s || ''));
    // Remove leading run of non-alphanumeric glyphs.
    s = s.replace(/^[^\p{L}\p{N}]+/u, '');
    // Drop a single stray leading character like "*".
    if (/^[^\p{L}\p{N}]$/u.test(s.charAt(0))) s = s.slice(1).trim();
    return s;
  }

  // Human label resolution priority:
  // 1 aria-label  2 title  3 accessible name (role of the element)  4 visible
  // text  5 alt text  6 input value  7 element role  8 element tag name.
  function meaningfulLabel(el) {
    if (!el || el.nodeType !== 1) return '';
    var label = '';
    try {
      label = el.getAttribute('aria-label') || el.getAttribute('title') || '';
    } catch (e) {}
    if (label) return cleanLabel(label);
    // Accessible name approximation: use the element's own role.
    try {
      var role = el.getAttribute('role') || '';
      if (role) return cleanLabel(role);
    } catch (e) {}
    try {
      var text = norm(el.innerText || el.textContent || '');
      if (text && text.length <= 200) return cleanLabel(text);
    } catch (e) {}
    try {
      var alt = el.getAttribute('alt') || '';
      if (alt) return cleanLabel(alt);
    } catch (e) {}
    try {
      if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') && el.value) {
        return el.type === 'password' ? '[type=password]' : String(el.value);
      }
    } catch (e) {}
    return '';
  }

  // The most specific (deepest) element's own visible text — used to prefer
  // "Epaper" (the span) over "* Epaper" (the concatenated anchor text) when a
  // click lands on a nested element.
  function directText(el) {
    if (!el || el.nodeType !== 1) return '';
    try {
      if (el.childElementCount === 0) {
        return cleanLabel(el.innerText || el.textContent || '');
      }
    } catch (e) {}
    return '';
  }

  function elInfo(el) {
    if (!el || el.nodeType !== 1) return {};
    var info = {};
    try {
      info.tag = el.tagName ? el.tagName.toLowerCase() : '';
      var txt = norm(el.innerText || el.textContent || '');
      if (txt && txt.length <= 200) info.text = txt;
      var attrs = ['id', 'class', 'href', 'role', 'name', 'aria-label', 'title', 'placeholder', 'value', 'type', 'src', 'alt'];
      for (var i = 0; i < attrs.length; i++) {
        var a = attrs[i];
        if (a === 'value') {
          if (el.tagName === 'INPUT' && (el.type === 'password' || el.type === 'hidden')) { info.value = '[REDACTED]'; continue; }
          if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
            var v = el.value;
            if (typeof v === 'string' && v.length > 80) v = v.slice(0, 80) + '…';
            info.value = v;
          }
          continue;
        }
        if (el.hasAttribute && el.hasAttribute(a)) {
          var vv = el.getAttribute(a);
          if (a === 'class') vv = vv.split(/\s+/).slice(0, 6).join(' ');
          if (vv && vv.length <= 200) info[a] = vv;
        }
      }
    } catch (e) {}
    return info;
  }

  // Resolve the nearest meaningful interactive ancestor of the event target.
  // Deccan Herald nav elements contain nested spans/icons, so a click on a
  // <span> inside <a class="menu-link"> must resolve to the <a>.
  // Returns null when nothing interactive is found — those clicks are handled
  // by the pointer handler instead of being reported as meaningless "DIV".
  function closestInteractive(el) {
    var sel = 'button, a, input, textarea, select, label, summary, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"], [role="option"], [role="checkbox"], [role="radio"], [role="switch"], [onclick], [data-testid], [aria-label], [title]';
    var cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.body && cur !== document.documentElement) {
      try {
        if (cur.matches && cur.matches(sel)) return cur;
      } catch (e) {}
      cur = cur.parentElement;
    }
    return null;
  }

  // Merge element info from the interactive ancestor first, then the actual
  // target — never overwrite with less meaningful info.
  function mergedElInfo(tgt, el) {
    var merged = {};
    var seenKeys = {};
    var src = tgt && tgt !== el ? [elInfo(tgt), elInfo(el)] : [elInfo(el)];
    for (var i = 0; i < src.length; i++) {
      var s = src[i];
      for (var k in s) {
        if (s.hasOwnProperty(k) && !(k in seenKeys)) { merged[k] = s[k]; seenKeys[k] = true; }
      }
    }
    // Prefer a meaningful label. For a nested click (span inside <a>), the
    // direct target's own text ("Epaper") wins over the ancestor's
    // concatenated text ("* Epaper"); aria-label/title on the ancestor still
    // wins overall.
    var label = '';
    if (tgt && tgt !== el) {
      label = meaningfulLabel(tgt) && !directText(el) ? meaningfulLabel(tgt)
        : (directText(el) || meaningfulLabel(tgt) || meaningfulLabel(el));
    } else {
      label = meaningfulLabel(el);
    }
    if (label) merged.text = label;
    return merged;
  }

  function interaction(action, extra) {
    var payload = Object.assign({ action: action }, extra || {});
    var el = payload.element || {};
    var label = meaningfulLabel(el) || (el && (el['aria-label'] || el.title || el.alt || el.text)) || '';
    label = norm(String(label)).slice(0, 160);
    var display = label || el.tag || action;
    var description = '';
    if (action === 'click') description = 'User clicked "' + display + '"';
    else if (action === 'pointer') description = 'User pressed "' + display + '"';
    else if (action === 'scroll') {
      var pct = payload.scroll_percent;
      description = 'User scrolled to ' + (pct !== undefined ? pct + '%' : 'a new position');
    }
    else if (action === 'page_load') description = 'Page loaded' + (document.title ? ': ' + document.title : '');
    else if (action === 'input') description = 'User typed in "' + display + '"';
    else if (action === 'change') description = 'User changed "' + display + '"';
    else if (action === 'submit') description = 'User submitted a form';
    else description = 'User ' + action;
    payload.description = description;
    payload.label = display;
    payload.in_frame = !isTop;
    payload.page = {
      url: location.href,
      title: document.title || ''
    };
    emit('interaction', payload);
  }

  // A click on an element inside an editable area (or the area itself) is not
  // an interesting "user clicked X" event; the input/change handlers cover it.
  function insideEditable(el) {
    var cur = el;
    while (cur && cur.nodeType === 1) {
      var tag = cur.tagName ? cur.tagName.toLowerCase() : '';
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || cur.isContentEditable) return true;
      cur = cur.parentElement;
    }
    return false;
  }

  function onCapture(e) {
    var el = e.target;
    if (!el || el.nodeType !== 1) return;
    if (insideEditable(el)) return;
    var tgt = closestInteractive(el);
    if (!tgt) {
      // A click with no interactive ancestor still deserves a record (it may
      // be a programmatic el.click() that never fires pointerdown, or a card/
      // image click). Resolve the label from the target's own text.
      var m = elInfo(el);
      interaction('click', { element: m });
      return;
    }
    var merged = mergedElInfo(tgt, el);
    interaction('click', { element: merged });
  }

  // Pointer capture: press-down on a non-interactive area is the closest thing
  // to "the user tapped here" for image cards / large divs. Keep it sparse —
  // only when the press will NOT produce a meaningful click record (no
  // interactive ancestor and no meaningful label text), and never on editable
  // areas. This avoids the redundant "pressed X" + "clicked X" pair for normal
  // clicks while still catching taps on blank regions.
  function onPointerDown(e) {
    var el = e.target;
    if (!el || el.nodeType !== 1) return;
    if (insideEditable(el)) return;
    if (e.button !== undefined && e.button !== 0) return;
    var tgt = closestInteractive(el);
    if (tgt) return; // click handler covers it
    var m = elInfo(el);
    if (meaningfulLabel(el) || (m.text || "").length > 1) return; // click record will cover it
    interaction('pointer', { element: m });
  }

  // Scroll milestones: 25 / 50 / 75 / 90 / 100. Throttled — at most one record
  // per milestone per document (plus an entry record at the first meaningful
  // scroll), so we never flood the backend.
  var SCROLL_MILESTONES = [25, 50, 75, 90, 100];
  function onScroll() {
    var doc = document.documentElement;
    var max = Math.max(doc.scrollHeight - window.innerHeight, 1);
    var y = Math.max(window.pageYOffset || doc.scrollTop || 0, 0);
    var pct = Math.min(100, Math.round((y / max) * 100));
    var st = document.__dlScrollState;
    if (!st) { st = { seen: {}, lastY: -1, lastPct: -1, lastT: 0, fired0: false, crossed: {} }; document.__dlScrollState = st; }
    var now = Date.now();
    // Debounce identical positions (programmatic or repeated scroll events).
    if (st.lastPct === pct && now - st.lastT < 800) return;
    var emitRecord = false;
    var crossed = null;
    if (!st.fired0 && y > 50) { emitRecord = true; st.fired0 = true; }
    // Crossed-milestone detection: mark EVERY milestone <= the current pct
    // that we haven't reported yet. This survives fast wheel-scrolls that
    // jump several milestones in a single event (the old code only looked at
    // the FIRST unmet milestone, so a 0 -> 100 scroll could skip 25/50/75/90).
    for (var i = 0; i < SCROLL_MILESTONES.length; i++) {
      var m = SCROLL_MILESTONES[i];
      if (pct >= m && !st.seen[m]) {
        st.seen[m] = true;
        if (crossed === null) { crossed = m; emitRecord = true; }
      }
    }
    if (!emitRecord) {
      // Still track a few sensible records so the timeline shows progress,
      // but never more often than once per ~600ms.
      if (now - st.lastT >= 600) { emitRecord = true; }
    }
    if (!emitRecord) { st.lastY = y; st.lastPct = pct; return; }
    st.lastY = y; st.lastPct = pct; st.lastT = now;
    interaction('scroll', {
      scroll_y: y,
      scroll_percent: pct,
      milestone: crossed,
      document_height: doc.scrollHeight,
      viewport_height: window.innerHeight
    });
  }

  function onInput(e) {
    var t = e.target;
    if (!t || !t.tagName) return;
    var tag = t.tagName.toLowerCase();
    if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') return;
    interaction('input', { element: elInfo(t) });
  }

  function onChange(e) {
    var t = e.target;
    if (!t || !t.tagName) return;
    interaction('change', { element: elInfo(t) });
  }

  function onSubmit(e) {
    var t = e.target;
    var info = t && t.tagName ? elInfo(t) : {};
    var action = '';
    try { action = t.getAttribute ? (t.getAttribute('action') || '') : ''; } catch (err) {}
    interaction('submit', { element: info, form_action: action });
  }

  function onLoad() {
    if (document.__dlLoadReported) return;
    try { Object.defineProperty(document, '__dlLoadReported', { value: true }); } catch (e) { document.__dlLoadReported = true; }
    interaction('page_load', { ready_state: document.readyState, title: document.title });
  }

  // A fragment / hash change on the SAME document is still a meaningful
  // navigation ("user moved somewhere"), but only when the hash actually
  // changes — we must not spam the log with duplicate hashchange events.
  var lastHash = '';
  function onHashChange() {
    try {
      if (location.hash === lastHash) return;
      lastHash = location.hash;
      emit('navigation', {
        action: 'navigation',
        from_url: location.href,
        to_url: location.href,
        same_document: true,
        hash: location.hash
      });
    } catch (e) {}
  }

  // Before the document tears down, flush a navigation marker into
  // localStorage so the backend can pair it with the framenavigated record.
  function onPageHide() {
    try {
      var raw = localStorage.getItem(LS_KEY);
      var arr = raw ? JSON.parse(raw) : [];
      arr.push({
        seq: -1,
        type: 'navigation',
        timestamp: new Date().toISOString(),
        url: location.href,
        page_title: document.title || '',
        data: { action: 'navigation', from_url: location.href, to_url: '' }
      });
      localStorage.setItem(LS_KEY, JSON.stringify(arr));
    } catch (e) {}
  }

  function install() {
    // Idempotent: a reused popup document re-runs this script when its URL
    // changes; avoid stacking duplicate listeners.
    if (document.__dlListenersInstalled) return;
    try { Object.defineProperty(document, '__dlListenersInstalled', { value: true }); } catch (e) { document.__dlListenersInstalled = true; }
    // Clicks are tracked in EVERY frame, including cross-origin iframes (SSO
    // "Sign In" widgets, embedded auth buttons, ad iframes, etc. commonly
    // render inside an iframe — without this, those clicks were invisible).
    try { document.addEventListener('click', onCapture, true); } catch (e) {}
    try { document.addEventListener('pointerdown', onPointerDown, true); } catch (e) {}
    if (!isTop) return; // scroll/input/submit/page_load/navigation stay top-only (avoids iframe noise: ads, embeds)
    try { window.addEventListener('scroll', onScroll, true); } catch (e) {}
    try { document.addEventListener('input', onInput, true); } catch (e) {}
    try { document.addEventListener('change', onChange, true); } catch (e) {}
    try { document.addEventListener('submit', onSubmit, true); } catch (e) {}
    try { window.addEventListener('load', onLoad); } catch (e) {}
    try { window.addEventListener('hashchange', onHashChange); } catch (e) {}
    try { window.addEventListener('pagehide', onPageHide); } catch (e) {}
  }

  // ---- arm: hook dataLayer whenever it appears / changes ----
  readSeq();
  function arm() {
    var dl = window.dataLayer;
    if (dl && Array.isArray(dl)) {
      hookPush();
      snapshotExisting();
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arm);
  } else {
    arm();
  }
  if (document.__dlArmTimer) clearInterval(document.__dlArmTimer);
  // Keep the watchdog running for the whole page lifetime: sites can replace
  // window.dataLayer = [] at ANY time (not just before load), and the hook
  // must re-arm + snapshot the fresh array so those pushes are not lost.
  document.__dlArmTimer = setInterval(arm, 500);
  install();
  try {
    if (document.readyState !== 'loading' && isTop) onLoad();
  } catch (e) {}

  // Final sweep on load (the watchdog stays alive — see above).
  window.addEventListener('load', function () {
    arm();
    snapshotExisting();
  });

  // ---- manager-style helpers (page console, optional) ----
  window.dlLog = function () {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch (e) { return []; }
  };
  window.dlLast = function () { var a = window.dlLog(); return a.length ? a[a.length - 1] : null; };
  window.dlDump = function () { var a = window.dlLog(); try { console.table(a.map(function (r) { return { seq: r.seq, type: r.type, timestamp: r.timestamp, url: r.url, data: r.data }; })); } catch (e) {} return a; };
  window.dlExport = function () { return JSON.stringify(window.dlLog(), null, 2); };
  window.dlClear = function () {
    try { localStorage.removeItem(LS_KEY); localStorage.removeItem(SEQ_KEY); } catch (e) {}
    maxSeq = 0;
    return true;
  };
})();
"""


def _normalize_record(rec: Any, fallback_url: str) -> Optional[Dict[str, Any]]:
    """Coerce a raw browser record dict into a clean backend record dict."""
    if not isinstance(rec, dict):
        return None
    data = rec.get("data")
    if not isinstance(data, dict):
        data = {}
    rtype = rec.get("type") or "dataLayer"
    if rtype == "dataLayer":
        inner = data.get("data")
        if isinstance(inner, dict):
            data = inner  # keep the EXACT pushed object as the record data
    elif rtype == "interaction" and "action" not in data:
        data["action"] = data.get("action") or "click"
    timestamp = rec.get("timestamp") or rec.get("time") or ""
    if not timestamp:
        import datetime

        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    page_title = rec.get("page_title")
    if not isinstance(page_title, str) or not page_title:
        # Fall back to the event's own payload when the envelope omits it.
        page_title = data.get("page", {}).get("title") if isinstance(data, dict) else None
    return {
        "seq": int(rec.get("seq") or 0),
        "type": rtype,
        "timestamp": timestamp,
        "url": rec.get("url") or fallback_url,
        "data": data,
        "page_title": page_title if isinstance(page_title, str) and page_title else None,
    }


class DataLayerSession:
    """One live browser session."""

    def __init__(self, session_id: str, url: str) -> None:
        self.id = session_id
        self.url = url
        self.status = "starting"
        self.current_url = url
        self.page_title: Optional[str] = None
        self.data_layer_found = False
        self.instrumented = False
        self.message: Optional[str] = None
        self.error: Optional[str] = None
        self.created = time.time()
        self.last_active = time.time()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._events: List[DataLayerRecord] = []
        self._max_seq = 0
        self._used_seqs: set = set()
        self._seen_ls_markers: set = set()
        self._sweep_task: Optional[asyncio.Task] = None
        self._popup_tasks: List[asyncio.Task] = []
        self._popup_tasks: List[asyncio.Task] = []
        self._ingest_lock = asyncio.Lock()

    def touch(self) -> None:
        self.last_active = time.time()

    def _next_seq(self) -> int:
        self._max_seq += 1
        self._used_seqs.add(self._max_seq)
        return self._max_seq

    def _register_seq(self, seq: int) -> None:
        """Track a seq adopted from the page's own counter."""
        if seq > 0:
            self._used_seqs.add(seq)
            if seq > self._max_seq:
                self._max_seq = seq

    def _unique_seq(self, preferred: int) -> int:
        """Return ``preferred`` if it is not already used, else a fresh seq.

        Page seq counters are per-origin (localStorage is origin-scoped), so a
        page that navigates cross-origin restarts its counter at 1 while the
        backend session may already hold seq 1..N. Using the page's seq when it
        collides would corrupt the authoritative ordering.
        """
        if preferred > 0 and preferred not in self._used_seqs:
            self._register_seq(preferred)
            return preferred
        return self._next_seq()

    def add_record(self, type_: str, url: str, data: Dict[str, Any], timestamp: Optional[str] = None, page_title: Optional[str] = None) -> DataLayerRecord:
        """Append one record to the authoritative backend log."""
        seq = self._next_seq()
        rec = DataLayerRecord(
            seq=seq,
            type=type_,
            timestamp=timestamp or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            url=url or self.current_url,
            data=data,
            page_title=page_title or self.page_title,
        )
        self._events.append(rec)
        if len(self._events) > DATA_LAYER_MAX_EVENTS:
            self._events = self._events[-DATA_LAYER_MAX_EVENTS:]
        return rec

    def _to_status(self, session_id: str) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "status": self.status,
            "url": self.url,
            "current_url": self.current_url,
            "page_title": self.page_title,
            "data_layer_found": self.data_layer_found,
            "instrumented": self.instrumented,
            "events": [e.model_dump() for e in self._events],
            "event_count": len(self._events),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.created)) + "Z",
            "message": self.message,
            "error": self.error,
        }

    async def collect_events(self) -> List[DataLayerRecord]:
        async with self._ingest_lock:
            return await self._collect_events_locked()

    async def _collect_events_locked(self) -> List[DataLayerRecord]:
        """Reconcile the in-page mirror (localStorage + live records) into the
        backend log.

        This is the AUTHORITATIVE sync path: the browser observer persists every
        record to localStorage immediately, and this method pulls them over. It
        runs on a background timer (fast sweep), on every navigation, and on
        every status/events poll, so interactions appear reliably even when a
        click navigates the page away in the same tick.
        """
        records: List[Dict[str, Any]] = []
        if self.page is not None:
            try:
                raw = await self.page.evaluate(
                    "() => { try { const r = localStorage.getItem('__dl_captured_events'); return r ? JSON.parse(r) : []; } catch (e) { return []; } }"
                )
                if isinstance(raw, list):
                    records.extend(raw)
            except Exception:  # noqa: BLE001 - page may be navigating
                return self._events

        # Deduplicate by content: the same real event can arrive twice (once via
        # the live postMessage bridge, once via the localStorage mirror), each
        # time with a different seq because the page and backend counters drift.
        # Match on (type, timestamp, url, data) — seq is intentionally ignored.
        def _key(rtype: str, ts: str, url: str, data: Any) -> Tuple[Any, ...]:
            try:
                dkey = repr(sorted((data or {}).items()))
            except Exception:  # noqa: BLE001
                dkey = repr(data)
            return (rtype, ts, url, dkey)

        known = {_key(e.type, e.timestamp, e.url, e.data) for e in self._events}
        changed = False
        for rec in records:
            norm = _normalize_record(rec, self.current_url)
            if norm is None:
                continue
            # pagehide navigation markers (seq -1, to_url empty): the real
            # navigation record is emitted by the backend framenavigated
            # handler, so skip the marker itself.
            if norm["type"] == "navigation" and not norm["data"].get("to_url"):
                continue
            key = _key(norm["type"], norm["timestamp"], norm["url"], norm["data"])
            if key in known:
                continue
            seq = self._unique_seq(norm["seq"])
            rec_obj = DataLayerRecord(
                seq=seq,
                type=norm["type"],
                timestamp=norm["timestamp"],
                url=norm["url"],
                data=norm["data"],
                page_title=norm["page_title"],
            )
            self._events.append(rec_obj)
            known.add(_key(norm["type"], norm["timestamp"], norm["url"], norm["data"]))
            changed = True
        if changed and len(self._events) > DATA_LAYER_MAX_EVENTS:
            self._events = self._events[-DATA_LAYER_MAX_EVENTS:]
        return self._events

    def _ingest_raw_localstorage(self, raw: str) -> None:
        self._ingest_raw_localstorage_locked(raw)

    def _ingest_raw_localstorage_locked(self, raw: str) -> None:
        """Ingest a raw localStorage JSON string (from a departing page) into
        the authoritative backend log, deduplicating by content."""
        import json as _json

        try:
            records = _json.loads(raw)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(records, list):
            return

        def _key(rtype: str, ts: str, url: str, data: Any) -> Tuple[Any, ...]:
            try:
                dkey = repr(sorted((data or {}).items()))
            except Exception:  # noqa: BLE001
                dkey = repr(data)
            return (rtype, ts, url, dkey)

        known = {_key(e.type, e.timestamp, e.url, e.data) for e in self._events}
        for rec in records:
            norm = _normalize_record(rec, self.current_url)
            if norm is None:
                continue
            if norm["type"] == "navigation" and not norm["data"].get("to_url"):
                continue  # pagehide marker — real nav record comes from backend
            key = _key(norm["type"], norm["timestamp"], norm["url"], norm["data"])
            if key in known:
                continue
            seq = self._unique_seq(norm["seq"])
            self._events.append(
                DataLayerRecord(
                    seq=seq,
                    type=norm["type"],
                    timestamp=norm["timestamp"],
                    url=norm["url"],
                    data=norm["data"],
                    page_title=norm["page_title"],
                )
            )
            known.add(key)
        if len(self._events) > DATA_LAYER_MAX_EVENTS:
            self._events = self._events[-DATA_LAYER_MAX_EVENTS:]


class DataLayerService:
    """Owns all live browser sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, DataLayerSession] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    def _new_session_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def get(self, session_id: str) -> Optional[DataLayerSession]:
        return self._sessions.get(session_id)

    async def start(
        self,
        url: str,
        navigation_pause_ms: int = 2500,
        click_text: Optional[str] = None,
        click_selector: Optional[str] = None,
        headless: bool = True,
    ) -> DataLayerSession:
        """Launch a persistent Chromium session, inject the observer BEFORE any
        page script runs, and open the URL. The browser stays open after this
        returns; callers poll ``status`` / ``events``.
        """
        sid = self._new_session_id()
        try:
            safe_url = validate_url(url, allow_localhost=_allow_localhost_debug())
        except Exception as exc:  # noqa: BLE001
            session = DataLayerSession(sid, url)
            session.status = "error"
            session.error = f"{type(exc).__name__}: {exc}"
            self._sessions[sid] = session
            import logging
            logging.exception("DATA LAYER START FAILED (validate_url) | session=%s | url=%s", sid, url)
            return session

        from playwright.async_api import async_playwright

        session = DataLayerSession(sid, safe_url)
        self._sessions[sid] = session
        session.status = "starting"
        session.message = "Launching Chromium…"

        try:
            playwright = await async_playwright().start()
            session.playwright = playwright
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
            try:
                browser = await playwright.chromium.launch(headless=headless, args=launch_args)
            except Exception as launch_exc:  # noqa: BLE001
                # headless=False needs a real display (X server). Locally
                # that's fine (Windows/macOS/Linux desktop) — but on a
                # headless cloud box (Render etc.) this throws immediately.
                # Fall back to headless=True instead of failing the whole
                # session, so a stray non-headless request in production
                # still works (just without a visible window).
                if not headless:
                    import logging
                    logging.warning(
                        "DATA LAYER: headless=False launch failed (%s) — no display available, "
                        "falling back to headless=True | session=%s",
                        launch_exc, sid,
                    )
                    browser = await playwright.chromium.launch(headless=True, args=launch_args)
                else:
                    raise
            session.browser = browser
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
            )
            session.context = context
            # Automatic instrumentation: runs before every page's own scripts,
            # on every navigation / reload / redirect.
            # First: inject the beacon config + session id (used by the observer
            # as a best-effort fast path for pre-navigation events).
            beacon_url = _beacon_url()
            if beacon_url:
                await context.add_init_script(
                    f"window.__dlBeaconUrl = {beacon_url!r}; window.__dlSessionId = {sid!r};"
                )
            await context.add_init_script(OBSERVER_SCRIPT)
            page = await context.new_page()
            session.page = page
            page.on("popup", lambda p: asyncio.create_task(_on_popup(p)))
            context.on("page", lambda p: asyncio.create_task(_on_popup(p)) if p != page else None)

            async def _on_message(msg) -> None:
                try:
                    data = msg.data
                    if not data or not data.get("__dlCapture"):
                        return
                    rec = data.get("record")
                    if rec is None:
                        return
                    # Navigation records from the bridge already carry their own
                    # metadata; everything else is a normal event.
                    if rec.get("type") == "navigation":
                        from_url = (rec.get("data") or {}).get("from_url", "")
                        to_url = (rec.get("data") or {}).get("to_url", "")
                        session.add_record(
                            "navigation",
                            to_url or session.current_url,
                            {
                                "action": "navigation",
                                "from_url": from_url or session.current_url,
                                "to_url": to_url or session.current_url,
                            },
                            rec.get("timestamp"),
                        )
                    else:
                        norm = _normalize_record(rec, session.current_url)
                        if norm is None:
                            return
                        session.add_record(
                            norm["type"],
                            norm["url"],
                            norm["data"],
                            norm["timestamp"],
                        )
                    session.touch()
                    try:
                        session.current_url = page.url
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass

            page.on("message", lambda msg: asyncio.create_task(_on_message(msg)))

            # Console bridge: the observer ALSO logs '__dl_capture__' + JSON so
            # Playwright can deliver records reliably (page.on('console')
            # works for same-window console, unlike postMessage). Content-based
            # dedup in ingest/collect_events makes double delivery harmless.
            async def _on_console(msg) -> None:
                try:
                    text = msg.text or ""
                    if not text.startswith("__dl_capture__"):
                        return
                    payload = text.split("__dl_capture__", 1)[1].strip()
                    rec = json.loads(payload)
                    if not isinstance(rec, dict):
                        return
                    await _service_ingest(rec)
                except Exception:  # noqa: BLE001
                    pass

            async def _service_ingest(rec: dict) -> None:
                """Dedup-aware ingest for console-bridge records."""
                norm = _normalize_record(rec, session.current_url)
                if norm is None:
                    return
                if norm["type"] == "navigation" and not norm["data"].get("to_url"):
                    return
                key = (norm["type"], norm["timestamp"], norm["url"], repr(sorted((norm["data"] or {}).items())))
                known = {
                    (e.type, e.timestamp, e.url, repr(sorted((e.data or {}).items())))
                    for e in session._events
                }
                if key in known:
                    return
                session.add_record(norm["type"], norm["url"], norm["data"], norm["timestamp"], norm.get("page_title"))
                session.touch()

            page.on("console", lambda m: asyncio.create_task(_on_console(m)))

            async def _on_navigation(frame) -> None:
                try:
                    session.touch()
                    session.status = "capturing"
                    if frame is None:
                        return
                    # framenavigated fires for the OLD document (navigation
                    # start) and the NEW document. Each time, attempt to read
                    # the CURRENT document's localStorage — this recovers
                    # interactions that happened right before a (possibly
                    # cross-origin) navigation and were never swept. Dedup in
                    # _ingest_raw_localstorage makes double reads harmless.
                    try:
                        if frame.url and frame.url.startswith("http"):
                            raw = await page.evaluate(
                                "() => { try { return localStorage.getItem('__dl_captured_events'); } catch (e) { return null; } }"
                            )
                            if raw:
                                session._ingest_raw_localstorage(raw)
                    except Exception:  # noqa: BLE001
                        pass
                    is_main = frame == page.main_frame
                    if not is_main:
                        return
                    new_url = page.url
                    # session.current_url is the last URL this session actually
                    # saw — using it as the from_url keeps the navigation record
                    # correct even though framenavigated can fire with the frame
                    # already pointing at the new document.
                    from_url = session.current_url or session.url
                    if new_url != from_url:
                        # Backend-side navigation record: reliable even when the
                        # page's beforeunload bridge message races with teardown.
                        session.add_record(
                            "navigation",
                            new_url,
                            {
                                "action": "navigation",
                                "from_url": from_url,
                                "to_url": new_url,
                            },
                        )
                        session.message = "Navigation detected — capturing continues."
                    session.current_url = new_url
                    try:
                        session.page_title = await page.title()
                    except Exception:  # noqa: BLE001
                        pass
                    # The init script re-injects on the new document; reconcile
                    # anything already persisted.
                    await session.collect_events()
                except Exception:  # noqa: BLE001
                    pass

            page.on("framenavigated", lambda f: asyncio.create_task(_on_navigation(f)))

            # A link may open a NEW tab (e.g. Epaper -> epaper.deccanherald.com
            # or Sign In -> web.tpml.in). The click is persisted on the
            # originating page BEFORE teardown; additionally record the popup's
            # own events into the same session so the manager sees the full
            # journey — page_load, clicks, scrolls AND dataLayer pushes inside
            # the popup all feed the ONE authoritative session.
            async def _on_popup(popup) -> None:
                try:
                    session.touch()
                    popup_url = popup.url or ""
                    session.add_record(
                        "navigation",
                        popup_url or session.current_url,
                        {
                            "action": "navigation",
                            "from_url": session.current_url or session.url,
                            "to_url": popup_url or "(new tab)",
                            "new_tab": True,
                        },
                    )
                    # Popups do NOT reliably inherit context.add_init_script
                    # (Chromium can reuse the about:blank document and skip the
                    # script on the real navigation). Attach the observer +
                    # beacon config explicitly so the popup is instrumented for
                    # ITS OWN interactions (click/scroll/page_load/dataLayer).
                    beacon_url2 = _beacon_url()
                    try:
                        if beacon_url2:
                            await popup.add_init_script(
                                f"window.__dlBeaconUrl = {beacon_url2!r}; window.__dlSessionId = {sid!r};"
                            )
                        await popup.add_init_script(OBSERVER_SCRIPT)
                    except Exception:  # noqa: BLE001
                        pass
                    # Attach the console bridge + a persistent localStorage
                    # sweep to the popup so its interactions and dataLayer
                    # events keep flowing for the popup's whole lifetime.
                    popup.on(
                        "console",
                        lambda m: asyncio.create_task(_on_console(m)),
                    )

                    async def _sweep_popup() -> None:
                        try:
                            while True:
                                await asyncio.sleep(0.8)
                                s = self.get(sid)
                                if s is None:
                                    return
                                try:
                                    raw = await popup.evaluate(
                                        "() => { try { return localStorage.getItem('__dl_captured_events'); } catch (e) { return null; } }"
                                    )
                                    if raw:
                                        s._ingest_raw_localstorage(raw)
                                except Exception:  # noqa: BLE001 - popup closed/navigated
                                    return
                        except asyncio.CancelledError:
                            pass

                    t = asyncio.create_task(_sweep_popup())
                    session._popup_tasks.append(t)
                    # If the popup is mid-load, wait for it to settle and
                    # re-inject the observer (init scripts apply to future
                    # navigations; a popup already past about:blank needs the
                    # script pushed into the live document).
                    try:
                        await popup.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        await popup.evaluate(OBSERVER_SCRIPT)
                    except Exception:  # noqa: BLE001
                        pass
                    # Initial reconcile once the popup settles.
                    await asyncio.sleep(1.0)
                    try:
                        raw = await popup.evaluate(
                            "() => { try { return localStorage.getItem('__dl_captured_events'); } catch (e) { return null; } }"
                        )
                        if raw and self.get(sid):
                            self.get(sid)._ingest_raw_localstorage(raw)
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass

            page.on("popup", lambda p: asyncio.create_task(_on_popup(p)))

            session.status = "open"
            session.message = "Opening page…"
            await page.goto(safe_url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(navigation_pause_ms)

            session.status = "capturing"
            session.instrumented = True
            session.current_url = page.url
            try:
                session.page_title = await page.title()
            except Exception:  # noqa: BLE001
                pass
            try:
                session.data_layer_found = await page.evaluate(
                    "() => !!(window.dataLayer && Array.isArray(window.dataLayer))"
                )
            except Exception:  # noqa: BLE001
                session.data_layer_found = False

            # Optional automated click (e.g. "Login") to trigger interaction events.
            if click_text or click_selector:
                try:
                    if click_text:
                        session.message = f'Clicking element with text "{click_text}"…'
                        await page.get_by_text(click_text, exact=True).first.click(timeout=6000)
                    elif click_selector:
                        session.message = f"Clicking selector {click_selector}…"
                        await page.locator(click_selector).first.click(timeout=6000)
                    await page.wait_for_timeout(1200)
                except Exception as exc:  # noqa: BLE001
                    session.error = f"Could not click element: {exc}"

            await session.collect_events()
            session.message = "Instrumentation active — interact with the page to capture events."
            session.status = "capturing"
            self._start_sweep(sid)
            return session
        except Exception as exc:  # noqa: BLE001
            session.status = "error"
            session.error = f"{type(exc).__name__}: {exc}"

            import logging
            logging.exception(
                "DATA LAYER START FAILED | session=%s | url=%s",
                sid,
                safe_url,
            )

            # Keep the session alive so the API can report the real error.
            return session

    # ------------------------------------------------------------------
    def _start_sweep(self, session_id: str, interval_seconds: float = 0.8) -> None:
        """Background task: fast localStorage sweep so interactions appear in
        the backend log promptly even though Playwright does not deliver
        same-window postMessage to page.on('message')."""
        session = self.get(session_id)
        if session is None:
            return
        if getattr(session, "_sweep_task", None) is not None and not session._sweep_task.done():
            return

        async def _sweep() -> None:
            try:
                while True:
                    await asyncio.sleep(interval_seconds)
                    s = self.get(session_id)
                    if s is None or s.page is None:
                        break
                    try:
                        await s.collect_events()
                        s.touch()
                    except Exception:  # noqa: BLE001
                        pass
            except asyncio.CancelledError:
                pass

        session._sweep_task = asyncio.create_task(_sweep())

    # ------------------------------------------------------------------
    async def click(self, session_id: str, text: str) -> Dict[str, Any]:
        """Click a visible element containing the given text in the live page."""
        session = self.get(session_id)
        if session is None or session.page is None:
            return {"clicked": False, "message": "No live browser session.", "session_id": session_id}
        try:
            clicked = await self._click_with_fallback(session.page, text=text)
            await session.page.wait_for_timeout(1500)
            session.touch()
            await session.collect_events()
            return {"clicked": clicked, "message": f'Clicked element with text "{text}".' if clicked else f'Could not click element with text "{text}" — not found or not visible.', "session_id": session_id}
        except Exception as exc:  # noqa: BLE001
            return {
                "clicked": False,
                "message": f"Could not click element with text \"{text}\": {exc}",
                "session_id": session_id,
            }

    async def _click_with_fallback(self, page, text: Optional[str] = None, selector: Optional[str] = None) -> bool:
        """Click an element by text or selector, falling back to a raw
        JavaScript dispatch when Playwright's actionability checks cannot find
        the element (e.g. elements hidden behind overlays / consent banners).
        Returns True when the click was dispatched."""
        locator = None
        if selector:
            locator = page.locator(selector).first
        elif text:
            locator = page.get_by_text(text, exact=True).first
        if locator is not None:
            try:
                await locator.click(timeout=5000)
                return True
            except Exception:  # noqa: BLE001 - fall through to JS dispatch
                pass
        # Raw DOM click fallback (Playwright's actionability checks can reject
        # elements covered by overlays). Exact-text match first, then any
        # element whose trimmed text equals the target.
        if text:
            js_click = """(text) => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const nodes = Array.from(document.querySelectorAll('a,button,[role="button"],summary,label'));
                let el = nodes.find((n) => norm(n.innerText || n.textContent) === text);
                if (!el) el = nodes.find((n) => (norm(n.innerText || n.textContent) || '').includes(text));
                if (!el) return false;
                try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
                try { el.click(); } catch (e) { return false; }
                return true;
            }"""
            try:
                if await page.evaluate(js_click, text):
                    return True
            except Exception:  # noqa: BLE001
                pass
        if selector:
            try:
                if await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (!el) return false;
                        try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
                        try { el.click(); } catch (e) { return false; }
                        return true;
                    }""",
                    selector,
                ):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    # ------------------------------------------------------------------
    async def ingest(self, session_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Accept a record beaconed directly from a monitored page.

        Used by the observer's navigator.sendBeacon fast path for events that
        occur right before a (possibly cross-origin) navigation, where the
        page's localStorage becomes unreachable. Deduplicates against the
        authoritative log so the same event arriving via both paths appears
        once.
        """
        session = self.get(session_id)
        if session is None:
            return {"ok": False, "message": "Session not found.", "session_id": session_id}
        session.touch()
        norm = _normalize_record(record, session.current_url)
        if norm is None:
            return {"ok": False, "message": "Invalid record.", "session_id": session_id}
        if norm["type"] == "navigation" and not norm["data"].get("to_url"):
            return {"ok": True, "message": "Ignored marker.", "session_id": session_id}
        known = {
            (e.type, e.timestamp, e.url, repr(sorted((e.data or {}).items())))
            for e in session._events
        }
        key = (norm["type"], norm["timestamp"], norm["url"], repr(sorted((norm["data"] or {}).items())))
        if key in known:
            return {"ok": True, "message": "Duplicate ignored.", "session_id": session_id}
        session.add_record(norm["type"], norm["url"], norm["data"], norm["timestamp"], norm.get("page_title"))
        return {"ok": True, "message": "Ingested.", "session_id": session_id}

    # ------------------------------------------------------------------
    async def get_events(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get(session_id)
        if session is None:
            return None
        session.touch()
        await session.collect_events()
        return session._to_status(session_id)

    async def status(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get(session_id)
        if session is None:
            return None
        session.touch()
        await session.collect_events()
        return session._to_status(session_id)

    # ------------------------------------------------------------------
    async def click_element(
        self,
        session_id: str,
        selector: Optional[str] = None,
        text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Click an element by selector (or text) and return rich element info.

        The element info is gathered in the page context and returned to the
        frontend; the click itself also produces a user-interaction record
        through the observer, so it shows up in the timeline.
        """
        session = self.get(session_id)
        if session is None or session.page is None:
            return {
                "clicked": False,
                "message": "No live browser session.",
                "session_id": session_id,
                "element": None,
            }
        try:
            if not selector and not text:
                return {
                    "clicked": False,
                    "message": "Provide either a selector or element text.",
                    "session_id": session_id,
                    "element": None,
                }
            clicked = await self._click_with_fallback(session.page, text=text, selector=selector)
            await session.page.wait_for_timeout(1200)
            session.touch()
            await session.collect_events()
            info = None
            try:
                if selector:
                    locator = session.page.locator(selector).first
                else:
                    locator = session.page.get_by_text(text or "", exact=True).first
                info = await locator.evaluate(
                    """(el) => {
                        const pick = (n) => { try { return el.getAttribute(n) || undefined; } catch (e) { return undefined; } };
                        const t = el.tagName ? el.tagName.toLowerCase() : '';
                        let text = '';
                        try { text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120); } catch (e) {}
                        const o = {
                            tag: t,
                            text: text || undefined,
                            id: pick('id') || undefined,
                            class: pick('class') || undefined,
                            href: pick('href') || undefined,
                            role: pick('role') || undefined,
                            aria_label: pick('aria-label') || undefined,
                            title: pick('title') || undefined,
                            name: pick('name') || undefined,
                        };
                        return JSON.parse(JSON.stringify(o));
                    }"""
                )
            except Exception:  # noqa: BLE001 - info is best-effort
                pass
            target_desc = f" {selector}" if selector else f' with text "{text}"'
            return {
                "clicked": clicked,
                "message": f"Clicked element{target_desc}." if clicked
                else f"Could not click element{target_desc} — not found or not visible.",
                "session_id": session_id,
                "element": info if isinstance(info, dict) else None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "clicked": False,
                "message": f"Could not click element: {exc}",
                "session_id": session_id,
                "element": None,
            }

    # ------------------------------------------------------------------
    async def export(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return the complete session (all metadata + full event log)."""
        session = self.get(session_id)
        if session is None:
            return None
        session.touch()
        await session.collect_events()
        return {
            "session_id": session.id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(session.created)) + "Z",
            "url": session.url,
            "current_url": session.current_url,
            "page_title": session.page_title,
            "data_layer_found": session.data_layer_found,
            "events": [e.model_dump() for e in session._events],
            "event_count": len(session._events),
        }

    # ------------------------------------------------------------------
    async def view_source(self, session_id: str, max_chars: int = 2_000_000) -> Optional[Dict[str, Any]]:
        """Return the current page's live HTML for the source viewer."""
        session = self.get(session_id)
        if session is None:
            return None
        session.touch()
        if session.page is None:
            return {"url": session.current_url, "html": "", "html_size": 0}
        try:
            html = await session.page.evaluate(
                "() => { try { return document.documentElement.outerHTML; } catch (e) { return ''; } }"
            )
            if not isinstance(html, str):
                html = ""
            if len(html) > max_chars:
                html = html[:max_chars]
            return {
                "url": session.current_url,
                "html": html,
                "html_size": len(html),
                "page_title": session.page_title,
            }
        except Exception as exc:  # noqa: BLE001 - page may be navigating
            return {
                "url": session.current_url,
                "html": "",
                "html_size": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

    # ------------------------------------------------------------------
    async def clear(self, session_id: str) -> Dict[str, Any]:
        """Clear the captured history in the browser (localStorage + live) and
        in the backend session log. Does NOT close the browser."""
        session = self.get(session_id)
        if session is None:
            return {"ok": False, "message": "Session not found.", "session_id": session_id}
        session.touch()
        if session.page is not None:
            try:
                await session.page.evaluate(
                    "() => { try { localStorage.removeItem('__dl_captured_events'); localStorage.removeItem('__dl_seq'); } catch (e) {} try { document.__dlScrollState = null; } catch (e) {} return true; }"
                )
            except Exception:  # noqa: BLE001
                pass
        session._events = []
        session._max_seq = 0
        session._used_seqs = set()
        session.message = "Log cleared — still capturing new events."
        return {"ok": True, "message": "Captured events cleared.", "session_id": session_id}

    # ------------------------------------------------------------------
    async def close(self, session_id: str) -> Dict[str, Any]:
        """Close the browser, context and playwright driver; free the session."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {"ok": True, "message": "Session already closed.", "session_id": session_id}
        # Stop the background sweep.
        if session._sweep_task is not None:
            session._sweep_task.cancel()
            session._sweep_task = None
        for t in session._popup_tasks:
            t.cancel()
        session._popup_tasks = []
        errors: List[str] = []
        for name, thing in (
            ("browser", session.browser),
            ("context", session.context),
            ("playwright", getattr(session, "playwright", None)),
        ):
            if thing is None:
                continue
            try:
                if name == "context":
                    await thing.close()
                elif name == "browser":
                    await thing.close()
                else:
                    await thing.stop()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
        return {
            "ok": not errors,
            "message": "Browser session closed." if not errors else "Closed with errors.",
            "error": "; ".join(errors) or None,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------
    def cleanup(self, max_age_seconds: float = 1800.0) -> None:
        """Close stale sessions (called opportunistically)."""
        now = time.time()
        for sid in [
            s
            for s, sess in self._sessions.items()
            if now - sess.last_active > max_age_seconds
        ]:
            asyncio.create_task(self.close(sid))

    async def close_all(self) -> None:
        for sid in list(self._sessions.keys()):
            await self.close(sid)