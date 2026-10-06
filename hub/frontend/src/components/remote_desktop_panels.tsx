import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { ToggleSwitch } from "./toggle_switch";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  RemoteDesktopConfigUpdate,
  RemoteDesktopDeviceView,
} from "../api_types";

/**
 * The Remote desktop module on one machine: the one switch that shares its
 * desktop.
 *
 * On, the machine runs the agent's own RustDesk for this hub's clients and
 * every other RustDesk host on it stops; off, the machine's RustDesk is put
 * back as it was. The page's notice says a failed step; Apply tries again.
 */

interface RemoteDesktopPanelsProps {
  /** The machine whose desktop this is. */
  deviceId: string;
  /** Where the module answers: `/agent/module/remote_desktop`. */
  basePath: string;
  isEditable: boolean;
}

/** The form's own field; the machine it is written to is the page's. */
type RemoteDesktopDraft = Omit<RemoteDesktopConfigUpdate, "device_id">;

export function RemoteDesktopPanels({
  deviceId,
  basePath,
  isEditable,
}: RemoteDesktopPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<RemoteDesktopDeviceView>(
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

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 140 }} />;
  }

  const isFailed = saved.state === "failed";
  // An agent older than the module: the switch and the bar stay off.
  const isUnsupported = saved.state === "unsupported";

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: RemoteDesktopConfigUpdate = {
      device_id: deviceId,
      ...draft,
    };
    try {
      if (isDirty) {
        resource.setData(
          await apiPost<RemoteDesktopDeviceView>(`${basePath}/set`, request),
        );
      } else {
        await apiPost(`${basePath}/apply`, { device_id: deviceId });
        resource.reload();
      }
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
      <ToggleSwitch
        isOn={draft.is_enabled}
        onChange={(isOn) => setDraft({ is_enabled: isOn })}
        label={t("ui.remote_desktop_module.switch")}
        description={t("ui.remote_desktop_module.switch_hint")}
        isDisabled={!isEditable || isUnsupported}
      />
      <ApplyBar
        isDirty={isDirty || isFailed}
        isBusy={isBusy}
        label={t("ui.remote_desktop_module.apply")}
        hint={t("ui.remote_desktop_module.apply_hint")}
        blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
        isApplyDisabled={isUnsupported}
        error={error}
        onReset={() => {
          reset();
          setError(null);
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What the form starts from: the switch as saved. */
function draftOf(view: RemoteDesktopDeviceView): RemoteDesktopDraft {
  return { is_enabled: view.is_enabled };
}
