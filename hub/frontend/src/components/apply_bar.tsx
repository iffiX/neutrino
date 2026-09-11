import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { t, useLanguage } from "../i18n";

import "./apply_bar.css";

/**
 * The one way anything in this panel is saved.
 *
 * Every group of settings ends with one of these, and the group it closes is
 * the unit of change: what is framed together is applied together. That
 * uniformity is the point — on a page with four boxes, four bars means four
 * independent things, and nobody has to work out which button covers what.
 *
 * Saving and applying are one action, never two. Writing configuration without
 * loading it leaves the panel showing one state and the box in another, and
 * the gap is invisible until something does not work.
 *
 * There is no auto-save anywhere, and that is deliberate rather than lazy.
 * Applying here restarts the proxy, reloads the firewall, or reconfigures an
 * interface — it drops live connections, and changing the LAN address drops
 * the session doing the changing. A setting that expensive should take a
 * deliberate press.
 */

interface ApplyBarProps {
  /** Whether anything in this group differs from what the gateway holds. */
  isDirty: boolean;
  isBusy: boolean;
  /** Names the scope, e.g. "Apply to enp1s0". */
  label: string;
  /** What pressing it will do. */
  hint: string;
  /** Said before the fact when applying is disruptive. */
  warning?: string;
  /**
   * Why this bar cannot be pressed at all, or null when it can. Stands in
   * for the hint and kills both buttons, however dirty the group is.
   */
  blockedHint?: string | null;
  error?: string | null;
  notice?: string | null;
  onReset: () => void;
  onApply: () => void;
}

export function ApplyBar({
  isDirty,
  isBusy,
  label,
  hint,
  warning,
  blockedHint = null,
  error = null,
  notice = null,
  onReset,
  onApply,
}: ApplyBarProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div className="apply_bar">
      {warning !== undefined && isDirty && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{warning}</div>
        </div>
      )}

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {notice !== null && (
        <div className="notice notice--ok">
          <Icon name="check" size={15} />
          <div className="notice_body">{notice}</div>
        </div>
      )}

      <div className="apply_bar_row">
        <span className="field_hint">
          {blockedHint ?? (isDirty ? hint : t("ui.apply_bar.clean"))}
        </span>
        <div className="button_row">
          <button
            type="button"
            className="button button--ghost"
            onClick={onReset}
            disabled={isBusy || !isDirty || blockedHint !== null}
          >
            {t("ui.apply_bar.reset")}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={onApply}
            disabled={isBusy || !isDirty || blockedHint !== null}
          >
            {isBusy ? <Spinner size={13} /> : <Icon name="check" size={14} />}
            {isBusy ? t("ui.apply_bar.applying") : label}
          </button>
        </div>
      </div>
    </div>
  );
}
