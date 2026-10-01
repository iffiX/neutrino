import { useState } from "react";

import { PasswordInput } from "./password_input";
import { t, useLanguage } from "../i18n";

import "./kept_secret_row.css";

/**
 * One secret the hub keeps: whether it is saved, with Replace and Forget.
 *
 * The field appears only while nothing is saved, after Replace, or while a
 * replacement is typed. With `onSave` a Save button beside the field writes
 * it at once; without it the panel's apply bar carries the typed value. A
 * holder that resets its draft remounts the row to fold the field away.
 */

interface KeptSecretRowProps {
  label: string;
  isKept: boolean;
  /** The replacement typed so far; empty keeps the saved one. */
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  onSave?: () => void;
  onForget?: () => void;
  isBusy?: boolean;
}

export function KeptSecretRow({
  label,
  isKept,
  value,
  onChange,
  placeholder,
  onSave,
  onForget,
  isBusy = false,
}: KeptSecretRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isReplacing, setIsReplacing] = useState(false);

  const isFieldShown = !isKept || isReplacing || value !== "";

  return (
    <div className="kept_secret_row">
      <span className="field_label">{label}</span>
      <span className="kept_secret_state">
        {isKept ? t("ui.kept_secret.kept") : t("ui.kept_secret.missing")}
      </span>
      {isFieldShown ? (
        <>
          <PasswordInput
            value={value}
            onChange={onChange}
            placeholder={placeholder}
            autoFocus={isReplacing}
          />
          {onSave !== undefined && (
            <button
              type="button"
              className="button button--small button--primary"
              disabled={isBusy || value.trim() === ""}
              onClick={onSave}
            >
              {t("ui.kept_secret.save")}
            </button>
          )}
          {isKept && (
            <button
              type="button"
              className="button button--small"
              disabled={isBusy}
              onClick={() => {
                onChange("");
                setIsReplacing(false);
              }}
            >
              {t("ui.kept_secret.cancel")}
            </button>
          )}
        </>
      ) : (
        <>
          <button
            type="button"
            className="button button--small"
            disabled={isBusy}
            onClick={() => setIsReplacing(true)}
          >
            {t("ui.kept_secret.replace")}
          </button>
          {onForget !== undefined && (
            <button
              type="button"
              className="button button--small button--danger"
              disabled={isBusy}
              onClick={onForget}
            >
              {t("ui.kept_secret.forget")}
            </button>
          )}
        </>
      )}
    </div>
  );
}
