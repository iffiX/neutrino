import { useState } from "react";

import { WINDOWS_NEW_DISK_GIB } from "./containers_run_settings";
import { DialogFrame } from "./dialog_frame";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Picker } from "./picker";
import { Spinner } from "./spinner";
import { ApiError, apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import type {
  AccountListView,
  AccountSetRequest,
  PodmanDeviceView,
  PodmanMachineUpdate,
} from "../api_types";

/**
 * The account of Containers' Podman machine, asked before an Install on a
 * Windows or macOS machine whose Run settings name none.
 *
 * A single choice among the accounts the machine reports. On Windows an
 * account with no stored login also takes its password. **Install** adds the
 * account when it is not yet available, writes the Run settings with the
 * default CPUs, memory and disk limit, and hands on to the press. Cancel
 * writes nothing.
 */

const ACCOUNT_PATH = "/agent/module/account";
const MACHINE_SET_PATH = "/agent/module/podman/machine/set";

/** The system whose machine starts with the account's Windows login. */
const WINDOWS_OS = "windows";

/** The refusal of a disk limit under the size of an existing machine's disk. */
const CODE_DISK_SHRINK = "machine_disk_shrink";

interface ContainersAccountModalProps {
  deviceId: string;
  /** Called once the Run settings name the account. */
  onChosen: () => void;
  onCancel: () => void;
}

export function ContainersAccountModal({
  deviceId,
  onChosen,
  onCancel,
}: ContainersAccountModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AccountListView>(
    apiPath(ACCOUNT_PATH, { device_id: deviceId }),
  );
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = resource.data;

  const isWindows = view?.platform_os === WINDOWS_OS;
  const held = view?.accounts.find((row) => row.account === account);
  const isPasswordAsked =
    isWindows && account !== "" && held?.has_login !== true;
  const isReady =
    view !== null &&
    account !== "" &&
    !isSaving &&
    !(isPasswordAsked && password === "");

  const writeAccount = async () => {
    const request: AccountSetRequest = {
      device_id: deviceId,
      account,
      password: isPasswordAsked ? password : "",
      share_path: held?.share_path ?? "",
      shell_path: held?.shell_path ?? "",
      is_ai_tools_enabled: held?.is_ai_tools_enabled ?? false,
      tool_configs: held?.tool_configs ?? {},
    };
    resource.setData(
      await apiPost<AccountListView>(
        `${ACCOUNT_PATH}/${held === undefined ? "add" : "set"}`,
        request,
      ),
    );
  };

  // A machine the account already has keeps its larger disk.
  const writeMachine = async () => {
    const request: PodmanMachineUpdate = {
      device_id: deviceId,
      account,
      cpus: 0,
      memory_gib: 0,
      disk_gib: isWindows ? WINDOWS_NEW_DISK_GIB : 0,
    };
    try {
      await apiPost<PodmanDeviceView>(MACHINE_SET_PATH, request);
    } catch (cause: unknown) {
      if (!(cause instanceof ApiError) || cause.code !== CODE_DISK_SHRINK) {
        throw cause;
      }
      await apiPost<PodmanDeviceView>(MACHINE_SET_PATH, {
        ...request,
        disk_gib: Number(cause.params.current_gib),
      });
    }
  };

  const confirm = async () => {
    setIsSaving(true);
    setError(null);
    try {
      if (held === undefined || isPasswordAsked) {
        await writeAccount();
      }
      await writeMachine();
      onChosen();
    } catch (cause: unknown) {
      setError(describeError(cause));
      setIsSaving(false);
    }
  };

  const cancel = () => {
    if (!isSaving) {
      onCancel();
    }
  };

  return (
    <DialogFrame
      title={t("ui.containers.account_title")}
      icon="server"
      hasHeadClose={false}
      foot={
        <>
          <button
            type="button"
            className="button"
            disabled={isSaving}
            onClick={cancel}
          >
            {t("ui.confirm.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={!isReady}
            onClick={() => void confirm()}
          >
            {isSaving ? (
              <Spinner size={13} />
            ) : (
              <Icon name="download" size={14} />
            )}
            {t("ui.modules.install")}
          </button>
        </>
      }
      onClose={cancel}
    >
      {resource.error !== null && view === null ? (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      ) : view === null ? (
        <div className="skeleton" style={{ height: 64 }} />
      ) : (
        <>
          <Picker
            options={view.system_accounts.map((entry) => ({
              id: entry.account,
              name: entry.account,
              detail: entry.home,
            }))}
            value={account}
            onChange={setAccount}
            label={t("ui.containers.run_account")}
            hint={t("ui.containers.account_hint")}
            placeholder={t("ui.accounts.system_account_placeholder")}
            emptyText={t("ui.containers.account_empty")}
            isDisabled={isSaving}
          />
          {isPasswordAsked && (
            <label className="field">
              <span className="field_label">{t("ui.accounts.password")}</span>
              <PasswordInput value={password} onChange={setPassword} />
              <span className="field_hint">
                {t("ui.accounts.password_hint")}
              </span>
            </label>
          )}
        </>
      )}
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </DialogFrame>
  );
}
