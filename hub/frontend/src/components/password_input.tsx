import { useState } from "react";

import { Icon } from "./icon";

import "./password_input.css";

/**
 * A password field with a reveal toggle.
 *
 * Every place the panel takes a secret uses this, so the show/hide affordance
 * is consistent and a mistyped password can always be checked. The value stays
 * controlled by the caller; only the masked/plain state is local.
 */

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

  return (
    <div className="password_input">
      <input
        className="input password_input_field"
        type={isRevealed ? "text" : "password"}
        value={value}
        placeholder={placeholder}
        autoComplete="new-password"
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
