import { useEffect, useState } from "react";
import { ApiError } from "../api_client";
import { copyText } from "../copy_text";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { ToggleSwitch } from "./toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type {
  ApplyResult,
  SambaDeviceView,
  SambaShare,
  SambaStatus,
  SambaUser,
} from "../api_types";

import "./samba_panels.css";

/**
 * The file share on one machine: what is exported, who may connect, who is
 * connected.
 *
 * Two framed groups follow the panel's one rule — save and apply together, per
 * frame. Passwords are the deliberate exception: they live only in Samba's
 * credential store, never in config/, so a box restored from backup honestly
 * shows "no password yet" instead of pretending the tarball knew it.
 *
 * A user is a credential, so it is added and deleted, never edited: the add
 * form takes the name and the password together, both staged behind Apply,
 * and replacing a password is removing the user and adding it again. Staged
 * means staged: reloading the page before applying forgets it.
 */

type GroupName = "shares" | "users";

/** The sentence keying each refusal the password endpoint returns. */
const PASSWORD_ERROR_KEYS: Record<string, string> = {
  user_unknown: "code.user_unknown",
  state_not_settled: "code.state_not_settled",
  agent_offline: "code.agent_offline",
  command_failed: "code.command_failed",
};

const EMPTY_SHARE: SambaShare = {
  name: "",
  path: "",
  comment: "",
  is_read_only: false,
  valid_users: [],
};

interface SambaPanelsProps {
  /** The machine whose Samba this is. */
  deviceId: string;
  /** Where this machine's Samba answers. */
  basePath: string;
  isEditable: boolean;
}

