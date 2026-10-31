import type { ReactNode } from "react";

import { DialogLayer } from "./dialog_layer";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { t, useLanguage } from "../i18n";

import "./dialog_frame.css";

/**
 * The frame every dialog of the panel is drawn in: the install dialog's.
 *
 * A head with the title and Close, a body that scrolls, and a foot that
 * holds the dialog's buttons at its right. Escape and the backdrop close it,
 * closing only this layer.
 */

interface DialogFrameProps {
  title: string;
  icon?: IconName;
  /** Beside the title, at the head's right: the catalog's search box. */
  headAction?: ReactNode;
  /** Whether the head carries Close; a dialog whose foot holds Close has
   * none up there. */
  hasHeadClose?: boolean;
  /** `dialog--wide` for the catalog. */
  className?: string;
  /** The foot's buttons; no foot without them. */
  foot?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export function DialogFrame({
  title,
  icon,
  headAction,
  hasHeadClose = true,
  className = "",
  foot,
  onClose,
  children,
}: DialogFrameProps) {
  // Redrawn when the panel's language changes.
  useLanguage();

  return (
    <DialogLayer label={title} onDismiss={onClose}>
      <div className={`dialog ${className}`}>
        <div className="dialog_head">
          <div className="dialog_title">
            {icon !== undefined && <Icon name={icon} size={15} />}
            <h2>{title}</h2>
          </div>
          {headAction}
          {hasHeadClose && (
            <button
              type="button"
              className="button button--small"
              onClick={onClose}
            >
              <Icon name="close" size={13} />
              {t("ui.dialog.close")}
            </button>
          )}
        </div>
        <div className="dialog_body">{children}</div>
        {foot !== undefined && <div className="dialog_foot">{foot}</div>}
      </div>
    </DialogLayer>
  );
}
