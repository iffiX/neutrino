import { useState } from "react";

import { ContainersMachineFields } from "./containers_machine_fields";
import { DialogFrame } from "./dialog_frame";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Picker } from "./picker";
import { Spinner } from "./spinner";
import { ApiError, apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { machineDiskError } from "../podman_machine";
import type { MachineSize } from "../podman_machine";
import { useApiResource } from "../use_api_resource";
import type {
  AccountListView,
  AccountPasswordTest,
  AccountSetRequest,
  PodmanDeviceView,
  PodmanMachineUpdate,
  PodmanNewMachineView,
} from "../api_types";

/**
 * The account and the size of Containers' Podman machine, asked before an
 * Install on a Windows or macOS machine whose Run settings name no account.
 *
 * A single choice among the accounts the machine reports, and the machine's
 * CPUs, memory and disk limit, each filled with the number the machine reports
 * for a new machine. On Windows an account with no stored login also takes its
 * password. **Install** first has Windows test the password on Windows, adds
 * the account when it is not yet available, writes the Run settings with the
 * numbers shown, and hands on to the press. Cancel writes nothing.
 */

const ACCOUNT_PATH = "/agent/module/account";
const PASSWORD_TEST_PATH = `${ACCOUNT_PATH}/password/test`;
const NEW_MACHINE_PATH = "/agent/module/podman/new_machine";
const MACHINE_SET_PATH = "/agent/module/podman/machine/set";

/** The system whose machine starts with the account's Windows login. */
const WINDOWS_OS = "windows";

/** The refusal of a password Windows does not accept. */
const CODE_CREDENTIAL_INVALID = "credential_invalid";

interface ContainersAccountModalProps {
  deviceId: string;
  /** The module being installed, counted in the memory hint. */
  module: string;
  /** Called once the Run settings name the account. */
  onChosen: () => void;
  onCancel: () => void;
}

export function ContainersAccountModal({
  deviceId,
  module,
  onChosen,
  onCancel,
}: ContainersAccountModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AccountListView>(
    apiPath(ACCOUNT_PATH, { device_id: deviceId }),
  );
  const [account, setAccount] = useState("");
  const newMachine = useApiResource<PodmanNewMachineView>(
    apiPath(NEW_MACHINE_PATH, { device_id: deviceId, account, module }),
  );
  const [password, setPassword] = useState("");
  const [isLoginRefused, setIsLoginRefused] = useState(false);
  const [edits, setEdits] = useState<Partial<MachineSize>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = resource.data;
  const numbers = newMachine.data;

  const isWindows = view?.platform_os === WINDOWS_OS;
  const held = view?.accounts.find((row) => row.account === account);
  const isPasswordAsked =
    isWindows && account !== "" && (held?.has_login !== true || isLoginRefused);
  const size: MachineSize = {
    cpus: edits.cpus ?? numbers?.cpus ?? 0,
    memory_gib: edits.memory_gib ?? numbers?.memory_gib ?? 0,
    disk_gib: edits.disk_gib ?? numbers?.disk_gib ?? 0,
  };
  const currentDisk = numbers?.disk_gib_now ?? 0;
  const needGib = numbers?.need_gib ?? 0;
  const memoryNow = size.memory_gib || (numbers?.memory_gib ?? 0);
  const loadError =
    view === null ? resource.error : numbers === null ? newMachine.error : null;
  const isReady =
    view !== null &&
    numbers !== null &&
    !newMachine.isLoading &&
    newMachine.error === null &&
    account !== "" &&
    !isSaving &&
    !(isPasswordAsked && password === "") &&
    machineDiskError(size.disk_gib, currentDisk, isWindows) === null;

  const shownError = error ?? (loadError === null ? newMachine.error : null);

  const pickAccount = (name: string) => {
    setAccount(name);
    setPassword("");
    setIsLoginRefused(false);
    setError(null);
  };

  const testPassword = async () => {
    const request: AccountPasswordTest = {
      device_id: deviceId,
      account,
      password: isPasswordAsked ? password : "",
    };
    await apiPost<AccountListView>(PASSWORD_TEST_PATH, request);
  };

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

  const writeMachine = async () => {
    const request: PodmanMachineUpdate = {
      device_id: deviceId,
      account,
      ...size,
    };
    await apiPost<PodmanDeviceView>(MACHINE_SET_PATH, request);
  };

  const confirm = async () => {
    setIsSaving(true);
    setError(null);
    try {
      if (isWindows) {
        await testPassword();
      }
      if (held === undefined || isPasswordAsked) {
        await writeAccount();
      }
      await writeMachine();
      onChosen();
    } catch (cause: unknown) {
      if (cause instanceof ApiError && cause.code === CODE_CREDENTIAL_INVALID) {
        setIsLoginRefused(true);
      }
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
      {loadError !== null ? (
        <ErrorPanel
          message={loadError}
          onRetry={view === null ? resource.reload : newMachine.reload}
        />
      ) : view === null || numbers === null ? (
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
            onChange={pickAccount}
            label={t("ui.containers.run_account")}
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
          <ContainersMachineFields
            size={size}
            currentDisk={currentDisk}
            isWindows={isWindows}
            memoryNeedGib={needGib > memoryNow ? needGib : null}
            isDisabled={isSaving}
            onChange={(change) => setEdits({ ...edits, ...change })}
          />
        </>
      )}
      {shownError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{shownError}</div>
        </div>
      )}
    </DialogFrame>
  );
}
