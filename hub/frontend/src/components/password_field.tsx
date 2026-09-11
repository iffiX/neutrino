import { Meter } from "./meter";
import { PasswordInput } from "./password_input";
import { t, useLanguage } from "../i18n";
import { passwordShortfall, passwordStrength } from "../password_strength";
import type { PasswordRules } from "../password_strength";

import "./password_field.css";

/**
 * A password being chosen: the field, its strength, and its repeat.
 *
 * Every place the panel sets a password — the wizard's panel password and
 * vault passphrase, the settings page's reset — draws this pair, so the
 * strength reading, the shortfall sentence and the match check look and
 * behave the same everywhere. Which rule set applies is the caller's.
 */

interface PasswordFieldProps {
  label: string;
  /** The label over the repeat field; "Again" when not given. */
  repeatLabel?: string;
  /** The requirement, worded when the field draws. */
  hint: () => string;
  value: string;
  repeated: string;
  rules: PasswordRules;
  autoFocus?: boolean;
  onChange: (value: string) => void;
  onRepeatedChange: (value: string) => void;
}

export function PasswordField({
  label,
  repeatLabel,
  hint,
  value,
  repeated,
  rules,
  autoFocus,
  onChange,
  onRepeatedChange,
}: PasswordFieldProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const strength = passwordStrength(value, rules);
  const shortfall = value.length > 0 ? passwordShortfall(value, rules) : null;

  return (
    <>
      <label className="field">
        <span className="field_label password_field_head">
          <span>{label}</span>
          <Meter
            percent={strength.percent}
            tone={strength.tone}
            label={strength.label}
          />
        </span>
        <PasswordInput
          value={value}
          autoFocus={autoFocus}
          onChange={onChange}
        />
        {shortfall !== null ? (
          <span className="field_error">{shortfall}</span>
        ) : (
          <span className="field_hint">{hint()}</span>
        )}
      </label>
      <label className="field">
        <span className="field_label">
          {repeatLabel ?? t("ui.password.repeat")}
        </span>
        <PasswordInput value={repeated} onChange={onRepeatedChange} />
        {repeated.length > 0 && repeated !== value && (
          <span className="field_error">{t("ui.password.mismatch")}</span>
        )}
      </label>
    </>
  );
}
