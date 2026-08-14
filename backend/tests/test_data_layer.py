"""Data Layer service tests using a local HTML fixture served over HTTP.

These tests drive the real DataLayerService (persistent Playwright session)
against a local fixture page, verifying:

- start keeps the browser session alive AND auto-instruments the page
  (no manual logger paste needed)
- existing dataLayer entries are captured automatically
- future dataLayer.push() events are captured (verbatim, not modified)
- user interactions (click / scroll / input) are captured separately as
  interaction records — never as dataLayer events
- events persist across navigation/reload (backend session log is
  authoritative; localStorage is a best-effort mirror)
- clear wipes the history without closing the browser
- close frees the browser
"""
from __future__ import annotations

import asyncio
import os

import pytest

# The data layer service reads this at import time; set it before import so the
# local fixture URLs (127.0.0.1) are allowed in tests only.
os.environ.setdefault("SEO_ALLOW_LOCALHOST_DEBUG", "1")

from app.services.data_layer import (  # noqa: E402
    OBSERVER_SCRIPT,
    DataLayerService,
)

# A minimal page that declares window.dataLayer like a GTM container.
FIXTURE_HTML = """<!DOCTYPE html>
<html>
<head><title>DL Fixture</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ "event": "gtm.js", "gtm.start": 123456 });
  window.dataLayer.push({ "event": "page_view", "page_type": "article", "nested": { "a": [1, 2, 3] } });
</script>
<button id="login-btn" aria-label="Login to your account">Login</button>
<button id="read-more">Read More</button>
<div style="height: 3000px"></div>
</body>
</html>
"""

# A page with NO dataLayer at all.
NO_DL_HTML = """<!DOCTYPE html>
<html><head><title>No DL</title></head><body><h1>No data layer</h1></body></html>
"""

# Icon-only controls (aria-label / title) + a password field to verify
# redaction and human-friendly label resolution.
LABELS_HTML = """<!DOCTYPE html>
<html>
<head><title>Labels Fixture</title></head>
<body>
<button id="icon-btn" aria-label="Sign in">►</button>
<a id="img-link" title="Epaper"><span class="icon">📰</span></a>
<input id="pw" type="password" name="password" placeholder="Password" value="super-secret">
</body>
</html>
"""

# A page with a logout button that pushes an event when clicked.
CLICK_HTML = """<!DOCTYPE html>
<html>
<head><title>Click Fixture</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
  function onLogout() {
    window.dataLayer.push({ "event": "logout", "user": "tester" });
  }
</script>
<button id="logout" onclick="onLogout()">Logout</button>
</body>
</html>
"""

# A two-page navigation fixture: page 1 has a link + nested clickable, page 2
# declares its own dataLayer and a tall body so scrolls are measurable.
PAGE1_HTML = """<!DOCTYPE html>
<html>
<head><title>Page 1</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ "event": "page_view", "page": 1 });
</script>
<a id="to-page2" href="/page2">Go to page 2</a>
<a id="nested-link" class="menu-link" href="/page2">
  <span class="icon">*</span>
  <span class="label">Epaper</span>
</a>
<div style="height: 3000px"></div>
</body>
</html>
"""

PAGE2_HTML = """<!DOCTYPE html>
<html>
<head><title>Page 2</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ "event": "page_view", "page": 2 });
</script>
<h1>Page 2</h1>
<div style="height: 4000px"></div>
</body>
</html>
"""

# A page that REASSIGNS window.dataLayer after the observer armed, to prove
# the hook is re-armed automatically.
REARM_HTML = """<!DOCTYPE html>
<html>
<head><title>Rearm Fixture</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ "event": "before_replace" });
  setTimeout(function () {
    // The site replaces the whole array later.
    window.dataLayer = [];
    window.dataLayer.push({ "event": "after_replace" });
  }, 300);
</script>
<button id="go">Go</button>
</body>
</html>
"""

