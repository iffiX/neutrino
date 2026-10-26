import { useState } from "react";

import { DialogFrame } from "./dialog_frame";
import { EnrollmentLink } from "./enrollment_link";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { ClientEnrollmentView } from "../api_types";

/**
 * The **New client link** dialog: the client's name, then the link its
 * program joins with and its QR code.
 */

interface ClientLinkModalProps {
  /** Called once a link was made, so the page reads the new row. */
  onCreated: () => void;
  onClose: () => void;
}

export function ClientLinkModal({ onCreated, onClose }: ClientLinkModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState("");
  const [enrollment, setEnrollment] = useState<ClientEnrollmentView | null>(
    null,
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    const wanted = name.trim();
    if (wanted === "") {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      setEnrollment(
        await apiPost<ClientEnrollmentView>("/hub/client/enrollment/create", {
          name: wanted,
        }),
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
            onClick={() => void create()}
          >
            {isBusy ? <Spinner size={13} /> : <Icon name="check" size={14} />}
            {t("ui.clients.create_link")}
          </button>
        ) : undefined
      }
    >
      {enrollment === null ? (
        <label className="field">
          <span className="field_label">{t("ui.clients.header_name")}</span>
          <input
            className="input"
            placeholder={t("ui.clients.name_placeholder")}
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void create();
              }
            }}
          />
        </label>
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
