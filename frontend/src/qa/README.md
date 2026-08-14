# Prajavani DataLayer QA Monitor

A browser-side QA tool that observes `window.dataLayer` on **prajavani.net** and
validates every event against the **Paywall Data Layer specification** (the Excel
source spec). It is a pure observer — it never manufactures analytics events and
never breaks the site's own `dataLayer.push`.

> This is **Part B** (QA monitor). The **Part A** production implementation (the
> website firing these events) lives in the site's own codebase. This monitor
> validates whatever the real site pushes.

---

## Quick start

### Option A — Paste into DevTools Console

1. Open `https://prajavani.net/` (or any Prajavani page).
2. Press `F12` → **Console**.
3. Open `frontend/dist-qa/prajavani-datalayer-qa-monitor.js`, copy its entire
   contents, and paste into the console. Press Enter.
4. A floating panel appears: **DataLayer QA Monitor — prajavani.net**.
5. Interact with the site (scroll, click Subscribe, open paywalls, log in/out…).
6. Watch events roll in with **PASS / FAIL / WARN / NO EVENT / SEQUENCE FAIL**.
7. Click **Payload** on any row for the full JSON + issues.
8. **Export CSV** / **Export JSON** when finished.

To tear down and remove the panel:

```js
destroyQaMonitor();
```

To re-init after a page that reassigned `window.dataLayer`:

```js
initQaMonitor();
```

Re-initializing is safe: the previous monitor is destroyed, listeners are
removed, the original `push` is restored, and event rows are never duplicated.

### Option B — Bookmarklet

1. Copy the contents of `frontend/dist-qa/bookmarklet.js`.
2. Create a new bookmark; paste the copied text as the URL.
3. On any Prajavani page, click the bookmark.

### Option C — Tampermonkey userscript

Install `frontend/dist-qa/prajavani-datalayer-qa-monitor.user.js` in
Tampermonkey. It auto-boots on every `prajavani.net` page (run-at
document-start, so the monitor hooks `dataLayer` before site scripts push).

---

## What it validates

All 28 spec variants:

`user_properties_update` (logged-in non-subscriber / logged-in subscriber /
non-logged-in), `sign_up`, `login` (with/without subscription), `logout`,
`paywall_impression` (logged-in / non-logged-in), `paywall_subscribe_button_click`,
`ad_lite_button_click`, `subscription_header_button_click`,
`subscription_plan_selection`, `plan_edit`, `proceed_to_pay_click`, `purchase`,
`payment_failed`, `retry_payment_click`, `renewal_cancellation`,
`plan_change_initiated`, `renewal_prompt_impression`, `accept_popup`,
`dismiss_popup`, and the Premium Article `page_view`.

Validation covers:

- **required** fields
- **exact** values (`event`, `page_type`, `auth_status`, `subscription_status`…)
- **enums** (`plan_name`, `plan_price`, `method`, `source`, `currency`,
  `user_type`, `access_level_value`, `premium_article`…)
- **types** (string / number / boolean)
- **UUID format** (with `"NA"` permitted where the spec allows)
- **date/time** format
- **dynamic URL** format
- **cross-field** rules — e.g. `plan_name` ↔ `plan_price`
  (`monthly` → 150, `1-year` → 1499, `2-year` → 2999; `plan_change_initiated`
  maps `yearly` → 1499 per the source spec)
- **sequence** rules — after `page_view` / `purchase` / `sign_up` / `login` /
  `logout`, a `user_properties_update` must arrive within the configurable
  window (default 2500 ms). Missing → **SEQUENCE FAIL**; late → **SEQUENCE FAIL**;
  on time → **PASS**.

Unknown events (no schema defined) are still displayed with **CHECK: —**
("event observed but no schema is currently defined").

### gtag support

Both `dataLayer.push({event, ...})` and gtag's Arguments objects
(`{0:"event", 1:"event_name", 2:{...}}`) are normalized for display without
corrupting the original dataLayer behavior. `fromGtag` is flagged on the row.

