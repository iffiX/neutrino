import { useEffect } from "react";
import { Icon } from "./icon";
import { t, useLanguage } from "../i18n";
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

const DEFAULT_TITLE_KEY = "ui.install_consent.title";
const DEFAULT_CONFIRM_KEY = "ui.install_consent.confirm";

/** The codes this dialog words, each with its own title and sentence. */
const CONSENT_KEYS: Record<string, { title: string; body: string }> = {
  device_install: {
    title: "ui.install_consent.device_install_title",
    body: "ui.install_consent.device_install_body",
  },
  device_uninstall: {
    title: "ui.install_consent.device_uninstall_title",
    body: "ui.install_consent.device_uninstall_body",
  },
  kernel_module_build: {
    title: "ui.install_consent.kernel_module_build_title",
    body: "ui.install_consent.kernel_module_build_body",
  },
  third_party_repository: {
    title: "ui.install_consent.third_party_repository_title",
    body: "ui.install_consent.third_party_repository_body",
  },
};

function describe(consent: ProvisionConsentView): {
  title: string;
  body: string;
  extra?: string;
} {
  const detail = consent.detail;
  const keys = CONSENT_KEYS[consent.code];
  if (keys === undefined) {
    return {
      title: consent.code.replace(/_/g, " "),
      body: t("ui.install_consent.unknown_body"),
      extra: JSON.stringify(detail),
    };
  }
  const described = { title: t(keys.title), body: t(keys.body) };
  switch (consent.code) {
    case "kernel_module_build":
      return {
        ...described,
        extra: [
          Array.isArray(detail.packages) ? detail.packages.join(", ") : null,
          typeof detail.kernel === "string"
            ? t("ui.install_consent.kernel", { kernel: detail.kernel })
            : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "third_party_repository":
      return {
        ...described,
        extra: typeof detail.repository === "string" ? detail.repository : "",
      };
    default:
      return {
        ...described,
        extra: Array.isArray(detail.devices) ? detail.devices.join(", ") : "",
      };
  }
}

interface Props {
  name: string;
  consents: ProvisionConsentView[];
  /** Names what is about to happen; the sentence carries `{name}`. */
  titleKey?: string;
  confirmKey?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function InstallConsentModal({
  name,
  consents,
  titleKey = DEFAULT_TITLE_KEY,
  confirmKey = DEFAULT_CONFIRM_KEY,
  onConfirm,
  onCancel,
}: Props) {
  // Redrawn when the panel's language changes.
  useLanguage();
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
      aria-label={t("ui.install_consent.dialog_label", { name })}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <div className="consent_modal">
        <div className="consent_head">
          <Icon name="alert" size={16} />
          <h2>{t(titleKey, { name })}</h2>
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
            {t("ui.install_consent.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={onConfirm}
          >
            {t(confirmKey)}
          </button>
        </div>
      </div>
    </div>
  );
}
