/**
 * Schema-driven validation engine for the Prajavani Paywall Data Layer spec.
 *
 * Pure, framework-free, and unit-testable. Given a dataLayer payload, picks the
 * matching schema(s) by event name, runs field checks (required / exact / enum /
 * type / uuid / datetime / url), cross-field checks, and reports PASS / FAIL /
 * WARN / UNCHECKED.
 */
import {
  EventSchema,
  FieldSpec,
  ValidationIssue,
  ValidationResult,
  ValidationStatus,
  isBool,
  isIsoDate,
  isNumber,
  isUrl,
  isUuid,
  schemasForEvent,
} from "./schemas";

export interface NormalizedPayload {
  /** Event name (the value of `event`). */
  eventName: string;
  /** Cleaned payload with DOM/window/functions/circular refs removed. */
  payload: Record<string, unknown>;
  /** True if the original push was a gtag('event', name, {...}) Arguments object. */
  fromGtag: boolean;
  /** Raw payload reference (for display). */
  raw: unknown;
}

/** Safe clone: never throws on DOM nodes, windows, functions, circular refs. */
export function safeClone(value: unknown, depth = 0, seen = new Set<unknown>()): unknown {
  if (value === null || value === undefined) return value;
  const t = typeof value;
  if (t === "string" || t === "boolean") return value;
  if (t === "number") return Number.isFinite(value as number) ? value : String(value);
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
  const out: Record<string, unknown> = {};
  try {
    for (const k of Object.keys(value as Record<string, unknown>)) {
      try {
        out[k] = safeClone((value as Record<string, unknown>)[k], depth + 1, seen);
      } catch {
        out[k] = "[unserializable]";
      }
    }
  } catch {
    /* cross-origin / proxied */
  }
  return out;
}

/** Normalize a gtag 'Arguments' object into a payload. */
export function normalizeGtagArguments(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null) return {};
  const raw = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(raw)) {
    try {
      const v = raw[k];
      if (k === "event_category" && typeof v === "string") out.event = v;
      else if (k === "event_label" && typeof v === "string" && !out.event) out.event = v;
      else out[k] = v;
    } catch {
      /* skip */
    }
  }
  return out;
}

