import { useState } from "react";

import { AiToolModels } from "./ai_tool_models";
import { DirectoryPickerModal } from "./directory_picker_modal";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Picker } from "./picker";
import { Spinner } from "./spinner";
import { ToggleSwitch } from "./toggle_switch";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type {
  AccountListView,
  AccountSetRequest,
  AiToolConfigs,
  AvailableAccountView,
} from "../api_types";

import "./account_form.css";

/**
 * The inline form of one available account: the system account, its
 * password on Windows, its share path and its shell each with Browse…, and
 * the switch that points its AI tools at the hub's gateway with the model
 * rows under it. Cancel and Save sit at its bottom right.
 *
 * An empty share path or shell sends empty, and the account's own default
 * holds; the field shows that default as its placeholder.
 */

const WINDOWS_OS = "windows";

/** The shell a Windows account runs when its field is left empty. */
const WINDOWS_SHELL_PLACEHOLDER = "powershell.exe";

/** Which field a path window is open for. */
type BrowseField = "share_path" | "shell_path";

interface AccountFormProps {
  deviceId: string;
  /** The machine's accounts, the form's choices and their defaults. */
  view: AccountListView;
  /** The account being edited, or null for a new one. */
  account: AvailableAccountView | null;
  isEditable: boolean;
  onSaved: (view: AccountListView) => void;
  onCancel: () => void;
}

export function AccountForm({
  deviceId,
  view,
  account,
  isEditable,
  onSaved,
  onCancel,
}: AccountFormProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState(account?.account ?? "");
  const [password, setPassword] = useState("");
  const [sharePath, setSharePath] = useState(account?.share_path ?? "");
  const [shellPath, setShellPath] = useState(account?.shell_path ?? "");
  const [isAiToolsEnabled, setIsAiToolsEnabled] = useState(
    account?.is_ai_tools_enabled ?? false,
  );
  const [toolConfigs, setToolConfigs] = useState<AiToolConfigs>(
    account?.tool_configs ?? {},
  );
  const [browsing, setBrowsing] = useState<BrowseField | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isWindows = view.platform_os === WINDOWS_OS;
  const isNew = account === null;
  const taken = view.accounts.map((entry) => entry.account);
  const choices = view.system_accounts.filter(
    (entry) =>
      entry.account === account?.account || !taken.includes(entry.account),
  );
  const details =
    view.system_accounts.find((entry) => entry.account === name) ?? null;
  const shellPlaceholder =
    details?.shell || (isWindows ? WINDOWS_SHELL_PLACEHOLDER : "");
  // A Windows account needs its password the first time.
  const isPasswordMissing =
    isWindows && password === "" && account?.has_login !== true;
  const canTurnAiToolsOn = isAiToolsEnabled || view.is_gateway_serving;
  const isReady = name !== "" && !isPasswordMissing && isEditable && !isSaving;

  const save = async () => {
    setIsSaving(true);
    setError(null);
    const request: AccountSetRequest = {
      device_id: deviceId,
      account: name,
      password: isWindows ? password : "",
      share_path: sharePath.trim(),
      shell_path: shellPath.trim(),
      is_ai_tools_enabled: isAiToolsEnabled,
      tool_configs: toolConfigs,
    };
    try {
      onSaved(
        await apiPost<AccountListView>(
          `/agent/module/account/${isNew ? "add" : "set"}`,
          request,
        ),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="inline_form account_form">
      <Picker
        options={choices.map((entry) => ({
          id: entry.account,
          name: entry.account,
          detail: entry.home,
        }))}
        value={name}
        onChange={setName}
        label={t("ui.accounts.system_account")}
        placeholder={t("ui.accounts.system_account_placeholder")}
        isDisabled={!isNew}
      />
      {isWindows && (
        <label className="field">
          <span className="field_label">{t("ui.accounts.password")}</span>
          <PasswordInput value={password} onChange={setPassword} />
          <span className="field_hint">{t("ui.accounts.password_hint")}</span>
        </label>
      )}
      <PathField
        label={t("ui.accounts.share_path")}
        value={sharePath}
        placeholder={details?.home ?? ""}
        isDisabled={name === ""}
        onChange={setSharePath}
        onBrowse={() => setBrowsing("share_path")}
      />
      <PathField
        label={t("ui.accounts.shell")}
        value={shellPath}
        placeholder={shellPlaceholder}
        isDisabled={name === ""}
        onChange={setShellPath}
        onBrowse={() => setBrowsing("shell_path")}
      />
      <ToggleSwitch
        isOn={isAiToolsEnabled}
        onChange={setIsAiToolsEnabled}
        label={t("ui.accounts.ai_tools")}
        isDisabled={!canTurnAiToolsOn}
      />
      {!canTurnAiToolsOn && (
        <span className="field_hint">{t("code.gateway_not_serving")}</span>
      )}
      {isAiToolsEnabled && (
        <AiToolModels
          configs={toolConfigs}
          models={view.models}
          onChange={setToolConfigs}
        />
      )}
      {error !== null && <span className="field_error">{error}</span>}
      <div className="inline_form_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          {t("ui.accounts.cancel")}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady}
          onClick={() => void save()}
        >
          {isSaving ? <Spinner size={13} /> : <Icon name="check" size={14} />}
          {t("ui.accounts.save")}
        </button>
      </div>
      {browsing !== null && (
        <DirectoryPickerModal
          deviceId={deviceId}
          startPath={
            browsing === "share_path"
              ? sharePath || (details?.home ?? "")
              : shellPath || shellPlaceholder
          }
          pick={browsing === "share_path" ? "directory" : "file"}
          onPick={(path) => {
            if (browsing === "share_path") {
              setSharePath(path);
            } else {
              setShellPath(path);
            }
            setBrowsing(null);
          }}
          onCancel={() => setBrowsing(null)}
        />
      )}
    </div>
  );
}

interface PathFieldProps {
  label: string;
  value: string;
  placeholder: string;
  isDisabled: boolean;
  onChange: (value: string) => void;
  onBrowse: () => void;
}

/** A path typed or picked with Browse…, the default as its placeholder. */
function PathField({
  label,
  value,
  placeholder,
  isDisabled,
  onChange,
  onBrowse,
}: PathFieldProps) {
  return (
    <label className="field">
      <span className="field_label">{label}</span>
      <span className="account_form_path">
        <input
          className="input mono"
          value={value}
          placeholder={placeholder}
          spellCheck={false}
          disabled={isDisabled}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className="button"
          disabled={isDisabled}
          onClick={onBrowse}
        >
          <Icon name="folder" size={14} />
          {t("ui.accounts.browse")}
        </button>
      </span>
    </label>
  );
}
