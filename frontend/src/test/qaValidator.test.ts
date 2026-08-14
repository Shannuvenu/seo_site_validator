/**
 * Tests for the schema-driven validation engine against the Prajavani Paywall
 * Data Layer spec — cases 1–39 from the requirements.
 */
import { describe, it, expect } from "vitest";
import { normalizePayload, validateEvent } from "../qa/validator";
import { EVENT_SCHEMAS, schemasForEvent } from "../qa/schemas";

const UUID = "3b241101-e2bb-4255-8caf-4136c566a962";
const DATE = "2026-01-15T10:30:00+05:30";

/** Build a normalized payload from a plain object. */
function check(payload: Record<string, unknown>) {
  const norm = normalizePayload(payload);
  if (!norm) throw new Error("normalize failed");
  return validateEvent(norm);
}

/** Base valid page_view payload. */
function validPageView(overrides: Record<string, unknown> = {}) {
  return {
    event: "page_view",
    article_id: "3933157",
    article_type: "syndicated",
    auth_status: "logged_in",
    author_id: "123",
    author_name: "DH Web Desk",
    comment_number: 3,
    content_id: UUID,
    content_title: "Sample headline",
    created_date: DATE,
    creator_name: "DH Web Desk",
    last_updated_date: DATE,
    page_type: "article_page",
    published_date: DATE,
    section_name: "Karnataka",
    story_tags: "karnataka,news",
    story_words: 259,
    uuid: UUID,
    premium_article: "Yes",
    access_level_value: 100,
    ...overrides,
  };
}

describe("page_view (Premium Article spec)", () => {
  it("1. valid page_view passes", () => {
    const r = check(validPageView());
    expect(r.status).toBe("PASS");
    expect(r.issues).toHaveLength(0);
  });

  it("2. missing required field fails", () => {
    const p = validPageView() as Record<string, unknown>;
    delete p.content_title;
    const r = check(p);
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "content_title" && i.reason.includes("missing"))).toBe(true);
  });

  it("3. invalid UUID fails", () => {
    const r = check(validPageView({ content_id: "not-a-uuid" }));
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "content_id" && i.reason.includes("UUID"))).toBe(true);
  });

  it("4. invalid date fails", () => {
    const r = check(validPageView({ published_date: "yesterday-ish" }));
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "published_date")).toBe(true);
  });

  it("5. invalid auth_status fails", () => {
    const r = check(validPageView({ auth_status: "anonymous" }));
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "auth_status")).toBe(true);
  });

  it("6. invalid premium_article fails", () => {
    const r = check(validPageView({ premium_article: "maybe" }));
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "premium_article")).toBe(true);
  });

  it("7. invalid access_level_value fails", () => {
    const r = check(validPageView({ access_level_value: 500 }));
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "access_level_value")).toBe(true);
  });
});

describe("user_properties_update", () => {
  const base = {
    event: "user_properties_update",
    auth_status: "logged_in",
    subscription_status: "non_subscriber",
    uuid: UUID,
    account_created_date: DATE,
    plan_name: "NA",
    plan_price: "NA",
  };

  it("8. valid logged-in non-subscriber passes", () => {
    expect(check(base).status).toBe("PASS");
  });

  it("9. valid logged-in subscriber passes", () => {
    const p = {
      ...base,
      subscription_status: "subscriber",
      plan_name: "monthly",
      plan_price: 150,
    };
    expect(check(p).status).toBe("PASS");
  });

  it("10. invalid subscriber plan_name fails", () => {
    const p = {
      ...base,
      subscription_status: "subscriber",
      plan_name: "annual",
      plan_price: 1499,
    };
    const r = check(p);
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "plan_name")).toBe(true);
  });

  it("11. invalid subscriber plan_price fails", () => {
    const p = {
      ...base,
      subscription_status: "subscriber",
      plan_name: "1-year",
      plan_price: 999,
    };
    const r = check(p);
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "plan_price")).toBe(true);
  });

  it("12. plan_name/plan_price mismatch fails (cross-field)", () => {
    const p = {
      ...base,
      subscription_status: "subscriber",
      plan_name: "monthly",
      plan_price: 2999,
    };
    const r = check(p);
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "(cross-field)" && i.reason.includes("does not match"))).toBe(true);
  });

  it("13. valid non-logged-in passes (no account_created_date required)", () => {
    const p = {
      event: "user_properties_update",
      auth_status: "non_logged_in",
      subscription_status: "NA",
      uuid: "NA",
      plan_name: "NA",
      plan_price: "NA",
    };
    const r = check(p);
    expect(r.status).toBe("PASS");
    // account_created_date must NOT be flagged as missing.
    expect(r.issues.some((i) => i.field === "account_created_date")).toBe(false);
  });
});