# A page that fires its OWN GTM-style scrollDepth on scroll — proves our
# observer's scroll records coexist with the site's dataLayer event.
SCROLL_HTML = """<!DOCTYPE html>
<html>
<head><title>Scroll Fixture</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
  window.addEventListener("scroll", function () {
    window.dataLayer.push({ "event": "gtm.scrollDepth", "percent": 90 });
  });
</script>
<div style="height: 3000px"></div>
</body>
</html>
"""

# A page whose button opens a POPUP (new tab) with its own nested interactive
# elements. The popup must receive the same interaction instrumentation.
POPUP_HTML = """<!DOCTYPE html>
<html>
<head><title>Popup Fixture</title></head>
<body>
<button id="popup-login">
  <span class="label">Login</span>
</button>
<div style="height: 3000px"></div>
</body>
</html>
"""

POPUP_TRIGGER_HTML = """<!DOCTYPE html>
<html>
<head><title>Popup Trigger</title></head>
<body>
<button id="open-popup" onclick="window.open('/popup', '_blank')">Open Popup</button>
</body>
</html>
"""


class _MultiPathServer:
    """Local HTTP server that serves different bodies per path (for navigation)."""

    def __init__(self, routes: dict) -> None:
        import threading

        from http.server import BaseHTTPRequestHandler, HTTPServer

        self.routes = routes

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = self.server.routes.get(self.path, self.server.routes.get("/", b"")).encode("utf-8")  # type: ignore[attr-defined]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # noqa: A002
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.routes = {p: b for p, b in routes.items()}  # type: ignore[attr-defined]
        self.server = server
        self.port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def shutdown(self) -> None:
        self.server.shutdown()


def _serve_fixture(content: str) -> tuple:
    """Serve a fixture over local HTTP and return (url, server)."""
    import threading

    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: A002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/", server


def _type_counts(events) -> dict:
    counts = {"dataLayer": 0, "interaction": 0, "navigation": 0}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return counts


