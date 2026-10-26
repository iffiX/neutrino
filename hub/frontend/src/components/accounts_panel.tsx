import { useState } from "react";

import { AccountForm } from "./account_form";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { apiPath, apiPost, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { hasWord, t, useLanguage } from "../i18n";
import { moduleTitle } from "../module_title";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  AccountListView,
  AccountRemoveRequest,
  AvailableAccountView,
} from "../api_types";

import "./accounts_panel.css";

/**
 * **Available accounts**: the machine's accounts the person added, the ones
 * its terminal, files and programs run as.
 *
 * **Add** opens the inline form under the list, lit with the accent frame;
 * **Edit** opens the same form in the row's place. A row is the account's
 * name and, while its AI tools switch is on, the machine's last result as a
 * dot and a word. **Remove** asks first, naming the modules that lose the
 * account. Each write acts at once.
 */

const ACCOUNTS_PATH = "/agent/module/account";

/** The word and the tone of each reported AI tools result. */
const AI_TOOLS_KEYS: Record<string, string> = {
  switched: "state.ai_tools_switched",
  switched_back: "state.ai_tools_switched_back",
};
const AI_TOOLS_TONES: Record<string, StatusTone> = {
  switched: "ok",
  switched_back: "idle",
  failed: "error",
};
const AI_TOOLS_FAILED = "failed";
const CODE_SWITCH_FAILED = "switch_failed";

/** Which form is open: a new account's, or an account's by name. */
const NEW_ACCOUNT = "";

interface AccountsPanelProps {
  deviceId: string;
  isEditable: boolean;
}

export function AccountsPanel({ deviceId, isEditable }: AccountsPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AccountListView>(
    apiPath(ACCOUNTS_PATH, { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );
  const confirm = useConfirm();
  // The open form: NEW_ACCOUNT, an account's name, or null.
  const [editing, setEditing] = useState<string | null>(null);
  const [busyAccount, setBusyAccount] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = resource.data;

  const handleSaved = (next: AccountListView) => {
    resource.setData(next);
    setEditing(null);
  };

  const remove = async (account: AvailableAccountView) => {
    setBusyAccount(account.account);
    setError(null);
    const request: AccountRemoveRequest = {
      device_id: deviceId,
      account: account.account,
    };
    try {
      resource.setData(
        await apiPost<AccountListView>(`${ACCOUNTS_PATH}/remove`, request),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setBusyAccount(null);
    }
  };

  const askRemove = (account: AvailableAccountView) =>
    confirm.ask({
      title: t("ui.accounts.remove_title", { account: account.account }),
      body:
        account.modules.length === 0
          ? t("ui.accounts.remove_body_none", { account: account.account })
          : t("ui.accounts.remove_body", {
              account: account.account,
              modules: account.modules
                .map((name) => moduleTitle(name, name))
                .join(", "),
            }),
      confirmLabel: t("ui.accounts.remove"),
      onConfirm: () => void remove(account),
    });

  return (
    <section className="settings_group">
      <div className="settings_group_title accounts_title">
        <h2>{t("ui.accounts.title")}</h2>
        <button
          type="button"
          className="button button--small"
          disabled={!isEditable || view === null || editing !== null}
          onClick={() => setEditing(NEW_ACCOUNT)}
        >
          <Icon name="plus" size={13} />
          {t("ui.accounts.add")}
        </button>
      </div>

      {resource.error !== null && view === null ? (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      ) : view === null ? (
        <div className="skeleton" style={{ height: 96 }} />
      ) : (
        <>
          {view.accounts.length === 0 && editing === null && (
            <div className="placeholder">
              <span>{t("ui.accounts.empty")}</span>
              <span className="faint">{t("ui.accounts.empty_hint")}</span>
            </div>
          )}
          {view.accounts.length > 0 && (
            <div className="accounts_list">
              {view.accounts.map((account) =>
                editing === account.account ? (
                  <AccountForm
                    key={account.account}
                    deviceId={deviceId}
                    view={view}
                    account={account}
                    isEditable={isEditable}
                    onSaved={handleSaved}
                    onCancel={() => setEditing(null)}
                  />
                ) : (
                  <div key={account.account} className="accounts_row">
                    <span className="accounts_row_name mono">
                      {account.account}
                    </span>
                    {account.is_ai_tools_enabled && (
                      <StatusDot
                        tone={AI_TOOLS_TONES[account.ai_tools.state] ?? "idle"}
                        label={describeAiTools(account)}
                      />
                    )}
                    <span className="accounts_row_actions">
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        disabled={!isEditable || editing !== null}
                        onClick={() => setEditing(account.account)}
                      >
                        {t("ui.accounts.edit")}
                      </button>
                      <button
                        type="button"
                        className="button button--ghost button--small button--danger"
                        disabled={
                          !isEditable || busyAccount === account.account
                        }
                        onClick={() => askRemove(account)}
                      >
                        {t("ui.accounts.remove")}
                      </button>
                    </span>
                  </div>
                ),
              )}
            </div>
          )}
          {editing === NEW_ACCOUNT && (
            <AccountForm
              deviceId={deviceId}
              view={view}
              account={null}
              isEditable={isEditable}
              onSaved={handleSaved}
              onCancel={() => setEditing(null)}
            />
          )}
          {error !== null && <span className="field_error">{error}</span>}
        </>
      )}
      {confirm.modal}
    </section>
  );
}

/** The machine's last word on an account's AI tools; a failure in its
 * code's words, a detail that is itself a code worded too. */
function describeAiTools(account: AvailableAccountView): string {
  const result = account.ai_tools;
  if (result.state !== AI_TOOLS_FAILED) {
    return t(AI_TOOLS_KEYS[result.state] ?? "ui.device_monitor.waiting");
  }
  const key =
    !account.is_ai_tools_enabled && result.code === CODE_SWITCH_FAILED
      ? "ui.ai_tools.switch_back_failed"
      : `code.${result.code}`;
  const params: Record<string, string | number> = {
    account: account.account,
    ...codeParams(result.params),
  };
  const detailKey = `code.${String(params.detail ?? "")}`;
  if (
    params.detail !== undefined &&
    hasWord(detailKey) &&
    !/\{\w+\}/.test(t(detailKey))
  ) {
    params.detail = t(detailKey);
  }
  return hasWord(key)
    ? t(key, params)
    : t("ui.modules.failed_code", { code: result.code });
}