describe("sign_up", () => {
  const base = {
    event: "sign_up",
    method: "email",
    source: "header_button",
    uuid: UUID,
    account_created_date: DATE,
    marketing_and_promotion_consent: true,
    Newsletter_consent: false,
  };

  it("14. valid sign_up passes", () => {
    expect(check(base).status).toBe("PASS");
  });

  it("15. invalid sign_up method fails", () => {
    const r = check({ ...base, method: "phone" });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "method")).toBe(true);
  });

  it("16. invalid sign_up source fails", () => {
    const r = check({ ...base, source: "footer" });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "source")).toBe(true);
  });
});

describe("login", () => {
  const base = {
    event: "login",
    method: "email",
    source: "header_button",
    uuid: UUID,
    account_created_date: DATE,
    marketing_and_promotion_consent: true,
    Newsletter_consent: true,
  };

  it("17. valid login (without subscription) passes", () => {
    expect(check(base).status).toBe("PASS");
  });

  it("17b. valid login with subscription (source without paywall) passes", () => {
    expect(check({ ...base, source: "ham_menu" }).status).toBe("PASS");
  });

  it("18. invalid login method fails", () => {
    const r = check({ ...base, method: "sms" });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "method")).toBe(true);
  });

  it("18b. login with subscription rejects paywall source per spec (variant check)", () => {
    // The With-Subscription variant's allowed source omits "paywall". A login
    // with source=paywall matches the WITHOUT-subscription variant (which does
    // allow paywall), so overall it PASSes as "login (without subscription)".
    // Validate that the with-subscription schema specifically rejects it.
    const withSub = schemasForEvent("login").find((s) => s.variant?.includes("With Subscription"));
    expect(withSub).toBeTruthy();
    const issues: string[] = [];
    const sourceSpec = withSub!.fields["source"];
    if (sourceSpec?.enum && !sourceSpec.enum.includes("paywall")) {
      issues.push("source");
    }
    expect(issues).toContain("source");
  });
});

describe("logout", () => {
  const base = { event: "logout", source: "profile", uuid: UUID, subscription_status: "subscribed" };

  it("19. valid logout passes", () => {
    expect(check(base).status).toBe("PASS");
  });

  it("20. invalid logout subscription_status fails", () => {
    const r = check({ ...base, subscription_status: "gold" });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "subscription_status")).toBe(true);
  });
});

describe("paywall + subscription clicks", () => {
  it("21. valid paywall_impression logged-in passes", () => {
    const r = check({
      event: "paywall_impression",
      auth_status: "logged_in",
      uuid: UUID,
      page_url: "https://prajavani.net/article/1",
    });
    expect(r.status).toBe("PASS");
  });

  it("22. valid paywall_impression non-logged-in passes", () => {
    const r = check({
      event: "paywall_impression",
      auth_status: "non_logged_in",
      uuid: "NA",
      page_url: "https://prajavani.net/article/1",
    });
    expect(r.status).toBe("PASS");
  });

  it("23. valid paywall subscribe click passes", () => {
    const r = check({
      event: "paywall_subscribe_button_click",
      auth_status: "non_logged_in",
      uuid: "NA",
      page_url: "https://prajavani.net/article/1",
    });
    expect(r.status).toBe("PASS");
  });

  it("24. valid ad_lite_button_click passes", () => {
    const r = check({
      event: "ad_lite_button_click",
      ad_slot_name: "DH_MWeb_AT_Top",
      auth_status: "logged_in",
      uuid: UUID,
    });
    expect(r.status).toBe("PASS");
  });

  it("25. valid subscription header click passes", () => {
    const r = check({
      event: "subscription_header_button_click",
      auth_status: "logged_in",
      source: "DH_site",
      uuid: UUID,
    });
    expect(r.status).toBe("PASS");
  });

  it("26. valid subscription plan selection passes", () => {
    const r = check({
      event: "subscription_plan_selection",
      auth_status: "non_logged_in",
      uuid: "NA",
      plan_name: "1-year",
      plan_price: 1499,
      currency: "INR",
    });
    expect(r.status).toBe("PASS");
  });
});

