import { useState } from "react";

import { DialogFrame } from "./dialog_frame";
import { EnrollmentLink } from "./enrollment_link";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type {
  DeviceEnrollmentRequest,
  DeviceEnrollmentView,
} from "../api_types";

/**
 * The **Add by link** dialog: the machine's name, the host name when left
 * empty, then **Generate link**, which shows the enrolment link for a
 * machine that joins on its own and its QR code.
 */

interface AgentLinkModalProps {
  onClose: () => void;
}

export function AgentLinkModal({ onClose }: AgentLinkModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState("");
  const [enrollment, setEnrollment] = useState<DeviceEnrollmentView | null>(
    null,
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    setIsBusy(true);
    setError(null);
    const request: DeviceEnrollmentRequest = {
      name: name.trim(),
      device_id: null,
    };
    try {
      setEnrollment(
        await apiPost<DeviceEnrollmentView>(
          "/hub/device/enrollment/create",
          request,
        ),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <DialogFrame
      title={t("ui.devices.add_by_link")}
      icon="link"
      onClose={onClose}
      foot={
        enrollment === null ? (
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={isBusy}
            onClick={() => void generate()}
          >
            {isBusy ? <Spinner size={13} /> : <Icon name="link" size={14} />}
            {t("ui.devices.generate_link")}
          </button>
        ) : (
          <button
            type="button"
            className="button button--primary"
            onClick={onClose}
          >
            <Icon name="check" size={14} />
            {t("ui.clients.done")}
          </button>
        )
      }
    >
      {enrollment === null ? (
        <label className="field">
          <span className="field_label">{t("ui.devices.header_name")}</span>
          <input
            className="input"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !isBusy) {
                void generate();
              }
            }}
          />
          <span className="field_hint">{t("ui.devices.link_name_hint")}</span>
        </label>
      ) : (
        <EnrollmentLink
          link={enrollment.link}
          expiresInS={enrollment.expires_in_s}
          hintKey="ui.devices.enrollment_hint"
        />
      )}
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </DialogFrame>
  );
}
