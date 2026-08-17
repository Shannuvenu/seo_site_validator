// ==UserScript==
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

  "use strict";
  var PrajavaniQA = (() => {
    var __defProp = Object.defineProperty;
    var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
    var __getOwnPropNames = Object.getOwnPropertyNames;
    var __hasOwnProp = Object.prototype.hasOwnProperty;
    var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
    var __export = (target, all) => {
      for (var name in all)
        __defProp(target, name, { get: all[name], enumerable: true });
    };
    var __copyProps = (to, from, except, desc) => {
      if (from && typeof from === "object" || typeof from === "function") {
        for (let key of __getOwnPropNames(from))
          if (!__hasOwnProp.call(to, key) && key !== except)
            __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
      }
      return to;
    };
    var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);
    var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);
  
    // src/qa/console-entry.ts
    var console_entry_exports = {};
    __export(console_entry_exports, {
      bootQaMonitor: () => bootQaMonitor
    });
  
    // src/qa/schemas.ts
    var UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    function isUuid(v) {
      return typeof v === "string" && UUID_RE.test(v.trim());
    }
    function isIsoDate(v) {
      if (typeof v !== "string") return false;
      const s2 = v.trim();
      if (!s2) return false;
      const d = new Date(s2);
      if (isNaN(d.getTime())) return false;
      return /^\d{4}-\d{2}-\d{2}/.test(s2);
    }
    function isNumber(v) {
      return typeof v === "number" && Number.isFinite(v);
    }
    function isBool(v) {
      return typeof v === "boolean";
    }
    function isUrl(v) {
      if (typeof v !== "string") return false;
      try {
        const u = new URL(v);
        return u.protocol === "http:" || u.protocol === "https:";
      } catch {
        return false;
      }
    }
    var PLAN_PRICE_MAP = {
      monthly: 150,
      "1-year": 1499,
      "2-year": 2999,
      // plan_change_initiated uses "yearly" per spec — 1499 like 1-year.
      yearly: 1499
    };
    function planPriceMismatch(planName, planPrice) {
      if (typeof planName !== "string" || typeof planPrice !== "number") return null;
      const expected = PLAN_PRICE_MAP[planName];
      if (expected === void 0) return null;
      if (expected !== planPrice) {
        return `"plan_price": does not match plan_name (expected ${expected}, got ${planPrice})`;
      }
      return null;
    }
    var s = (spec = {}) => {
      var _a;
      return {
        type: (_a = spec.type) != null ? _a : "string",
        ...spec
      };
    };
    var na = (spec = {}) => ({ ...spec, allowNA: true });
    var en = (values) => ({ enum: values });
    var AUTH_STATUS = ["logged_in", "non_logged_in"];
    var SSO_METHODS = ["email", "mobile no", "google_onetap", "google_icon"];
    var LOGIN_METHODS = [...SSO_METHODS, "sso_auto_login"];
    var SSO_SOURCES = ["header_button", "plan_selection", "comment", "ham_menu", "paywall"];
    var LOGIN_WITH_SUB_SOURCES = ["header_button", "comment", "ham_menu"];
    var LOGOUT_SOURCES = ["profile", "change_account"];
    var PLAN_NAMES = ["monthly", "1-year", "2-year"];
    var CURRENCIES = ["INR", "USD"];
    var uuidField = { type: "uuid", required: true };
    var naUuidField = na({ type: "uuid", required: true });
    var accountDateField = { type: "datetime", required: true };
    var boolField = { type: "boolean", required: true };
    var consentFields = {
      marketing_and_promotion_consent: boolField,
      // Preserve the exact capitalization from the source spec.
      Newsletter_consent: boolField
    };
    var EVENT_SCHEMAS = [
      /* ---------- page_view (Premium Article page spec) ---------- */
      {
        event: "page_view",
        variant: "Premium Article page_view",
        trigger: "Premium article page loads",
        fields: {
          event: { exact: "page_view", required: true },
          article_id: s({ required: true }),
          article_type: s({ required: true }),
          auth_status: { ...en([...AUTH_STATUS]), required: true },
          author_id: s({ required: true }),
          author_name: s({ required: true }),
          comment_number: { type: "number", required: true },
          content_id: uuidField,
          content_title: s({ required: true }),
          created_date: accountDateField,
          creator_name: s({ required: true }),
          last_updated_date: accountDateField,
          page_type: { exact: "article_page", required: true },
          published_date: accountDateField,
          section_name: s({ required: true }),
          story_tags: s({ required: true }),
          story_words: { type: "number", required: true },
          uuid: naUuidField,
          premium_article: en(["Yes", "No"]),
          access_level_value: en([100, 200])
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      /* ---------- user_properties_update variants ---------- */
      {
        event: "user_properties_update",
        variant: "Logged-In Non-Subscriber",
        trigger: "After page_view / purchase / sign_up / login / logout (logged-in, non-subscriber)",
        fields: {
          event: { exact: "user_properties_update", required: true },
          auth_status: { exact: "logged_in", required: true },
          subscription_status: { exact: "non_subscriber", required: true },
          uuid: uuidField,
          account_created_date: accountDateField,
          plan_name: { exact: "NA", required: true },
          plan_price: { exact: "NA", required: true }
        },
        sequenceTrigger: false
      },
      {
        event: "user_properties_update",
        variant: "Logged-In Subscriber",
        trigger: "After page_view / purchase / sign_up / login / logout (logged-in, subscriber)",
        fields: {
          event: { exact: "user_properties_update", required: true },
          auth_status: { exact: "logged_in", required: true },
          subscription_status: { exact: "subscriber", required: true },
          uuid: uuidField,
          account_created_date: accountDateField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999])
        },
        cross: (p) => {
          var _a;
          return (_a = planPriceMismatch(p.plan_name, p.plan_price)) != null ? _a : typeof p.plan_name === "string" && typeof p.plan_price === "number" ? planPriceMismatch(p.plan_name, p.plan_price) : null;
        }
      },
      {
        event: "user_properties_update",
        variant: "Non-Logged-In",
        trigger: "After page_view (non-logged-in)",
        fields: {
          event: { exact: "user_properties_update", required: true },
          auth_status: { exact: "non_logged_in", required: true },
          subscription_status: { exact: "NA", required: true },
          uuid: { exact: "NA", required: true },
          // Spec does NOT define account_created_date for this variant — no check.
          plan_name: { exact: "NA", required: true },
          plan_price: { exact: "NA", required: true }
        }
      },
      /* ---------- sign_up ---------- */
      {
        event: "sign_up",
        variant: "Sign Up",
        trigger: "SSO first-time account creation completes and redirects back",
        fields: {
          event: { exact: "sign_up", required: true },
          method: en(SSO_METHODS),
          source: en(SSO_SOURCES),
          uuid: uuidField,
          account_created_date: accountDateField,
          ...consentFields
        },
        sequenceTrigger: true
      },
      /* ---------- login (without subscription) ---------- */
      {
        event: "login",
        variant: "Login (Without Subscription)",
        trigger: "User logs in (no subscription)",
        fields: {
          event: { exact: "login", required: true },
          method: en(LOGIN_METHODS),
          source: en(SSO_SOURCES),
          uuid: uuidField,
          account_created_date: accountDateField,
          ...consentFields
        },
        sequenceTrigger: true
      },
      /* ---------- login (with subscription) ---------- */
      {
        event: "login",
        variant: "Login (With Subscription)",
        trigger: "User logs in (has subscription)",
        fields: {
          event: { exact: "login", required: true },
          method: en(LOGIN_METHODS),
          // Spec: header_button / comment / ham_menu only (no paywall).
          source: en(LOGIN_WITH_SUB_SOURCES),
          uuid: uuidField,
          account_created_date: accountDateField,
          ...consentFields
        },
        sequenceTrigger: true
      },
      /* ---------- logout ---------- */
      {
        event: "logout",
        variant: "Logout",
        trigger: "User logs out and is redirected back",
        fields: {
          event: { exact: "logout", required: true },
          source: en(LOGOUT_SOURCES),
          uuid: uuidField,
          subscription_status: en(["subscribed", "non_subscriber"])
        },
        sequenceTrigger: true
      },
      /* ---------- paywall_impression ---------- */
      {
        event: "paywall_impression",
        variant: "Paywall Impression (Logged-In)",
        trigger: "Paywall shown >= 75% to a logged-in user",
        fields: {
          event: { exact: "paywall_impression", required: true },
          auth_status: { exact: "logged_in", required: true },
          uuid: uuidField,
          page_url: { type: "url", required: true }
        }
      },
      {
        event: "paywall_impression",
        variant: "Paywall Impression (Non-Logged-In)",
        trigger: "Paywall shown >= 75% to a non-logged-in user",
        fields: {
          event: { exact: "paywall_impression", required: true },
          auth_status: { exact: "non_logged_in", required: true },
          uuid: { exact: "NA", required: true },
          page_url: { type: "url", required: true }
        }
      },
      /* ---------- paywall_subscribe_button_click ---------- */
      {
        event: "paywall_subscribe_button_click",
        variant: "Paywall Subscribe Button Click (Logged-In)",
        trigger: "User clicks Subscribe Now on the paywall (logged-in)",
        fields: {
          event: { exact: "paywall_subscribe_button_click", required: true },
          auth_status: { exact: "logged_in", required: true },
          uuid: uuidField,
          page_url: { type: "url", required: true }
        }
      },
      {
        event: "paywall_subscribe_button_click",
        variant: "Paywall Subscribe Button Click (Non-Logged-In)",
        trigger: "User clicks Subscribe Now on the paywall (non-logged-in)",
        fields: {
          event: { exact: "paywall_subscribe_button_click", required: true },
          auth_status: { exact: "non_logged_in", required: true },
          uuid: { exact: "NA", required: true },
          page_url: { type: "url", required: true }
        }
      },
      /* ---------- ad_lite_button_click ---------- */
      {
        event: "ad_lite_button_click",
        variant: "Go Ad Lite Button Click (Logged-In)",
        trigger: "User clicks Go Ad Lite above an advertisement (logged-in)",
        fields: {
          event: { exact: "ad_lite_button_click", required: true },
          ad_slot_name: s({ required: true }),
          auth_status: { exact: "logged_in", required: true },
          uuid: uuidField
        }
      },
      {
        event: "ad_lite_button_click",
        variant: "Go Ad Lite Button Click (Non-Logged-In)",
        trigger: "User clicks Go Ad Lite above an advertisement (non-logged-in)",
        fields: {
          event: { exact: "ad_lite_button_click", required: true },
          ad_slot_name: s({ required: true }),
          auth_status: { exact: "non_logged_in", required: true },
          uuid: { exact: "NA", required: true }
        }
      },
      /* ---------- subscription_header_button_click ---------- */
      {
        event: "subscription_header_button_click",
        variant: "Subscription Header Button Click (Logged-In)",
        trigger: "User clicks Subscribe in the website header (logged-in)",
        fields: {
          event: { exact: "subscription_header_button_click", required: true },
          auth_status: { exact: "logged_in", required: true },
          source: en(["DH_site", "DH_epaper"]),
          uuid: uuidField
        }
      },
      {
        event: "subscription_header_button_click",
        variant: "Subscription Header Button Click (Non-Logged-In)",
        trigger: "User clicks Subscribe in the website header (non-logged-in)",
        fields: {
          event: { exact: "subscription_header_button_click", required: true },
          auth_status: { exact: "non_logged_in", required: true },
          source: en(["DH_site", "DH_epaper"]),
          uuid: { exact: "NA", required: true }
        }
      },
      /* ---------- subscription_plan_selection ---------- */
      {
        event: "subscription_plan_selection",
        variant: "Subscription Plan Selection (Logged-In)",
        trigger: "User clicks Buy Now on a plan card (logged-in)",
        fields: {
          event: { exact: "subscription_plan_selection", required: true },
          auth_status: { exact: "logged_in", required: true },
          uuid: uuidField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES)
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      {
        event: "subscription_plan_selection",
        variant: "Subscription Plan Selection (Non-Logged-In)",
        trigger: "User clicks Buy Now on a plan card (non-logged-in)",
        fields: {
          event: { exact: "subscription_plan_selection", required: true },
          auth_status: { exact: "non_logged_in", required: true },
          uuid: { exact: "NA", required: true },
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES)
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      /* ---------- plan_edit ---------- */
      {
        event: "plan_edit",
        variant: "Edit Plan",
        trigger: "User clicks Edit Plan on Review & Pay page",
        fields: {
          event: { exact: "plan_edit", required: true },
          uuid: uuidField,
          from_plan: en(PLAN_NAMES),
          from_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES)
        },
        cross: (p) => planPriceMismatch(p.from_plan, p.from_price)
      },
      /* ---------- proceed_to_pay_click ---------- */
      {
        event: "proceed_to_pay_click",
        variant: "Proceed to Pay",
        trigger: "User clicks Proceed to Pay on Review & Pay page",
        fields: {
          event: { exact: "proceed_to_pay_click", required: true },
          uuid: uuidField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES)
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      /* ---------- purchase ---------- */
      {
        event: "purchase",
        variant: "Purchase",
        trigger: "Payment success page shown / subscription confirmed",
        fields: {
          event: { exact: "purchase", required: true },
          uuid: uuidField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES),
          transaction_id: s({ required: true }),
          redirection_url: { type: "url", required: true },
          user_type: en(["new user", "returning user"])
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price),
        sequenceTrigger: true
      },
      /* ---------- payment_failed ---------- */
      {
        event: "payment_failed",
        variant: "Payment Failed",
        trigger: "Payment failed window shown",
        fields: {
          event: { exact: "payment_failed", required: true },
          uuid: uuidField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES),
          reference_id: s({ required: true })
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      /* ---------- retry_payment_click ---------- */
      {
        event: "retry_payment_click",
        variant: "Retry Payment",
        trigger: "User clicks Retry Payment on payment failed page",
        fields: {
          event: { exact: "retry_payment_click", required: true },
          uuid: uuidField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES)
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      /* ---------- renewal_cancellation ---------- */
      {
        event: "renewal_cancellation",
        variant: "Renewal Cancellation",
        trigger: "User completes auto-renewal cancellation; 'Auto renewal cancelled' popup appears",
        fields: {
          event: { exact: "renewal_cancellation", required: true },
          uuid: uuidField,
          plan_name: en(PLAN_NAMES),
          plan_price: en([150, 1499, 2999])
        },
        cross: (p) => planPriceMismatch(p.plan_name, p.plan_price)
      },
      /* ---------- plan_change_initiated ---------- */
      {
        event: "plan_change_initiated",
        variant: "Plan Change Initiated",
        trigger: "'Plan Change Requested' popup appears for upgrade/downgrade",
        fields: {
          event: { exact: "plan_change_initiated", required: true },
          uuid: uuidField,
          // SPEC: from_plan/to_plan literally use "yearly", not "1-year".
          from_plan: en(["monthly", "yearly", "2-year"]),
          to_plan: en(["monthly", "yearly", "2-year"]),
          plan_price: en([150, 1499, 2999]),
          currency: en(CURRENCIES)
        }
      },
      /* ---------- renewal_prompt_impression ---------- */
      {
        event: "renewal_prompt_impression",
        variant: "Renewal Prompt Impression",
        trigger: "'Your subscription has expired' popup appears",
        fields: {
          event: { exact: "renewal_prompt_impression", required: true },
          uuid: uuidField
        }
      },
      /* ---------- accept_popup ---------- */
      {
        event: "accept_popup",
        variant: "Accept Popup",
        trigger: "User clicks Renew Now on subscription-expired popup",
        fields: {
          event: { exact: "accept_popup", required: true },
          uuid: uuidField
        }
      },
      /* ---------- dismiss_popup ---------- */
      {
        event: "dismiss_popup",
        variant: "Dismiss Popup",
        trigger: "User dismisses the subscription-expired popup (Remind me later / click outside)",
        fields: {
          event: { exact: "dismiss_popup", required: true },
          uuid: uuidField
        }
      }
    ];
    function schemasForEvent(eventName) {
      return EVENT_SCHEMAS.filter((s2) => s2.event === eventName);
    }
  
    // src/qa/validator.ts
    function safeClone(value, depth = 0, seen = /* @__PURE__ */ new Set()) {
      if (value === null || value === void 0) return value;
      const t = typeof value;
      if (t === "string" || t === "boolean") return value;
      if (t === "number") return Number.isFinite(value) ? value : String(value);
      if (t === "function") return "[function]";
      if (t === "symbol" || t === "bigint") return String(value);
      if (depth > 12) return "[deep]";
      if (value instanceof Error) return { name: value.name, message: value.message };
      if (value instanceof Date) return value.toISOString();
      if (typeof Element !== "undefined" && value instanceof Element) {
        return `<${value.tagName.toLowerCase()}${value.id ? "#" + value.id : ""}>`;
      }
      if (typeof Window !== "undefined" && value === window) return "[window]";
      if (seen.has(value)) return "[circular]";
      seen.add(value);
      if (Array.isArray(value)) {
        return value.map((v) => safeClone(v, depth + 1, seen));
      }
      const out = {};
      try {
        for (const k of Object.keys(value)) {
          try {
            out[k] = safeClone(value[k], depth + 1, seen);
          } catch {
            out[k] = "[unserializable]";
          }
        }
      } catch {
      }
      return out;
    }
    function normalizeGtagArguments(value) {
      if (typeof value !== "object" || value === null) return {};
      const raw = value;
      const out = {};
      for (const k of Object.keys(raw)) {
        try {
          const v = raw[k];
          if (k === "event_category" && typeof v === "string") out.event = v;
          else if (k === "event_label" && typeof v === "string" && !out.event) out.event = v;
          else out[k] = v;
        } catch {
        }
      }
      return out;
    }
    function normalizePayload(value) {
      if (typeof value !== "object" || value === null) return null;
      const raw = value;
      let fromGtag = false;
      let payload = null;
      if (raw[0] === "event") {
        fromGtag = true;
        if (typeof raw[1] === "string") {
          payload = { event: raw[1] };
          if (raw[2] && typeof raw[2] === "object") {
            payload = { ...payload, ...normalizeGtagArguments(raw[2]) };
          }
        } else if (raw[1] && typeof raw[1] === "object") {
          payload = normalizeGtagArguments(raw[1]);
          if (!payload.event && typeof raw[2] === "string") payload.event = raw[2];
        } else {
          payload = {};
        }
      } else if (typeof raw["event"] === "string") {
        payload = { ...raw };
        fromGtag = "__gtagTracker" in raw || "__gtag" in raw;
      } else if (typeof raw["eventName"] === "string") {
        payload = { event: raw["eventName"], ...raw };
      } else if (typeof raw["event_name"] === "string") {
        payload = { event: raw["event_name"], ...raw };
      }
      if (!payload || typeof payload.event !== "string") {
        payload = { event: "(unnamed)", ...raw };
      }
      const eventName = typeof payload.event === "string" ? payload.event : "(unnamed)";
      return {
        eventName,
        payload: safeClone(payload),
        fromGtag,
        raw: value
      };
    }
    function checkField(field, spec, payload, issues) {
      const value = payload[field];
      const present = value !== void 0 && value !== null;
      if (!present) {
        if (spec.required) {
          issues.push({ field, reason: "required field is missing", severity: "FAIL" });
        }
        return;
      }
      if (spec.exact !== void 0) {
        if (value !== spec.exact) {
          issues.push({
            field,
            reason: `expected exactly "${spec.exact}", got ${jsonPreview(value)}`,
            severity: "FAIL"
          });
        }
        return;
      }
      if (spec.enum !== void 0) {
        if (!spec.enum.some((e) => String(e) === String(value))) {
          issues.push({
            field,
            reason: `expected one of [${spec.enum.map((e) => JSON.stringify(e)).join(", ")}], got ${jsonPreview(value)}`,
            severity: "FAIL"
          });
        }
        return;
      }
      const naAllowed = spec.allowNA && value === "NA";
      if (naAllowed) return;
      switch (spec.type) {
        case "string":
          if (typeof value !== "string") {
            issues.push({ field, reason: `expected a string, got ${jsonPreview(value)}`, severity: "FAIL" });
          }
          break;
        case "number":
          if (!isNumber(value)) {
            issues.push({ field, reason: `expected a number, got ${jsonPreview(value)}`, severity: "FAIL" });
          }
          break;
        case "boolean":
          if (!isBool(value)) {
            issues.push({ field, reason: `expected a boolean, got ${jsonPreview(value)}`, severity: "FAIL" });
          }
          break;
        case "uuid":
          if (spec.uuid !== false && !isUuid(value)) {
            issues.push({ field, reason: `expected a valid UUID, got ${jsonPreview(value)}`, severity: "FAIL" });
          }
          break;
        case "datetime":
          if (!isIsoDate(value)) {
            issues.push({ field, reason: `expected a valid date/time, got ${jsonPreview(value)}`, severity: "FAIL" });
          }
          break;
        case "url":
          if (!isUrl(value)) {
            issues.push({ field, reason: `expected a valid http(s) URL, got ${jsonPreview(value)}`, severity: "FAIL" });
          }
          break;
      }
      if (spec.check) {
        const err = spec.check(value, payload);
        if (err) issues.push({ field, reason: err, severity: "FAIL" });
      }
    }
    function jsonPreview(value) {
      try {
        const s2 = JSON.stringify(value);
        if (s2 === void 0) return String(value);
        return s2.length > 60 ? s2.slice(0, 60) + "\u2026" : s2;
      } catch {
        return String(value);
      }
    }
    function schemaApplies(schema, payload) {
      const pageTypeSpec = schema.fields.page_type;
      if ((pageTypeSpec == null ? void 0 : pageTypeSpec.exact) !== void 0) {
        const actual = payload.page_type;
        if (actual !== void 0 && actual !== pageTypeSpec.exact) {
          return false;
        }
      }
      return true;
    }
    function validateEvent(normalized) {
      const schemas = schemasForEvent(normalized.eventName);
      if (schemas.length === 0) {
        return { status: "UNCHECKED", issues: [], uncovered: true };
      }
      const candidates = schemas.filter((schema) => schemaApplies(schema, normalized.payload));
      if (candidates.length === 0) {
        return { status: "UNCHECKED", issues: [], uncovered: true };
      }
      let best = null;
      for (const schema of candidates) {
        const issues = [];
        for (const [field, spec] of Object.entries(schema.fields)) {
          checkField(field, spec, normalized.payload, issues);
        }
        if (schema.cross) {
          const crossErr = schema.cross(normalized.payload);
          if (crossErr) issues.push({ field: "(cross-field)", reason: crossErr, severity: "FAIL" });
        }
        const failCount = issues.filter((i) => i.severity === "FAIL").length;
        const warnCount = issues.filter((i) => i.severity === "WARN").length;
        const status = failCount > 0 ? "FAIL" : warnCount > 0 ? "WARN" : "PASS";
        const result = { status, issues, uncovered: false };
        if (!best || failCount < best.issues.filter((i) => i.severity === "FAIL").length) {
          best = result;
        }
      }
      return best;
    }
  
    // src/qa/monitor.ts
    var MONITOR_VERSION = "1.0.0";
    var STORAGE_KEY = "pv.datalayer.qa.log.v1";
    var TRIGGER_EVENTS = ["page_view", "purchase", "sign_up", "login", "logout"];
    function uid() {
      return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    }
    function fmtTime(iso) {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleTimeString([], { hour12: false });
    }
    function elementInfo(el2) {
      if (!el2 || !(el2 instanceof Element)) return null;
      const info = {
        tag: el2.tagName.toLowerCase(),
        dataAttrs: {}
      };
      const id = el2.getAttribute("id");
      if (id) info.id = id;
      const cls = el2.getAttribute("class");
      if (cls) info.class = cls.split(/\s+/).filter(Boolean).slice(0, 8).join(" ");
      const href = el2.getAttribute("href");
      if (href) info.href = href;
      const role = el2.getAttribute("role");
      if (role) info.role = role;
      const aria = el2.getAttribute("aria-label");
      if (aria) info.ariaLabel = aria;
      const text = (el2.textContent || "").replace(/\s+/g, " ").trim();
      if (text && text.length <= 120) info.text = text;
      for (const attr of Array.from(el2.attributes)) {
        if (attr.name.startsWith("data-")) {
          info.dataAttrs[attr.name] = attr.value;
        }
      }
      return info;
    }
    function interactiveAncestor(el2) {
      const sel = [
        "a",
        "button",
        "input",
        "textarea",
        "select",
        "label",
        "summary",
        '[role="button"]',
        '[role="link"]',
        '[role="tab"]',
        '[role="menuitem"]',
        "[onclick]",
        "[data-testid]",
        "[aria-label]",
        "[title]"
      ].join(",");
      let cur = el2;
      while (cur && cur !== document.body && cur !== document.documentElement) {
        if (cur.matches && cur.matches(sel)) return cur;
        cur = cur.parentElement;
      }
      return el2;
    }
    var QaMonitor = class {
      constructor(options = {}) {
        __publicField(this, "rows", []);
        __publicField(this, "options");
        __publicField(this, "originalPush", null);
        __publicField(this, "hookedArray", null);
        __publicField(this, "rearmTimer", null);
        __publicField(this, "clickHandler", null);
        __publicField(this, "pendingClicks", []);
        __publicField(this, "sequence", null);
        __publicField(this, "eventListener", null);
        __publicField(this, "destroyed", false);
        var _a, _b, _c, _d;
        this.options = {
          sequenceWindowMs: (_a = options.sequenceWindowMs) != null ? _a : 2500,
          clickEventWindowMs: (_b = options.clickEventWindowMs) != null ? _b : 1200,
          maxRows: (_c = options.maxRows) != null ? _c : 1e3,
          markClickNoEventAsFailure: (_d = options.markClickNoEventAsFailure) != null ? _d : true,
          onLogChange: options.onLogChange,
          onStatus: options.onStatus
        };
      }
      /* ---------------- lifecycle ---------------- */
      start() {
        if (this.destroyed) return;
        this.addSystemRow(`Monitor v${MONITOR_VERSION} started`);
        this.hookDataLayer();
        this.installClickListener();
        this.installEventListener();
        this.rearmTimer = setInterval(() => this.hookDataLayer(), 250);
        this.emitLog();
        this.emitStatus("Monitoring window.dataLayer \u2014 interact with the site.");
      }
      destroy() {
        var _a;
        this.destroyed = true;
        if (this.rearmTimer) clearInterval(this.rearmTimer);
        if ((_a = this.sequence) == null ? void 0 : _a.timer) clearTimeout(this.sequence.timer);
        for (const c of this.pendingClicks) if (c.timer) clearTimeout(c.timer);
        this.pendingClicks = [];
        if (this.clickHandler) {
          document.removeEventListener("click", this.clickHandler, true);
          this.clickHandler = null;
        }
        if (this.eventListener) {
          window.removeEventListener("dataLayerPush", this.eventListener);
          this.eventListener = null;
        }
        this.restorePush();
      }
      restorePush() {
        if (this.hookedArray && this.originalPush) {
          try {
            const arr = this.hookedArray;
            const orig = arr.__qaOriginalPush;
            if (typeof orig === "function") {
              arr.push = orig;
            } else {
              arr.push = this.originalPush;
            }
            delete arr.__qaHooked;
            delete arr.__qaOriginalPush;
          } catch {
          }
        }
        this.hookedArray = null;
        this.originalPush = null;
      }
      /* ---------------- dataLayer hooking ---------------- */
      hookDataLayer() {
        var _a;
        const dl = window.dataLayer;
        if (!Array.isArray(dl)) return;
        if (dl === this.hookedArray && dl.__qaHooked) return;
        const prev = dl;
        if (prev.__qaHooked && prev.push && dl !== this.hookedArray) {
          try {
            const arr = dl;
            const orig = dl.__qaOriginalPush;
            if (typeof orig === "function") arr.push = orig;
          } catch {
          }
        }
        this.originalPush = dl.push;
        this.hookedArray = dl;
        try {
          Object.defineProperty(dl, "__qaOriginalPush", {
            value: this.originalPush,
            enumerable: false,
            configurable: true,
            writable: true
          });
        } catch {
          dl.__qaOriginalPush = this.originalPush;
        }
        try {
          Object.defineProperty(dl, "__qaHooked", { value: true, enumerable: false });
        } catch {
          dl.__qaHooked = true;
        }
        const original = dl.push.bind(dl);
        dl.push = (...args) => {
          const ret = original(...args);
          try {
            for (const arg of args) this.observePush(arg);
          } catch {
          }
          return ret;
        };
        const seen = (_a = dl.__qaSeen) != null ? _a : /* @__PURE__ */ new Set();
        try {
          Object.defineProperty(dl, "__qaSeen", { value: seen, enumerable: false });
        } catch {
          dl.__qaSeen = seen;
        }
        for (const item of dl) {
          if (seen.has(item)) continue;
          seen.add(item);
          this.observePush(item);
        }
      }
      observePush(value) {
        var _a;
        const dl = window.dataLayer;
        if (Array.isArray(dl)) {
          const seen = dl.__qaSeen;
          if (seen) seen.add(value);
        }
        const normalized = normalizePayload(value);
        if (!normalized) return;
        const result = validateEvent(normalized);
        const schemas = (_a = window.__qaSchemas) != null ? _a : EVENT_SCHEMAS;
        const variants = schemas.filter((s2) => s2.event === normalized.eventName);
        const variant = variants.length ? variants.map((v) => v.variant).filter(Boolean).join(" / ") : void 0;
        const row = {
          id: uid(),
          time: (/* @__PURE__ */ new Date()).toISOString(),
          timeLabel: fmtTime((/* @__PURE__ */ new Date()).toISOString()),
          kind: "event",
          status: "FIRED",
          eventName: normalized.eventName,
          variant,
          check: result.uncovered ? "\u2014" : result.status,
          validationIssues: result.issues.map((i) => `${i.field}: ${i.reason}`),
          payload: normalized.payload,
          rawPayload: value,
          fromGtag: normalized.fromGtag,
          url: location.href
        };
        this.addRow(row);
        if (TRIGGER_EVENTS.includes(normalized.eventName)) {
          this.expectUserPropertiesUpdate(normalized.eventName);
        }
        if (normalized.eventName === "user_properties_update") {
          this.resolveSequence();
        }
        const now = Date.now();
        for (const click of this.pendingClicks) {
          if (now - click.time <= this.options.clickEventWindowMs && !click.matched) {
            click.matched = true;
            row.element = click.element;
            if (click.timer) clearTimeout(click.timer);
            this.updateRow(row.id, { status: "FIRED", element: click.element });
            this.emitLog();
          }
        }
      }
      /* ---------------- click tracking ---------------- */
      installClickListener() {
        this.clickHandler = (e) => {
          const el2 = interactiveAncestor(e.target);
          const info = elementInfo(el2);
          if (!info) return;
          const tracker = {
            element: info,
            time: Date.now(),
            matched: false,
            timer: null
          };
          tracker.timer = setTimeout(() => {
            if (!tracker.matched) {
              const clickRow = {
                id: uid(),
                time: (/* @__PURE__ */ new Date()).toISOString(),
                timeLabel: fmtTime((/* @__PURE__ */ new Date()).toISOString()),
                kind: "click",
                status: "NO EVENT",
                check: "NO EVENT",
                validationIssues: [],
                element: info,
                url: location.href
              };
              if (!this.options.markClickNoEventAsFailure) {
                clickRow.check = "\u2014";
                clickRow.status = "SYSTEM";
                clickRow.validationIssues = ["click observed; element not expected to fire analytics (informational)"];
              } else {
                clickRow.validationIssues = [
                  `no dataLayer event fired within ${this.options.clickEventWindowMs}ms of clicking`
                ];
              }
              this.addRow(clickRow);
            }
            const idx = this.pendingClicks.indexOf(tracker);
            if (idx >= 0) this.pendingClicks.splice(idx, 1);
          }, this.options.clickEventWindowMs);
          this.pendingClicks.push(tracker);
          if (this.pendingClicks.length > 50) {
            const dropped = this.pendingClicks.shift();
            if (dropped == null ? void 0 : dropped.timer) clearTimeout(dropped.timer);
          }
        };
        document.addEventListener("click", this.clickHandler, true);
      }
      /* ---------------- sequence validation ---------------- */
      expectUserPropertiesUpdate(triggerEvent) {
        if (this.sequence) {
          this.failSequence("superseded by another trigger event");
        }
        const st = {
          triggerEvent,
          triggerTime: Date.now(),
          triggeredBy: "dataLayer.push",
          timer: null
        };
        st.timer = setTimeout(() => {
          this.failSequence("no user_properties_update within the sequence window");
        }, this.options.sequenceWindowMs);
        this.sequence = st;
        this.addRow({
          id: uid(),
          time: (/* @__PURE__ */ new Date()).toISOString(),
          timeLabel: fmtTime((/* @__PURE__ */ new Date()).toISOString()),
          kind: "sequence",
          status: "WAITING",
          check: "WAITING",
          eventName: `sequence: ${triggerEvent} \u2192 user_properties_update`,
          sequenceNote: `waiting up to ${this.options.sequenceWindowMs}ms for user_properties_update`,
          validationIssues: [],
          url: location.href
        });
      }
      resolveSequence() {
        if (!this.sequence) return;
        const st = this.sequence;
        this.sequence = null;
        if (st.timer) clearTimeout(st.timer);
        this.addRow({
          id: uid(),
          time: (/* @__PURE__ */ new Date()).toISOString(),
          timeLabel: fmtTime((/* @__PURE__ */ new Date()).toISOString()),
          kind: "sequence",
          status: "FIRED",
          check: "PASS",
          eventName: `sequence: ${st.triggerEvent} \u2192 user_properties_update`,
          sequenceNote: `follow-up arrived within ${Date.now() - st.triggerTime}ms (window ${this.options.sequenceWindowMs}ms)`,
          validationIssues: [],
          url: location.href
        });
      }
      failSequence(reason) {
        if (!this.sequence) return;
        const st = this.sequence;
        this.sequence = null;
        if (st.timer) clearTimeout(st.timer);
        this.addRow({
          id: uid(),
          time: (/* @__PURE__ */ new Date()).toISOString(),
          timeLabel: fmtTime((/* @__PURE__ */ new Date()).toISOString()),
          kind: "sequence",
          status: "NO EVENT",
          check: "SEQUENCE FAIL",
          eventName: `sequence: ${st.triggerEvent} \u2192 user_properties_update`,
          sequenceNote: reason,
          validationIssues: [reason],
          url: location.href
        });
      }
      /* ---------------- cross-monitor / page events ---------------- */
      installEventListener() {
        this.eventListener = (e) => {
          const custom = e;
          if (custom.detail && typeof custom.detail === "object") {
            const v = custom.detail.value;
            if (v !== void 0) this.observePush(v);
          }
        };
        window.addEventListener("dataLayerPush", this.eventListener);
      }
      /* ---------------- persistence ---------------- */
      addRow(row) {
        this.rows.push(row);
        if (this.rows.length > this.options.maxRows) {
          this.rows = this.rows.slice(-this.options.maxRows);
        }
        this.emitLog();
      }
      updateRow(id, patch) {
        const row = this.rows.find((r) => r.id === id);
        if (row) Object.assign(row, patch);
      }
      emitLog() {
        var _a, _b;
        (_b = (_a = this.options).onLogChange) == null ? void 0 : _b.call(_a, this.rows.slice());
        try {
          sessionStorage.setItem(STORAGE_KEY, JSON.stringify(this.rows));
        } catch {
        }
      }
      emitStatus(msg) {
        var _a, _b;
        (_b = (_a = this.options).onStatus) == null ? void 0 : _b.call(_a, msg);
      }
      addSystemRow(message) {
        this.addRow({
          id: uid(),
          time: (/* @__PURE__ */ new Date()).toISOString(),
          timeLabel: fmtTime((/* @__PURE__ */ new Date()).toISOString()),
          kind: "system",
          status: "SYSTEM",
          check: "SYSTEM",
          eventName: "system",
          validationIssues: [],
          sequenceNote: message,
          url: location.href
        });
      }
      clear() {
        this.rows = [];
        try {
          sessionStorage.removeItem(STORAGE_KEY);
        } catch {
        }
        this.addSystemRow("QA log cleared");
        this.emitLog();
      }
      /** Restore rows persisted by a previous monitor instance in this tab. */
      restore() {
        try {
          const raw = sessionStorage.getItem(STORAGE_KEY);
          if (!raw) return 0;
          const parsed = JSON.parse(raw);
          if (!Array.isArray(parsed)) return 0;
          this.rows = parsed.slice(-this.options.maxRows);
          this.emitLog();
          return parsed.length;
        } catch {
          return 0;
        }
      }
    };
    var activeMonitor = null;
    function createMonitor(options = {}) {
      if (activeMonitor) {
        activeMonitor.destroy();
      }
      activeMonitor = new QaMonitor(options);
      return activeMonitor;
    }
  
    // src/qa/qa-monitor.ts
    var PANEL_ID = "pv-datalayer-qa-monitor";
    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== void 0) node.textContent = text;
      return node;
    }
    function statusClass(status) {
      switch (status) {
        case "FIRED":
          return "pvqa-pass";
        case "NO EVENT":
          return "pvqa-noevent";
        case "WAITING":
          return "pvqa-wait";
        case "SYSTEM":
          return "pvqa-system";
        default:
          return "";
      }
    }
    function checkClass(check) {
      if (check === "PASS") return "pvqa-pass";
      if (check === "FAIL" || check === "SEQUENCE FAIL") return "pvqa-noevent";
      if (check === "WARN") return "pvqa-warn";
      if (check === "\u2014") return "pvqa-unchecked";
      return "";
    }
    function csvCell(v) {
      if (v === void 0 || v === null) return "";
      const s2 = typeof v === "string" ? v : JSON.stringify(v);
      return '"' + String(s2).replace(/"/g, '""') + '"';
    }
    function download(filename, content, mime) {
      const blob = new Blob([content], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2e3);
    }
    function elementSummary(row) {
      if (!row.element) return "";
      const e = row.element;
      const parts = [e.tag, e.id ? `#${e.id}` : "", e.class ? `.${e.class.split(" ").join(".")}` : ""];
      return parts.join("") + (e.text ? ` "${e.text.slice(0, 40)}"` : "");
    }
    var QaMonitorPanel = class {
      constructor(options = {}) {
        __publicField(this, "monitor");
        __publicField(this, "root");
        __publicField(this, "header");
        __publicField(this, "body");
        __publicField(this, "tableBody");
        __publicField(this, "searchInput");
        __publicField(this, "countLabel");
        __publicField(this, "statusLabel");
        __publicField(this, "minimized", false);
        __publicField(this, "filter", "all");
        __publicField(this, "rows", []);
        const existing = document.getElementById(PANEL_ID);
        if (existing) existing.remove();
        this.monitor = createMonitor({
          sequenceWindowMs: options.sequenceWindowMs,
          clickEventWindowMs: options.clickEventWindowMs,
          maxRows: options.maxRows,
          markClickNoEventAsFailure: options.markClickNoEventAsFailure,
          onLogChange: (rows) => {
            this.rows = rows;
            this.render();
          },
          onStatus: (msg) => {
            this.statusLabel.textContent = msg;
          }
        });
        this.root = el("div", "pvqa-root");
        this.root.id = PANEL_ID;
        this.header = el("div", "pvqa-header");
        this.header.textContent = "DataLayer QA Monitor \u2014 prajavani.net";
        this.header.title = "Drag to move";
        const btnMin = el("button", "pvqa-btn", "\u2014");
        btnMin.title = "Minimize / restore";
        btnMin.addEventListener("click", () => this.toggleMinimize());
        const btnClear = el("button", "pvqa-btn", "Clear");
        btnClear.title = "Clear QA log (current session)";
        btnClear.addEventListener("click", () => this.monitor.clear());
        const btnCsv = el("button", "pvqa-btn", "Export CSV");
        btnCsv.addEventListener("click", () => this.exportCsv());
        const btnJson = el("button", "pvqa-btn", "Export JSON");
        btnJson.addEventListener("click", () => this.exportJson());
        this.header.appendChild(el("span", "pvqa-title", "DataLayer QA Monitor \u2014 prajavani.net"));
        const actions = el("div", "pvqa-actions");
        actions.append(btnMin, btnClear, btnCsv, btnJson);
        this.header.appendChild(actions);
        this.body = el("div", "pvqa-body");
        this.body.style.flex = "1";
        this.body.style.minHeight = "0";
        this.body.style.overflow = "hidden";
        const toolbar = el("div", "pvqa-toolbar");
        this.searchInput = el("input", "pvqa-search");
        this.searchInput.placeholder = "Search event / element / payload\u2026";
        this.searchInput.addEventListener("input", () => this.render());
        const filterSelect = el("select", "pvqa-filter");
        ["all", "PASS", "FAIL", "WARN", "NO EVENT", "SEQUENCE", "\u2014"].forEach((f) => {
          const opt = el("option", void 0, f);
          opt.value = f;
          filterSelect.appendChild(opt);
        });
        filterSelect.addEventListener("change", () => {
          this.filter = filterSelect.value;
          this.render();
        });
        this.countLabel = el("span", "pvqa-count", "0 events");
        toolbar.append(this.searchInput, filterSelect, this.countLabel);
        this.statusLabel = el("div", "pvqa-status", "Ready.");
        const table = el("table", "pvqa-table");
        const thead = el("thead");
        const headRow = el("tr");
        ["Time", "Status", "Event", "Check", "Triggered by", "Payload"].forEach(
          (h) => headRow.appendChild(el("th", void 0, h))
        );
        thead.appendChild(headRow);
        this.tableBody = el("tbody");
        table.append(thead, this.tableBody);
        const tableWrap = el("div", "pvqa-table-wrap");
        tableWrap.appendChild(table);
        this.body.append(toolbar, this.statusLabel, tableWrap);
        this.root.append(this.header, this.body);
        document.body.appendChild(this.root);
        this.makeDraggable();
        const restored = this.monitor.restore();
        if (restored > 0) {
          this.statusLabel.textContent = `Restored ${restored} events from this browser session\u2026`;
        }
        if (options.autoStart !== false) {
          this.monitor.start();
        }
      }
      render() {
        var _a;
        const q = this.searchInput.value.trim().toLowerCase();
        const visible = this.rows.filter((row) => {
          var _a2;
          if (this.filter !== "all") {
            if (this.filter === "SEQUENCE" && row.kind !== "sequence") return false;
            if (this.filter !== "SEQUENCE" && row.check !== this.filter && row.status !== this.filter) return false;
          }
          if (!q) return true;
          const hay = [
            row.eventName,
            row.check,
            row.status,
            row.variant,
            elementSummary(row),
            row.validationIssues.join(" "),
            row.sequenceNote,
            (_a2 = row.payloadJson) != null ? _a2 : "",
            row.payload ? JSON.stringify(row.payload) : ""
          ].join(" ").toLowerCase();
          return hay.includes(q);
        });
        this.countLabel.textContent = `${visible.length} of ${this.rows.length}`;
        this.tableBody.textContent = "";
        for (const row of visible) {
          const tr = el("tr");
          const timeTd = el("td", "pvqa-mono", row.timeLabel);
          const statusTd = el("td");
          const statusBadge = el("span", `pvqa-badge ${statusClass(row.status)}`, row.status);
          statusTd.appendChild(statusBadge);
          const eventTd = el("td");
          eventTd.appendChild(el("span", "pvqa-eventname", (_a = row.eventName) != null ? _a : row.kind));
          if (row.variant) eventTd.appendChild(el("div", "pvqa-variant", row.variant));
          if (row.sequenceNote) eventTd.appendChild(el("div", "pvqa-seqnote", row.sequenceNote));
          const checkTd = el("td");
          const checkBadge = el("span", `pvqa-badge ${checkClass(row.check)}`, row.check);
          if (row.validationIssues.length) checkBadge.title = row.validationIssues.join("\n");
          checkBadge.style.cursor = "pointer";
          checkBadge.addEventListener("click", () => this.showPayloadModal(row));
          checkTd.appendChild(checkBadge);
          const elTd = el("td", "pvqa-el", elementSummary(row));
          const payloadTd = el("td");
          const payloadBtn = el("button", "pvqa-btn pvqa-btn-small", row.kind === "event" ? "View" : "\u2014");
          if (row.kind === "event" && row.payload) {
            payloadBtn.addEventListener("click", () => this.showPayloadModal(row));
          } else {
            payloadBtn.disabled = true;
          }
          payloadTd.appendChild(payloadBtn);
          tr.append(timeTd, statusTd, eventTd, checkTd, elTd, payloadTd);
          this.tableBody.appendChild(tr);
        }
      }
      toggleMinimize() {
        this.minimized = !this.minimized;
        this.body.style.display = this.minimized ? "none" : "";
      }
      showPayloadModal(row) {
        var _a;
        const backdrop = el("div", "pvqa-modal-backdrop");
        const modal = el("div", "pvqa-modal");
        const head = el("div", "pvqa-modal-head");
        head.appendChild(
          el("span", "pvqa-modal-title", `${(_a = row.eventName) != null ? _a : row.kind} \u2014 ${row.check}`)
        );
        const btnCopy = el("button", "pvqa-btn", "Copy");
        btnCopy.addEventListener("click", () => {
          var _a2, _b;
          try {
            (_b = navigator.clipboard) == null ? void 0 : _b.writeText(JSON.stringify((_a2 = row.payload) != null ? _a2 : {}, null, 2));
          } catch {
          }
        });
        const btnClose = el("button", "pvqa-btn", "Close");
        btnClose.addEventListener("click", () => backdrop.remove());
        head.append(btnCopy, btnClose);
        modal.append(head);
        if (row.variant) {
          modal.appendChild(el("div", "pvqa-variant", `Schema/variant: ${row.variant}`));
        }
        if (row.validationIssues.length) {
          modal.appendChild(el("div", void 0, `${row.validationIssues.length} issue(s):`));
          const list = el("ul");
          for (const issue of row.validationIssues) {
            list.appendChild(el("li", void 0, issue));
          }
          modal.appendChild(list);
        }
        if (row.sequenceNote) {
          modal.appendChild(el("div", "pvqa-seqnote", row.sequenceNote));
        }
        if (row.element) {
          modal.appendChild(el("div", void 0, "Clicked element:"));
          const elPre = el("pre", "pvqa-modal-json");
          elPre.textContent = JSON.stringify(row.element, null, 2);
          modal.appendChild(elPre);
        }
        if (row.payload) {
          modal.appendChild(el("div", void 0, "Payload:"));
          const pre = el("pre", "pvqa-modal-json");
          pre.textContent = JSON.stringify(row.payload, null, 2);
          modal.appendChild(pre);
        } else if (!row.element) {
          modal.appendChild(el("div", void 0, "No payload captured for this row."));
        }
        backdrop.appendChild(modal);
        backdrop.addEventListener("click", (e) => {
          if (e.target === backdrop) backdrop.remove();
        });
        document.body.appendChild(backdrop);
      }
      exportCsv() {
        var _a;
        const header = [
          "time",
          "status",
          "event_name",
          "check",
          "validation_issues",
          "element",
          "element_attributes",
          "payload_json",
          "sequence"
        ];
        const lines = [header.join(",")];
        for (const row of this.rows) {
          const attrs = row.element ? JSON.stringify({ ...row.element, dataAttrs: row.element.dataAttrs }) : "";
          lines.push(
            [
              csvCell(row.time),
              csvCell(row.status),
              csvCell(row.eventName),
              csvCell(row.check),
              csvCell(row.validationIssues.join(" | ")),
              csvCell(elementSummary(row)),
              csvCell(attrs),
              csvCell((_a = row.payloadJson) != null ? _a : row.payload ? JSON.stringify(row.payload) : ""),
              csvCell(row.sequenceNote)
            ].join(",")
          );
        }
        const stamp = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-");
        download(`prajavani-datalayer-qa-${stamp}.csv`, lines.join("\n"), "text/csv");
      }
      exportJson() {
        const payload = {
          exportedAt: (/* @__PURE__ */ new Date()).toISOString(),
          site: "prajavani.net",
          monitorVersion: "1.0.0",
          total: this.rows.length,
          rows: this.rows.map((r) => ({
            time: r.time,
            status: r.status,
            event: r.eventName,
            variant: r.variant,
            check: r.check,
            validationIssues: r.validationIssues,
            payload: r.payload,
            clickedElement: r.element,
            sequence: r.sequenceNote,
            url: r.url
          }))
        };
        const stamp = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-");
        download(
          `prajavani-datalayer-qa-${stamp}.json`,
          JSON.stringify(payload, null, 2),
          "application/json"
        );
      }
      makeDraggable() {
        let dragging = false;
        let startX = 0;
        let startY = 0;
        let origLeft = 0;
        let origTop = 0;
        this.header.addEventListener("mousedown", (e) => {
          if (e.target.closest(".pvqa-btn")) return;
          dragging = true;
          const rect = this.root.getBoundingClientRect();
          startX = e.clientX;
          startY = e.clientY;
          origLeft = rect.left;
          origTop = rect.top;
          e.preventDefault();
        });
        document.addEventListener("mousemove", (e) => {
          if (!dragging) return;
          const dx = e.clientX - startX;
          const dy = e.clientY - startY;
          this.root.style.left = `${Math.max(0, origLeft + dx)}px`;
          this.root.style.top = `${Math.max(0, origTop + dy)}px`;
        });
        document.addEventListener("mouseup", () => {
          dragging = false;
        });
      }
    };
    var panel = null;
    function initQaMonitor(options = {}) {
      var _a;
      if (panel) {
        (_a = document.getElementById(PANEL_ID)) == null ? void 0 : _a.remove();
      }
      panel = new QaMonitorPanel(options);
      window.__qaMonitor = panel["monitor"];
      return panel;
    }
    function destroyQaMonitor() {
      var _a;
      const active = window.__qaMonitor;
      active == null ? void 0 : active.destroy();
      (_a = document.getElementById(PANEL_ID)) == null ? void 0 : _a.remove();
      panel = null;
    }
    function ensureQaStyles(css) {
      if (document.getElementById("pvqa-styles")) return;
      const style = document.createElement("style");
      style.id = "pvqa-styles";
      style.textContent = css;
      document.head.appendChild(style);
    }
  
    // src/qa/qa-monitor.css?inline
    var qa_monitor_default = `/* DataLayer QA Monitor \u2014 prajavani.net floating panel styles.
     Self-contained (fixed z-index, its own classes) so it never interferes with
     the host site's CSS. */
  
  .pvqa-root {
    position: fixed;
    top: 20px;
    right: 20px;
    width: 560px;
    max-width: 92vw;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    box-shadow: 0 12px 40px rgba(15, 23, 42, 0.25);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 12.5px;
    line-height: 1.45;
    z-index: 2147483000;
    box-sizing: border-box;
  }
  
  .pvqa-root *,
  .pvqa-root *::before,
  .pvqa-root *::after {
    box-sizing: border-box;
  }
  
  .pvqa-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 10px;
    background: #1e3a8a;
    color: #fff;
    border-radius: 10px 10px 0 0;
    cursor: grab;
    user-select: none;
    flex-shrink: 0;
  }
  
  .pvqa-title {
    font-weight: 700;
    font-size: 12.5px;
    letter-spacing: 0.2px;
  }
  
  .pvqa-actions {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
  }
  
  .pvqa-btn {
    font: inherit;
    font-size: 11.5px;
    padding: 3px 8px;
    border-radius: 6px;
    border: 1px solid transparent;
    background: rgba(255, 255, 255, 0.15);
    color: #fff;
    cursor: pointer;
  }
  
  .pvqa-btn:hover {
    background: rgba(255, 255, 255, 0.28);
  }
  
  .pvqa-btn:disabled {
    opacity: 0.4;
    cursor: default;
  }
  
  .pvqa-btn-small {
    font-size: 10.5px;
    padding: 1px 7px;
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
  }
  
  .pvqa-btn-small:hover {
    background: #dbeafe;
  }
  
  .pvqa-body {
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  
  .pvqa-toolbar {
    display: flex;
    gap: 6px;
    padding: 8px 10px;
    border-bottom: 1px solid #e2e8f0;
    align-items: center;
    flex-wrap: wrap;
  }
  
  .pvqa-search {
    flex: 1;
    min-width: 140px;
    font: inherit;
    font-size: 12px;
    padding: 4px 8px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #1f2937;
    background: #fff;
  }
  
  .pvqa-filter {
    font: inherit;
    font-size: 12px;
    padding: 3px 6px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #1f2937;
  }
  
  .pvqa-count {
    color: #475569;
    font-size: 11.5px;
  }
  
  .pvqa-status {
    padding: 4px 10px;
    font-size: 11.5px;
    color: #475569;
    border-bottom: 1px solid #e2e8f0;
    background: #f8fafc;
    min-height: 22px;
  }
  
  .pvqa-table-wrap {
    overflow: auto;
    min-height: 0;
    flex: 1;
  }
  
  .pvqa-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11.5px;
    table-layout: fixed;
  }
  
  .pvqa-table th {
    position: sticky;
    top: 0;
    background: #f1f5f9;
    color: #334155;
    font-weight: 700;
    text-align: left;
    padding: 5px 6px;
    border-bottom: 1px solid #cbd5e1;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    z-index: 1;
  }
  
  .pvqa-table td {
    padding: 4px 6px;
    border-bottom: 1px solid #f1f5f9;
    vertical-align: top;
    word-break: break-word;
  }
  
  .pvqa-table tr:hover td {
    background: #f8fafc;
  }
  
  .pvqa-mono {
    font-family: ui-monospace, SFMono-Regular, Consolas, Menlo, monospace;
    font-size: 10.5px;
    white-space: nowrap;
  }
  
  .pvqa-eventname {
    font-weight: 600;
    color: #0f172a;
  }
  
  .pvqa-variant {
    font-size: 10.5px;
    color: #64748b;
  }
  
  .pvqa-seqnote {
    font-size: 10.5px;
    color: #475569;
    font-style: italic;
  }
  
  .pvqa-el {
    color: #334155;
    font-size: 11px;
  }
  
  /* Status / check badges \u2014 text + color (not color-only). */
  .pvqa-badge {
    display: inline-block;
    padding: 1px 7px;
    border-radius: 20px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    border: 1px solid transparent;
  }
  
  .pvqa-pass {
    background: #dcfce7;
    color: #166534;
    border-color: #86efac;
  }
  
  .pvqa-noevent {
    background: #fee2e2;
    color: #991b1b;
    border-color: #fca5a5;
  }
  
  .pvqa-wait {
    background: #fef9c3;
    color: #854d0e;
    border-color: #fde047;
  }
  
  .pvqa-warn {
    background: #ffedd5;
    color: #9a3412;
    border-color: #fdba74;
  }
  
  .pvqa-system {
    background: #e2e8f0;
    color: #334155;
    border-color: #cbd5e1;
  }
  
  .pvqa-unchecked {
    background: #f1f5f9;
    color: #64748b;
    border-color: #cbd5e1;
  }
  
  /* Payload modal */
  .pvqa-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2147483001;
    padding: 24px;
  }
  
  .pvqa-modal {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    width: 680px;
    max-width: 94vw;
    max-height: 84vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(15, 23, 42, 0.3);
  }
  
  .pvqa-modal-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
  }
  
  .pvqa-modal-title {
    font-weight: 700;
    color: #1e3a8a;
  }
  
  .pvqa-modal-json {
    flex: 1;
    overflow: auto;
    margin: 0;
    padding: 12px;
    font-family: ui-monospace, SFMono-Regular, Consolas, Menlo, monospace;
    font-size: 11.5px;
    line-height: 1.5;
    color: #0f172a;
    white-space: pre-wrap;
    word-break: break-word;
  }
  `;
  
    // src/qa/console-entry.ts
    function bootQaMonitor(options = {}) {
      ensureQaStyles(qa_monitor_default);
      initQaMonitor(options);
    }
    window.initQaMonitor = (opts) => {
      ensureQaStyles(qa_monitor_default);
      return initQaMonitor(opts);
    };
    window.destroyQaMonitor = () => {
      destroyQaMonitor();
    };
    if (typeof window !== "undefined" && window.__QA_BOOT) {
      bootQaMonitor();
    }
    return __toCommonJS(console_entry_exports);
  })();
  

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
