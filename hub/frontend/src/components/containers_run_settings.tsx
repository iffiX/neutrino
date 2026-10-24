import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Picker } from "./picker";
import { VaultPicker } from "./vault_picker";
import { apiPost, describeApplyFailure, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useDraft } from "../use_draft";
import type {
  ApplyResult,
  PodmanDeviceView,
  PodmanMachine,
  PodmanMachineState,
  PodmanMachineUpdate,
} from "../api_types";

import "./containers_run_settings.css";

/**
 * The Run settings of Containers on a Windows or macOS machine: the account
 * whose Podman machine runs the containers, on Windows the login it starts
 * with, and the machine's CPUs, memory and disk limit, each 0 for Podman's
 * default.
 *
 * The disk limit starts at the disk's size now, as the machine reported it,
 * the way Podman Desktop's edit form for a machine holds its disk size.
 */

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** The Run settings while none are stored: no account, Podman's defaults. */
const EMPTY_MACHINE: PodmanMachine = {
  account: "",
  login_id: "",
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
  /** Reads the view again once an apply has run. */
  onApplied: () => void;
}

/** The form's own fields; the machine they are written to is the page's. */
type RunDraft = Omit<PodmanMachineUpdate, "device_id">;

export function ContainersRunSettings({
  deviceId,
  basePath,
  saved,
  isEditable,
  isWindows,
  onApplied,
}: ContainersRunSettingsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { draft, setDraft, isDirty, reset } = useDraft(saved, draftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (draft === null) {
    return null;
  }

  const stored = saved.machine ?? EMPTY_MACHINE;
  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const currentDisk = currentDiskGib(saved.machine_state, draft.account);
  const isShrunk = draft.disk_gib !== 0 && draft.disk_gib < currentDisk;

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    const request: PodmanMachineUpdate = { device_id: deviceId, ...draft };
    try {
      await apiPost<PodmanDeviceView>(`${basePath}/machine/set`, request);
      const result = await apiPost<ApplyResult>(`${basePath}/apply`, {
        device_id: deviceId,
      });
      onApplied();
      if (!result.is_applied) {
        setError(describeApplyFailure(result));
        return;
      }
      setNotice(t("ui.api.applied"));
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
          isTyped
          isDisabled={isUnsupported}
        />
        {isWindows && draft.account !== "" && (
          <VaultPicker
            kind="login"
            value={draft.login_id === "" ? null : draft.login_id}
            onChange={(loginId) =>
              setDraft({ ...draft, login_id: loginId ?? "" })
            }
            label={t("ui.containers.run_login", { account: draft.account })}
            hint={t("ui.containers.run_login_hint")}
            isDisabled={isUnsupported}
          />
        )}
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
        </label>
        <label className="field">
          <span className="field_label">{t("ui.containers.run_disk")}</span>
          <input
            className="input"
            type="number"
            min={currentDisk}
            value={draft.disk_gib}
            disabled={isUnsupported}
            onChange={(event) =>
              setDraft({ ...draft, disk_gib: wholeNumber(event.target.value) })
            }
          />
          {currentDisk > 0 && (
            <span className="field_hint">
              {t("ui.containers.run_disk_hint", { current: currentDisk })}
            </span>
          )}
        </label>
      </div>
      <p className="field_hint">{t("ui.containers.run_default_hint")}</p>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.containers.run_apply")}
        hint={t("ui.containers.run_apply_hint")}
        warning={runWarning(stored, draft, saved.machine_state, isWindows)}
        blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
        isApplyDisabled={isUnsupported || isShrunk}
        error={error}
        notice={notice}
        onReset={() => {
          reset();
          setError(null);
          setNotice(null);
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What the form starts from: the Run settings as stored. */
function draftOf(view: PodmanDeviceView): RunDraft {
  const machine = view.machine ?? EMPTY_MACHINE;
  return {
    account: machine.account,
    login_id: machine.login_id,
    cpus: machine.cpus,
    memory_gib: machine.memory_gib,
    disk_gib: machine.disk_gib,
  };
}

/** The least disk limit for the account's machine: its disk's size now, in
 * whole GiB; 0 while the account has no machine reported. */
function currentDiskGib(
  reported: PodmanMachineState | null,
  account: string,
): number {
  if (reported === null || reported.account !== account) {
    return 0;
  }
  return Math.ceil(reported.disk_gib);
}

/** What applying the draft interrupts, or nothing when it interrupts
 * nothing. */
function runWarning(
  stored: PodmanMachine,
  draft: RunDraft,
  reported: PodmanMachineState | null,
  isWindows: boolean,
): string | undefined {
  const lines: string[] = [];
  const isResourceChanged =
    draft.cpus !== stored.cpus || draft.memory_gib !== stored.memory_gib;
  const isDiskChanged = draft.disk_gib !== stored.disk_gib;
  if (reported !== null && isResourceChanged) {
    lines.push(t("ui.containers.run_restart_warning"));
  }
  if (reported !== null && isWindows && (isResourceChanged || isDiskChanged)) {
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
