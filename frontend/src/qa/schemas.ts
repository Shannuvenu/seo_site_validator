/**
 * Prajavani.net Paywall Data Layer — event schema definitions.
 *
 * The Excel specification is the authority. Where the spec uses a literal
 * value ("NA", "mobile no", "yearly", "Newsletter_consent", "subscribed"),
 * we preserve it EXACTLY. Deliberate inconsistencies in the source spec are
 * preserved and called out in comments + the final report — we do NOT
 * silently normalize them.
 *
 * Known source-spec inconsistencies (preserved on purpose):
 * - plan_change_initiated uses from_plan/to_plan "yearly" while every other
 *   event uses "1-year". Preserved per spec; the cross-check that maps
 *   "yearly" -> 1499 exists only for that event.
 * - "subscribed" (logout subscription_status) vs "subscriber"
 *   (user_properties_update subscription_status) are different enums.
 * - Non-Logged-In user_properties_update has NO account_created_date in the
 *   spec — we do not require it.
 * - login (With Subscription) spec omits "paywall" from allowed `source`
 *   while login (Without Subscription) includes it. Preserved as-is.
 */

/** Validator result statuses. */
export type ValidationStatus = "PASS" | "FAIL" | "WARN" | "UNCHECKED";

export interface ValidationIssue {
  field: string;
  reason: string;
  severity: "FAIL" | "WARN";
}

export interface ValidationResult {
  status: ValidationStatus;
  issues: ValidationIssue[];
  /** True when this event name has NO schema defined (CHECK: —). */
  uncovered: boolean;
}

/* ------------------------------------------------------------------ */
/* Shared value helpers                                                */
/* ------------------------------------------------------------------ */

export const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(v: unknown): boolean {
  return typeof v === "string" && UUID_RE.test(v.trim());
}

export function isIsoDate(v: unknown): boolean {
  if (typeof v !== "string") return false;
  const s = v.trim();
  if (!s) return false;
  const d = new Date(s);
  if (isNaN(d.getTime())) return false;
  // Require at least a date part; ISO 8601 with time preferred.
  return /^\d{4}-\d{2}-\d{2}/.test(s);
}

export function isNumber(v: unknown): boolean {
  return typeof v === "number" && Number.isFinite(v);
}

export function isBool(v: unknown): boolean {
  return typeof v === "boolean";
}

