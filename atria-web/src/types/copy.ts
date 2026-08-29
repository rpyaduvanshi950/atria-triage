/**
 * Plain-language equivalents for everything the engine calls something else.
 *
 * The board previously showed the internal vocabulary — band, abstain, pathway,
 * DX confidence. That is the right language in the code and the wrong language
 * on a screen someone uses at 3am. Nothing here changes behaviour; it changes
 * what the words say.
 */

/** Priority is what a nurse calls it. "Band" is what the ranking code calls it. */
export const PRIORITY_NAME: Record<number, string> = {
  1: "Now",
  2: "Very soon",
  3: "Soon",
  4: "Can wait",
  5: "Can wait longest",
};

export const ESI_FULL: Record<number, string> = {
  1: "Resuscitation. Life-saving intervention now",
  2: "Emergent. High risk, cannot wait",
  3: "Urgent. Stable enough to wait briefly",
  4: "Less urgent. Stable, one resource",
  5: "Non-urgent. Stable, examination only",
};

export const ESI_SHORT: Record<number, string> = {
  1: "Resuscitation",
  2: "Emergent",
  3: "Urgent",
  4: "Less urgent",
  5: "Non-urgent",
};

/** Which of the three gates is closing, said the way a clinician would say it. */
export const PATHWAY_NAME: Record<string, string> = {
  respiratory: "Breathing is the concern",
  circulatory: "Circulation is the concern",
  neurological: "Consciousness is the concern",
};

export const CONFIDENCE_URGENCY: Record<string, string> = {
  HIGH: "Sure how urgent",
  MODERATE: "Fairly sure how urgent",
  LOW: "Unsure how urgent",
};

export const CONFIDENCE_CAUSE: Record<string, string> = {
  HIGH: "Clear what is wrong",
  MODERATE: "Cause not certain",
  LOW: "Cannot say what is wrong",
};

export const LANE_NAME: Record<string, string> = {
  RESUS: "Resus",
  ACUTE: "Acute",
  "FAST TRACK": "Fast track",
};

export const REASON_CHOICES: Record<string, string> = {
  reassessed_at_bedside: "I went and looked at the patient",
  clinically_well: "The numbers look worse than the patient does",
  known_baseline: "These readings are normal for this patient",
  artefact: "The reading is wrong. Bad probe or cuff",
  resource_constraint: "We do not have the capacity right now",
  other: "Something else",
};

export const VITAL_INFO: Record<string, {
  label: string; full: string; normal: string; unit: string;
  /** Outside this, flag it. */
  ok: [number, number];
  /** Outside this, it is a red flag rather than merely abnormal. */
  bad: [number, number];
}> = {
  heartrate:   { label: "Pulse",     full: "Heart rate",         normal: "50-110",  unit: "bpm",
                 ok: [50, 110],   bad: [40, 130] },
  sbp:         { label: "BP",        full: "Blood pressure",     normal: "90-180",  unit: "mmHg",
                 ok: [90, 180],   bad: [80, 200] },
  o2sat:       { label: "Oxygen",    full: "Oxygen saturation",  normal: "94+",     unit: "%",
                 ok: [94, 100],   bad: [90, 100] },
  resprate:    { label: "Breathing", full: "Breaths per minute", normal: "10-30",   unit: "/min",
                 ok: [10, 30],    bad: [8, 36] },
  temperature: { label: "Temp",      full: "Temperature",        normal: "36-38.5", unit: "\u00b0C",
                 ok: [36, 38.5],  bad: [35, 40] },
};

/**
 * How far outside normal a reading is.
 *
 * These thresholds are for COLOUR ONLY. The clinical decision is made in
 * layer0/rules.yaml on the server, against age-banded values a browser does not
 * have. Two sources of truth for a threshold is how they drift, so nothing here
 * may ever change a band, a warning, or what the nurse is asked to justify.
 */
export type VitalLevel = "normal" | "abnormal" | "critical";

export function vitalLevel(key: string, value: number): VitalLevel {
  const info = VITAL_INFO[key];
  if (!info) return "normal";
  const [lo, hi] = info.ok;
  const [blo, bhi] = info.bad;
  if (value < blo || value > bhi) return "critical";
  if (value < lo || value > hi) return "abnormal";
  return "normal";
}
