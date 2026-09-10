import { Icon } from "./icon";
import { copyText } from "../copy_text";

import "./device_enrollment_notice.css";

/**
 * A generated enrollment link, worded by whoever minted it.
 *
 * The devices page and a device's drawer mint links for agents, the clients
 * page for a person's program; each passes its own title and hint, and the
 * hint's `{minutes}` is filled with how long the link lasts.
 */

interface DeviceEnrollmentNoticeProps {
  link: string;
  expiresInS: number;
  title: string;
  /** May carry `{minutes}`, filled with the link's remaining minutes. */
  hint: string;
  onDismiss: () => void;
}

export function DeviceEnrollmentNotice({
  link,
  expiresInS,
  title,
  hint,
  onDismiss,
}: DeviceEnrollmentNoticeProps) {
  const minutes = Math.max(0, Math.round(expiresInS / 60));
  return (
    <div className="notice">
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
            Copy
          </button>
          <button
            type="button"
            className="button button--small button--ghost"
            aria-label="Close"
            onClick={onDismiss}
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
