import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Picker } from "./picker";
import { apiPost, describeApplyFailure, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useDraft } from "../use_draft";
import { isFailing, useSettledApply } from "../use_settled_apply";
import type { ReportedModule } from "../use_settled_apply";
import type {
  ApplyResult,
  ComfyuiDeviceView,
  ComfyuiSettingsUpdate,
} from "../api_types";

import "./comfyui_settings.css";

/**
 * **Settings** of the ComfyUI module on one machine: the PyTorch build it
 * runs on, among the builds the machine's entry has a lock of, how long a
 * loaded model stays in memory with no job, and the shared models folder,
 * read-only. Applying stores them, and holds until the machine reports the
 * module where the hub asks it; a new build installs its PyTorch.
 */

/** The idle unload times, `-1` for never. */
const IDLE_UNLOAD_CHOICES: { id: string; key: string }[] = [
  { id: "5m", key: "ui.comfyui.idle_unload_5m" },
  { id: "30m", key: "ui.comfyui.idle_unload_30m" },
  { id: "1h", key: "ui.comfyui.idle_unload_1h" },
  { id: "4h", key: "ui.comfyui.idle_unload_4h" },
  { id: "-1", key: "ui.comfyui.idle_unload_never" },
];

/** The system whose one lock names no build. */
const DARWIN = "darwin";

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** The state of a module whose service runs, which a new build stops. */
const STATE_RUNNING = "running";

/** The `want` of a module a person pressed Start on. */
const WANT_RUNNING = "running";

interface ComfyuiSettingsProps {
  /** The machine ComfyUI runs on. */
  deviceId: string;
  /** Where the module answers: `/agent/module/comfyui`. */
  basePath: string;
  /** The ComfyUI view: the stored settings and the builds on offer. */
  saved: ComfyuiDeviceView;
  /** Why nothing here can be applied, or null while it can. */
  blockedHint: string | null;
  /** The machine's system: `linux`, `windows` or `darwin`. */
  platformOs: string;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** Takes the view the stored settings give. */
  onSaved: (view: ComfyuiDeviceView) => void;
}

/** The form's own fields: the build and the idle unload time. */
interface SettingsDraft {
  torch_build: string;
  idle_unload: string;
}

export function ComfyuiSettings({
  deviceId,
  basePath,
  saved,
  blockedHint,
  platformOs,
  want,
  onSaved,
}: ComfyuiSettingsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { draft, setDraft, isDirty, reset } = useDraft(saved, draftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const report: ReportedModule = { state: saved.state, instances: [] };
  const settle = useSettledApply(report, want);

  if (draft === null) {
    return null;
  }

  const isBuildShown = platformOs !== DARWIN && saved.torch_builds.length > 0;
  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const isDisabled = blockedHint !== null || isUnsupported;
  const isBuildChanged = draft.torch_build !== saved.torch_build;

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request: ComfyuiSettingsUpdate = {
      device_id: deviceId,
      torch_build: isBuildShown ? draft.torch_build : "",
      idle_unload: draft.idle_unload,
    };
    try {
      onSaved(await apiPost<ComfyuiDeviceView>(`${basePath}/set`, request));
      const result = await apiPost<ApplyResult>(`${basePath}/apply`, {
        device_id: deviceId,
      });
      if (!result.is_applied) {
        setError(describeApplyFailure(result));
        return;
      }
      settle.begin();
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
        <h2>{t("ui.comfyui.settings_title")}</h2>
      </div>
      <div className="comfyui_settings_fields">
        {isBuildShown && (
          <Picker
            options={saved.torch_builds.map((build) => ({
              id: build,
              name: t(`ui.comfyui.torch_build_${build}`),
            }))}
            value={draft.torch_build}
            onChange={(build) => {
              setDraft({ ...draft, torch_build: build });
            }}
            label={t("ui.comfyui.torch_build")}
            isDisabled={isDisabled}
          />
        )}
        <Picker
          options={IDLE_UNLOAD_CHOICES.map((choice) => ({
            id: choice.id,
            name: t(choice.key),
          }))}
          value={draft.idle_unload}
          onChange={(idleUnload) => {
            setDraft({ ...draft, idle_unload: idleUnload });
          }}
          label={t("ui.comfyui.idle_unload")}
          isDisabled={isDisabled}
        />
        <div className="field comfyui_settings_models">
          <span className="field_label">{t("ui.comfyui.models_dir")}</span>
          <span className="comfyui_settings_path mono">{saved.models_dir}</span>
        </div>
      </div>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy || settle.isSettling}
        label={t("ui.comfyui.settings_apply")}
        hint={
          want !== WANT_RUNNING
            ? t("ui.modules.stopped_hint")
            : t("ui.comfyui.settings_apply_hint")
        }
        warning={
          isDirty && isBuildChanged && saved.state === STATE_RUNNING
            ? t("ui.comfyui.torch_build_warning")
            : undefined
        }
        blockedHint={blockedHint}
        isApplyDisabled={isUnsupported}
        error={error}
        notice={
          settle.isApplied && !isFailing(report) ? t("ui.api.applied") : null
        }
        onReset={() => {
          reset();
          setError(null);
          settle.clear();
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What the form starts from: the stored build and idle unload time. */
function draftOf(view: ComfyuiDeviceView): SettingsDraft {
  return {
    torch_build: view.torch_build,
    idle_unload: view.idle_unload,
  };
}
