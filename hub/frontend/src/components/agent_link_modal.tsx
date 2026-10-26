import { useEffect, useState } from "react";

import { DialogFrame } from "./dialog_frame";
import { EnrollmentLink } from "./enrollment_link";
import { Icon } from "./icon";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type {
  DeviceEnrollmentRequest,
  DeviceEnrollmentView,
} from "../api_types";

/**
 * The **Add by link** dialog: a blank enrolment link for a machine that
 * joins on its own, and its QR code. The link is made when the dialog
 * opens.
 */

interface AgentLinkModalProps {
  onClose: () => void;
}

export function AgentLinkModal({ onClose }: AgentLinkModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [enrollment, setEnrollment] = useState<DeviceEnrollmentView | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    const request: DeviceEnrollmentRequest = { name: "", device_id: null };
    apiPost<DeviceEnrollmentView>("/hub/device/enrollment/create", request)
      .then((view) => {
        if (!isCancelled) {
          setEnrollment(view);
        }
      })
      .catch((cause: unknown) => {
        if (!isCancelled) {
          setError(describeError(cause));
        }
      });
    return () => {
      isCancelled = true;
    };
  }, []);

  return (
    <DialogFrame
      title={t("ui.devices.add_by_link")}
      icon="link"
      onClose={onClose}
    >
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      {enrollment === null && error === null && (
        <div className="skeleton" style={{ height: 320 }} />
      )}
      {enrollment !== null && (
        <EnrollmentLink
          link={enrollment.link}
          expiresInS={enrollment.expires_in_s}
          hintKey="ui.devices.enrollment_hint"
        />
      )}
    </DialogFrame>
  );
}