/** Turn any pushed value into a normalized payload (never throws). */
export function normalizePayload(value: unknown): NormalizedPayload | null {
  if (typeof value !== "object" || value === null) return null;

  // gtag("event", name, {...}) → dataLayer gets a gtag.js Arguments object
  // shaped like { event: "event_name", ...params } or with 0:name, 1:params.
  const raw = value as Record<string, unknown>;
  let fromGtag = false;
  let payload: Record<string, unknown> | null = null;

  if (raw[0] === "event") {
    // gtag.js Arguments shapes:
    //   {0: "event", 1: "event_name", 2: {params}}
    //   {0: "event", 1: {event: "event_name", ...params}}
    fromGtag = true;
    if (typeof raw[1] === "string") {
      payload = { event: raw[1] };
      if (raw[2] && typeof raw[2] === "object") {
        payload = { ...payload, ...normalizeGtagArguments(raw[2] as Record<string, unknown>) };
      }
    } else if (raw[1] && typeof raw[1] === "object") {
      payload = normalizeGtagArguments(raw[1] as Record<string, unknown>);
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
    // Unknown shape: keep it visible as an unnamed push.
    payload = { event: "(unnamed)", ...(raw as Record<string, unknown>) };
  }

  const eventName = typeof payload.event === "string" ? payload.event : "(unnamed)";
  return {
    eventName,
    payload: safeClone(payload) as Record<string, unknown>,
    fromGtag,
    raw: value,
  };
}

/* ------------------------------------------------------------------ */
/* Field check helpers                                                */
/* ------------------------------------------------------------------ */

function checkField(
  field: string,
  spec: FieldSpec,
  payload: Record<string, unknown>,
  issues: ValidationIssue[],
): void {
  const value = payload[field];
  const present = value !== undefined && value !== null;

  if (!present) {
    if (spec.required) {
      issues.push({ field, reason: "required field is missing", severity: "FAIL" });
    }
    return;
  }

  if (spec.exact !== undefined) {
    if (value !== spec.exact) {
      issues.push({
        field,
        reason: `expected exactly "${spec.exact}", got ${jsonPreview(value)}`,
        severity: "FAIL",
      });
    }
    return;
  }

  if (spec.enum !== undefined) {
    // Loose match: the CMS/GTM sometimes sends "100" (string) where the spec
    // lists 100 (number), e.g. access_level_value, plan_price. Compare by
    // string form so a real, valid value never gets flagged as a FAIL just
    // because of type, while still catching genuinely wrong values.
    if (!spec.enum.some((e) => String(e) === String(value))) {
      issues.push({
        field,
        reason: `expected one of [${spec.enum.map((e) => JSON.stringify(e)).join(", ")}], got ${jsonPreview(value)}`,
        severity: "FAIL",
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

function jsonPreview(value: unknown): string {
  try {
    const s = JSON.stringify(value);
    if (s === undefined) return String(value);
    return s.length > 60 ? s.slice(0, 60) + "…" : s;
  } catch {
    return String(value);
  }
}

/* ------------------------------------------------------------------ */
/* Entry point                                                        */
/* ------------------------------------------------------------------ */

/**
 * True if `schema` is even a candidate for this payload, based on the
 * schema's own exact-match discriminator field(s) — currently `page_type`.
 *
 * This does NOT invent new spec data. `page_type: { exact: "article_page" }`
 * already exists in the Premium Article page_view schema; we're just using
 * it to decide whether the schema applies before running full field
 * validation, instead of running it unconditionally and reporting every
 * other page_view shape (e.g. page_type: "home_page") as a pile of FAILs
 * against a schema that was never meant to describe it.
 */
function schemaApplies(schema: EventSchema, payload: Record<string, unknown>): boolean {
  const pageTypeSpec = schema.fields.page_type;
  if (pageTypeSpec?.exact !== undefined) {
    const actual = payload.page_type;
    if (actual !== undefined && actual !== pageTypeSpec.exact) {
      return false;
    }
  }
  return true;
}

/**
 * Validate a normalized payload against the spec. If no schema exists for the
 * event name, OR no existing schema variant's discriminator matches this
 * payload's shape, returns UNCHECKED with uncovered=true (the "CHECK: —"
 * case) rather than forcing an inapplicable schema onto it.
 */
export function validateEvent(normalized: NormalizedPayload): ValidationResult {
  const schemas = schemasForEvent(normalized.eventName);
  if (schemas.length === 0) {
    return { status: "UNCHECKED", issues: [], uncovered: true };
  }

  const candidates = schemas.filter((schema) => schemaApplies(schema, normalized.payload));
  if (candidates.length === 0) {
    return { status: "UNCHECKED", issues: [], uncovered: true };
  }

  // A payload may match multiple variants of the same event name (e.g. the two
  // login variants). Validate against each, and pick the result with the fewest
  // FAIL issues — a payload valid for one variant should PASS.
  let best: ValidationResult | null = null;
  for (const schema of candidates) {
    const issues: ValidationIssue[] = [];
    for (const [field, spec] of Object.entries(schema.fields)) {
      checkField(field, spec, normalized.payload, issues);
    }
    if (schema.cross) {
      const crossErr = schema.cross(normalized.payload);
      if (crossErr) issues.push({ field: "(cross-field)", reason: crossErr, severity: "FAIL" });
    }
    const failCount = issues.filter((i) => i.severity === "FAIL").length;
    const warnCount = issues.filter((i) => i.severity === "WARN").length;
    const status: ValidationStatus =
      failCount > 0 ? "FAIL" : warnCount > 0 ? "WARN" : "PASS";
    const result: ValidationResult = { status, issues, uncovered: false };
    if (!best || failCount < best.issues.filter((i) => i.severity === "FAIL").length) {
      best = result;
    }
  }
  return best!;
}