describe("payment flow", () => {
  it("27. valid plan_edit passes", () => {
    const r = check({
      event: "plan_edit",
      uuid: UUID,
      from_plan: "1-year",
      from_price: 1499,
      currency: "INR",
    });
    expect(r.status).toBe("PASS");
  });

  it("28. valid proceed_to_pay_click passes", () => {
    const r = check({
      event: "proceed_to_pay_click",
      uuid: UUID,
      plan_name: "monthly",
      plan_price: 150,
      currency: "INR",
    });
    expect(r.status).toBe("PASS");
  });

  it("29. valid purchase passes", () => {
    const r = check({
      event: "purchase",
      uuid: UUID,
      plan_name: "2-year",
      plan_price: 2999,
      currency: "INR",
      transaction_id: "pay_abc123",
      redirection_url: "https://prajavani.net/subscription/success",
      user_type: "new user",
    });
    expect(r.status).toBe("PASS");
  });

  it("30. invalid purchase plan fails", () => {
    const r = check({
      event: "purchase",
      uuid: UUID,
      plan_name: "decade",
      plan_price: 2999,
      currency: "INR",
      transaction_id: "pay_abc123",
      redirection_url: "https://prajavani.net/subscription/success",
      user_type: "new user",
    });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "plan_name")).toBe(true);
  });

  it("31. invalid purchase user_type fails", () => {
    const r = check({
      event: "purchase",
      uuid: UUID,
      plan_name: "1-year",
      plan_price: 1499,
      currency: "INR",
      transaction_id: "pay_abc123",
      redirection_url: "https://prajavani.net/subscription/success",
      user_type: "VIP",
    });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "user_type")).toBe(true);
  });

  it("32. valid payment_failed passes", () => {
    const r = check({
      event: "payment_failed",
      uuid: UUID,
      plan_name: "monthly",
      plan_price: 150,
      currency: "INR",
      reference_id: "pay_fail_1",
    });
    expect(r.status).toBe("PASS");
  });

  it("33. valid retry_payment_click passes", () => {
    const r = check({
      event: "retry_payment_click",
      uuid: UUID,
      plan_name: "monthly",
      plan_price: 150,
      currency: "INR",
    });
    expect(r.status).toBe("PASS");
  });
});

describe("renewal + popups", () => {
  it("34. valid renewal_cancellation passes", () => {
    const r = check({
      event: "renewal_cancellation",
      uuid: UUID,
      plan_name: "1-year",
      plan_price: 1499,
    });
    expect(r.status).toBe("PASS");
  });

  it("35. valid plan_change_initiated passes (with 'yearly' per spec)", () => {
    const r = check({
      event: "plan_change_initiated",
      uuid: UUID,
      from_plan: "yearly",
      to_plan: "2-year",
      plan_price: 1499,
      currency: "INR",
    });
    expect(r.status).toBe("PASS");
  });

  it("36. invalid plan_change_initiated from_plan fails", () => {
    const r = check({
      event: "plan_change_initiated",
      uuid: UUID,
      from_plan: "1-year", // spec says "yearly", not "1-year"
      to_plan: "2-year",
      plan_price: 1499,
      currency: "INR",
    });
    expect(r.status).toBe("FAIL");
    expect(r.issues.some((i) => i.field === "from_plan")).toBe(true);
  });

  it("37. valid renewal_prompt_impression passes", () => {
    expect(check({ event: "renewal_prompt_impression", uuid: UUID }).status).toBe("PASS");
  });

  it("38. valid accept_popup passes", () => {
    expect(check({ event: "accept_popup", uuid: UUID }).status).toBe("PASS");
  });

  it("39. valid dismiss_popup passes", () => {
    expect(check({ event: "dismiss_popup", uuid: UUID }).status).toBe("PASS");
  });
});

describe("uncovered events", () => {
  it("unknown event returns UNCHECKED with uncovered=true", () => {
    const norm = normalizePayload({ event: "some_future_event", x: 1 });
    const r = validateEvent(norm!);
    expect(r.status).toBe("UNCHECKED");
    expect(r.uncovered).toBe(true);
    expect(r.issues).toHaveLength(0);
  });
});

describe("gtag normalization", () => {
  it("gtag Arguments object is normalized to an event payload", () => {
    // gtag.js Arguments shape: {0: "event", 1: "page_view", 2: {...}}
    const args = {
      0: "event",
      1: "page_view",
      2: {
        article_id: "3933157",
        article_type: "syndicated",
        auth_status: "non_logged_in",
        author_id: "1",
        author_name: "DH Web Desk",
        comment_number: 3,
        content_id: UUID,
        content_title: "t",
        created_date: DATE,
        creator_name: "DH Web Desk",
        last_updated_date: DATE,
        page_type: "article_page",
        published_date: DATE,
        section_name: "s",
        story_tags: "t",
        story_words: 100,
        uuid: "NA",
        premium_article: "Yes",
        access_level_value: 100,
      },
    };
    const norm = normalizePayload(args);
    expect(norm).not.toBeNull();
    expect(norm!.eventName).toBe("page_view");
    expect(norm!.fromGtag).toBe(true);
    const r = validateEvent(norm!);
    expect(r.status).toBe("PASS");
  });
});

// Sanity: every event name in the spec has at least one schema.
describe("schema coverage", () => {
  it("all spec event names are covered", () => {
    const names = new Set(EVENT_SCHEMAS.map((s) => s.event));
    for (const n of [
      "user_properties_update",
      "sign_up",
      "login",
      "logout",
      "paywall_impression",
      "paywall_subscribe_button_click",
      "ad_lite_button_click",
      "subscription_header_button_click",
      "subscription_plan_selection",
      "plan_edit",
      "proceed_to_pay_click",
      "purchase",
      "payment_failed",
      "retry_payment_click",
      "renewal_cancellation",
      "plan_change_initiated",
      "renewal_prompt_impression",
      "accept_popup",
      "dismiss_popup",
      "page_view",
    ]) {
      expect(names.has(n), `missing schema for ${n}`).toBe(true);
    }
  });
});