export function isUrl(v: unknown): boolean {
  if (typeof v !== "string") return false;
  try {
    const u = new URL(v);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

/** Field types usable in schemas. */
export type FieldType =
  | "string"
  | "number"
  | "boolean"
  | "uuid"
  | "datetime"
  | "url";

export interface FieldSpec {
  required?: boolean;
  type?: FieldType;
  /** Exact string match (including "NA"). */
  exact?: string;
  /** Allowed enum values. */
  enum?: unknown[];
  /** If true, "NA" is an allowed substitute for a uuid/string field. */
  allowNA?: boolean;
  /** If provided, the field must be a valid UUID. */
  uuid?: boolean;
  /** Custom predicate; receives (value, payload). */
  check?: (value: unknown, payload: Record<string, unknown>) => string | null;
}

export interface EventSchema {
  event: string;
  /** Descriptive variant name from the Excel (for display). */
  variant?: string;
  /** Trigger description for the QA UI. */
  trigger?: string;
  fields: Record<string, FieldSpec>;
  /** Cross-field checks: return an issue message or null. */
  cross?: (payload: Record<string, unknown>) => string | null;
  /** True if this event is one of the sequence TRIGGERS (expects a
   * user_properties_update follow-up). */
  sequenceTrigger?: boolean;
}

/* ------------------------------------------------------------------ */
/* Shared plan/price pairs (cross-field).                             */
/* ------------------------------------------------------------------ */

/** plan_name -> plan_price map for subscriber/plan events. */
export const PLAN_PRICE_MAP: Record<string, number> = {
  monthly: 150,
  "1-year": 1499,
  "2-year": 2999,
  // plan_change_initiated uses "yearly" per spec — 1499 like 1-year.
  yearly: 1499,
};

export function planPriceMismatch(
  planName: unknown,
  planPrice: unknown,
): string | null {
  if (typeof planName !== "string" || typeof planPrice !== "number") return null;
  const expected = PLAN_PRICE_MAP[planName];
  if (expected === undefined) return null; // plan_name itself already flagged
  if (expected !== planPrice) {
    return `"plan_price": does not match plan_name (expected ${expected}, got ${planPrice})`;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Field factory helpers (keeps the schemas readable).                */
/* ------------------------------------------------------------------ */

const s = (spec: Omit<FieldSpec, "type"> & { type?: FieldType } = {}): FieldSpec => ({
  type: spec.type ?? "string",
  ...spec,
});

const na = (spec: FieldSpec = {}): FieldSpec => ({ ...spec, allowNA: true });

const en = (values: unknown[]): FieldSpec => ({ enum: values });

/* ------------------------------------------------------------------ */
/* Event schemas                                                      */
/* ------------------------------------------------------------------ */

const AUTH_STATUS: unknown[] = ["logged_in", "non_logged_in"];

const SSO_METHODS: unknown[] = ["email", "mobile no", "google_onetap", "google_icon"];
const LOGIN_METHODS: unknown[] = [...SSO_METHODS, "sso_auto_login"];
const SSO_SOURCES: unknown[] = ["header_button", "plan_selection", "comment", "ham_menu", "paywall"];
const LOGIN_WITH_SUB_SOURCES: unknown[] = ["header_button", "comment", "ham_menu"]; // per spec
const LOGOUT_SOURCES: unknown[] = ["profile", "change_account"];

const PLAN_NAMES: unknown[] = ["monthly", "1-year", "2-year"];
const CURRENCIES: unknown[] = ["INR", "USD"];

const uuidField = { type: "uuid" as const, required: true };
const naUuidField = na({ type: "uuid" as const, required: true });
const accountDateField = { type: "datetime" as const, required: true };
const boolField = { type: "boolean" as const, required: true };

const consentFields = {
  marketing_and_promotion_consent: boolField,
  // Preserve the exact capitalization from the source spec.
  Newsletter_consent: boolField,
};

export const EVENT_SCHEMAS: EventSchema[] = [
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
      access_level_value: en([100, 200]),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      plan_price: { exact: "NA", required: true },
    },
    sequenceTrigger: false,
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
      plan_price: en([150, 1499, 2999]),
    },
    cross: (p) =>
      planPriceMismatch(p.plan_name as string, p.plan_price as number) ??
      (typeof p.plan_name === "string" && typeof p.plan_price === "number"
        ? planPriceMismatch(p.plan_name, p.plan_price)
        : null),
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
      plan_price: { exact: "NA", required: true },
    },
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
      ...consentFields,
    },
    sequenceTrigger: true,
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
      ...consentFields,
    },
    sequenceTrigger: true,
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
      ...consentFields,
    },
    sequenceTrigger: true,
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
      subscription_status: en(["subscribed", "non_subscriber"]),
    },
    sequenceTrigger: true,
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
      page_url: { type: "url", required: true },
    },
  },
  {
    event: "paywall_impression",
    variant: "Paywall Impression (Non-Logged-In)",
    trigger: "Paywall shown >= 75% to a non-logged-in user",
    fields: {
      event: { exact: "paywall_impression", required: true },
      auth_status: { exact: "non_logged_in", required: true },
      uuid: { exact: "NA", required: true },
      page_url: { type: "url", required: true },
    },
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
      page_url: { type: "url", required: true },
    },
  },
  {
    event: "paywall_subscribe_button_click",
    variant: "Paywall Subscribe Button Click (Non-Logged-In)",
    trigger: "User clicks Subscribe Now on the paywall (non-logged-in)",
    fields: {
      event: { exact: "paywall_subscribe_button_click", required: true },
      auth_status: { exact: "non_logged_in", required: true },
      uuid: { exact: "NA", required: true },
      page_url: { type: "url", required: true },
    },
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
      uuid: uuidField,
    },
  },
  {
    event: "ad_lite_button_click",
    variant: "Go Ad Lite Button Click (Non-Logged-In)",
    trigger: "User clicks Go Ad Lite above an advertisement (non-logged-in)",
    fields: {
      event: { exact: "ad_lite_button_click", required: true },
      ad_slot_name: s({ required: true }),
      auth_status: { exact: "non_logged_in", required: true },
      uuid: { exact: "NA", required: true },
    },
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
      uuid: uuidField,
    },
  },
  {
    event: "subscription_header_button_click",
    variant: "Subscription Header Button Click (Non-Logged-In)",
    trigger: "User clicks Subscribe in the website header (non-logged-in)",
    fields: {
      event: { exact: "subscription_header_button_click", required: true },
      auth_status: { exact: "non_logged_in", required: true },
      source: en(["DH_site", "DH_epaper"]),
      uuid: { exact: "NA", required: true },
    },
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
      currency: en(CURRENCIES),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      currency: en(CURRENCIES),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      currency: en(CURRENCIES),
    },
    cross: (p) => planPriceMismatch(p.from_plan as string, p.from_price as number),
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
      currency: en(CURRENCIES),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      user_type: en(["new user", "returning user"]),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
    sequenceTrigger: true,
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
      reference_id: s({ required: true }),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      currency: en(CURRENCIES),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      plan_price: en([150, 1499, 2999]),
    },
    cross: (p) => planPriceMismatch(p.plan_name as string, p.plan_price as number),
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
      currency: en(CURRENCIES),
    },
  },

  /* ---------- renewal_prompt_impression ---------- */
  {
    event: "renewal_prompt_impression",
    variant: "Renewal Prompt Impression",
    trigger: "'Your subscription has expired' popup appears",
    fields: {
      event: { exact: "renewal_prompt_impression", required: true },
      uuid: uuidField,
    },
  },

  /* ---------- accept_popup ---------- */
  {
    event: "accept_popup",
    variant: "Accept Popup",
    trigger: "User clicks Renew Now on subscription-expired popup",
    fields: {
      event: { exact: "accept_popup", required: true },
      uuid: uuidField,
    },
  },

  /* ---------- dismiss_popup ---------- */
  {
    event: "dismiss_popup",
    variant: "Dismiss Popup",
    trigger: "User dismisses the subscription-expired popup (Remind me later / click outside)",
    fields: {
      event: { exact: "dismiss_popup", required: true },
      uuid: uuidField,
    },
  },
];

/** Schemas grouped by event name (multiple variants per name allowed). */
export function schemasForEvent(eventName: string): EventSchema[] {
  return EVENT_SCHEMAS.filter((s) => s.event === eventName);
}

/** True if any schema exists for this event name. */
export function hasSchemaForEvent(eventName: string): boolean {
  return schemasForEvent(eventName).length > 0;
}
