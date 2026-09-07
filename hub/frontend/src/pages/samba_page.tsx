import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { ModuleStateBadge } from "../components/module_state_badge";
import { Icon } from "../components/icon";
import { PasswordInput } from "../components/password_input";
import { StatusDot } from "../components/status_dot";
import { ToggleSwitch } from "../components/toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { formatBytes } from "../format_bytes";
import { useApiResource } from "../use_api_resource";
import type {
  ApplyResult,
  SambaSettings,
  SambaShare,
  SambaStatus,
  SambaUser,
} from "../api_types";

import "./samba_page.css";

/**
 * The file share: what is exported, who may connect, who is connected.
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

const USERS_TITLE = "Users";
const USERS_HINT =
  "Accounts that may connect. Adding stages name and password together; " +
  "replacing a password is removing the user and adding it again.";
const USER_BADGE_STAGED = "created on apply";
const USER_BADGE_PASSWORD_STAGED = "password set on apply"; // scan: allow
const USER_BADGE_NO_PASSWORD = "no password yet"; // scan: allow
const USER_BADGE_READY = "ready";
const USER_REMOVE_LABEL = "Remove";
const USER_ADD_LABEL = "Add user";
const USERS_APPLY_LABEL = "Apply users";
const USERS_APPLY_HINT =
  "Creates accounts, sets staged passwords, revokes removed ones.";

type GroupName = "shares" | "users";

const EMPTY_SHARE: SambaShare = {
  name: "",
  path: "",
  comment: "",
  is_read_only: false,
  valid_users: [],
};

export function SambaPage() {
  const resource = useApiResource<SambaSettings>("/samba");
  const status = useApiResource<SambaStatus>("/samba/status");

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

  // Sessions come and go as machines mount and unmount, so the status section
  // follows along once a second — paused while the tab is not being looked at.
  const reloadStatus = status.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reloadStatus();
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [reloadStatus]);

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
        ? apiPut<SambaSettings>("/samba/shares", { shares })
        : apiPut<SambaSettings>("/samba/users", { users }));
      const result = await apiPost<ApplyResult>("/samba/apply");
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
          await apiPost(`/samba/users/${name}/password`, { password });
        } catch (cause: unknown) {
          failures.push(`${name}: ${describeError(cause)}`);
        }
      }
      setPendingPasswords({});
      resource.reload();
      if (failures.length > 0) {
        setErrors({ [group]: `password not set: ${failures.join("; ")}` });
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
    return (
      <div className="page">
        <h1>Samba</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (resource.data === null) {
    return (
      <div className="page">
        <h1>Samba</h1>
        <div className="skeleton" style={{ height: 420 }} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>Samba</h1>
          <ModuleStateBadge name="samba" />
        </div>
      </div>

      <section
        className={`settings_group ${isSharesDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>Shares</h2>
        </div>
        {shares.length === 0 && (
          <p className="field_hint">No directories are exported.</p>
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
            Add share
          </button>
        </div>
        <ApplyBar
          isDirty={isSharesDirty}
          isBusy={busyGroup === "shares"}
          label="Apply shares"
          hint="Saves shares and reloads the server."
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
          <h2>{USERS_TITLE}</h2>
        </div>
        <p className="field_hint">{USERS_HINT}</p>
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
            placeholder="new user name"
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
            placeholder="password"
          />
          <button type="button" className="button" onClick={addUser}>
            <Icon name="plus" size={14} />
            {USER_ADD_LABEL}
          </button>
        </div>
        <ApplyBar
          isDirty={isUsersUnapplied}
          isBusy={busyGroup === "users"}
          label={USERS_APPLY_LABEL}
          hint={USERS_APPLY_HINT}
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
    </div>
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
          {share.name === "" ? "new share" : share.name}
        </span>
        {isLive && (
          <button
            type="button"
            className="samba_share_url"
            title="Copy the address"
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
          Remove
        </button>
      </div>
      <div className="samba_share_fields">
        <label className="field">
          <span className="field_label">Name</span>
          <input
            className="input"
            value={share.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">Path</span>
          <input
            className="input"
            placeholder="/srv/share"
            value={share.path}
            onChange={(event) => onChange({ path: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">Comment</span>
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
        label="Read only"
        description="Whether writing is refused for everyone, whoever they are."
      />
      <div className="field">
        <span className="field_label">Who may use it</span>
        {userNames.length === 0 ? (
          <span className="field_hint">
            Every user; none are configured yet.
          </span>
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
                ? "None picked: every user may use it."
                : "Only the picked users may use it."}
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
          <span className="badge badge--accent">{USER_BADGE_STAGED}</span>
        ) : !saved.has_password ? (
          hasPendingPassword ? (
            <span className="badge badge--accent">
              {USER_BADGE_PASSWORD_STAGED}
            </span>
          ) : (
            <span className="badge badge--warn">{USER_BADGE_NO_PASSWORD}</span>
          )
        ) : (
          <span className="badge badge--ok">{USER_BADGE_READY}</span>
        )}
        <div className="samba_user_actions">
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onRemove}
          >
            <Icon name="trash" size={12} />
            {USER_REMOVE_LABEL}
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
        <h2>Now serving</h2>
        {/* Polled every second, so there is nothing for a button to add. */}
        <span className="badge">
          <StatusDot tone="ok" isPulsing />
          live
        </span>
      </div>
      {status === null ? (
        <div className="skeleton" style={{ height: 60 }} />
      ) : (
        <>
          {status.sessions.length === 0 ? (
            <p className="field_hint">Nobody is connected.</p>
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
                    {session.shares.join(", ") || "no share open"}
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
                        {formatBytes(used)} of {formatBytes(disk.total_bytes)}
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
