"""API-path test: start -> app-driven scroll/click -> poll (frontend path)."""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, ".")

TARGET = "https://www.deccanherald.com/"
BASE = "http://127.0.0.1:8000/api"


def _post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _get(path):
    with urllib.request.urlopen(BASE + path) as r:
        return json.loads(r.read())


async def main() -> None:
    start = _post("/data-layer/start", {"url": TARGET, "navigation_pause_ms": 4000})
    sid = start["session_id"]
    print(f"START via API: session={sid}")

    # Wait for initial dataLayer events.
    dl_seen = False
    for _ in range(10):
        st = _get(f"/data-layer/events?session_id={sid}")
        if any(e["type"] == "dataLayer" for e in st["events"]):
            dl_seen = True
            break
        await asyncio.sleep(1.0)
    print(f"initial dataLayer events: {dl_seen}")

    # Trigger a scroll via the app's own driver? The API has no scroll endpoint,
    # so scrolls come from the controlled browser. Use the click endpoint for a
    # real element, which drives the same browser the observer instruments.
    res = _post("/data-layer/click", {"session_id": sid, "text": "Epaper"})
    print(f"click Epaper: {res['message']}")

    # Poll like the frontend.
    epaper_seen = nav_seen = False
    for i in range(20):
        await asyncio.sleep(1.5)
        st = _get(f"/data-layer/events?session_id={sid}")
        clicks = [
            e for e in st["events"]
            if e["type"] == "interaction" and (e["data"] or {}).get("action") == "click"
            and "Epaper" in str((e["data"] or {}).get("element") or {})
        ]
        navs = [
            e for e in st["events"]
            if e["type"] == "navigation" and "epaper" in str((e["data"] or {}).get("to_url") or "").lower()
        ]
        epaper_seen = bool(clicks)
        nav_seen = bool(navs)
        print(f"  poll {i}: {st['event_count']} events epaper_click={epaper_seen} epaper_nav={nav_seen}")
        if epaper_seen and nav_seen:
            break

    # Dump + export + clear via API.
    dump = _get(f"/data-layer/events?session_id={sid}")
    export = _post("/data-layer/export", {"session_id": sid})
    clear = _post("/data-layer/clear", {"session_id": sid})
    close = _post("/data-layer/close", {"session_id": sid})
    print(f"\nDUMP: {dump['event_count']} events")
    print(f"EXPORT: {export['event_count']} events")
    print(f"CLEAR: {clear['message']}")
    print(f"CLOSE: {close['message']}")
    print(f"\nVERDICT epaper_click={epaper_seen} epaper_nav={nav_seen}")


if __name__ == "__main__":
    asyncio.run(main())
