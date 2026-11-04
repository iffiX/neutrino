import { useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { StatusDot } from "./status_dot";
import { AI_TOOLS_TONES, aiToolsWords } from "../ai_tools_words";
import { apiPath, apiPost, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { hasWord, t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import {
  FAILED_STATES,
  isFailing,
  useSettledApply,
} from "../use_settled_apply";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type { ReportedModule } from "../use_settled_apply";
import type { ModuleDescriptor } from "../module_descriptors";
import type {
  AccountAiToolsView,
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
 * of the order, and the apply bar writes the whole list. While the module
 * reads failed the bar is lit, and its apply with nothing changed tries the
 * module again. An apply writes no want on a module not running. A row shows the module's own field of the account, whether
 * its instance runs, and its code's words. A command line program's row shows
 * the copy the account uses, its path, its version and the account's AI
 * tools state, and on macOS a line under the rows asks for `~/.local/bin`
 * on `PATH` while an account uses the module's copy. The SSH server shows
 * the machine's
 * host key under the rows. The module's words come from its descriptor.
 */

/** What an agent older than the module reports for it. */
const STATE_UNSUPPORTED = "unsupported";

/** What a module that runs reports. */
const STATE_RUNNING = "running";

/** The module whose rows end with the machine's host key. */
const SSH_SERVER_MODULE = "ssh_server";

/** What an apply on a module the agent carries waits for. */
const WANT_RUNNING = "running";

/** The words a row's field shows while it is empty and the default holds. */
const FIELD_DEFAULT_KEYS: Record<string, string> = {
  shell_path: "ui.modules.login_shell",
  share_path: "ui.modules.home_folder",
};

/** The copy a command line program's account uses, in the source chip's
 * words. */
const COPY_KEYS: Record<string, string> = {
  user: "ui.modules.source_user",
  module: "ui.modules.source_upstream",
};

/** The copy of a command line program's account that runs the module's own. */
const COPY_MODULE = "module";

/** The system whose shells put `~/.local/bin` on no `PATH`. */
const OS_DARWIN = "darwin";

/** The AI tools result of an account the machine has not reported: its tools
 * keep their own settings. */
const AI_TOOLS_UNREPORTED: AccountAiToolsView = {
  state: "switched_back",
  code: "",
  params: {},
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
  /** Whether the change takes effect at the module's next Start. */
  isWaitingForStart: boolean;
  /** What the hub asks of the module: `running`, `stopped`, `installed`, or
   * empty. */
  want: string;
  /** The system the machine's agent reports: `linux`, `windows`, `darwin`. */
  platformOs: string;
}

export function InstancesPanel({
  descriptor,
  deviceId,
  basePath,
  isEditable,
  isWaitingForStart,
  want,
  platformOs,
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
  const settle = useSettledApply(
    reportOf(saved, descriptor),
    isWaitingForStart || descriptor.isProgram === true ? want : WANT_RUNNING,
  );

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }
  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 160 }} />;
  }

  const isUnsupported = saved.state === STATE_UNSUPPORTED;
  const isLocked = !isEditable || isUnsupported;
  const isPending = isDirty || FAILED_STATES.includes(saved.state);
  const isReady =
    descriptor.isWithoutProgram === true && saved.state === STATE_RUNNING;
  const version = saved.version ?? "";
  const isPathHintShown =
    descriptor.isProgram === true &&
    platformOs === OS_DARWIN &&
    saved.accounts.some((row) => row.is_enabled && row.copy === COPY_MODULE);

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
      if (isDirty) {
        resource.setData(
          await apiPost<EnabledAccountsView>(`${basePath}/set`, request),
        );
      } else {
        await apiPost(`${basePath}/apply`, { device_id: deviceId });
        resource.reload();
      }
      settle.begin();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const report = reportOf(saved, descriptor);
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
        className={`settings_group ${isPending ? "settings_group--dirty" : ""}`}
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
            {saved.accounts.map((row) =>
              descriptor.isProgram === true ? (
                <ProgramAccountRow
                  key={row.account}
                  row={row}
                  isChecked={draft.accounts.includes(row.account)}
                  isDisabled={isLocked}
                  onToggle={(isOn) => {
                    toggle(row.account, isOn);
                  }}
                />
              ) : (
                <AccountRow
                  key={row.account}
                  row={row}
                  descriptor={descriptor}
                  isReady={isReady}
                  isChecked={draft.accounts.includes(row.account)}
                  isDisabled={isLocked}
                  onToggle={(isOn) => {
                    toggle(row.account, isOn);
                  }}
                />
              ),
            )}
          </div>
        )}
        {isPathHintShown && (
          <p className="field_hint">{t("ui.program.macos_path_hint")}</p>
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
          isDirty={isPending}
          hasChanges={isDirty}
          isBusy={isBusy || settle.isSettling}
          label={t(descriptor.apply)}
          hint={
            isWaitingForStart
              ? t("ui.modules.stopped_hint")
              : t(descriptor.applyHint)
          }
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
  /** Whether the row shows `state.ready` in place of its running dot. */
  isReady: boolean;
  isChecked: boolean;
  isDisabled: boolean;
  onToggle: (isOn: boolean) => void;
}

/** One available account: its check, its field, its instance's state. */
function AccountRow({
  row,
  descriptor,
  isReady,
  isChecked,
  isDisabled,
  onToggle,
}: AccountRowProps) {
  const field = descriptor.field;
  const fieldValue = field === null ? "" : (row[field] ?? "");
  return (
    <div className="instances_row">
      <AccountCheck
        account={row.account}
        isChecked={isChecked}
        isDisabled={isDisabled}
        onToggle={onToggle}
      />
      {field !== null && (
        <span className="instances_row_field mono">
          {fieldValue !== "" ? (
            fieldValue
          ) : (
            <span className="faint">{t(FIELD_DEFAULT_KEYS[field] ?? "")}</span>
          )}
        </span>
      )}
      {row.is_enabled &&
        (isReady ? (
          <StatusDot tone="ok" label={t("state.ready")} isPulsing={false} />
        ) : (
          <StatusDot
            tone={row.is_running ? "ok" : "idle"}
            label={t(row.is_running ? "state.running" : "state.stopped")}
          />
        ))}
      {row.code !== "" && (
        <span className="field_error instances_row_error">
          {describeCode(row)}
        </span>
      )}
    </div>
  );
}

interface ProgramAccountRowProps {
  row: EnabledAccountView;
  isChecked: boolean;
  isDisabled: boolean;
  onToggle: (isOn: boolean) => void;
}

/** One available account of a command line program: its check, and once it
 * is enabled the copy it uses, that copy's version, its AI tools state, shown
 * and never set here, and the copy's path on a line of its own. */
function ProgramAccountRow({
  row,
  isChecked,
  isDisabled,
  onToggle,
}: ProgramAccountRowProps) {
  const copyKey = COPY_KEYS[row.copy ?? ""];
  const reported = row.ai_tools ?? AI_TOOLS_UNREPORTED;
  const tools = reported.state === "" ? AI_TOOLS_UNREPORTED : reported;
  return (
    <div className="instances_row">
      <AccountCheck
        account={row.account}
        isChecked={isChecked}
        isDisabled={isDisabled}
        onToggle={onToggle}
      />
      {row.is_enabled && copyKey !== undefined && (
        <>
          <span className="badge">{t(copyKey)}</span>
          <span className="instances_row_version mono">{row.version}</span>
        </>
      )}
      {row.is_enabled && (
        <span className="instances_row_tools">
          <StatusDot
            tone={AI_TOOLS_TONES[tools.state] ?? "idle"}
            label={aiToolsWords(
              row.account,
              tools,
              row.is_ai_tools_enabled === true,
            )}
          />
        </span>
      )}
      {row.is_enabled && copyKey !== undefined && (
        <span className="instances_row_path mono">{row.path}</span>
      )}
      {row.code !== "" && (
        <span className="field_error instances_row_error">
          {describeCode(row)}
        </span>
      )}
    </div>
  );
}

interface AccountCheckProps {
  account: string;
  isChecked: boolean;
  isDisabled: boolean;
  onToggle: (isOn: boolean) => void;
}

/** An account's check and its name, at the start of its row. */
function AccountCheck({
  account,
  isChecked,
  isDisabled,
  onToggle,
}: AccountCheckProps) {
  return (
    <label className="instances_row_check">
      <input
        type="checkbox"
        checked={isChecked}
        disabled={isDisabled}
        onChange={(event) => {
          onToggle(event.target.checked);
        }}
      />
      <span className="mono">{account}</span>
    </label>
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

/** The module as an apply waits on it: its state and its enabled rows. A
 * module without a program waits for its state alone, and a command line
 * program for its state with no row. */
function reportOf(
  view: EnabledAccountsView | null,
  descriptor: ModuleDescriptor,
): ReportedModule | null {
  if (view === null) {
    return null;
  }
  return {
    state: view.state,
    instances:
      descriptor.isProgram === true
        ? []
        : view.accounts
            .filter((row) => row.is_enabled)
            .map((row) => ({
              is_running:
                row.is_running || descriptor.isWithoutProgram === true,
              code: row.code,
            })),
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
