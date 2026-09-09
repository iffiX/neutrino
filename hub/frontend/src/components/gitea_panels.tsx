import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { ToggleSwitch } from "./toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import type {
  ApplyResult,
  GiteaConfigUpdate,
  GiteaDeviceView,
} from "../api_types";

import "./gitea_panels.css";

/**
 * The git server on one machine: the seams the hub owns, and a door into the
 * rest.
 *
 * Deliberately thin. Gitea has a complete admin UI of its own, so these
 * panels manage only what must agree with the hub — the port, the advertised
 * URL, the sign-up switch — plus the one thing Gitea cannot do for itself:
 * its first administrator.
 */

const WORDING = {
  open: "Open Gitea",
  notInstalled: "Gitea is not installed on this machine.",
  accessTitle: "Access",
  accessHint:
    "What must agree with the hub. Repositories, accounts and everything " +
    "else are managed in Gitea itself.",
  portLabel: "Port",
  rootUrlLabel: "Root URL",
  rootUrlHint:
    "Written into clone addresses. Leave empty to derive from the machine's " +
    "address.",
  registrationLabel: "Open registration",
  registrationHint: "Whether visitors can create their own accounts.",
  accessApplyLabel: "Apply access",
  accessApplyHint: "Rewrites app.ini and restarts Gitea.",
  adminTitle: "Administrator",
  adminExists: "exists",
  adminManaged:
    "Accounts and repositories are managed in Gitea; reset the password here.",
  adminCreate: "Create the first administrator.",
  adminNotReady: " Start the service first.",
  adminUsername: "username",
  adminPassword: "password",
  adminEmail: "email (optional)",
  adminCreateButton: "Create administrator",
  adminNewPassword: "new password", // scan: allow
  adminSave: "Save",
  adminReset: "Reset password",
  offline: "The agent is offline",
};

interface GiteaPanelsProps {
  /** Where this machine's Gitea answers. */
  basePath: string;
  isEditable: boolean;
}

export function GiteaPanels({ basePath, isEditable }: GiteaPanelsProps) {
  const resource = useApiResource<GiteaDeviceView>(basePath);

  const [draft, setDraft] = useState<GiteaConfigUpdate | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setDraft({
        listen_port: resource.data.listen_port,
        root_url: resource.data.root_url,
        is_registration_enabled: resource.data.is_registration_enabled,
      });
    }
  }, [resource.data]);

  const saved = resource.data;
  const isDirty =
    draft !== null &&
    saved !== null &&
    (draft.listen_port !== saved.listen_port ||
      draft.root_url !== saved.root_url ||
      draft.is_registration_enabled !== saved.is_registration_enabled);

  const applyAccess = async () => {
    if (draft === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiPut<GiteaDeviceView>(basePath, draft);
      const result = await apiPost<ApplyResult>(`${basePath}/apply`);
      resource.reload();
      if (!result.is_applied) {
        setError(result.message);
        return;
      }
      setNotice(result.message);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  if (resource.error !== null && saved === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (saved === null || draft === null) {
    return <div className="skeleton" style={{ height: 320 }} />;
  }

  // The host the browser reached this panel by is a host Gitea answers on
  // too, whatever root_url advertises — right on the LAN and over an overlay.
  const openUrl = `http://${window.location.hostname}:${saved.listen_port}/`;

  return (
    <>
      {!saved.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{WORDING.notInstalled}</div>
        </div>
      )}

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{WORDING.accessTitle}</h2>
          {saved.version !== "" && (
            <span className="badge">v{saved.version}</span>
          )}
          <div className="gitea_open">
            {saved.is_active ? (
              <a
                className="button button--primary"
                href={openUrl}
                target="_blank"
                rel="noreferrer"
              >
                <Icon name="server" size={14} />
                {WORDING.open}
              </a>
            ) : (
              <button type="button" className="button button--primary" disabled>
                <Icon name="server" size={14} />
                {WORDING.open}
              </button>
            )}
          </div>
        </div>
        <p className="field_hint">{WORDING.accessHint}</p>
        <div className="gitea_fields">
          <label className="field">
            <span className="field_label">{WORDING.portLabel}</span>
            <input
              className="input"
              type="number"
              min={1}
              max={65535}
              value={draft.listen_port}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  listen_port: Number(event.target.value),
                })
              }
            />
          </label>
          <label className="field gitea_field_url">
            <span className="field_label">{WORDING.rootUrlLabel}</span>
            <input
              className="input"
              placeholder={`http://${window.location.hostname}:${draft.listen_port}/ (derived)`}
              value={draft.root_url}
              onChange={(event) =>
                setDraft({ ...draft, root_url: event.target.value })
              }
            />
            <span className="field_hint">{WORDING.rootUrlHint}</span>
          </label>
        </div>
        <ToggleSwitch
          isOn={draft.is_registration_enabled}
          onChange={(isOn) =>
            setDraft({ ...draft, is_registration_enabled: isOn })
          }
          label={WORDING.registrationLabel}
          description={WORDING.registrationHint}
        />
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label={WORDING.accessApplyLabel}
          hint={WORDING.accessApplyHint}
          blockedHint={isEditable ? null : WORDING.offline}
          error={error}
          notice={notice}
          onReset={() =>
            setDraft({
              listen_port: saved.listen_port,
              root_url: saved.root_url,
              is_registration_enabled: saved.is_registration_enabled,
            })
          }
          onApply={() => void applyAccess()}
        />
      </section>

      <AdminSection
        basePath={basePath}
        isReady={saved.is_installed && saved.is_active}
        adminUsernames={saved.admin_usernames}
        onChanged={resource.reload}
      />
    </>
  );
}

