"""EXACT user-specified manual test:

URL: https://www.deccanherald.com/india/jharkhand/jharkhand-jlkms-devendra-mahto-writes-to-civil-surgeon-seeking-permission-to-return-to-protest-site-4109171

1. START CAPTURE
2. wait for load
3. manually scroll once
4. wait
5. manually scroll again
6. wait
7. manually click the real Epaper link
8. wait
9. inspect backend session

Expected:
  USER INTERACTION User scrolled to XX%
  USER INTERACTION User scrolled to YY%
  USER INTERACTION User clicked "Epaper"
  NAVIGATION DH article -> Epaper URL
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.services.data_layer import DataLayerService  # noqa: E402

TARGET = (
    "https://www.deccanherald.com/india/jharkhand/jharkhand-jlkms-devendra-mahto-"
    "writes-to-civil-surgeon-seeking-permission-to-return-to-protest-site-4109171"
)


async def main() -> None:
    service = DataLayerService()
    session = await service.start(TARGET, navigation_pause_ms=4500)
    sid = session.id
    page = session.page
    print(f"SESSION {sid} opened {session.current_url[:80]}")
    await asyncio.sleep(4)

    # 3. Manual scroll #1 (real mouse wheel)
    print("\n[3] manual scroll #1 (mouse wheel)")
    await page.mouse.move(683, 384)
    for _ in range(12):
        await page.mouse.wheel(0, 400)
        await asyncio.sleep(0.15)
    await asyncio.sleep(2.0)

    # 5. Manual scroll #2
    print("[5] manual scroll #2 (mouse wheel)")
    for _ in range(12):
        await page.mouse.wheel(0, 400)
        await asyncio.sleep(0.15)
    await asyncio.sleep(2.0)

    # 7. Manual click on the real Epaper link (leaf SPAN -> real mouse click)
    print("[7] manual click on Epaper")
    pos = await page.evaluate(
        """() => {
            const all = Array.from(document.querySelectorAll('*'));
            const el = all.find(n => {
                const s = (n.innerText || n.textContent || '').replace(/\\s+/g, ' ').trim();
                return s === 'Epaper' && n.children.length === 0;
            });
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2, text: (el.innerText||el.textContent||'').trim() };
        }"""
    )
    if pos:
        print(f"  found Epaper leaf at ({pos['x']:.0f},{pos['y']:.0f}) text={pos['text']!r}")
        await page.mouse.click(pos["x"], pos["y"])
    else:
        print("  Epaper leaf not found; trying text locator")
        try:
            await page.get_by_text("Epaper", exact=True).first.click(timeout=6000)
        except Exception as exc:  # noqa: BLE001
            print(f"  locator click failed: {exc}")
    await asyncio.sleep(4.0)

    # 9. Inspect backend session
    print("\n[9] backend session inspection")
    st = await service.get_events(sid)
    scrolls = [
        e for e in st["events"]
        if e["type"] == "interaction" and (e["data"] or {}).get("action") == "scroll"
    ]
    epaper_clicks = [
        e for e in st["events"]
        if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
        and "Epaper" in str((e["data"] or {}).get("element") or {})
    ]
    navs = [
        e for e in st["events"]
        if e["type"] == "navigation" and "epaper" in str((e["data"] or {}).get("to_url") or "").lower()
    ]
    print(f"total events: {st['event_count']}")
    print(f"scroll interactions: {len(scrolls)}")
    for s in scrolls:
        print(f"  {s['data'].get('description')} @ {s['url'][:60]}")
    print(f"Epaper clicks: {len(epaper_clicks)}")
    for c in epaper_clicks:
        print(f"  {c['data'].get('description')} tag={c['data'].get('element',{}).get('tag')} text={c['data'].get('element',{}).get('text')!r}")
    print(f"Epaper navigations: {len(navs)}")
    for n in navs:
        print(f"  {str(n['data'].get('from_url'))[:55]} -> {str(n['data'].get('to_url'))[:55]} new_tab={n['data'].get('new_tab')}")

    # Verdicts
    ok_scroll = len(scrolls) >= 2
    ok_epaper_click = len(epaper_clicks) >= 1 and epaper_clicks[0]["data"].get("description") == 'User clicked "Epaper"'
    ok_nav = len(navs) >= 1
    print(f"\nVERDICT scrolls: {'PASS' if ok_scroll else 'FAIL'} ({len(scrolls)})")
    print(f"VERDICT epaper click: {'PASS' if ok_epaper_click else 'FAIL'} ({epaper_clicks[0]['data'].get('description') if epaper_clicks else 'none'})")
    print(f"VERDICT navigation: {'PASS' if ok_nav else 'FAIL'} ({len(navs)})")
    await service.close(sid)
    return 0 if (ok_scroll and ok_epaper_click and ok_nav) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
