import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { StatusDot } from "./status_dot";
import { apiPath, apiPost, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { hasWord, t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import { isFailing, useSettledApply } from "../use_settled_apply";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type { ReportedModule } from "../use_settled_apply";
import type { ModuleDescriptor } from "../module_descriptors";
import type {
  EnabledAccountsUpdate,
  EnabledAccountsView,
  EnabledAccountView,
} from "../api_types";

import "./instances_panel.css";

/**
 * A module of the account layer on one machine: which of the machine's
 * available accounts it runs for, **Enabled accounts**.
 *
 * One check row per available account; an account checked goes to the end
 * of the order, and the apply bar writes the whole list. A row shows the
 * module's own field of the account, whether its instance runs, and its
 * code's words. The SSH server shows the machine's host key under the rows.
 * The module's words come from its descriptor.
 */

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** The module whose rows end with the machine's host key. */
const SSH_SERVER_MODULE = "ssh_server";

/** What the apply asks of the module. */
const WANT_RUNNING = "running";

/** The words a row's field shows while it is empty and the default holds. */
const FIELD_DEFAULT_KEYS: Record<string, string> = {
  shell_path: "ui.modules.login_shell",
  share_path: "ui.modules.home_folder",
};

/** The enabled accounts, in the order they were checked. */
interface EnabledDraft {
  accounts: string[];
}

interface InstancesPanelProps {
  /** The module, as the page's descriptor table describes it. */
  descriptor: ModuleDescriptor;
  /** The machine whose module this is. */
  deviceId: string;
  /** Where the module answers: `/agent/module/<module>`. */
  basePath: string;
  isEditable: boolean;
}

export function InstancesPanel({
  descriptor,
  deviceId,
  basePath,
  isEditable,
}: InstancesPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<EnabledAccountsView>(
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
  const settle = useSettledApply(reportOf(saved), WANT_RUNNING);

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 160 }} />;
  }

  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const isLocked = !isEditable || isUnsupported;
  const version = saved.version ?? "";

  const toggle = (account: string, isOn: boolean) => {
    setDraft({
      accounts: isOn
        ? [...draft.accounts.filter((name) => name !== account), account]
        : draft.accounts.filter((name) => name !== account),
    });
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    settle.clear();
    const request: EnabledAccountsUpdate = {
      device_id: deviceId,
      accounts: draft.accounts,
    };
    try {
      resource.setData(
        await apiPost<EnabledAccountsView>(`${basePath}/set`, request),
      );
      settle.begin();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const report = reportOf(saved);
  return (
    <>
      {descriptor.ownerNotice !== undefined && (
        <p className="field_hint">
          {version === "" || descriptor.ownerNoticeVersion === undefined
            ? t(descriptor.ownerNotice)
            : t(descriptor.ownerNoticeVersion, { version })}
        </p>
      )}
      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t(descriptor.title ?? "ui.modules.enabled_accounts")}</h2>
        </div>
        {descriptor.titleHint !== undefined && (
          <p className="field_hint">{t(descriptor.titleHint)}</p>
        )}
        {saved.accounts.length === 0 ? (
          <p className="field_hint">{t("ui.modules.no_accounts")}</p>
        ) : (
          <div className="instances_rows">
            {saved.accounts.map((row) => (
              <AccountRow
                key={row.account}
                row={row}
                descriptor={descriptor}
                isChecked={draft.accounts.includes(row.account)}
                isDisabled={isLocked}
                onToggle={(isOn) => toggle(row.account, isOn)}
              />
            ))}
          </div>
        )}
        {descriptor.name === SSH_SERVER_MODULE &&
          (saved.host_key_fingerprint ?? "") !== "" && (
            <p className="field_hint mono">
              {t("ui.ssh_server.host_key", {
                fingerprint: saved.host_key_fingerprint ?? "",
              })}
            </p>
          )}
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy || settle.isSettling}
          label={t(descriptor.apply)}
          hint={t(descriptor.applyHint)}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
          isApplyDisabled={isUnsupported}
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
    </>
  );
}

interface AccountRowProps {
  row: EnabledAccountView;
  descriptor: ModuleDescriptor;
  isChecked: boolean;
  isDisabled: boolean;
  onToggle: (isOn: boolean) => void;
}

/** One available account: its check, its field, its instance's state. */
function AccountRow({
  row,
  descriptor,
  isChecked,
  isDisabled,
  onToggle,
}: AccountRowProps) {
  const field = descriptor.field;
  const fieldValue = field === null ? "" : (row[field] ?? "");
  return (
    <div className="instances_row">
      <label className="instances_row_check">
        <input
          type="checkbox"
          checked={isChecked}
          disabled={isDisabled}
          onChange={(event) => onToggle(event.target.checked)}
        />
        <span className="mono">{row.account}</span>
      </label>
      {field !== null && (
        <span className="instances_row_field mono">
          {fieldValue !== "" ? (
            fieldValue
          ) : (
            <span className="faint">{t(FIELD_DEFAULT_KEYS[field] ?? "")}</span>
          )}
        </span>
      )}
      {row.is_enabled && (
        <StatusDot
          tone={row.is_running ? "ok" : "idle"}
          label={t(row.is_running ? "state.running" : "state.stopped")}
        />
      )}
      {row.code !== "" && (
        <span className="field_error instances_row_error">
          {describeCode(row)}
        </span>
      )}
    </div>
  );
}

/** What the form starts from: the enabled accounts in their order. */
function draftOf(view: EnabledAccountsView): EnabledDraft {
  return {
    accounts: view.accounts
      .filter((row) => row.is_enabled)
      .map((row) => row.account),
  };
}

/** The module as an apply waits on it: its state and its enabled rows. */
function reportOf(view: EnabledAccountsView | null): ReportedModule | null {
  if (view === null) {
    return null;
  }
  return {
    state: view.state,
    instances: view.accounts
      .filter((row) => row.is_enabled)
      .map((row) => ({ is_running: row.is_running, code: row.code })),
  };
}

/** Why an account's instance does not run, from the code the machine
 * reported. */
function describeCode(row: EnabledAccountView): string {
  const key = `code.${row.code}`;
  return hasWord(key)
    ? t(key, { account: row.account, ...codeParams(row.params) })
    : t("ui.modules.failed_code", { code: row.code });
}
