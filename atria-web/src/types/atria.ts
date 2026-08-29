/**
 * Domain types, written by hand against what the engine actually emits.
 *
 * The generated OpenAPI types are structurally correct but useless here: the
 * FastAPI endpoints return bare JSONResponse, so every body types as `unknown`.
 * These are the real shapes, verified against a live /v1/queue response.
 *
 * Nothing here re-implements clinical logic. Bands, reasons and outcomes are
 * decided server-side; the client only renders them.
 */

export type Confidence = "HIGH" | "MODERATE" | "LOW";
export type Lane = "RESUS" | "ACUTE" | "FAST TRACK";
export type RowState = "STABLE" | "ESCALATED" | "AWAITING" | "IN TREATMENT";

export type Vitals = Partial<
  Record<"heartrate" | "sbp" | "o2sat" | "resprate" | "temperature", number>
>;

export interface QueueRow {
  stay_id: number;
  ticket: string;
  band: number;
  band_before: number | null;
  state: RowState;
  lane: Lane;
  complaint: string;
  age: number | null;
  gender: string | null;
  waited: number;
  overdue_by: number;
  readings: number;
  risk: number;
  confidence: Confidence;
  diagnostic_confidence: Confidence;
  reasons: string[];
  missing: string[];
  conflicts: string[];
  pathway: string | null;
  red_flag: string | null;
  needs_measurement: string | null;
  abstained: boolean;
  abstain_reason: string;
  worsening: boolean;
  signed_off: boolean;
  vitals: Vitals;
}

export interface TickerItem {
  at: string;
  kind: "arrived" | "seen" | "left" | "escalated";
  ticket: string;
  detail: string;
}

export interface Snapshot {
  now: string;
  degraded: boolean;
  rows: QueueRow[];
  ticker: TickerItem[];
  lanes: Record<Lane, number>;
  waiting: number;
  in_treatment: number;
  seen: number;
  slots: number;
  escalated: number;
  abstained: number;
  p95_ms: number | null;
  audit_entries: number;
  audit_intact: boolean;
}

/** Blind-assessment stages, mirroring layer3/workflow.py. */
export type Stage = "awaiting_nurse" | "compared" | "signed";

export type Outcome =
  | "match"
  | "nurse_escalation"
  | "nurse_downgrade"
  | "guardrail"
  | "uncertain";

/**
 * Before the nurse commits, the server sends no recommendation at all — the
 * fields below are absent, not null. A client cannot leak what it never receives.
 */
export interface AssessmentView {
  stay_id: number;
  stage: Stage;
  cycle: number;
  nurse_esi: number | null;
  revealed: boolean;
  guardrail: boolean;
  atria_esi?: number | null;
  atria_abstained?: boolean;
  outcome?: Outcome | null;
  needs_reason?: boolean;
  final_esi?: number | null;
  reason_code?: string;
}

export interface ForecastPoint {
  minute: number;
  in_treatment: number;
  waiting: number;
}

export interface Forecast {
  points: ForecastPoint[];
  staffed_spaces: number;
  open_spaces: number;
  arrivals_next_hour: number;
  wait_buffer_minutes: number;
  state: "Steady" | "Busy" | "Surge";
  explanation: string;
  assumptions: string[];
  version: string;
}

export interface AuditEvent {
  seq: number;
  at: string;
  kind: string;
  stay_id: number;
  hash: string;
  prev: string;
  [extra: string]: unknown;
}

export interface History {
  mode: string;
  intact: boolean;
  note: string;
  events: AuditEvent[];
}

export const ESI_LABEL: Record<number, string> = {
  1: "Resuscitation",
  2: "Emergent",
  3: "Urgent",
  4: "Less urgent",
  5: "Non-urgent",
};

export const ESI_MEANING: Record<number, string> = {
  1: "Needs a life-saving intervention now",
  2: "High risk, or time-critical — cannot wait",
  3: "Stable enough to wait briefly; likely several resources",
  4: "Stable; likely one resource",
  5: "Stable; likely nothing beyond an examination",
};

export const REASON_CODES: Record<string, string> = {
  reassessed_at_bedside: "I reassessed at the bedside",
  clinically_well: "Vitals look alarming, the patient does not",
  known_baseline: "These readings are normal for this patient",
  artefact: "The reading is an artefact",
  resource_constraint: "Triage under genuine scarcity",
  other: "Other",
};

/** Adult reference ranges, shown so a number means something on its own. */
export const VITAL_REF: Record<string, { label: string; range: string; unit: string }> = {
  heartrate: { label: "HR", range: "50–110", unit: "bpm" },
  sbp: { label: "SBP", range: "90–180", unit: "mmHg" },
  o2sat: { label: "SpO₂", range: "≥94", unit: "%" },
  resprate: { label: "RR", range: "10–30", unit: "/min" },
  temperature: { label: "Temp", range: "36–38.5", unit: "°C" },
};

/**
 * Shadow mode's report: what ATRIA would have done, while doing nothing.
 * `escalations_for_review` is the list a department actually chart-reviews —
 * the rate on its own does not tell anyone whether ATRIA was right to disagree.
 */
export interface ShadowReport {
  enabled: boolean;
  baseline_band: number;
  n: number;
  agreement_rate?: number;
  would_have_escalated?: number;
  would_have_escalated_rate?: number;
  would_have_lowered?: number;
  band_delta_histogram?: Record<string, number>;
  escalations_for_review?: {
    stay_id: number;
    at: string;
    from: number;
    to: number;
    reasons: string[];
  }[];
  note?: string;
}
