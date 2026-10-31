import { DialogLayer } from "./dialog_layer";
import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";

import "./confirm_modal.css";

/**
 * The one way this panel asks before doing something irreversible.
 *
 * A native `confirm()` suspends the page, cannot be styled, and renders the
 * browser's own chrome over an application that has its own — so nothing here
 * uses one. The shape is the page's: a title naming what is about to happen,
 * a sentence of what it costs, and the action's own verb on the button.
 *
 * Settings are not confirmed here. A group of them ends in an apply bar, and
 * that bar's warning is where its cost is stated; this is for the buttons that
 * act at once — delete, revoke, forget, destroy.
 */

interface ConfirmModalProps {
  /** What is about to happen, as a title: "Delete the pool tank". */
  title: string;
  /** What it costs. One or two sentences, mechanism first; empty for none. */
  body: string;
  /** Names listed under the body, one to a line. */
  items?: string[];
  /** A question under the list. */
  question?: string;
  /** The action's own verb, on the button that performs it. */
  confirmLabel: string;
  /** The button that cancels; `ui.confirm.cancel` when absent. */
  cancelLabel?: string;
  /** A line under the body about the person's data. */
  detail?: string;
  /** Whether the act destroys data. The detail then takes the error tone,
   * and the button `button--danger`. */
  isDanger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  title,
  body,
  items = [],
  question = "",
  confirmLabel,
  cancelLabel,
  detail = "",
  isDanger = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();

  return (
    <DialogLayer label={title} onDismiss={onCancel}>
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="alert" size={16} />
          <h2>{title}</h2>
        </div>
        {(body !== "" || detail !== "") && (
          <div className="confirm_body">
            {body !== "" && <p>{body}</p>}
            {items.length > 0 && (
              <ul className="confirm_items">
                {items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
            {question !== "" && <p>{question}</p>}
            {detail !== "" && (
              <p
                className={
                  isDanger
                    ? "confirm_detail confirm_detail--danger"
                    : "confirm_detail"
                }
              >
                {detail}
              </p>
            )}
          </div>
        )}
        <div className="confirm_foot">
          <button type="button" className="button" onClick={onCancel}>
            {cancelLabel ?? t("ui.confirm.cancel")}
          </button>
          <button
            type="button"
            className={
              isDanger ? "button button--danger" : "button button--primary"
            }
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </DialogLayer>
  );
}
