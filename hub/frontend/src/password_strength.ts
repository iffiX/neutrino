/**
 * How good a password is, in the terms a person can act on.
 *
 * Eight characters is the rule the hub enforces; everything above that is a
 * preference, and this is how the panel says so without turning a preference
 * into a refusal. Length and variety both count, because either alone is a
 * password somebody guesses: sixteen lowercase letters and `Aa1!` are both
 * weak for opposite reasons.
 */

import type { MeterTone } from "./components/meter";

/** What the hub will not accept. */
export const PASSWORD_MIN_LENGTH = 8;

export interface PasswordStrength {
  /** How full the bar is, 0 to 100. */
  percent: number;
  /** One word for it, empty while nothing has been typed. */
  label: string;
  tone: MeterTone;
  /** Whether it clears the rule, rather than whether it is any good. */
  is_allowed: boolean;
}

/** The character families a password can draw on. */
const FAMILIES = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/];
/** The most a password can score, which is what fills the bar. */
const TOP_SCORE = 6;

interface PasswordGrade {
  /** The highest score this grade covers. */
  top: number;
  label: string;
  tone: MeterTone;
}

/** What a password that scores everything is called. */
const STRONGEST: PasswordGrade = {
  top: TOP_SCORE,
  label: "Strong",
  tone: "ok",
};
/** By rising score; the first grade the score fits inside wins. */
const GRADES: PasswordGrade[] = [
  { top: 2, label: "Weak", tone: "error" },
  { top: 3, label: "Fair", tone: "warn" },
  { top: 5, label: "Good", tone: "accent" },
  STRONGEST,
];

export function passwordStrength(password: string): PasswordStrength {
  if (password.length === 0) {
    return { percent: 0, label: "", tone: "error", is_allowed: false };
  }
  if (password.length < PASSWORD_MIN_LENGTH) {
    return {
      // Short of the rule, so the bar shows a stub rather than nothing: an
      // empty bar beside characters that are plainly there reads as broken.
      percent: 10,
      label: "Too short",
      tone: "error",
      is_allowed: false,
    };
  }
  // Long enough to be allowed at all, then a point per extra family and a
  // point at each length where guessing it gets meaningfully harder.
  const families = FAMILIES.filter((family) => family.test(password)).length;
  let score = families;
  if (password.length >= 12) {
    score += 1;
  }
  if (password.length >= 16) {
    score += 1;
  }
  const grade = GRADES.find((entry) => score <= entry.top) ?? STRONGEST;
  return {
    percent: Math.round((Math.min(score, TOP_SCORE) / TOP_SCORE) * 100),
    label: grade.label,
    tone: grade.tone,
    is_allowed: true,
  };
}
