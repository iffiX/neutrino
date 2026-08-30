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
 */
function describe(consent: ProvisionConsentView): {
  title: string;
  body: string;
  extra?: string;
} {
  const detail = consent.detail;
  switch (consent.code) {
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
  onConfirm: () => void;
  onCancel: () => void;
}

export function InstallConsentModal({
  name,
  consents,
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
          <h2>Installing {name} does more than install packages</h2>
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
            Cancel
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={onConfirm}
          >
            Install anyway
          </button>
        </div>
      </div>
    </div>
  );
}
