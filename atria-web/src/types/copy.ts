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
  1: "Resuscitation — needs a life-saving intervention now",
  2: "Emergent — high risk or time-critical, cannot wait",
  3: "Urgent — stable enough to wait briefly, likely several resources",
  4: "Less urgent — stable, likely one resource",
  5: "Non-urgent — stable, likely nothing beyond an examination",
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
  artefact: "The reading is wrong — bad probe or cuff",
  resource_constraint: "We do not have the capacity right now",
  other: "Something else",
};

export const VITAL_INFO: Record<string, { label: string; full: string; normal: string; unit: string }> = {
  heartrate:   { label: "Pulse",     full: "Heart rate",        normal: "50–110",  unit: "bpm" },
  sbp:         { label: "BP",        full: "Blood pressure",    normal: "90–180",  unit: "mmHg" },
  o2sat:       { label: "Oxygen",    full: "Oxygen saturation", normal: "94 +",    unit: "%" },
  resprate:    { label: "Breathing", full: "Breaths per minute", normal: "10–30",  unit: "/min" },
  temperature: { label: "Temp",      full: "Temperature",       normal: "36–38.5", unit: "°C" },
};
