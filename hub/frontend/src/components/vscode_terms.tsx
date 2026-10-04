import { useState } from "react";

import { Icon } from "./icon";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { VscodeDeviceView, VscodeTermsUpdate } from "../api_types";

import "./vscode_panels.css";

/**
 * Microsoft's terms for VS Code on one machine, above the module's tab.
 *
 * Until they are accepted the notice is all the tab shows. The one button
 * opens the terms in a new tab, and the same press records the acceptance
 * for this machine; afterwards it stays disabled and reads as accepted.
 */
interface VscodeTermsProps {
  /** The machine the acceptance is recorded for. */
  deviceId: string;
  /** The machine's VS Code, as last read. */
  view: VscodeDeviceView;
  /** Called with the view the hub answered after recording the press. */
  onRecorded: (view: VscodeDeviceView) => void;
}

export function VscodeTerms({ deviceId, view, onRecorded }: VscodeTermsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [error, setError] = useState<string | null>(null);

  const accept = async () => {
    setError(null);
    const request: VscodeTermsUpdate = {
      device_id: deviceId,
      is_accepted: true,
    };
    try {
      onRecorded(
        await apiPost<VscodeDeviceView>(
          "/agent/module/vscode/terms/set",
          request,
        ),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  return (
    <div className="notice vscode_terms">
      <Icon name="alert" size={15} />
      <div className="notice_body">
        <span>{t("ui.vscode.terms_notice")}</span>
        {view.is_terms_accepted ? (
          <button type="button" className="button button--primary" disabled>
            {t("ui.vscode.terms_accepted")}
          </button>
        ) : (
          <a
            className="button button--primary"
            href={view.terms_url}
            target="_blank"
            rel="noreferrer"
            onClick={() => void accept()}
          >
            {t("ui.vscode.terms_accept")}
          </a>
        )}
        {error !== null && <span className="field_error">{error}</span>}
      </div>
    </div>
  );
}