interface AdminSectionProps {
  basePath: string;
  /** Whether the server is installed and running, which the CLI needs. */
  isReady: boolean;
  adminUsernames: string[];
  onChanged: () => void;
}

function AdminSection({
  basePath,
  isReady,
  adminUsernames,
  onChanged,
}: AdminSectionProps) {
  const hasAdmin = adminUsernames.length > 0;
  const onCreated = onChanged;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiPost(`${basePath}/admin`, {
        username,
        password,
        // Gitea insists on an address even where no mail will ever be sent.
        email: email !== "" ? email : `${username}@neutrino.local`,
      });
      onCreated();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{WORDING.adminTitle}</h2>
        {hasAdmin && (
          <span className="badge badge--ok">{WORDING.adminExists}</span>
        )}
      </div>
      {hasAdmin ? (
        <>
          <p className="field_hint">{WORDING.adminManaged}</p>
          {adminUsernames.map((name) => (
            <AdminRow
              key={name}
              basePath={basePath}
              name={name}
              onChanged={onChanged}
            />
          ))}
        </>
      ) : (
        <>
          <p className="field_hint">
            {WORDING.adminCreate}
            {!isReady && WORDING.adminNotReady}
          </p>
          <div className="gitea_admin_form">
            <input
              className="input"
              placeholder={WORDING.adminUsername}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <PasswordInput
              value={password}
              onChange={setPassword}
              placeholder={WORDING.adminPassword}
            />
            <input
              className="input"
              placeholder={WORDING.adminEmail}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <button
              type="button"
              className="button button--primary"
              disabled={
                !isReady || isBusy || username === "" || password === ""
              }
              onClick={() => void create()}
            >
              <Icon name="plus" size={14} />
              {WORDING.adminCreateButton}
            </button>
          </div>
          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

interface AdminRowProps {
  basePath: string;
  name: string;
  onChanged: () => void;
}

function AdminRow({ basePath, name, onChanged }: AdminRowProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [password, setPassword] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (password === "") {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      await apiPost(`${basePath}/admin/${name}/password`, { password });
      setIsEditing(false);
      setPassword("");
      onChanged();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="gitea_admin_row">
      <span className="gitea_admin_name">
        <Icon name="key" size={13} />
        {name}
      </span>
      {isEditing && (
        <div className="gitea_admin_password">
          <PasswordInput
            value={password}
            onChange={setPassword}
            placeholder={WORDING.adminNewPassword}
            autoFocus
          />
          <button
            type="button"
            className="button button--primary button--small"
            disabled={isBusy || password === ""}
            onClick={() => void submit()}
          >
            <Icon name="check" size={13} />
            {WORDING.adminSave}
          </button>
        </div>
      )}
      <button
        type="button"
        className="button button--small gitea_admin_reset"
        onClick={() => {
          setIsEditing((current) => !current);
          setError(null);
        }}
      >
        <Icon name="lock" size={12} />
        {WORDING.adminReset}
      </button>
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </div>
  );
}
