/**
 * How good a password is, in the terms a person can act on.
 *
 * Each password the hub takes is graded against its own rule set: the panel
 * password needs length alone, the vault master passphrase needs length and
 * every character class. Everything above a rule is a preference, and this is
 * how the panel says so without turning a preference into a refusal. Length
 * and variety both count, because either alone is a password somebody
 * guesses: sixteen lowercase letters and `Aa1!` are both weak for opposite
 * reasons.
 */

import { t } from "./i18n";
import type { MeterTone } from "./components/meter";

/** What one password field refuses. Thresholds mirror the backend's. */
export interface PasswordRules {
  min_length: number;
  /** Whether every class — lowercase, uppercase, digit, symbol — is required. */
  is_every_class_needed: boolean;
}

/** What the panel's own password must clear. */
export const PANEL_PASSWORD_RULES: PasswordRules = {
  min_length: 8,
  is_every_class_needed: false,
};

/** What the vault master passphrase must clear. */
export const VAULT_PASSPHRASE_RULES: PasswordRules = {
  min_length: 16,
  is_every_class_needed: true,
};

/** The panel password's requirement, said under its field. */
export const panelPasswordHint = (): string =>
  t("ui.password.panel_hint", { count: PANEL_PASSWORD_RULES.min_length });

/** The vault passphrase's requirement, said under its field. */
export const vaultPassphraseHint = (): string =>
  t("ui.password.vault_hint", { count: VAULT_PASSPHRASE_RULES.min_length });

export interface PasswordStrength {
  /** How full the bar is, 0 to 100. */
  percent: number;
  /** One word for it, empty while nothing has been typed. */
  label: string;
  tone: MeterTone;
  /** Whether it clears the rule, rather than whether it is any good. */
  is_allowed: boolean;
}

/** The character families a password can draw on, keyed for the shortfall
 * sentence. */
const FAMILIES: { pattern: RegExp; missingKey: string }[] = [
  { pattern: /[a-z]/, missingKey: "ui.password.class_lowercase" },
  { pattern: /[A-Z]/, missingKey: "ui.password.class_uppercase" },
  { pattern: /[0-9]/, missingKey: "ui.password.class_digit" },
  { pattern: /[^A-Za-z0-9]/, missingKey: "ui.password.class_symbol" },
];
/** The most a password can score, which is what fills the bar. */
const TOP_SCORE = 6;

interface PasswordGrade {
  /** The highest score this grade covers. */
  top: number;
  labelKey: string;
  tone: MeterTone;
}

/** What a password that scores everything is called. */
const STRONGEST: PasswordGrade = {
  top: TOP_SCORE,
  labelKey: "ui.password.grade_strong",
  tone: "ok",
};
/** By rising score; the first grade the score fits inside wins. */
const GRADES: PasswordGrade[] = [
  { top: 2, labelKey: "ui.password.grade_weak", tone: "error" },
  { top: 3, labelKey: "ui.password.grade_fair", tone: "warn" },
  { top: 5, labelKey: "ui.password.grade_good", tone: "accent" },
  STRONGEST,
];

export function passwordStrength(
  password: string,
  rules: PasswordRules,
): PasswordStrength {
  if (password.length === 0) {
    return { percent: 0, label: "", tone: "error", is_allowed: false };
  }
  if (password.length < rules.min_length) {
    return {
      // Short of the rule, so the bar shows a stub rather than nothing: an
      // empty bar beside characters that are plainly there reads as broken.
      percent: 10,
      label: t("ui.password.grade_too_short"),
      tone: "error",
      is_allowed: false,
    };
  }
  const families = FAMILIES.filter((family) =>
    family.pattern.test(password),
  ).length;
  if (rules.is_every_class_needed && families < FAMILIES.length) {
    return {
      percent: 25,
      label: t("ui.password.grade_too_plain"),
      tone: "error",
      is_allowed: false,
    };
  }
  // Long enough to be allowed at all, then a point per extra family and a
  // point at each length where guessing it gets meaningfully harder.
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
    label: t(grade.labelKey),
    tone: grade.tone,
    is_allowed: true,
  };
}

/** The sentence naming what the password still lacks, null once it clears. */
export function passwordShortfall(
  password: string,
  rules: PasswordRules,
): string | null {
  if (password.length < rules.min_length) {
    return t("ui.password.shortfall_length", { count: rules.min_length });
  }
  if (!rules.is_every_class_needed) {
    return null;
  }
  const missing = FAMILIES.filter(
    (family) => !family.pattern.test(password),
  ).map((family) => t(family.missingKey));
  if (missing.length === 0) {
    return null;
  }
  return t("ui.password.shortfall_classes", { names: joinNames(missing) });
}

/** Whether the password clears its rule and its repeat matches it. */
export function isPasswordAccepted(
  password: string,
  repeated: string,
  rules: PasswordRules,
): boolean {
  return passwordStrength(password, rules).is_allowed && password === repeated;
}

function joinNames(names: string[]): string {
  if (names.length === 1) {
    return names[0] ?? "";
  }
  return [
    names.slice(0, -1).join(t("ui.password.name_separator")),
    names[names.length - 1],
  ].join(t("ui.password.name_last_separator"));
}
