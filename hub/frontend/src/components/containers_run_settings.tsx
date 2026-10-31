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
  PodmanDeviceView,
  PodmanMachine,
  PodmanMachineState,
  PodmanMachineUpdate,
} from "../api_types";

import "./containers_run_settings.css";

/**
 * The Run settings of Containers on a Windows or macOS machine: the
 * available account whose Podman machine runs the containers, and the
 * machine's CPUs, memory and disk limit, each 0 for the default except the
 * disk limit on Windows, which is at least 1. On Windows the machine starts
 * with the login the account's form holds. While the container modules need
 * more memory than the machine has, the memory field advises their need.
 *
 * The disk limit starts at the disk's size now, as the machine reported it,
 * the way Podman Desktop's edit form for a machine holds its disk size. An
 * apply holds until the machine reports the module where the hub asks it.
 */

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** The `want` of a module the person stopped. */
const WANT_STOPPED = "stopped";

/** The disk limit a Windows machine with none stored starts at, in GiB. */
const WINDOWS_NEW_DISK_GIB = 100;

/** The Run settings while none are stored: no account, Podman's defaults. */
const EMPTY_MACHINE: PodmanMachine = {
  account: "",
  cpus: 0,
  memory_gib: 0,
  disk_gib: 0,
};

interface ContainersRunSettingsProps {
  /** The machine whose Run settings these are. */
  deviceId: string;
  /** Where podman answers: `/agent/module/podman`. */
  basePath: string;
  /** The Containers view: the stored Run settings and the reported machine. */
  saved: PodmanDeviceView;
  isEditable: boolean;
  /** Whether the machine is Windows, whose machine starts with a login. */
  isWindows: boolean;
  /** What the hub asks of the module: `running`, `stopped`, or empty. */
  want: string;
  /** The module as the machine reports it, for an apply to wait on. */
  report: ReportedModule | null;
  /** Takes the view the stored Run settings give. */
  onSaved: (view: PodmanDeviceView) => void;
}

/** The form's own fields; the machine they are written to is the page's. */
type RunDraft = Omit<PodmanMachineUpdate, "device_id">;