class TestDataLayerService:
    def test_observer_and_bridge_are_complete(self):
        """The observer must hook push, capture interactions, persist to
        localStorage, expose the manager's helpers, and never break push."""
        assert "dl.push = function" in OBSERVER_SCRIPT
        assert "localStorage" in OBSERVER_SCRIPT
        assert "__dl_captured_events" in OBSERVER_SCRIPT
        assert "dlDump" in OBSERVER_SCRIPT
        assert "dlLast" in OBSERVER_SCRIPT
        assert "dlExport" in OBSERVER_SCRIPT
        assert "dlClear" in OBSERVER_SCRIPT
        assert "addEventListener('click'" in OBSERVER_SCRIPT
        assert "addEventListener('scroll'" in OBSERVER_SCRIPT
        assert "addEventListener('input'" in OBSERVER_SCRIPT
        assert "addEventListener('submit'" in OBSERVER_SCRIPT
        assert "addEventListener('pointerdown'" in OBSERVER_SCRIPT
        assert "addEventListener('hashchange'" in OBSERVER_SCRIPT
        # Human-friendly enrichment is built in.
        assert "description" in OBSERVER_SCRIPT
        assert "User clicked" in OBSERVER_SCRIPT
        assert "aria-label" in OBSERVER_SCRIPT
        assert "[REDACTED]" in OBSERVER_SCRIPT
        # Sensitive values are never captured verbatim.
        assert "[type=password]" in OBSERVER_SCRIPT

    def test_observer_has_no_custom_script_execution(self):
        """The custom-script bridge was removed; capture is fully automatic."""
        assert "EXECUTE_BRIDGE" not in OBSERVER_SCRIPT
        assert "eval(" not in OBSERVER_SCRIPT
        assert "{script}" not in OBSERVER_SCRIPT

    def test_full_service_workflow_auto_instrumented(self):
        """start -> auto-captured existing+push -> interaction -> events -> clear -> close.

        No manual logger paste required: the observer is injected by the
        service itself (add_init_script) before any page script runs.
        """
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=800)
            sid = session.id
            assert session.status in ("capturing", "open")
            assert session.instrumented is True

            # Simulate a future push from the page.
            await session.page.evaluate(
                "() => window.dataLayer.push({ 'event': 'afterInteraction', 'value': 42 })"
            )
            await asyncio.sleep(0.6)

            status = await service.get_events(sid)
            events = status["events"]
            names = [e["data"].get("event") for e in events if e["type"] == "dataLayer"]
            assert "gtm.js" in names  # existing entry captured automatically
            assert "page_view" in names  # existing entry captured automatically
            assert "afterInteraction" in names  # future push captured

            # The pushed object is preserved verbatim (nested structure intact).
            dl_records = [e for e in events if e["type"] == "dataLayer"]
            page_view = next(e for e in dl_records if e["data"].get("event") == "page_view")
            assert page_view["data"]["nested"]["a"] == [1, 2, 3]

            # Every record carries seq / timestamp / url.
            for e in events:
                assert e["seq"] > 0
                assert e["timestamp"]
                assert e["url"].startswith("http://127.0.0.1")

            # Clear wipes history but keeps the browser alive.
            cleared = await service.clear(sid)
            assert cleared["ok"] is True
            status2 = await service.get_events(sid)
            assert status2["events"] == []
            assert service.get(sid) is not None  # browser still open

            # Close frees the session.
            closed = await service.close(sid)
            assert closed["ok"] is True
            assert service.get(sid) is None
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_user_interactions_captured_separately(self):
        """Clicks and scrolls are captured as interaction records with element
        info — never as dataLayer events (the fixture pushes nothing on click)."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            page = session.page
            await page.click("#login-btn")
            await asyncio.sleep(0.6)
            await page.click("#read-more")
            await asyncio.sleep(0.6)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.0)

            events = await service.get_events(sid)
            interactions = [e for e in events["events"] if e["type"] == "interaction"]
            actions = [e["data"].get("action") for e in interactions]

            # Login click captured with rich element info (aria-label wins over
            # raw visible text per the label-resolution priority).
            login_click = next(
                (e for e in interactions if e["data"].get("action") == "click"
                 and (e["data"].get("element") or {}).get("text") == "Login to your account"),
                None,
            )
            assert login_click is not None, f"Login click not found in {actions}"
            el = login_click["data"]["element"]
            assert el.get("tag") == "button"
            assert el.get("id") == "login-btn"
            assert el.get("aria-label") == "Login to your account"
            assert login_click["data"].get("description") == 'User clicked "Login to your account"'

            # Read More click captured (visible text used when no aria-label).
            read_more = next(
                (e for e in interactions if e["data"].get("action") == "click"
                 and (e["data"].get("element") or {}).get("text") == "Read More"),
                None,
            )
            assert read_more is not None

            # Scroll captured with percentage (retry — the background sweep is
            # async, so under load the milestone may take a moment to land).
            scrolls = []
            for _ in range(10):
                events = await service.get_events(sid)
                scrolls = [e for e in events["events"] if e["type"] == "interaction" and e["data"].get("action") == "scroll"]
                if any(e["data"].get("scroll_percent", 0) >= 90 for e in scrolls):
                    break
                await asyncio.sleep(0.5)
            assert scrolls, "no scroll records"
            assert any(e["data"].get("scroll_percent", 0) >= 90 for e in scrolls), \
                f"no deep scroll milestone: {[s['data'].get('scroll_percent') for s in scrolls]}"

            # The interaction records must NOT be labeled dataLayer.
            dl = [e for e in events["events"] if e["type"] == "dataLayer"]
            assert all("action" not in e["data"] for e in dl)
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_click_element_triggers_real_push(self):
        """A click that triggers dataLayer.push shows BOTH the interaction and
        the real dataLayer event."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(CLICK_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            res = await service.click(sid, "Logout")
            assert res["clicked"] is True, res
            await asyncio.sleep(0.6)
            events = await service.get_events(sid)
            types = _type_counts(events["events"])
            # Both an interaction click AND the real dataLayer logout push.
            assert types["interaction"] >= 1
            dl_names = [e["data"].get("event") for e in events["events"] if e["type"] == "dataLayer"]
            assert "logout" in dl_names
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_no_data_layer_page_does_not_crash(self):
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(NO_DL_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            assert session.data_layer_found is False
            events = await service.get_events(sid)
            dl = [e for e in events["events"] if e["type"] == "dataLayer"]
            assert dl == []
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_nested_element_click_captured(self):
        """A click on a <span> inside an <a> resolves to the anchor and captures
        the anchor's text/href/class — not the span's."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": PAGE1_HTML, "/page2": PAGE2_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=600)
            sid = session.id
            # Click the SPAN inside the Epaper anchor.
            await session.page.click("#nested-link .label")
            await asyncio.sleep(1.0)

            events = await service.get_events(sid)
            clicks = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "click"
            ]
            epaper = next(
                (e for e in clicks if "Epaper" in ((e["data"].get("element") or {}).get("text") or "")),
                None,
            )
            assert epaper is not None, f"Epaper click not found in {[c['data'] for c in clicks]}"
            el = epaper["data"]["element"]
            assert el.get("tag") == "a"
            assert el.get("href", "").endswith("/page2")
            assert el.get("class", "") == "menu-link"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_navigation_persistence_click_plus_navigation(self):
        """Clicking a real link must record BOTH the USER INTERACTION click and
        a NAVIGATION record, keep all previous events, and continue capturing
        the dataLayer on the NEW page."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": PAGE1_HTML, "/page2": PAGE2_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=600)
            sid = session.id

            # Click the "Go to page 2" link -> real navigation.
            await session.page.click("#to-page2")
            await asyncio.sleep(2.0)

            events = await service.get_events(sid)
            types = _type_counts(events["events"])
            # click interaction + navigation record + page 2 dataLayer.
            assert types["interaction"] >= 1, f"no interaction: {types}"
            assert types["navigation"] >= 1, f"no navigation: {types}"

            clicks = [e for e in events["events"] if e["type"] == "interaction" and e["data"].get("action") == "click"]
            assert any(
                (c["data"].get("element") or {}).get("text") == "Go to page 2"
                for c in clicks
            ), f"click not captured: {[c['data'] for c in clicks]}"

            navs = [e for e in events["events"] if e["type"] == "navigation"]
            assert navs[0]["data"]["from_url"].endswith("/")
            assert navs[0]["data"]["to_url"].endswith("/page2")

            # Previous events (page 1 dataLayer) must survive.
            dl_names = [e["data"].get("event") for e in events["events"] if e["type"] == "dataLayer"]
            assert "page_view" in dl_names
            urls = {e["url"] for e in events["events"]}
            assert any(u.endswith("/") for u in urls) and any(u.endswith("/page2") for u in urls)

            # Page 2 dataLayer continues to be captured.
            assert any(
                e["type"] == "dataLayer" and e["data"].get("page") == 2
                for e in events["events"]
            ), f"page2 dataLayer missing: {[e['data'] for e in events['events'] if e['type']=='dataLayer']}"

            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_scroll_milestones_captured(self):
        """Scrolling captures milestone records (25/50/75/90/100) without
        flooding the backend with duplicates."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": PAGE1_HTML, "/page2": PAGE2_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=600)
            sid = session.id
            # Scroll in steps so milestones cross.
            await session.page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
            await asyncio.sleep(0.5)
            await session.page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            await asyncio.sleep(0.5)
            await session.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.0)

            events = await service.get_events(sid)
            scrolls = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "scroll"
            ]
            assert scrolls, "no scroll records"
            pcts = [s["data"].get("scroll_percent", 0) for s in scrolls]
            # At least 2 distinct milestone positions captured (e.g. >=50 and 100).
            assert len(set(pcts)) >= 2, f"too few distinct scroll positions: {pcts}"
            assert max(pcts) >= 90, f"never reached deep scroll: {pcts}"
            # No two identical percentage records back to back (no duplicates).
            for i in range(1, len(scrolls)):
                assert not (
                    scrolls[i]["data"].get("scroll_percent") == scrolls[i - 1]["data"].get("scroll_percent")
                    and scrolls[i]["data"].get("scroll_y") == scrolls[i - 1]["data"].get("scroll_y")
                ), "duplicate scroll records"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_data_layer_reassignment_rearms_hook(self):
        """If the site replaces window.dataLayer = [] after our observer armed,
        the hook must re-arm and capture the new pushes."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(REARM_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=1200)
            sid = session.id
            events = await service.get_events(sid)
            dl_names = [e["data"].get("event") for e in events["events"] if e["type"] == "dataLayer"]
            assert "before_replace" in dl_names, f"pre-replace push missing: {dl_names}"
            assert "after_replace" in dl_names, f"post-replace push missing: {dl_names}"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_clear_resets_backend_log_and_capture_continues(self):
        """Clear Log wipes the backend authoritative log; the browser stays open
        and NEW interactions still appear after clearing."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            await session.page.click("#login-btn")
            await asyncio.sleep(0.8)
            before = await service.get_events(sid)
            assert before["event_count"] > 0

            cleared = await service.clear(sid)
            assert cleared["ok"] is True
            after_clear = await service.get_events(sid)
            assert after_clear["event_count"] == 0
            assert service.get(sid) is not None  # browser still open

            # New interaction after clear appears again.
            await session.page.click("#read-more")
            await asyncio.sleep(1.0)
            after = await service.get_events(sid)
            assert after["event_count"] > 0
            clicks = [e for e in after["events"] if e["type"] == "interaction" and e["data"].get("action") == "click"]
            assert any(
                (c["data"].get("element") or {}).get("text") == "Read More"
                for c in clicks
            ), f"post-clear click missing: {[c['data'] for c in clicks]}"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_export_contains_full_session(self):
        """Export returns session metadata + the complete event log across
        navigation, not just the current page's events."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": PAGE1_HTML, "/page2": PAGE2_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=600)
            sid = session.id
            await session.page.click("#to-page2")
            await asyncio.sleep(2.0)

            payload = await service.export(sid)
            assert payload["session_id"] == sid
            assert payload["started_at"]
            assert payload["event_count"] == len(payload["events"])
            assert payload["event_count"] > 0
            urls = {e["url"] for e in payload["events"]}
            assert any(u.endswith("/") for u in urls) and any(u.endswith("/page2") for u in urls)
            types = {e["type"] for e in payload["events"]}
            assert "dataLayer" in types and "interaction" in types and "navigation" in types
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_interaction_descriptions_human_readable(self):
        """Clicks produce 'User clicked \"...\"' descriptions with page context;
        scrolls produce 'User scrolled to N%'."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            await session.page.click("#read-more")
            await asyncio.sleep(0.8)
            await session.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.0)

            events = await service.get_events(sid)
            clicks = [e for e in events["events"] if e["type"] == "interaction" and e["data"].get("action") == "click"]
            click = next(
                (e for e in clicks if "Read More" in (e["data"].get("element") or {}).get("text", "")),
                None,
            )
            assert click is not None
            assert click["data"]["description"] == 'User clicked "Read More"'
            assert click["data"].get("page", {}).get("url", "").startswith("http://127.0.0.1")
            assert click["data"]["page"].get("title") == "DL Fixture"

            scrolls = [e for e in events["events"] if e["type"] == "interaction" and e["data"].get("action") == "scroll"]
            assert scrolls
            assert "User scrolled to" in scrolls[0]["data"]["description"]
            assert "scroll_percent" in scrolls[0]["data"]
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_icon_only_controls_resolve_label_and_redact_password(self):
        """aria-label/title resolve the label; password values are redacted."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(LABELS_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            # Click the icon-only button (aria-label "Sign in").
            await session.page.click("#icon-btn")
            await asyncio.sleep(0.8)
            # Click the title-only link (span inside <a title="Epaper">).
            await session.page.click("#img-link .icon")
            await asyncio.sleep(0.8)
            # Type into the password field.
            await session.page.fill("#pw", "hunter2")
            await asyncio.sleep(0.8)

            events = await service.get_events(sid)
            clicks = [e for e in events["events"] if e["type"] == "interaction" and e["data"].get("action") == "click"]
            sign_in = next(
                (e for e in clicks if "Sign in" in (e["data"].get("element") or {}).get("text", "")),
                None,
            )
            assert sign_in is not None, f"Sign in click missing: {[c['data'] for c in clicks]}"
            assert sign_in["data"]["description"] == 'User clicked "Sign in"'

            epaper = next(
                (e for e in clicks if "Epaper" in (e["data"].get("element") or {}).get("text", "")),
                None,
            )
            assert epaper is not None, f"Epaper click missing: {[c['data'] for c in clicks]}"
            assert epaper["data"]["description"] == 'User clicked "Epaper"'

            # No sensitive value anywhere in the log.
            dump = repr(events["events"])
            assert "hunter2" not in dump
            assert "super-secret" not in dump
            assert "[REDACTED]" in dump or "[hidden]" in dump
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_data_layer_events_not_mislabeled(self):
        """dataLayer records must never contain an 'action' field."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(CLICK_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            res = await service.click(sid, "Logout")  # triggers real dataLayer push
            assert res["clicked"] is True
            await asyncio.sleep(0.8)
            events = await service.get_events(sid)
            dls = [e for e in events["events"] if e["type"] == "dataLayer"]
            assert dls, "no dataLayer records"
            assert all("action" not in e["data"] for e in dls)
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_ingest_beacon_record_and_dedup(self):
        """The beacon fast-path endpoint ingests a record once and dedupes a
        repeated beacon."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            record = {
                "seq": 99,
                "type": "interaction",
                "timestamp": "2026-08-12T10:00:00.000Z",
                "url": url,
                "data": {"action": "click", "description": 'User clicked "Sign in"', "element": {"text": "Sign in"}},
            }
            r1 = await service.ingest(sid, record)
            assert r1["ok"] is True
            r2 = await service.ingest(sid, record)  # duplicate beacon
            assert r2["ok"] is True
            assert "Duplicate" in r2["message"]
            events = await service.get_events(sid)
            clicks = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "click"
                and e["data"].get("description") == 'User clicked "Sign in"'
            ]
            assert len(clicks) == 1, f"expected 1 deduped record, got {len(clicks)}"
            # Session id validation.
            bad = await service.ingest("nope", record)
            assert bad["ok"] is False
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_records_carry_page_title(self):
        """Every record carries the page title captured at event time."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            await session.page.click("#login-btn")
            await asyncio.sleep(0.8)
            events = await service.get_events(sid)
            recs = events["events"]
            assert recs, "no events"
            # dataLayer records AND interactions carry the fixture title.
            assert any(r["page_title"] == "DL Fixture" for r in recs)
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_pointer_interactions_captured(self):
        """pointerdown on a non-interactive element produces an interaction
        record — clicks on interactive elements stay click records."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            # Click a neutral area (the tall spacer div) — the click handler
            # skips non-interactive targets; the pointer handler records it.
            await session.page.mouse.click(400, 500)
            await asyncio.sleep(0.8)
            events = await service.get_events(sid)
            actions = [e["data"].get("action") for e in events["events"] if e["type"] == "interaction"]
            assert "pointer" in actions, f"pointer action missing: {actions}"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_view_source_returns_live_html(self):
        """The source endpoint returns the current page's serialized DOM."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            src = await service.view_source(sid)
            assert src is not None
            assert "DL Fixture" in src["html"]
            assert src["html_size"] > 0
            assert src["url"].startswith("http://127.0.0.1")
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_clear_keeps_capturing_after_scroll_state_reset(self):
        """Clear resets the page's scroll-state so a fresh scroll after clear
        still produces milestone records."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            await session.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.0)
            events = await service.get_events(sid)
            assert any(
                e["type"] == "interaction" and e["data"].get("action") == "scroll"
                for e in events["events"]
            ), "expected scroll before clear"
            await service.clear(sid)
            # Scroll back to top then deep again — the milestone state was
            # reset by clear, so a NEW deep-scroll record should appear.
            await session.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            await session.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.0)
            events2 = await service.get_events(sid)
            scrolls = [
                e for e in events2["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "scroll"
            ]
            assert scrolls, "no scroll records after clear"
            assert any(s["data"].get("scroll_percent", 0) >= 90 for s in scrolls), \
                f"no deep scroll after clear: {[s['data'].get('scroll_percent') for s in scrolls]}"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    # ------------------------------------------------------------------
    # Regression tests for the "manual interaction capture" bug report.
    # These prove a REAL human click/scroll (mouse events, not page.click /
    # window.scrollTo which synthesize trusted events differently) produces
    # backend interaction records, even without any dataLayer push.
    # ------------------------------------------------------------------

    def test_manual_dom_click_captured(self):
        """(A) A raw DOM click (el.click()) — what a real pointer produces at
        the element level — must create an interaction/click record."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            await session.page.evaluate("document.getElementById('read-more').click()")
            await asyncio.sleep(1.2)
            events = await service.get_events(sid)
            clicks = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "click"
                and "Read More" in str(e["data"].get("element") or {})
            ]
            assert clicks, f"manual DOM click not captured: {[e['data'] for e in events['events'] if e['type']=='interaction']}"
            assert clicks[0]["data"].get("description") == 'User clicked "Read More"'
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_manual_nested_span_click_resolves_to_epaper(self):
        """(B) Clicking the SPAN inside the Epaper anchor resolves to the
        anchor's label — 'User clicked "Epaper"', never 'SPAN'/'DIV'."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": PAGE1_HTML, "/page2": PAGE2_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=600)
            sid = session.id
            # Real pointer click on the nested span (Playwright clicks the
            # element center -> real mousedown/mouseup/click sequence).
            await session.page.click("#nested-link .label")
            await asyncio.sleep(1.2)
            events = await service.get_events(sid)
            clicks = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "click"
            ]
            epaper = next(
                (c for c in clicks if "Epaper" in ((c["data"].get("element") or {}).get("text") or "")),
                None,
            )
            assert epaper is not None, f"Epaper click missing: {[c['data'] for c in clicks]}"
            assert epaper["data"]["description"] == 'User clicked "Epaper"'
            assert (epaper["data"]["element"] or {}).get("tag") == "a"
            # Never a bare SPAN/DIV label.
            assert "SPAN" not in (epaper["data"]["description"] or "")
            assert "DIV" not in (epaper["data"]["description"] or "")
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_manual_wheel_scroll_captured(self):
        """(C) A real mouse-wheel scroll (page.mouse.wheel) must produce
        interaction/scroll records — NOT rely on the site's GTM scrollDepth."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            page = session.page
            await page.mouse.move(400, 300)
            for _ in range(15):
                await page.mouse.wheel(0, 400)
                await asyncio.sleep(0.12)
            await asyncio.sleep(1.5)
            events = await service.get_events(sid)
            scrolls = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "scroll"
            ]
            assert scrolls, "wheel scroll produced no interaction records"
            assert any(s["data"].get("scroll_percent", 0) >= 50 for s in scrolls), \
                f"no meaningful scroll: {[s['data'].get('scroll_percent') for s in scrolls]}"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_scroll_captured_without_gtm(self):
        """(D) Scroll interaction appears even when the page has NO dataLayer /
        GTM at all."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(NO_DL_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            page = session.page
            # NO_DL_HTML has no tall body; make it scrollable.
            await page.evaluate("document.body.style.height = '3000px'")
            await page.mouse.move(400, 300)
            for _ in range(12):
                await page.mouse.wheel(0, 400)
                await asyncio.sleep(0.12)
            await asyncio.sleep(1.5)
            events = await service.get_events(sid)
            dl = [e for e in events["events"] if e["type"] == "dataLayer"]
            scrolls = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "scroll"
            ]
            assert dl == [], f"page should have no dataLayer: {[e['data'] for e in dl]}"
            assert scrolls, "scroll interaction missing on GTM-less page"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_gtm_scroll_and_observer_scroll_both_present(self):
        """(E) When the site fires gtm.scrollDepth AND our observer scrolls,
        BOTH the dataLayer event and the interaction record must exist."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(SCROLL_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            page = session.page
            await page.mouse.move(400, 300)
            for _ in range(15):
                await page.mouse.wheel(0, 400)
                await asyncio.sleep(0.12)
            await asyncio.sleep(1.5)
            events = await service.get_events(sid)
            dl_events = [e["data"].get("event") for e in events["events"] if e["type"] == "dataLayer"]
            scrolls = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "scroll"
            ]
            assert "gtm.scrollDepth" in dl_events, f"site scrollDepth missing: {dl_events}"
            assert scrolls, "observer scroll missing alongside site scrollDepth"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_epaper_cross_origin_click_plus_navigation(self):
        """(F) A click that navigates cross-origin keeps BOTH the interaction
        click and the navigation record, persisted before teardown."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": PAGE1_HTML, "/page2": PAGE2_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=600)
            sid = session.id
            await session.page.click("#nested-link .label")  # Epaper anchor -> /page2
            await asyncio.sleep(2.0)
            events = await service.get_events(sid)
            clicks = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "click"
                and "Epaper" in str(e["data"].get("element") or {})
            ]
            navs = [e for e in events["events"] if e["type"] == "navigation"]
            assert clicks, f"Epaper click lost across navigation: {[e['data'] for e in events['events']]}"
            assert navs, "navigation record missing"
            assert navs[0]["data"]["from_url"].endswith("/")
            assert navs[0]["data"]["to_url"].endswith("/page2")
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_popup_click_and_scroll_captured(self):
        """(G+H) Interactions inside a popup (new tab) feed the same session."""
        playwright = pytest.importorskip("playwright")
        server = _MultiPathServer({"/": POPUP_TRIGGER_HTML, "/popup": POPUP_HTML})
        service = DataLayerService()

        async def run():
            session = await service.start(server.url("/"), navigation_pause_ms=500)
            sid = session.id
            page = session.page
            # Click the button that opens a popup.
            await page.click("#open-popup")
            await asyncio.sleep(2.5)
            # Find the popup.
            popup = None
            for p in session.context.pages:
                if p is not page:
                    popup = p
                    break
            assert popup is not None, "popup did not open"
            # Click inside the popup (nested span -> Login button).
            await popup.click("#popup-login .label")
            await asyncio.sleep(1.2)
            # Scroll inside the popup.
            await popup.mouse.move(200, 200)
            for _ in range(10):
                await popup.mouse.wheel(0, 400)
                await asyncio.sleep(0.12)
            await asyncio.sleep(2.0)
            events = await service.get_events(sid)
            popup_events = [e for e in events["events"] if "/popup" in e["url"]]
            popup_clicks = [
                e for e in popup_events
                if e["type"] == "interaction" and e["data"].get("action") == "click"
            ]
            popup_scrolls = [
                e for e in popup_events
                if e["type"] == "interaction" and e["data"].get("action") == "scroll"
            ]
            assert popup_clicks, f"popup click missing: {[e['data'] for e in popup_events]}"
            assert any("Login" in (c["data"].get("description") or "") for c in popup_clicks), \
                f"popup click label wrong: {[c['data'].get('description') for c in popup_clicks]}"
            assert popup_scrolls, "popup scroll missing"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True

    def test_duplicate_transport_delivery_single_record(self):
        """(I) The same interaction reaching the backend via localStorage sweep
        AND the console bridge must be deduplicated to ONE record."""
        playwright = pytest.importorskip("playwright")
        url, server = _serve_fixture(FIXTURE_HTML)
        service = DataLayerService()

        async def run():
            session = await service.start(url, navigation_pause_ms=500)
            sid = session.id
            await session.page.click("#read-more")
            await asyncio.sleep(1.2)
            # Force a double collect (simulates sweep + console bridge both
            # delivering the same record).
            await service.get_events(sid)
            await service.get_events(sid)
            await asyncio.sleep(1.0)
            events = await service.get_events(sid)
            read_more = [
                e for e in events["events"]
                if e["type"] == "interaction" and e["data"].get("action") == "click"
                and "Read More" in str(e["data"].get("element") or {})
            ]
            assert len(read_more) == 1, \
                f"expected 1 deduped Read More click, got {len(read_more)}: {[r['data'] for r in read_more]}"
            await service.close(sid)
            return True

        try:
            ok = asyncio.run(run())
        finally:
            server.shutdown()
        assert ok is True
