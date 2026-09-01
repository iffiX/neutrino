import { useEffect } from "react";

import { Icon } from "./icon";

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
  /** What it costs. One or two sentences, mechanism first. */
  body: string;
  /** The action's own verb, on the button that performs it. */
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="confirm_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="alert" size={16} />
          <h2>{title}</h2>
        </div>
        <p className="confirm_body">{body}</p>
        <div className="confirm_foot">
          <button type="button" className="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