export function SambaPanels({
  deviceId,
  basePath,
  isEditable,
}: SambaPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  // Sessions come and go as machines mount and unmount, which the machine's
  // own report says; the shares and users are a write like any other.
  const liveOn = [
    { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
    { type: HUB_EVENT_CONFIG },
  ];
  const resource = useApiResource<SambaDeviceView>(basePath, {
    invalidateOn: liveOn,
  });
  const status = useApiResource<SambaStatus>(`${basePath}/status`, {
    invalidateOn: liveOn,
  });

  const [shares, setShares] = useState<SambaShare[]>([]);
  const [users, setUsers] = useState<string[]>([]);
  const [newUser, setNewUser] = useState("");
  const [newPassword, setNewPassword] = useState("");
  // Passwords waiting for Apply to create their accounts. Held here and
  // nowhere else — never written to config/ — and flushed right after apply.
  const [pendingPasswords, setPendingPasswords] = useState<
    Record<string, string>
  >({});
  const [busyGroup, setBusyGroup] = useState<GroupName | null>(null);
  const [notice, setNotice] = useState<Partial<Record<GroupName, string>>>({});
  const [errors, setErrors] = useState<Partial<Record<GroupName, string>>>({});

  useEffect(() => {
    if (resource.data !== null) {
      setShares(resource.data.shares);
      setUsers(resource.data.users.map((user) => user.name));
    }
  }, [resource.data]);

  const savedShares = resource.data?.shares ?? [];
  const savedUsers = resource.data?.users ?? [];
  const savedUserNames = savedUsers.map((user) => user.name);

  const isSharesDirty =
    resource.data !== null &&
    JSON.stringify(shares) !== JSON.stringify(savedShares);
  const isUsersDirty =
    resource.data !== null &&
    JSON.stringify(users) !== JSON.stringify(savedUserNames);
  // A staged password is a change like any other, and the frame has to say so:
  // the glow and the Apply beneath it answer one question — is there something
  // here that has not been applied — so a box that lights the button and not
  // its own edge is telling two stories.
  const isUsersUnapplied =
    isUsersDirty || Object.keys(pendingPasswords).length > 0;

  const applyGroup = async (group: GroupName) => {
    setBusyGroup(group);
    setErrors({});
    setNotice({});
    try {
      await (group === "shares"
        ? apiPut<SambaDeviceView>(`${basePath}/shares`, { shares })
        : apiPut<SambaDeviceView>(`${basePath}/users`, { users }));
      const result = await apiPost<ApplyResult>(`${basePath}/apply`);
      status.reload();
      if (!result.is_applied) {
        resource.reload();
        setErrors({ [group]: result.message });
        return;
      }
      // Apply created the accounts, so the staged passwords can land now.
      const failures: string[] = [];
      for (const [name, password] of Object.entries(pendingPasswords)) {
        if (!users.includes(name)) {
          continue;
        }
        try {
          await apiPost(`${basePath}/users/${name}/password`, { password });
        } catch (cause: unknown) {
          failures.push(
            t("ui.samba.password_failure_item", {
              name,
              reason: wordPasswordFailure(cause),
            }),
          );
        }
      }
      setPendingPasswords({});
      resource.reload();
      if (failures.length > 0) {
        setErrors({
          [group]: t("ui.samba.password_failure", {
            failures: failures.join("; "),
          }),
        });
        return;
      }
      setNotice({ [group]: result.message });
    } catch (cause: unknown) {
      resource.reload();
      setErrors({ [group]: describeError(cause) });
    } finally {
      setBusyGroup(null);
    }
  };

  const updateShare = (index: number, patch: Partial<SambaShare>) => {
    setNotice({});
    setShares((current) =>
      current.map((share, at) =>
        at === index ? { ...share, ...patch } : share,
      ),
    );
  };

  const removeUser = (name: string) => {
    setNotice({});
    setUsers((current) => current.filter((user) => user !== name));
    setPendingPasswords(({ [name]: _, ...rest }) => rest);
    // Mirrors what the gateway will do on save, so the shares group does not
    // sit there naming an account that is about to stop existing.
    setShares((current) =>
      current.map((share) => ({
        ...share,
        valid_users: share.valid_users.filter((user) => user !== name),
      })),
    );
  };

  const addUser = () => {
    const name = newUser.trim();
    if (name === "" || users.includes(name)) {
      return;
    }
    setNotice({});
    setUsers((current) => [...current, name]);
    if (newPassword !== "") {
      setPendingPasswords((current) => ({ ...current, [name]: newPassword }));
    }
    setNewUser("");
    setNewPassword("");
  };

  if (resource.error !== null && resource.data === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (resource.data === null) {
    return <div className="skeleton" style={{ height: 420 }} />;
  }

  const blockedHint = isEditable ? null : t("ui.modules.agent_offline");

  return (
    <>
      <section
        className={`settings_group ${isSharesDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.samba.shares_title")}</h2>
        </div>
        {shares.length === 0 && (
          <p className="field_hint">{t("ui.samba.shares_empty")}</p>
        )}
        {shares.map((share, index) => (
          <ShareEditor
            key={index}
            share={share}
            userNames={users}
            isLive={savedShares.some((saved) => saved.name === share.name)}
            onChange={(patch) => updateShare(index, patch)}
            onRemove={() =>
              setShares((current) => current.filter((_, at) => at !== index))
            }
          />
        ))}
        <div>
          <button
            type="button"
            className="button"
            onClick={() => setShares((current) => [...current, EMPTY_SHARE])}
          >
            <Icon name="plus" size={14} />
            {t("ui.samba.share_add")}
          </button>
        </div>
        <ApplyBar
          isDirty={isSharesDirty}
          isBusy={busyGroup === "shares"}
          label={t("ui.samba.shares_apply")}
          hint={t("ui.samba.shares_apply_hint")}
          blockedHint={blockedHint}
          error={errors.shares}
          notice={notice.shares}
          onReset={() => setShares(savedShares)}
          onApply={() => void applyGroup("shares")}
        />
      </section>

      <section
        className={`settings_group ${
          isUsersUnapplied ? "settings_group--dirty" : ""
        }`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.samba.users_title")}</h2>
        </div>
        <p className="field_hint">{t("ui.samba.users_hint")}</p>
        {users.map((name) => (
          <UserRow
            key={name}
            name={name}
            saved={savedUsers.find((user) => user.name === name) ?? null}
            hasPendingPassword={name in pendingPasswords}
            onRemove={() => removeUser(name)}
          />
        ))}
        <div className="samba_add_user">
          <input
            className="input"
            placeholder={t("ui.samba.user_name_placeholder")}
            value={newUser}
            onChange={(event) => setNewUser(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                addUser();
              }
            }}
          />
          <PasswordInput
            value={newPassword}
            onChange={setNewPassword}
            placeholder={t("ui.samba.user_password_placeholder")}
          />
          <button type="button" className="button" onClick={addUser}>
            <Icon name="plus" size={14} />
            {t("ui.samba.user_add")}
          </button>
        </div>
        <ApplyBar
          isDirty={isUsersUnapplied}
          isBusy={busyGroup === "users"}
          label={t("ui.samba.users_apply")}
          hint={t("ui.samba.users_apply_hint")}
          blockedHint={blockedHint}
          error={errors.users}
          notice={notice.users}
          onReset={() => {
            setUsers(savedUserNames);
            setPendingPasswords({});
          }}
          onApply={() => void applyGroup("users")}
        />
      </section>

      <StatusSection status={status.data} />
    </>
  );
}

interface ShareEditorProps {
  share: SambaShare;
  userNames: string[];
  /** Whether a share by this name is applied — its address answers. */
  isLive: boolean;
  onChange: (patch: Partial<SambaShare>) => void;
  onRemove: () => void;
}

function ShareEditor({
  share,
  userNames,
  isLive,
  onChange,
  onRemove,
}: ShareEditorProps) {
  const [isCopied, setIsCopied] = useState(false);

  // The host the browser reached this panel by is the host the share answers
  // on — true on the LAN today and still true over an overlay later.
  const shareUrl = `smb://${window.location.hostname}/${encodeURIComponent(share.name)}`;

  const toggleUser = (name: string) => {
    onChange({
      valid_users: share.valid_users.includes(name)
        ? share.valid_users.filter((user) => user !== name)
        : [...share.valid_users, name],
    });
  };

  const copyUrl = () => {
    void copyText(shareUrl).then(() => {
      setIsCopied(true);
      window.setTimeout(() => setIsCopied(false), 1600);
    });
  };

  return (
    <div className="samba_share">
      <div className="samba_share_head">
        <span className="samba_share_title">
          <Icon name="nas" size={15} />
          {share.name === "" ? t("ui.samba.share_new") : share.name}
        </span>
        {isLive && (
          <button
            type="button"
            className="samba_share_url"
            title={t("ui.samba.share_copy_title")}
            onClick={copyUrl}
          >
            {shareUrl}
            <Icon name={isCopied ? "check" : "link"} size={12} />
          </button>
        )}
        <button
          type="button"
          className="button button--ghost button--small samba_share_remove"
          onClick={onRemove}
        >
          <Icon name="trash" size={13} />
          {t("ui.samba.share_remove")}
        </button>
      </div>
      <div className="samba_share_fields">
        <label className="field">
          <span className="field_label">{t("ui.samba.share_name")}</span>
          <input
            className="input"
            value={share.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.samba.share_path")}</span>
          <input
            className="input"
            placeholder="/srv/share"
            value={share.path}
            onChange={(event) => onChange({ path: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.samba.share_comment")}</span>
          <input
            className="input"
            value={share.comment}
            onChange={(event) => onChange({ comment: event.target.value })}
          />
        </label>
      </div>
      <ToggleSwitch
        isOn={share.is_read_only}
        onChange={(isOn) => onChange({ is_read_only: isOn })}
        label={t("ui.samba.share_read_only")}
        description={t("ui.samba.share_read_only_hint")}
      />
      <div className="field">
        <span className="field_label">{t("ui.samba.share_users")}</span>
        {userNames.length === 0 ? (
          <span className="field_hint">{t("ui.samba.share_users_none")}</span>
        ) : (
          <div className="samba_user_chips">
            <div className="samba_user_chip_list">
              {userNames.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={`samba_user_chip ${
                    share.valid_users.includes(name)
                      ? "samba_user_chip--on"
                      : ""
                  }`}
                  onClick={() => toggleUser(name)}
                >
                  {name}
                </button>
              ))}
            </div>
            <span className="field_hint">
              {share.valid_users.length === 0
                ? t("ui.samba.share_users_all")
                : t("ui.samba.share_users_picked")}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

interface UserRowProps {
  name: string;
  /** The gateway's view of this user, or null for one not yet saved. */
  saved: SambaUser | null;
  /** Whether a password sits staged for this user, waiting for Apply. */
  hasPendingPassword: boolean;
  onRemove: () => void;
}

function UserRow({ name, saved, hasPendingPassword, onRemove }: UserRowProps) {
  const isApplied = saved !== null && saved.is_present;

  return (
    <div className="samba_user">
      <div className="samba_user_row">
        <span className="samba_user_name">
          <StatusDot
            tone={!isApplied ? "idle" : saved.has_password ? "ok" : "warn"}
          />
          {name}
        </span>
        {!isApplied ? (
          <span className="badge badge--accent">
            {t("ui.samba.user_staged")}
          </span>
        ) : !saved.has_password ? (
          hasPendingPassword ? (
            <span className="badge badge--accent">
              {t("ui.samba.user_password_staged")}
            </span>
          ) : (
            <span className="badge badge--warn">
              {t("ui.samba.user_no_password")}
            </span>
          )
        ) : (
          <span className="badge badge--ok">{t("ui.samba.user_ready")}</span>
        )}
        <div className="samba_user_actions">
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onRemove}
          >
            <Icon name="trash" size={12} />
            {t("ui.samba.user_remove")}
          </button>
        </div>
      </div>
    </div>
  );
}

interface StatusSectionProps {
  status: SambaStatus | null;
}

function StatusSection({ status }: StatusSectionProps) {
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.samba.status_title")}</h2>
        {/* Polled every second, so there is nothing for a button to add. */}
        <span className="badge">
          <StatusDot tone="ok" isPulsing />
          {t("state.live")}
        </span>
      </div>
      {status === null ? (
        <div className="skeleton" style={{ height: 60 }} />
      ) : (
        <>
          {status.sessions.length === 0 ? (
            <p className="field_hint">{t("ui.samba.status_empty")}</p>
          ) : (
            <div className="samba_sessions">
              {status.sessions.map((session, index) => (
                <div key={index} className="samba_session">
                  <span className="samba_session_user">
                    <StatusDot tone="ok" isPulsing />
                    {session.username}
                  </span>
                  <span className="samba_session_from">
                    {session.hostname || session.remote_address}
                  </span>
                  <span className="samba_session_shares">
                    {session.shares.join(", ") || t("ui.samba.status_no_share")}
                  </span>
                </div>
              ))}
            </div>
          )}
          {status.disks.length > 0 && (
            <div className="samba_disks">
              {status.disks.map((disk) => {
                const used = disk.total_bytes - disk.free_bytes;
                const fraction =
                  disk.total_bytes > 0 ? used / disk.total_bytes : 0;
                return (
                  <div key={disk.share} className="samba_disk">
                    <div className="samba_disk_row">
                      <span>{disk.share}</span>
                      <span className="samba_disk_numbers">
                        {t("ui.samba.status_used", {
                          used: formatBytes(used),
                          total: formatBytes(disk.total_bytes),
                        })}
                      </span>
                    </div>
                    <div className="samba_disk_bar">
                      <div
                        className="samba_disk_fill"
                        style={{ width: `${Math.round(fraction * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function wordPasswordFailure(cause: unknown): string {
  if (cause instanceof ApiError) {
    const key = PASSWORD_ERROR_KEYS[cause.code];
    if (key !== undefined) {
      const detail = cause.detail;
      const params =
        typeof detail === "object" && detail !== null && "params" in detail
          ? ((detail as { params?: Record<string, unknown> }).params ?? {})
          : {};
      return t(key, { detail: String(params.detail ?? cause.message) });
    }
  }
  return describeError(cause);
}
