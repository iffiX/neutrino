import { useState } from "react";

import { DirectoryPickerModal } from "./directory_picker_modal";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPath, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  FolderShareListView,
  FolderShareRemove,
  FolderShareUpdate,
  FolderShareView,
} from "../api_types";

import "./folder_shares_panel.css";

/**
 * **Folder shares**: shares the person names, each at a folder on the
 * machine, open to the accounts checked for it.
 *
 * **Add** opens the inline form under the list, lit with the accent frame;
 * **Edit** opens the same form in the row's place, its name fixed. A row is
 * the share's name, its folder and its accounts. **Remove** asks first. Each
 * write acts at once, with no apply bar. The checkboxes list the accounts
 * **Home shares** enables as applied, and **Add** waits for one.
 */

/** Which form is open: a new share's, or a share's by name. */
const NEW_SHARE = "";

interface FolderSharesPanelProps {
  deviceId: string;
  /** Where the file share answers: `/agent/module/samba`. */
  basePath: string;
  isEditable: boolean;
}

export function FolderSharesPanel({
  deviceId,
  basePath,
  isEditable,
}: FolderSharesPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const path = `${basePath}/folder_share`;
  const resource = useApiResource<FolderShareListView>(
    apiPath(path, { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );
  const confirm = useConfirm();
  // The open form: NEW_SHARE, a share's name, or null.
  const [editing, setEditing] = useState<string | null>(null);
  const [busyShare, setBusyShare] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = resource.data;
  const hasAccounts = view !== null && view.accounts.length > 0;

  const handleSaved = (next: FolderShareListView) => {
    resource.setData(next);
    setEditing(null);
  };

  const remove = async (share: FolderShareView) => {
    setBusyShare(share.name);
    setError(null);
    const request: FolderShareRemove = {
      device_id: deviceId,
      name: share.name,
    };
    try {
      resource.setData(
        await apiPost<FolderShareListView>(`${path}/remove`, request),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setBusyShare(null);
    }
  };

  const askRemove = (share: FolderShareView) =>
    confirm.ask({
      title: t("ui.samba.folder_remove_title", { name: share.name }),
      body: t("ui.samba.folder_remove_body", { path: share.path }),
      confirmLabel: t("ui.samba.folder_remove"),
      onConfirm: () => void remove(share),
    });

  return (
    <section className="settings_group">
      <div className="settings_group_title folder_shares_title">
        <h2>{t("ui.samba.folder_shares")}</h2>
        <button
          type="button"
          className="button button--small"
          disabled={!isEditable || !hasAccounts || editing !== null}
          title={
            view !== null && !hasAccounts
              ? t("ui.samba.folder_no_accounts")
              : undefined
          }
          onClick={() => setEditing(NEW_SHARE)}
        >
          <Icon name="plus" size={13} />
          {t("ui.samba.folder_add")}
        </button>
      </div>
      <p className="field_hint">{t("ui.samba.folder_shares_hint")}</p>

      {resource.error !== null && view === null ? (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      ) : view === null ? (
        <div className="skeleton" style={{ height: 96 }} />
      ) : (
        <>
          {view.shares.length === 0 && editing === null && (
            <div className="placeholder">
              <span>{t("ui.samba.folder_empty")}</span>
              {!hasAccounts && (
                <span className="faint">
                  {t("ui.samba.folder_no_accounts")}
                </span>
              )}
            </div>
          )}
          {view.shares.length > 0 && (
            <div className="folder_shares_list">
              {view.shares.map((share) =>
                editing === share.name ? (
                  <FolderShareForm
                    key={share.name}
                    deviceId={deviceId}
                    path={path}
                    view={view}
                    share={share}
                    isEditable={isEditable}
                    onSaved={handleSaved}
                    onCancel={() => setEditing(null)}
                  />
                ) : (
                  <div key={share.name} className="folder_shares_row">
                    <span className="folder_shares_row_name mono">
                      {share.name}
                    </span>
                    <span className="folder_shares_row_path mono">
                      {share.path}
                    </span>
                    <span className="folder_shares_row_accounts">
                      {share.accounts.join(", ")}
                    </span>
                    <span className="folder_shares_row_actions">
                      <button
                        type="button"
                        className="button button--ghost button--small"
                        disabled={!isEditable || editing !== null}
                        onClick={() => setEditing(share.name)}
                      >
                        {t("ui.samba.folder_edit")}
                      </button>
                      <button
                        type="button"
                        className="button button--ghost button--small button--danger"
                        disabled={!isEditable || busyShare === share.name}
                        onClick={() => askRemove(share)}
                      >
                        {t("ui.samba.folder_remove")}
                      </button>
                    </span>
                  </div>
                ),
              )}
            </div>
          )}
          {editing === NEW_SHARE && (
            <FolderShareForm
              deviceId={deviceId}
              path={path}
              view={view}
              share={null}
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

interface FolderShareFormProps {
  deviceId: string;
  /** Where the folder shares answer: `/agent/module/samba/folder_share`. */
  path: string;
  view: FolderShareListView;
  /** The share being edited, or null for a new one. */
  share: FolderShareView | null;
  isEditable: boolean;
  onSaved: (view: FolderShareListView) => void;
  onCancel: () => void;
}

/** The inline form of a folder share: its name, its folder with Browse…,
 * and a checkbox per account **Home shares** enables. */
function FolderShareForm({
  deviceId,
  path,
  view,
  share,
  isEditable,
  onSaved,
  onCancel,
}: FolderShareFormProps) {
  const [name, setName] = useState(share?.name ?? "");
  const [folder, setFolder] = useState(share?.path ?? "");
  const [accounts, setAccounts] = useState<string[]>(
    share?.accounts.filter((account) => view.accounts.includes(account)) ?? [],
  );
  const [isBrowsing, setIsBrowsing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = share === null;
  const isReady =
    name.trim() !== "" &&
    folder.trim() !== "" &&
    accounts.length > 0 &&
    isEditable &&
    !isSaving;

  const toggle = (account: string, isOn: boolean) => {
    setAccounts(
      isOn
        ? view.accounts.filter(
            (held) => held === account || accounts.includes(held),
          )
        : accounts.filter((held) => held !== account),
    );
  };

  const save = async () => {
    setIsSaving(true);
    setError(null);
    const request: FolderShareUpdate = {
      device_id: deviceId,
      name: name.trim(),
      path: folder.trim(),
      accounts,
    };
    try {
      onSaved(
        await apiPost<FolderShareListView>(
          `${path}/${isNew ? "add" : "set"}`,
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
    <div className="inline_form folder_share_form">
      <label className="field">
        <span className="field_label">{t("ui.samba.folder_name")}</span>
        <input
          className="input mono"
          value={name}
          spellCheck={false}
          disabled={!isNew}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        <span className="field_label">{t("ui.samba.folder_path")}</span>
        <span className="folder_share_form_path">
          <input
            className="input mono"
            value={folder}
            spellCheck={false}
            onChange={(event) => setFolder(event.target.value)}
          />
          <button
            type="button"
            className="button"
            onClick={() => setIsBrowsing(true)}
          >
            <Icon name="folder" size={14} />
            {t("ui.accounts.browse")}
          </button>
        </span>
      </label>
      <div className="field">
        <span className="field_label">{t("ui.samba.folder_accounts")}</span>
        <div className="folder_share_form_accounts">
          {view.accounts.map((account) => (
            <label key={account} className="folder_share_form_account">
              <input
                type="checkbox"
                checked={accounts.includes(account)}
                onChange={(event) => toggle(account, event.target.checked)}
              />
              <span className="mono">{account}</span>
            </label>
          ))}
        </div>
      </div>
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
      {isBrowsing && (
        <DirectoryPickerModal
          deviceId={deviceId}
          startPath={folder}
          pick="directory"
          onPick={(picked) => {
            setFolder(picked);
            setIsBrowsing(false);
          }}
          onCancel={() => setIsBrowsing(false)}
        />
      )}
    </div>
  );
}
