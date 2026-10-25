import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { isFailing, useSettledApply } from "../use_settled_apply";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  HermesWebuiConfigUpdate,
  HermesWebuiDeviceView,
} from "../api_types";

/**
 * The Hermes WebUI module on one machine: the port its page is served on.
 *
 * The machine's agent serves the page through its forwarder at this port, and
 * a client opens it from its Web page with the token the hub hands, so the
 * tab holds no link to it. The apply bar waits until the machine reports the
 * module where the hub asks it to be.
 */

interface HermesWebuiPanelsProps {
  /** The machine the module runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/hermes_webui`. */
  basePath: string;
  isEditable: boolean;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
}

/** The form's own field; the machine it is written to is the page's. */
type HermesWebuiDraft = Omit<HermesWebuiConfigUpdate, "device_id">;

/** The ports the forwarder may listen on. */
const PORT_MIN = 1024;
const PORT_MAX = 65535;

export function HermesWebuiPanels({
  deviceId,
  basePath,
  isEditable,
  want,
}: HermesWebuiPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<HermesWebuiDeviceView>(
    apiPath(basePath, { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );
  const saved = resource.data;
  const { draft, setDraft, isDirty, reset } = useDraft(saved, draftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const report = saved === null ? null : { state: saved.state, instances: [] };
  const settle = useSettledApply(report, want);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null || report === null) {
    return <div className="skeleton" style={{ height: 140 }} />;
  }

  const isPortValid = isPortInRange(draft.port);
  const isFailed = isFailing(report);

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request: HermesWebuiConfigUpdate = { device_id: deviceId, ...draft };
    try {
      if (isDirty) {
        resource.setData(
          await apiPost<HermesWebuiDeviceView>(`${basePath}/set`, request),
        );
      } else {
        await apiPost(`${basePath}/apply`, { device_id: deviceId });
        resource.reload();
      }
      settle.begin();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <>
      <p className="field_hint">
        {saved.version === ""
          ? t("ui.hermes_webui.owner_notice")
          : t("ui.hermes_webui.owner_notice_version", {
              version: saved.version,
            })}
      </p>
      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <label className="field">
          <span className="field_label">{t("ui.hermes_webui.port")}</span>
          <input
            className="input"
            type="number"
            min={PORT_MIN}
            max={PORT_MAX}
            value={draft.port}
            disabled={!isEditable}
            onChange={(event) => setDraft({ port: Number(event.target.value) })}
          />
          {isPortValid ? (
            <span className="field_hint">{t("ui.hermes_webui.port_hint")}</span>
          ) : (
            <span className="field_error">
              {t("code.port_invalid", { port: draft.port })}
            </span>
          )}
        </label>
        <ApplyBar
          isDirty={isDirty || isFailed}
          isBusy={isBusy || settle.isSettling}
          label={t("ui.hermes_webui.apply")}
          hint={t("ui.hermes_webui.apply_hint")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          isApplyDisabled={!isPortValid}
          error={error}
          notice={settle.isApplied && !isFailed ? t("ui.api.applied") : null}
          onReset={() => {
            reset();
            setError(null);
            settle.clear();
          }}
          onApply={() => void apply()}
        />
      </section>
    </>
  );
}

/** What the form starts from: the port as saved. */
function draftOf(view: HermesWebuiDeviceView): HermesWebuiDraft {
  return { port: view.port };
}

/** Whether a port is one the forwarder may listen on. */
function isPortInRange(port: number): boolean {
  return Number.isInteger(port) && port >= PORT_MIN && port <= PORT_MAX;
}
