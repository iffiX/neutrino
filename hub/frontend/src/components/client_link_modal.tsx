import { useState } from "react";

import { ClientPermissionForm } from "./client_permission_form";
import type {
  PermissionDeviceChoice,
  PermissionValue,
} from "./client_permission_form";
import { DialogFrame } from "./dialog_frame";
import { EnrollmentLink } from "./enrollment_link";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPost, describeError } from "../api_client";
import { defaultPermissionOf } from "../client_permission_value";
import { t, useLanguage } from "../i18n";
import type {
  ClientEnrollmentRequest,
  ClientEnrollmentView,
  ClientListView,
} from "../api_types";

/**
 * The **New client link** dialog: the client's name and the permission it
 * joins with, then **Generate link**, which makes the client's waiting row
 * and shows the link its program joins with and its QR code.
 */

interface ClientLinkModalProps {
  /** The list, for the kinds, the rows and the default permission. */
  listView: ClientListView;
  /** The managed devices a filter may name. */
  devices: PermissionDeviceChoice[];
  /** Called once a link was made, so the page reads the new row. */
  onCreated: () => void;
  onClose: () => void;
}

export function ClientLinkModal({
  listView,
  devices,
  onCreated,
  onClose,
}: ClientLinkModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState("");
  // The permission the client joins with; null follows the default.
  const [permission, setPermission] = useState<PermissionValue | null>(null);
  const [enrollment, setEnrollment] = useState<ClientEnrollmentView | null>(
    null,
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    const wanted = name.trim();
    if (wanted === "") {
      return;
    }
    setIsBusy(true);
    setError(null);
    const request: ClientEnrollmentRequest = { name: wanted, permission };
    try {
      setEnrollment(
        await apiPost<ClientEnrollmentView>(
          "/hub/client/enrollment/create",
          request,
        ),
      );
      onCreated();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <DialogFrame
      title={t("ui.clients.new_link")}
      icon="link"
      onClose={onClose}
      foot={
        enrollment === null ? (
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={isBusy || name.trim() === ""}
            onClick={() => void generate()}
          >
            {isBusy ? <Spinner size={13} /> : <Icon name="link" size={14} />}
            {t("ui.clients.generate_link")}
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
        <>
          <label className="field">
            <span className="field_label">{t("ui.clients.header_name")}</span>
            <input
              className="input"
              placeholder={t("ui.clients.name_placeholder")}
              value={name}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <div className="field">
            <span className="field_label">{t("ui.clients.permission")}</span>
            <ClientPermissionForm
              kinds={listView.permission_kinds}
              rows={listView.permission_rows}
              defaultValue={defaultPermissionOf(listView)}
              applied={null}
              devices={devices}
              canFollowDefault
              onChange={setPermission}
            />
          </div>
        </>
      ) : (
        <>
          <strong>
            {t("ui.clients.enrollment_title", { name: name.trim() })}
          </strong>
          <EnrollmentLink
            link={enrollment.link}
            expiresInS={enrollment.expires_in_s}
            hintKey="ui.clients.enrollment_hint"
          />
        </>
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