export function ContainersRunSettings({
  deviceId,
  basePath,
  saved,
  isEditable,
  isWindows,
  want,
  report,
  onSaved,
}: ContainersRunSettingsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { draft, setDraft, isDirty, reset } = useDraft(saved, (view) =>
    draftOf(view, isWindows),
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const settle = useSettledApply(report, want);

  if (draft === null) {
    return null;
  }

  const stored = draftOf(saved, isWindows);
  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const currentDisk = currentDiskGib(saved.machine_state, draft.account);
  const leastDisk = isWindows ? Math.max(1, currentDisk) : currentDisk;
  const isShrunk = draft.disk_gib !== 0 && draft.disk_gib < currentDisk;
  const isDiskMissing = isWindows && draft.disk_gib < 1;
  const memoryNeed = saved.memory_need;
  const isMemoryShort =
    memoryNeed !== null && draft.memory_gib < memoryNeed.need_gib;
  const diskError = isDiskMissing
    ? t("code.machine_disk_invalid", { disk_gib: draft.disk_gib })
    : isShrunk
      ? t("code.machine_disk_shrink", {
          disk_gib: draft.disk_gib,
          current_gib: currentDisk,
        })
      : null;

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request: PodmanMachineUpdate = { device_id: deviceId, ...draft };
    try {
      onSaved(
        await apiPost<PodmanDeviceView>(`${basePath}/machine/set`, request),
      );
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
        <h2>{t("ui.containers.run_title")}</h2>
      </div>
      <div className="containers_run_account">
        <Picker
          options={saved.accounts.map((account) => ({
            id: account,
            name: account,
          }))}
          value={draft.account}
          onChange={(account) => setDraft({ ...draft, account })}
          label={t("ui.containers.run_account")}
          hint={t("ui.containers.run_account_hint")}
          emptyText={t("ui.accounts.empty")}
          isDisabled={isUnsupported}
        />
      </div>
      <div className="containers_run_numbers">
        <label className="field">
          <span className="field_label">{t("ui.containers.run_cpus")}</span>
          <input
            className="input"
            type="number"
            min={0}
            value={draft.cpus}
            disabled={isUnsupported}
            onChange={(event) =>
              setDraft({ ...draft, cpus: wholeNumber(event.target.value) })
            }
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.containers.run_memory")}</span>
          <input
            className="input"
            type="number"
            min={0}
            value={draft.memory_gib}
            disabled={isUnsupported}
            onChange={(event) =>
              setDraft({
                ...draft,
                memory_gib: wholeNumber(event.target.value),
              })
            }
          />
          {isMemoryShort && (
            <span className="field_hint">
              {t("ui.containers.run_memory_need", {
                need: memoryNeed.need_gib,
              })}
            </span>
          )}
        </label>
        <label className="field">
          <span className="field_label">{t("ui.containers.run_disk")}</span>
          <input
            className="input"
            type="number"
            min={leastDisk}
            value={draft.disk_gib}
            disabled={isUnsupported}
            onChange={(event) =>
              setDraft({ ...draft, disk_gib: wholeNumber(event.target.value) })
            }
          />
          {diskError !== null ? (
            <span className="field_error">{diskError}</span>
          ) : (
            currentDisk > 0 && (
              <span className="field_hint">
                {t("ui.containers.run_disk_hint", { current: currentDisk })}
              </span>
            )
          )}
        </label>
      </div>
      <p className="field_hint">
        {isWindows
          ? t("ui.containers.run_default_hint_windows")
          : t("ui.containers.run_default_hint")}
      </p>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy || settle.isSettling}
        label={t("ui.containers.run_apply")}
        hint={
          want === WANT_STOPPED
            ? t("ui.modules.stopped_hint")
            : t("ui.containers.run_apply_hint")
        }
        warning={runWarning(stored, draft, saved.machine_state, isWindows)}
        blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
        isApplyDisabled={isUnsupported || diskError !== null}
        error={error}
        notice={
          settle.isApplied && report !== null && !isFailing(report)
            ? t("ui.api.applied")
            : null
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

/** What the form starts from: the Run settings as stored; on Windows, while
 * none name an account, a disk limit of 100 GiB. */
function draftOf(view: PodmanDeviceView, isWindows: boolean): RunDraft {
  const machine = view.machine ?? EMPTY_MACHINE;
  const isNewWindowsMachine = isWindows && machine.account === "";
  return {
    account: machine.account,
    cpus: machine.cpus,
    memory_gib: machine.memory_gib,
    disk_gib: isNewWindowsMachine ? WINDOWS_NEW_DISK_GIB : machine.disk_gib,
  };
}

/** Whether the account's machine exists: the report names it for the
 * account. */
function isMachineMade(
  reported: PodmanMachineState | null,
  account: string,
): reported is PodmanMachineState {
  return reported !== null && account !== "" && reported.account === account;
}

/** The least disk limit for the account's machine: its disk's size now, in
 * whole GiB; 0 while the account has no machine reported. */
function currentDiskGib(
  reported: PodmanMachineState | null,
  account: string,
): number {
  return isMachineMade(reported, account) ? Math.ceil(reported.disk_gib) : 0;
}

/** What applying the draft interrupts, or nothing when it interrupts
 * nothing. */
function runWarning(
  stored: RunDraft,
  draft: RunDraft,
  reported: PodmanMachineState | null,
  isWindows: boolean,
): string | undefined {
  const lines: string[] = [];
  const isResourceChanged =
    draft.cpus !== stored.cpus ||
    draft.memory_gib !== stored.memory_gib ||
    draft.disk_gib !== stored.disk_gib;
  const isRestarted =
    isResourceChanged && isMachineMade(reported, draft.account);
  if (isRestarted) {
    lines.push(t("ui.containers.run_restart_warning"));
  }
  if (isRestarted && isWindows) {
    lines.push(t("ui.containers.run_wsl_warning"));
  }
  if (stored.account !== "" && draft.account !== stored.account) {
    lines.push(t("ui.containers.run_account_warning"));
  }
  return lines.length === 0 ? undefined : lines.join(" ");
}

/** A number field's text as a count: a whole number, 0 for none. */
function wholeNumber(text: string): number {
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) || value < 0 ? 0 : value;
}
