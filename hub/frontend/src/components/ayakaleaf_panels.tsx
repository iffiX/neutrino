import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Picker } from "./picker";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type { AyakaleafDeviceView, AyakaleafModelUpdate } from "../api_types";
import type { PickerOption } from "./picker";

/**
 * The Ayakaleaf module on one machine: the AI model the editor's assistant
 * uses, from the models the gateway serves, its first row the gateway's
 * first model.
 *
 * A new model rewrites the app's environment, which restarts the app, so
 * the bar stays busy after its press until the machine reports the module
 * running again, at most two minutes.
 */

interface AyakaleafPanelsProps {
  /** The machine Ayakaleaf runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/ayakaleaf`. */
  basePath: string;
  isEditable: boolean;
}

/** The form's own field; the machine it is written to is the page's. */
type AyakaleafDraft = Omit<AyakaleafModelUpdate, "device_id">;

/** The picker's row for no model: the gateway's first. */
const GATEWAY_DEFAULT = "";

/** How long the bar waits for the app to run again after a press. */
const RESTART_HOLD_MS = 2 * 60 * 1000;

/** The press the bar waits on: when it was, and whether the module has read
 * anything but `running` since. */
interface RestartWait {
  at: number;
  hasLeftRunning: boolean;
}

export function AyakaleafPanels({
  deviceId,
  basePath,
  isEditable,
}: AyakaleafPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AyakaleafDeviceView>(
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
  const [wait, setWait] = useState<RestartWait | null>(null);
  const [error, setError] = useState<string | null>(null);

  const state = saved?.state ?? "";
  useEffect(() => {
    if (wait === null) {
      return;
    }
    if (state !== "running" && !wait.hasLeftRunning) {
      setWait({ ...wait, hasLeftRunning: true });
      return;
    }
    if (state === "running" && wait.hasLeftRunning) {
      setWait(null);
      return;
    }
    const left = wait.at + RESTART_HOLD_MS - Date.now();
    const timer = window.setTimeout(() => setWait(null), Math.max(0, left));
    return () => window.clearTimeout(timer);
  }, [state, wait]);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 140 }} />;
  }

  // An agent older than the module: the picker and the bar stay off.
  const isUnsupported = saved.state === "unsupported";
  const options: PickerOption[] = [
    { id: GATEWAY_DEFAULT, name: t("ui.ai_tools.gateway_default") },
    ...saved.models.map((model) => ({ id: model, name: model })),
  ];

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: AyakaleafModelUpdate = { device_id: deviceId, ...draft };
    try {
      resource.setData(
        await apiPost<AyakaleafDeviceView>(`${basePath}/set`, request),
      );
      setWait({ at: Date.now(), hasLeftRunning: false });
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
      <Picker
        options={options}
        value={
          saved.models.includes(draft.model) ? draft.model : GATEWAY_DEFAULT
        }
        onChange={(model) => setDraft({ model })}
        label={t("ui.ayakaleaf.model")}
        hint={
          saved.is_gateway_serving
            ? t("ui.ayakaleaf.model_hint")
            : t("code.gateway_not_serving")
        }
        isDisabled={!isEditable || isUnsupported || !saved.is_gateway_serving}
      />
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy || wait !== null}
        label={t("ui.ayakaleaf.apply")}
        hint={t("ui.ayakaleaf.model_hint")}
        warning={t("ui.ayakaleaf.apply_warning")}
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

/** What the form starts from: the model as saved. */
function draftOf(view: AyakaleafDeviceView): AyakaleafDraft {
  return { model: view.model };
}
