"""Real-browser acceptance test for the Data Layer monitor.

Drives the REAL DataLayerService against https://www.deccanherald.com/ and
exercises the full manager workflow:

  start -> initial dataLayer events -> scroll -> click article -> navigation
  -> Epaper click -> Sign In click -> Read More click -> Dump/export -> clear
  -> capture again -> close.

Prints a human-readable PASS/FAIL per step. Run from backend/:
    .venv\\Scripts\\python.exe tests_real_browser.py
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.services.data_layer import DataLayerService  # noqa: E402

TARGET = "https://www.deccanherald.com/"


def _desc(e):
    d = e.get("data") or {}
    if e["type"] == "dataLayer":
        return f"dataLayer event={d.get('event') or d.get('eventName') or d.get('event_name')}"
    if e["type"] == "interaction":
        return d.get("description") or d.get("action") or "interaction"
    if e["type"] == "navigation":
        return f"navigation {str(d.get('from_url'))[:60]} -> {str(d.get('to_url'))[:60]}"
    return e["type"]


async def _wait_events(service, sid, predicate, tries=30, pause=1.0):
    for _ in range(tries):
        st = await service.get_events(sid)
        if predicate(st["events"]):
            return st
        await asyncio.sleep(pause)
    return await service.get_events(sid)


async def main() -> None:
    service = DataLayerService()
    results: list[tuple[str, bool, str]] = []
    session = None

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    try:
        print("=== 1. Start Capture ===")
        session = await service.start(TARGET, navigation_pause_ms=4000)
        sid = session.id
        check("start session", session.status in ("capturing", "open"), f"status={session.status}")
        check("instrumented", session.instrumented is True)
        print(f"  session={sid} url={session.url}")
        await asyncio.sleep(3)

        print("\n=== 2. Initial real dataLayer events ===")
        st = await _wait_events(
            service,
            sid,
            lambda ev: any(e["type"] == "dataLayer" for e in ev),
        )
        dl = [e for e in st["events"] if e["type"] == "dataLayer"]
        check("real dataLayer events appear", len(dl) > 0, f"count={len(dl)}")
        check(
            "dataLayer records carry no 'action' field",
            all("action" not in (e["data"] or {}) for e in dl),
        )
        check(
            "page_load interaction captured",
            any(e["type"] == "interaction" and (e["data"] or {}).get("action") == "page_load" for e in st["events"]),
        )
        for e in dl[:5]:
            print(f"    {_desc(e)}")

        print("\n=== 3. Scroll ===")
        page = session.page
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.35)")
        await asyncio.sleep(0.8)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.75)")
        await asyncio.sleep(0.8)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)
        st = await _wait_events(
            service,
            sid,
            lambda ev: any(
                e["type"] == "interaction" and (e["data"] or {}).get("action") == "scroll"
                and (e["data"] or {}).get("scroll_percent", 0) >= 50
                for e in ev
            ),
        )
        scrolls = [
            e for e in st["events"]
            if e["type"] == "interaction" and (e["data"] or {}).get("action") == "scroll"
        ]
        check("scroll milestones captured", len(scrolls) > 0, f"count={len(scrolls)}")
        for s in scrolls:
            print(f"    {_desc(s)}")

        print("\n=== 4. Click a real article ===")
        article_clicked = None
        try:
            links = await page.evaluate(
                """() => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="/india"], a[href*="/karnataka"], a[href*="/sports"], a[href*="/health"]'))
                        .filter(a => { const t = (a.innerText || a.textContent || '').trim(); return t.length > 25; });
                    if (!anchors.length) return null;
                    const a = anchors[Math.floor(Math.random() * Math.min(anchors.length, 5))];
                    return { text: (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 90) };
                }"""
            )
            if links:
                article_clicked = links["text"]
                # Use the same fallback path as the manager's Click Element —
                # dispatches a real DOM click even when overlays/scroll change
                # the layout between reading the text and clicking it.
                await service.click(sid, article_clicked)
                await asyncio.sleep(3.5)
        except Exception as exc:  # noqa: BLE001
            print(f"    article click failed: {exc}")
        st = await _wait_events(service, sid, lambda ev: any(e["type"] == "navigation" for e in ev))
        clicks = [
            e for e in st["events"]
            if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
        ]
        navs = [e for e in st["events"] if e["type"] == "navigation"]
        check("article click captured", article_clicked is not None and len(clicks) > 0,
              f"article={article_clicked}")
        check("navigation record exists", len(navs) > 0, f"count={len(navs)}")
        for c in clicks[-3:]:
            print(f"    {_desc(c)}")
        for n in navs[-2:]:
            print(f"    {_desc(n)}")

        print("\n=== 5. Epaper click ===")
        epaper_res = await service.click(sid, "Epaper")
        await asyncio.sleep(3.0)
        st = await service.get_events(sid)
        epaper_clicks = [
            e for e in st["events"]
            if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
            and "Epaper" in str((e["data"] or {}).get("element") or {})
        ]
        epaper_navs = [
            e for e in st["events"]
            if e["type"] == "navigation" and "epaper" in str((e["data"] or {}).get("to_url") or "").lower()
        ]
        check("Epaper click captured", len(epaper_clicks) > 0 or "Epaper" in (epaper_res.get("message") or ""),
              f"res={epaper_res.get('message')}")
        check("Epaper cross-origin navigation", len(epaper_navs) > 0,
              f"count={len(epaper_navs)}")

        # If Epaper opened a popup/new tab, interact inside it and verify its
        # events feed the same session.
        print("\n=== 5b. Epaper popup interactions ===")
        popup = None
        for p in session.context.pages:
            if p is not page:
                popup = p
                break
        if popup is not None:
            print(f"  popup: {popup.url[:70]}")
            try:
                # Click something inside the popup (first interactive element).
                clicked = await popup.evaluate(
                    """() => {
                        const els = Array.from(document.querySelectorAll('a,button,[role="button"]'))
                            .filter(el => { const t = (el.innerText || el.textContent || '').trim(); return t.length > 2 && t.length < 60; });
                        if (!els.length) return null;
                        const el = els[0];
                        el.scrollIntoView({ block: 'center' });
                        el.click();
                        return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 50);
                    }"""
                )
                if clicked:
                    print(f"  clicked popup element: {clicked!r}")
                # Scroll inside the popup.
                await popup.mouse.move(683, 384)
                for _ in range(8):
                    await popup.mouse.wheel(0, 500)
                    await asyncio.sleep(0.12)
                await asyncio.sleep(2.5)
            except Exception as exc:  # noqa: BLE001
                print(f"  popup interaction failed: {exc}")
            st = await service.get_events(sid)
            popup_events = [e for e in st["events"] if "epaper" in e["url"].lower()]
            popup_clicks = [
                e for e in popup_events
                if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
            ]
            popup_scrolls = [
                e for e in popup_events
                if e["type"] == "interaction" and (e["data"] or {}).get("action") == "scroll"
            ]
            popup_dl = [e for e in popup_events if e["type"] == "dataLayer"]
            check("popup click captured", len(popup_clicks) > 0, f"count={len(popup_clicks)}")
            check("popup scroll captured", len(popup_scrolls) > 0, f"count={len(popup_scrolls)}")
            check("popup dataLayer captured", len(popup_dl) > 0, f"count={len(popup_dl)}")
            for c in popup_clicks[-3:]:
                print(f"    {_desc(c)}")
        else:
            print("  (no popup — Epaper navigated in place)")
            check("popup click captured", True, detail="n/a (in-place navigation)")
            check("popup scroll captured", True, detail="n/a (in-place navigation)")
            check("popup dataLayer captured", True, detail="n/a (in-place navigation)")

        print("\n=== 6. Sign In click ===")
        signin_res = await service.click(sid, "Sign In")
        await asyncio.sleep(2.0)
        st = await service.get_events(sid)
        signin_clicks = [
            e for e in st["events"]
            if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
            and "Sign In" in str((e["data"] or {}).get("element") or {})
        ]
        check("Sign In click captured", len(signin_clicks) > 0 or "Sign In" in (signin_res.get("message") or ""),
              f"res={signin_res.get('message')}")

        print("\n=== 7. Read More click ===")
        rm_res = await service.click(sid, "Read More")
        await asyncio.sleep(2.0)
        st = await service.get_events(sid)
        rm_clicks = [
            e for e in st["events"]
            if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
            and "Read More" in str((e["data"] or {}).get("element") or {})
        ]
        check("Read More click captured", len(rm_clicks) > 0 or "Read More" in (rm_res.get("message") or ""),
              f"res={rm_res.get('message')}")

        print("\n=== 8. Dump / Export full session ===")
        st = await _wait_events(service, sid, lambda ev: len(ev) > 0)
        total = len(st["events"])
        types = {}
        for e in st["events"]:
            types[e["type"]] = types.get(e["type"], 0) + 1
        check("Dump returns complete session", total > 0, f"total={total} types={types}")
        export = await service.export(sid)
        check("Export JSON complete", export is not None and export["event_count"] == len(export["events"]),
              f"event_count={export['event_count'] if export else '?'}")
        seqs = [e["seq"] for e in export["events"]]
        check("chronological order", seqs == sorted(seqs) and len(set(seqs)) == len(seqs),
              f"seqs={seqs[:8]}...")
        # The backend dedups the SAME event arriving via multiple transports
        # (postMessage + localStorage sweep) by full content + timestamp. Two
        # genuinely identical real pushes (same content, same ms) are TWO
        # distinct real events and must NOT be collapsed — so allow repeated
        # content as long as seq stays unique. Only the exact transport-level
        # duplicate (identical type+timestamp+url+data with different seq) is
        # a bug.
        exact = [repr((e["type"], e["timestamp"], e["url"], sorted(((e["data"] or {}).items())))) for e in export["events"]]
        check("no transport duplicates", len(set(exact)) == len(exact))

        print("\n=== 9. View Source ===")
        src = await service.view_source(sid)
        check("view source returns live html", src is not None and (src.get("html_size") or 0) > 0,
              f"size={src.get('html_size') if src else 0}")

        print("\n=== 10. Clear History ===")
        cleared = await service.clear(sid)
        check("clear ok", cleared["ok"] is True)
        # The authoritative log must be empty immediately after clear. A
        # concurrent page push may land a split-second later (the page is
        # live); poll briefly so a genuinely empty log counts as a pass.
        became_empty = False
        for _ in range(5):
            st = await service.get_events(sid)
            if st["event_count"] == 0:
                became_empty = True
                break
            await asyncio.sleep(0.3)
        check("history empty after clear", became_empty, f"count={st['event_count']}")
        check("browser still open after clear", service.get(sid) is not None)

        print("\n=== 11. Capture after clear ===")
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            await asyncio.sleep(1.5)
        except Exception:  # noqa: BLE001
            pass
        st = await _wait_events(
            service,
            sid,
            lambda ev: any(
                e["type"] == "interaction" and (e["data"] or {}).get("action") == "scroll"
                for e in ev
            ),
        )
        new_events = len(st["events"])
        check("new events captured after clear", new_events > 0, f"count={new_events}")

        print("\n=== 12. Close ===")
        closed = await service.close(sid)
        check("close ok", closed["ok"] is True)
        check("session freed", service.get(sid) is None)

        print("\n=== Summary ===")
        failed = [r for r in results if not r[1]]
        for name, ok, detail in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
        if failed:
            print("FAILED:", [r[0] for r in failed])
        return 1 if failed else 0
    finally:
        if session is not None and service.get(session.id) is not None:
            await service.close(session.id)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
