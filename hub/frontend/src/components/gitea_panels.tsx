import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { ToggleSwitch } from "./toggle_switch";
import { apiPost, apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
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

interface GiteaPanelsProps {
  /** Where this machine's Gitea answers. */
  basePath: string;
  isEditable: boolean;
}

export function GiteaPanels({ basePath, isEditable }: GiteaPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
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
          <div className="notice_body">{t("ui.gitea.not_installed")}</div>
        </div>
      )}

      <section
        className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{t("ui.gitea.access_title")}</h2>
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
                {t("ui.gitea.open")}
              </a>
            ) : (
              <button type="button" className="button button--primary" disabled>
                <Icon name="server" size={14} />
                {t("ui.gitea.open")}
              </button>
            )}
          </div>
        </div>
        <p className="field_hint">{t("ui.gitea.access_hint")}</p>
        <div className="gitea_fields">
          <label className="field">
            <span className="field_label">{t("ui.gitea.port")}</span>
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
            <span className="field_label">{t("ui.gitea.root_url")}</span>
            <input
              className="input"
              placeholder={t("ui.gitea.root_url_placeholder", {
                url: `http://${window.location.hostname}:${draft.listen_port}/`,
              })}
              value={draft.root_url}
              onChange={(event) =>
                setDraft({ ...draft, root_url: event.target.value })
              }
            />
            <span className="field_hint">{t("ui.gitea.root_url_hint")}</span>
          </label>
        </div>
        <ToggleSwitch
          isOn={draft.is_registration_enabled}
          onChange={(isOn) =>
            setDraft({ ...draft, is_registration_enabled: isOn })
          }
          label={t("ui.gitea.registration")}
          description={t("ui.gitea.registration_hint")}
        />
        <ApplyBar
          isDirty={isDirty}
          isBusy={isBusy}
          label={t("ui.gitea.access_apply")}
          hint={t("ui.gitea.access_apply_hint")}
          blockedHint={isEditable ? null : t("ui.modules.agent_offline")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
        <h2>{t("ui.gitea.admin_title")}</h2>
        {hasAdmin && (
          <span className="badge badge--ok">{t("state.exists")}</span>
        )}
      </div>
      {hasAdmin ? (
        <>
          <p className="field_hint">{t("ui.gitea.admin_managed")}</p>
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
            {isReady
              ? t("ui.gitea.admin_create")
              : t("ui.gitea.admin_create_not_ready")}
          </p>
          <div className="gitea_admin_form">
            <input
              className="input"
              placeholder={t("ui.gitea.admin_username")}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <PasswordInput
              value={password}
              onChange={setPassword}
              placeholder={t("ui.gitea.admin_password")}
            />
            <input
              className="input"
              placeholder={t("ui.gitea.admin_email")}
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
              {t("ui.gitea.admin_create_button")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
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
            placeholder={t("ui.gitea.admin_new_password")}
            autoFocus
          />
          <button
            type="button"
            className="button button--primary button--small"
            disabled={isBusy || password === ""}
            onClick={() => void submit()}
          >
            <Icon name="check" size={13} />
            {t("ui.gitea.admin_save")}
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
        {t("ui.gitea.admin_reset")}
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
