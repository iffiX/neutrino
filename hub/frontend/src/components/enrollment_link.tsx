import { CopyButton } from "./copy_button";
import { QrCode } from "./qr_code";
import { t, useLanguage } from "../i18n";

import "./enrollment_link.css";

/**
 * A link a machine or a client joins with, as a dialog shows it: how to use
 * it and how long it lasts, the link with Copy, and its QR code at the
 * bottom, centred.
 */

interface EnrollmentLinkProps {
  link: string;
  expiresInS: number;
  /** What to do with the link; its `{minutes}` is filled with how long the
   * link lasts. */
  hintKey: string;
}

export function EnrollmentLink({
  link,
  expiresInS,
  hintKey,
}: EnrollmentLinkProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const minutes = Math.max(0, Math.round(expiresInS / 60));
  return (
    <div className="enrollment_link">
      <p className="field_hint">{t(hintKey, { minutes })}</p>
      <div className="enrollment_link_row">
        <code>{link}</code>
        <CopyButton text={link} />
      </div>
      <div className="enrollment_link_qr">
        <QrCode text={link} label={t("ui.enrollment_link.qr_code")} />
      </div>
    </div>
  );
}
