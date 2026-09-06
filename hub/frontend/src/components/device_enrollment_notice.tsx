import { Icon } from "./icon";
import { copyText } from "../copy_text";
import type { DeviceEnrollmentView } from "../api_types";

import "./device_enrollment_notice.css";

/**
 * A generated enrollment link, with the machine it was generated for.
 *
 * The same notice serves the page's "Add by link" button, which names no
 * machine, and a device's own drawer, which names it.
 */

const ENROLLMENT_TITLE_ANY =
  "Paste this link into the machine's own agent window.";

const ENROLLMENT_TITLE_DEVICE =
  "Paste this link into the agent window on {name}.";

const ENROLLMENT_HINT =
  "Install the agent there, then paste the link into its window (`nagent gui`) — or run `sudo nagent connect <link>` in its terminal; it pastes safely unquoted. It works for {minutes} minutes.";

interface DeviceEnrollmentNoticeProps {
  enrollment: DeviceEnrollmentView;
  /** The device the link is bound to, or null for a machine not in the list. */
  deviceName: string | null;
  onDismiss: () => void;
}

export function DeviceEnrollmentNotice({
  enrollment,
  deviceName,
  onDismiss,
}: DeviceEnrollmentNoticeProps) {
  const minutes = Math.round(enrollment.expires_in_s / 60);
  return (
    <div className="notice">
      <Icon name="link" size={15} />
      <div className="notice_body">
        <strong>{enrollmentTitle(deviceName)}</strong>
        <span className="muted">
          {ENROLLMENT_HINT.replace("{minutes}", String(minutes))}
        </span>
        <div className="device_enrollment_link">
          <code>{enrollment.link}</code>
          <button
            type="button"
            className="button button--small"
            onClick={() => void copyText(enrollment.link)}
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

function enrollmentTitle(deviceName: string | null): string {
  if (deviceName === null) {
    return ENROLLMENT_TITLE_ANY;
  }
  return ENROLLMENT_TITLE_DEVICE.replace("{name}", deviceName);
}
