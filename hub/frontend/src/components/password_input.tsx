import { useState } from "react";

import { Icon } from "./icon";

import "./password_input.css";

/**
 * A secret field with a reveal toggle.
 *
 * Every place the panel takes a secret uses this, so the show/hide affordance
 * is consistent and a mistyped password can always be checked. The value stays
 * controlled by the caller; only the masked/plain state is local.
 *
 * The panel's secrets are node keys, device passwords and API tokens, not
 * logins, so the browser's password manager has no business offering to save
 * or generate here. A `type="password"` input summons it regardless of
 * `autocomplete`, so where the engine can mask plain text
 * (`-webkit-text-security`) the field stays `type="text"` and masks with CSS;
 * elsewhere it falls back to a real password input.
 */

const IS_CSS_MASK_SUPPORTED =
  typeof CSS !== "undefined" && CSS.supports("-webkit-text-security", "disc");

interface PasswordInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

export function PasswordInput({
  value,
  onChange,
  placeholder,
  autoFocus,
}: PasswordInputProps) {
  const [isRevealed, setIsRevealed] = useState(false);
  const isCssMasked = IS_CSS_MASK_SUPPORTED && !isRevealed;

  return (
    <div className="password_input">
      <input
        className={`input password_input_field${
          isCssMasked ? " password_input_field--masked" : ""
        }`}
        type={isRevealed || IS_CSS_MASK_SUPPORTED ? "text" : "password"}
        name="secret"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        data-1p-ignore=""
        data-lpignore="true"
        autoFocus={autoFocus}
        onChange={(event) => onChange(event.target.value)}
      />
      <button
        type="button"
        className="password_input_toggle"
        onClick={() => setIsRevealed((current) => !current)}
        title={isRevealed ? "Hide" : "Show"}
        aria-label={isRevealed ? "Hide password" : "Show password"}
        tabIndex={-1}
      >
        <Icon name={isRevealed ? "eye_off" : "eye"} size={15} />
      </button>
    </div>
  );
}
