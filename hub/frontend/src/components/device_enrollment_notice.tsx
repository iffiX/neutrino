import { Icon } from "./icon";
import { QrCode } from "./qr_code";
import { copyText } from "../copy_text";
import { t, useLanguage } from "../i18n";

import "./device_enrollment_notice.css";

/**
 * A generated enrollment link, worded by whoever minted it.
 *
 * The devices page and a device's drawer mint links for agents, the clients
 * page for a person's program; each passes its own title and hint, and the
 * hint's `{minutes}` is filled with how long the link lasts. With `qrLink`
 * that link is drawn as a QR code at the bottom, centred.
 */

interface DeviceEnrollmentNoticeProps {
  link: string;
  expiresInS: number;
  title: string;
  /** May carry `{minutes}`, filled with the link's remaining minutes. */
  hint: string;
  /** The link the QR code carries; no QR code without it. */
  qrLink?: string;
  onDismiss: () => void;
}

export function DeviceEnrollmentNotice({
  link,
  expiresInS,
  title,
  hint,
  qrLink = "",
  onDismiss,
}: DeviceEnrollmentNoticeProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const minutes = Math.max(0, Math.round(expiresInS / 60));
  return (
    <div className="notice device_enrollment_notice">
      <Icon name="link" size={15} />
      <div className="notice_body">
        <strong>{title}</strong>
        <span className="muted">
          {hint.replace("{minutes}", String(minutes))}
        </span>
        <div className="device_enrollment_link">
          <code>{link}</code>
          <button
            type="button"
            className="button button--small"
            onClick={() => void copyText(link)}
          >
            <Icon name="file" size={13} />
            {t("ui.enrollment_notice.copy")}
          </button>
          <button
            type="button"
            className="button button--small button--ghost"
            aria-label={t("ui.enrollment_notice.close")}
            onClick={onDismiss}
          >
            <Icon name="close" size={13} />
          </button>
        </div>
        {qrLink !== "" && (
          <div className="device_enrollment_qr">
            <QrCode text={qrLink} label={t("ui.enrollment_notice.qr_code")} />
          </div>
        )}
      </div>
    </div>
  );
}
