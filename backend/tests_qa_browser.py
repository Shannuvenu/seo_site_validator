"""Browser-integration test for the Prajavani DataLayer QA Monitor.

Loads the built dist-qa bundle into a real Chromium page (via the existing
DataLayerService Playwright infra), injects a test dataLayer, fires real
events, clicks a button, and verifies the floating QA panel appears and rows
are validated (PASS/FAIL/NO EVENT + sequence).
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ["SEO_ALLOW_LOCALHOST_DEBUG"] = "1"
sys.path.insert(0, ".")

from app.services.data_layer import DataLayerService  # noqa: E402

BUNDLE_PATH = os.path.abspath(os.path.join("..", "frontend", "dist-qa", "prajavani-datalayer-qa-monitor.js"))

UUID = "3b241101-e2bb-4255-8caf-4136c566a962"

FIXTURE = """<!DOCTYPE html>
<html><head><title>QA Monitor Test</title></head>
<body>
<script>
  window.dataLayer = window.dataLayer || [];
</script>
<button id="paywall-cta">Subscribe Now</button>
<div id="plain">Just text</div>
</body></html>
"""


async def main() -> None:
    import threading

    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = FIXTURE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with open(BUNDLE_PATH, "r", encoding="utf-8") as f:
        bundle = f.read()

    service = DataLayerService()
    session = await service.start(f"http://127.0.0.1:{port}/", navigation_pause_ms=800)
    sid = session.id
    page = session.page
    await asyncio.sleep(1)

    # Inject the QA bundle + boot it.
    await page.evaluate(bundle)
    await page.evaluate("window.initQaMonitor && window.initQaMonitor({ autoStart: true })")
    await asyncio.sleep(0.5)

    panel_exists = await page.evaluate("() => !!document.getElementById('pv-datalayer-qa-monitor')")
    print(f"[1] floating panel present: {panel_exists}")

    # Push a valid event + a sequence trigger (valid page_view per spec).
    await page.evaluate(
        """() => {
            window.dataLayer.push({
                event: 'paywall_subscribe_button_click',
                auth_status: 'non_logged_in',
                uuid: 'NA',
                page_url: location.href
            });
            window.dataLayer.push({
                event: 'page_view',
                article_id: '3933157',
                article_type: 'syndicated',
                auth_status: 'non_logged_in',
                author_id: '1',
                author_name: 'DH Web Desk',
                comment_number: 0,
                content_id: '""" + UUID + """',
                content_title: 'Test',
                created_date: '2026-01-15T10:30:00+05:30',
                creator_name: 'DH Web Desk',
                last_updated_date: '2026-01-15T10:30:00+05:30',
                page_type: 'article_page',
                published_date: '2026-01-15T10:30:00+05:30',
                section_name: 'Karnataka',
                story_tags: 'test',
                story_words: 10,
                uuid: 'NA',
                premium_article: 'No',
                access_level_value: 200
            });
        }"""
    )
    await asyncio.sleep(0.3)
    # The sequence trigger expects user_properties_update — fire it.
    await page.evaluate(
        """() => {
            window.dataLayer.push({
                event: 'user_properties_update',
                auth_status: 'non_logged_in',
                subscription_status: 'NA',
                uuid: 'NA',
                plan_name: 'NA',
                plan_price: 'NA'
            });
        }"""
    )
    await asyncio.sleep(0.5)

    # Click the paywall CTA -> NO EVENT or FIRED depending on timing.
    await page.click("#paywall-cta")
    await asyncio.sleep(1.0)

    # Click the plain div -> expect NO EVENT.
    await page.click("#plain")
    await asyncio.sleep(0.5)

    # Read back the monitor state from the page.
    state = await page.evaluate(
        """() => {
            const rows = window.__qaMonitor ? window.__qaMonitor.rows : [];
            return {
                total: rows.length,
                events: rows.filter(r => r.kind === 'event').map(r => ({
                    event: r.eventName, check: r.check, status: r.status
                })),
                clicks: rows.filter(r => r.kind === 'click').map(r => ({
                    status: r.status, check: r.check, el: r.element && r.element.text
                })),
                sequences: rows.filter(r => r.kind === 'sequence').map(r => ({
                    check: r.check, event: r.eventName, note: r.sequenceNote
                }))
            };
        }"""
    )
    print(f"[2] total rows: {state['total']}")
    print(f"    events: {state['events']}")
    print(f"    clicks: {state['clicks']}")
    print(f"    sequences: {state['sequences']}")

    # Verify validation happened.
    ok_paywall = any(e["event"] == "paywall_subscribe_button_click" and e["check"] == "PASS" for e in state["events"])
    ok_pageview = any(e["event"] == "page_view" and e["check"] == "PASS" for e in state["events"])
    ok_noevent = any(c["status"] == "NO EVENT" for c in state["clicks"])
    ok_seq = any(s["check"] == "PASS" and "page_view" in s["event"] for s in state["sequences"])
    ok_panel = bool(panel_exists)
    print(
        f"\nVERDICT panel={ok_panel} paywall_click_PASS={ok_paywall} "
        f"page_view_PASS={ok_pageview} seq_PASS={ok_seq} no_event_detected={ok_noevent}"
    )

    # Re-init (simulate re-paste): the new monitor restores prior rows from
    # sessionStorage + adds a system row; it must NOT duplicate event rows.
    await page.evaluate("window.initQaMonitor && window.initQaMonitor({ autoStart: true })")
    await asyncio.sleep(0.5)
    after = await page.evaluate(
        """() => {
            const rows = window.__qaMonitor ? window.__qaMonitor.rows : [];
            return {
                total: rows.length,
                eventRows: rows.filter(r => r.kind === 'event' && r.eventName === 'page_view').length,
                restoreInfo: rows.filter(r => r.kind === 'system' && /Restored/.test(r.sequenceNote || '')).length
            };
        }"""
    )
    print(f"[3] re-init: event rows={after['eventRows']} restored-note={after['restoreInfo']}")
    ok_reinit = after["eventRows"] == 1  # exactly one page_view event row, no dup

    await service.close(sid)
    server.shutdown()

    all_ok = ok_panel and ok_paywall and ok_pageview and ok_seq and ok_noevent and ok_reinit
    print(f"\nOVERALL: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
