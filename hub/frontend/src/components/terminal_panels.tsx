import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { DirectoryPickerModal } from "./directory_picker_modal";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type { PickerOption } from "./picker";
import type { TerminalConfigUpdate, TerminalDeviceView } from "../api_types";

import "./terminal_panels.css";

/**
 * The Terminal module on one machine: the account a terminal runs as and its
 * shell program.
 *
 * Both empty is the shell the agent runs by default. Terminals opened after
 * an apply use the settings, from the panel and from clients alike; open
 * ones keep what they run. A Windows machine takes the shell program alone.
 */

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** The picker's row for the agent's own account, which is stored empty. */
const AGENT_ACCOUNT = "";

interface TerminalPanelsProps {
  /** The machine whose terminal this is. */
  deviceId: string;
  /** Where the module answers: `/agent/module/terminal`. */
  basePath: string;
  isEditable: boolean;
}

/** The form's own fields; the machine they are written to is the page's. */
type TerminalDraft = Omit<TerminalConfigUpdate, "device_id">;

export function TerminalPanels({
  deviceId,
  basePath,
  isEditable,
}: TerminalPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<TerminalDeviceView>(
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
  const [isBrowsing, setIsBrowsing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 200 }} />;
  }

  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const accounts: PickerOption[] = [
    { id: AGENT_ACCOUNT, name: t("ui.terminal_module.account_agent") },
    ...saved.accounts.map((account) => ({ id: account, name: account })),
  ];

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: TerminalConfigUpdate = { device_id: deviceId, ...draft };
    try {
      resource.setData(
        await apiPost<TerminalDeviceView>(`${basePath}/set`, request),
      );
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
      <div className="terminal_module_fields">
        <Picker
          options={accounts}
          value={saved.is_account_settable ? draft.account : AGENT_ACCOUNT}
          onChange={(account) => setDraft({ ...draft, account })}
          label={t("ui.terminal_module.account")}
          hint={
            saved.is_account_settable
              ? undefined
              : t("ui.terminal_module.account_windows")
          }
          isDisabled={!saved.is_account_settable || isUnsupported}
        />
        <label className="field">
          <span className="field_label">
            {t("ui.terminal_module.shell_path")}
          </span>
          <span className="terminal_module_path">
            <input
              className="input mono"
              value={draft.shell_path}
              spellCheck={false}
              disabled={isUnsupported}
              onChange={(event) =>
                setDraft({ ...draft, shell_path: event.target.value })
              }
            />
            <button
              type="button"
              className="button"
              disabled={!isEditable || isUnsupported}
              onClick={() => setIsBrowsing(true)}
            >
              <Icon name="folder" size={14} />
              {t("ui.terminal_module.browse")}
            </button>
          </span>
          <span className="field_hint">
            {t("ui.terminal_module.shell_path_hint")}
          </span>
        </label>
      </div>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.terminal_module.apply")}
        hint={t("ui.terminal_module.apply_hint")}
        blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
        isApplyDisabled={isUnsupported}
        error={error}
        onReset={() => {
          reset();
          setError(null);
        }}
        onApply={() => void apply()}
      />
      {isBrowsing && (
        <DirectoryPickerModal
          deviceId={deviceId}
          startPath={folderOf(draft.shell_path)}
          pick="file"
          onPick={(path) => {
            setDraft({ ...draft, shell_path: path });
            setIsBrowsing(false);
          }}
          onCancel={() => setIsBrowsing(false)}
        />
      )}
    </section>
  );
}

/** What the form starts from: the settings as saved. */
function draftOf(view: TerminalDeviceView): TerminalDraft {
  return { account: view.account, shell_path: view.shell_path };
}

/** The folder a path's file is in, where the path window opens; empty for
 * the machine's root. */
function folderOf(path: string): string {
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return cut > 0 ? path.slice(0, cut) : "";
}