---

## The panel

| Column    | Meaning                                                              |
|-----------|----------------------------------------------------------------------|
| Time      | `HH:MM:SS` of the event/click                                       |
| Status    | `WAITING` / `FIRED` / `NO EVENT` / `SYSTEM`                          |
| Event     | Event name (+ spec variant, + sequence note)                         |
| Check     | `PASS` / `FAIL` / `WARN` / `SEQUENCE FAIL` / `—` (uncovered)         |
| Triggered by | The clicked DOM element (tag, id, class, text, href, role, aria)   |
| Payload   | "View" opens the full JSON + validation issues + Copy button         |

Toolbar: **Clear** (wipes current-session history), **Export CSV**, **Export
JSON**, **Minimize/Restore**, **search box**, **status filter**.

### Click → event matching

Every user click is recorded. If a `dataLayer` event fires within the
configurable window (default 1200 ms), the click is marked **FIRED** and the
event row gets the element as "Triggered by". If no event fires, the click is
marked **NO EVENT** — a QA failure candidate. Clicks on elements unlikely to
fire analytics can be treated as informational instead by setting
`markClickNoEventAsFailure: false` in `initQaMonitor({...})`.

---

## Persistence

QA history is stored in **sessionStorage** (`pv.datalayer.qa.log.v1`), so it:

- survives page reload and Back/Forward navigation,
- survives navigating away from prajavani.net and returning in the same tab,
- is restored on monitor start ("Restored N events…"),
- is cleared when the tab/session ends,
- is capped at 1000 rows (configurable).

The **Clear** button deletes the current-session history.

---

## SPA / Next.js / dataLayer reassignment

If the site replaces `window.dataLayer = []`, the monitor re-hooks the new array
within 250 ms. Re-running `initQaMonitor()` (or pasting the script again):

- removes the previous panel,
- destroys the previous monitor (removes its click listener, restores the
  original `push`),
- never stacks wrappers and never duplicates rows or sequence warnings.

---

## Building / testing

```bash
cd frontend
npm run build          # TypeScript build (tsc + vite)
npm run build:qa       # produces dist-qa/* bundles
npm test               # full vitest suite (QA + existing app tests)
```

The QA test files:

- `src/test/qaValidator.test.ts` — 44 validation-engine tests (cases 1–39 + gtag
  + uncovered + coverage).
- `src/test/qaMonitor.test.ts` — 15 monitor-behavior tests (cases 40–54:
  sequences, click matching, reassignment, re-init dedup, circular payloads,
  gtag display, persistence, CSV/JSON export).

A real-browser integration test drives the built bundle in Chromium:
`backend/tests_qa_browser.py` (from `backend/`, with Playwright installed).

---

## Source-spec inconsistencies (preserved, not "fixed")

1. **`plan_change_initiated`** uses `from_plan`/`to_plan` value **`yearly`**,
   while every other event uses **`1-year`**. The monitor preserves `yearly`
   for this event exactly (and maps it to price 1499 in the cross-check).
2. **`logout.subscription_status`** uses **`subscribed`** while
   `user_properties_update.subscription_status` uses **`subscriber`**. These are
   separate enums; both are enforced as written.
3. **`login` (With Subscription)** omits `paywall` from allowed `source`, while
   **`login` (Without Subscription)** includes it. Preserved; a `login` with
   `source=paywall` validates as the without-subscription variant.
4. **Non-Logged-In `user_properties_update`** has **no `account_created_date`**
   in the spec — it is not required by the monitor.
5. **`Newsletter_consent`** capitalization (vs `marketing_and_promotion_consent`)
   is preserved exactly as specified.
6. **`page_view`** has no `variant`/trigger in the spec beyond "Premium Article
   Pages"; the monitor validates the full Premium Article field set only for
   payloads that carry it, and does not flag generic `page_view` pushes that
   lack those fields.
