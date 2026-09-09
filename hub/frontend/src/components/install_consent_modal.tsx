import { useEffect } from "react";
import { Icon } from "./icon";
import type { ProvisionConsentView } from "../api_types";
import "./install_consent_modal.css";

/**
 * What a module's install would do that the person agrees to first.
 *
 * The backend sends a code and its values, never a sentence, so the wording
 * lives here and can be translated. A code this panel does not know still
 * shows: an unworded consequence is better than a hidden one.
 *
 * The device codes are the panel's own: a service page composes them from the
 * machines its Apply would change, so one dialog covers both what an install
 * entails and where it is about to land.
 */

const DEFAULT_TITLE = "Installing {name} does more than install packages";
const DEFAULT_CONFIRM_LABEL = "Install anyway";
const CANCEL_LABEL = "Cancel";

function describe(consent: ProvisionConsentView): {
  title: string;
  body: string;
  extra?: string;
} {
  const detail = consent.detail;
  const devices = Array.isArray(detail.devices)
    ? detail.devices.join(", ")
    : "";
  switch (consent.code) {
    case "device_install":
      return {
        title: "It will be installed on these machines",
        body:
          "Each machine's agent fetches the packages and starts the " +
          "service. A machine slow to answer keeps the step open until it " +
          "does.",
        extra: devices,
      };
    case "device_uninstall":
      return {
        title: "It will be removed from these machines",
        body:
          "The service stops and its packages go. What it wrote outside the " +
          "packages stays on the machine.",
        extra: devices,
      };
    case "kernel_module_build":
      return {
        title: "A kernel module will be compiled",
        body:
          "This distribution has no prebuilt module for the running kernel, " +
          "so one is built here. It takes several minutes, and it has to be " +
          "built again after every kernel upgrade.",
        extra: [
          Array.isArray(detail.packages) ? detail.packages.join(", ") : null,
          typeof detail.kernel === "string" ? `kernel ${detail.kernel}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "third_party_repository":
      return {
        title: "A repository outside the distribution will be added",
        body:
          "This software is not in the distribution's own repositories, so " +
          "packages will come from the address below and be trusted the way " +
          "the distribution's own are.",
        extra: typeof detail.repository === "string" ? detail.repository : "",
      };
    default:
      return {
        title: consent.code.replace(/_/g, " "),
        body: "This install does something the panel has no wording for yet.",
        extra: JSON.stringify(detail),
      };
  }
}

interface Props {
  name: string;
  consents: ProvisionConsentView[];
  /** Names what is about to happen; `{name}` is filled with the module. */
  title?: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function InstallConsentModal({
  name,
  consents,
  title = DEFAULT_TITLE,
  confirmLabel = DEFAULT_CONFIRM_LABEL,
  onConfirm,
  onCancel,
}: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="consent_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`Install ${name}`}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <div className="consent_modal">
        <div className="consent_head">
          <Icon name="alert" size={16} />
          <h2>{title.replace("{name}", name)}</h2>
        </div>
        <div className="consent_body">
          {consents.map((consent) => {
            const described = describe(consent);
            return (
              <div className="consent_item" key={consent.code}>
                <strong>{described.title}</strong>
                <p>{described.body}</p>
                {described.extra ? <code>{described.extra}</code> : null}
              </div>
            );
          })}
        </div>
        <div className="consent_foot">
          <button type="button" className="button" onClick={onCancel}>
            {CANCEL_LABEL}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
