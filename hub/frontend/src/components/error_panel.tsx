import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";
import "./error_panel.css";

/**
 * The inline failure state every page falls back to.
 *
 * A gateway panel is most needed exactly when the gateway is unwell, so a
 * failed request has to render as a readable panel with a retry, never as a
 * blank page that leaves the user guessing whether the box is down or the
 * browser is.
 */

interface ErrorPanelProps {
  title?: string;
  message: string;
  hint?: string;
  onRetry?: () => void;
}

export function ErrorPanel({ title, message, hint, onRetry }: ErrorPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div className="error_panel" role="alert">
      <div className="error_panel_head">
        <Icon name="alert" size={16} />
        <span>{title ?? t("ui.error_panel.title")}</span>
      </div>
      <p className="error_panel_message">{message}</p>
      <p className="error_panel_hint">{hint ?? t("ui.error_panel.hint")}</p>
      {onRetry !== undefined && (
        <button
          type="button"
          className="button button--small"
          onClick={onRetry}
        >
          <Icon name="refresh" size={13} />
          {t("ui.error_panel.retry")}
        </button>
      )}
    </div>
  );
}
