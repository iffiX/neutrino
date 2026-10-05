import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { HUB_EVENT_CONFIG } from "../use_hub_events";
import type {
  DirectInterfaceState,
  DirectSetRequest,
  DirectView,
} from "../api_types";

import "./relay_panels.css";

/**
 * Direct: the hub's connection port on every enabled interface, and the
 * public address the person states for the hub. The switch is on the card
 * above; this section says what it opens, holds the public address with its
 * own apply bar, and lists the addresses clients are given.
 */

const DIRECT_PATH = "/hub/overlay/direct";

// The sentence under the addresses for each way Direct stands with the
// hub's interface addresses; none while it adds some.
const INTERFACE_STATE_KEYS: Record<DirectInterfaceState, string | null> = {
  added: null,
  exposed: "ui.overlay.direct_addresses_exposed",
  none: "ui.overlay.direct_addresses_empty",
};

// The switch above writes the hub's configuration, which moves this view.
const DIRECT_INVALIDATE_ON = [{ type: HUB_EVENT_CONFIG }];

export function DirectSection() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DirectView>(DIRECT_PATH, {
    invalidateOn: DIRECT_INVALIDATE_ON,
  });
  const view = resource.data;

  if (resource.error !== null && view === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (view === null) {
    return <div className="skeleton" style={{ height: 240 }} />;
  }

  return (
    <>
      <div className="overlay_product_header">
        <div className="page_title_row">
          <h2>{t("ui.overlay.direct_title")}</h2>
        </div>
      </div>
      <DirectSettingsPanel view={view} onChanged={resource.setData} />
    </>
  );
}

interface DirectPanelProps {
  view: DirectView;
  onChanged: (view: DirectView) => void;
}

/** The public address, held as the form edits it; the port stays text. */
interface DirectDraft {
  publicHost: string;
  publicPort: string;
}

function draftOf(view: DirectView): DirectDraft {
  return {
    publicHost: view.public_host,
    publicPort: String(view.public_port),
  };
}

/** What the switch opens, the public address, and the addresses given out. */
function DirectSettingsPanel({ view, onChanged }: DirectPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { draft, setDraft, isDirty, reset } = useDraft(view, draftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (draft === null) {
    return null;
  }

  const stateKey = INTERFACE_STATE_KEYS[view.interface_state];

  const change = (patch: Partial<DirectDraft>) => {
    setError(null);
    setDraft((current) => ({ ...current, ...patch }));
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: DirectSetRequest = {
      public_host: draft.publicHost.trim(),
      public_port: Number(draft.publicPort),
    };
    try {
      onChanged(await apiPost<DirectView>(`${DIRECT_PATH}/set`, request));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.settings_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.overlay.direct_switch_hint")}</p>
      <div className="relay_fields">
        <label className="field">
          <span className="field_label">
            {t("ui.overlay.direct_public_host")}
          </span>
          <input
            className="input"
            value={draft.publicHost}
            spellCheck={false}
            placeholder="hub.example.org"
            onChange={(event) => change({ publicHost: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">
            {t("ui.overlay.direct_public_port")}
          </span>
          <input
            className="input"
            inputMode="numeric"
            value={draft.publicPort}
            onChange={(event) => change({ publicPort: event.target.value })}
          />
        </label>
      </div>
      <p className="field_hint">{t("ui.overlay.direct_public_host_hint")}</p>
      <div className="relay_fact">
        <span className="field_label">{t("ui.overlay.direct_addresses")}</span>
        {view.urls.map((url) => (
          <span key={url} className="relay_fact_value">
            {url}
          </span>
        ))}
        {stateKey !== null && (
          <span className="relay_fact_value">{t(stateKey)}</span>
        )}
      </div>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.direct_apply")}
        hint={t("ui.overlay.direct_apply_hint")}
        error={error}
        onReset={reset}
        onApply={() => void apply()}
      />
    </section>
  );
}
