import { useEffect, useState } from "react";

import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { PasswordInput } from "../components/password_input";
import { ToggleSwitch } from "../components/toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import type {
  ApplyResult,
  GiteaConfigUpdate,
  GiteaSettings,
} from "../api_types";

import "./gitea_page.css";

/**
 * The git server: the seams the gateway owns, and a door into the rest.
 *
 * Deliberately thin. Gitea has a complete admin UI of its own, so this page
 * manages only what must agree with the gateway — the port, the advertised
 * URL, the sign-up switch — plus the one thing Gitea cannot do for itself:
 * its first administrator.
 */

export function GiteaPage() {
  const resource = useApiResource<GiteaSettings>("/gitea");

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
      await apiPut<GiteaSettings>("/gitea", draft);
      const result = await apiPost<ApplyResult>("/gitea/apply");
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
    return (
      <div className="page">
        <h1>Gitea</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (saved === null || draft === null) {
    return (
      <div className="page">
        <h1>Gitea</h1>
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  // The host the browser reached this panel by is a host Gitea answers on
  // too, whatever root_url advertises — right on the LAN and over an overlay.
  const openUrl = `http://${window.location.hostname}:${saved.listen_port}/`;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>Gitea</h1>
          {!saved.is_installed ? (
            <span className="badge">not installed</span>
          ) : saved.is_active ? (
            <span className="badge badge--ok">serving</span>
          ) : (
            <span className="badge badge--warn">stopped</span>
          )}
          {saved.version !== "" && (
            <span className="badge">v{saved.version}</span>
          )}
        </div>
        <div className="page_actions">
          <a
            className={`button button--primary ${saved.is_active ? "" : "button--disabled"}`}
            href={saved.is_active ? openUrl : undefined}
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="server" size={14} />
            Open Gitea
          </a>
        </div>
      </div>

      {!saved.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            Gitea is not installed. Run the installer with --with-extras, then
            enable the service on the Services page.
          </div>
        </div>
      )}

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>Access</h2>
        </div>
        <p className="field_hint">
          What must agree with the gateway. Repositories, accounts and
          everything else are managed in Gitea itself.
        </p>
        <div className="gitea_fields">
          <label className="field">
            <span className="field_label">Port</span>
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
            <span className="field_label">Root URL</span>
            <input
              className="input"
              placeholder={`http://${window.location.hostname}:${draft.listen_port}/ (derived)`}
              value={draft.root_url}
              onChange={(event) =>
                setDraft({ ...draft, root_url: event.target.value })
              }
            />
            <span className="field_hint">
              Written into clone addresses. Leave empty to derive from the LAN
              address.
            </span>
          </label>
        </div>
        <ToggleSwitch
          isOn={draft.is_registration_enabled}
          onChange={(isOn) =>
            setDraft({ ...draft, is_registration_enabled: isOn })
          }
          label="Open registration"
          description="Let visitors create their own accounts."
        />
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label="Apply access"
          hint="Rewrites app.ini and restarts Gitea."
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
        isReady={saved.is_installed && saved.is_active}
        adminUsernames={saved.admin_usernames}
        onChanged={resource.reload}
      />
    </div>
  );
}

interface AdminSectionProps {
  /** Whether the server is installed and running, which the CLI needs. */
  isReady: boolean;
  adminUsernames: string[];
  onChanged: () => void;
}

function AdminSection({
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
      await apiPost("/gitea/admin", {
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
        <h2>Administrator</h2>
        {hasAdmin && <span className="badge badge--ok">exists</span>}
      </div>
      {hasAdmin ? (
        <>
          <p className="field_hint">
            Accounts and repositories are managed in Gitea; reset the password
            here.
          </p>
          {adminUsernames.map((name) => (
            <AdminRow key={name} name={name} onChanged={onChanged} />
          ))}
        </>
      ) : (
        <>
          <p className="field_hint">
            Create the first administrator.
            {!isReady && " Start the service first."}
          </p>
          <div className="gitea_admin_form">
            <input
              className="input"
              placeholder="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <PasswordInput
              value={password}
              onChange={setPassword}
              placeholder="password"
            />
            <input
              className="input"
              placeholder="email (optional)"
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
              Create administrator
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
  name: string;
  onChanged: () => void;
}

function AdminRow({ name, onChanged }: AdminRowProps) {
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
      await apiPost(`/gitea/admin/${name}/password`, { password });
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
            placeholder="new password"
            autoFocus
          />
          <button
            type="button"
            className="button button--primary button--small"
            disabled={isBusy || password === ""}
            onClick={() => void submit()}
          >
            <Icon name="check" size={13} />
            Save
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
        Reset password
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
