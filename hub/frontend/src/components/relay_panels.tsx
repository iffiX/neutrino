import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { VaultPicker } from "./vault_picker";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { useDraft } from "../use_draft";
import type { RelaySetRequest, RelayState, RelayView } from "../api_types";

import "./relay_panels.css";

/**
 * The SSH Relay: a reverse SSH forward to a server the person owns. A status
 * panel reads where it stands, and a settings panel with its own apply bar
 * stores where it goes and how the hub signs in there: with an SSH key or a
 * login's password, chosen with the agent install's controls.
 */

const RELAY_PATH = "/hub/overlay/relay";

/** How often the status is read; the check runs on the hub's own clock. */
const RELAY_RELOAD_MS = 10000;

/** Which of the two the hub signs in with, as the agent install names them. */
type CredentialKind = "key" | "login";

const STATE_TONES: Record<RelayState, StatusTone> = {
  disabled: "idle",
  not_configured: "idle",
  vault_locked: "error",
  connecting: "warn",
  connected: "ok",
  port_closed: "error",
  auth_failed: "error",
  host_key_changed: "error",
  forward_refused: "error",
  unreachable: "error",
};

export function RelaySection() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<RelayView>(RELAY_PATH);

  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, RELAY_RELOAD_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const view = resource.data;

  if (resource.error !== null && view === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (view === null) {
    return <div className="skeleton" style={{ height: 320 }} />;
  }

  return (
    <>
      <div className="overlay_product_header">
        <div className="page_title_row">
          <h2>{t("ui.overlay.relay_title")}</h2>
        </div>
      </div>
      <RelayStatusPanel view={view} onChanged={resource.setData} />
      <RelaySettingsPanel view={view} onChanged={resource.setData} />
    </>
  );
}

interface RelayPanelProps {
  view: RelayView;
  onChanged: (view: RelayView) => void;
}

/** Where the relay stands, and the one action on its recorded host key. */
function RelayStatusPanel({ view, onChanged }: RelayPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const forget = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onChanged(await apiPost<RelayView>(`${RELAY_PATH}/host_key/remove`, {}));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askForget = () => {
    confirm.ask({
      title: t("ui.overlay.relay_forget_title"),
      body: t("ui.overlay.relay_forget_body"),
      confirmLabel: t("ui.overlay.relay_forget"),
      onConfirm: () => void forget(),
    });
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.relay_status_title")}</h2>
        <span className="badge">
          <StatusDot tone={STATE_TONES[view.state]} />
          {t(`state.relay_${view.state}`)}
        </span>
      </div>
      {view.last_error !== "" && (
        <p className="relay_error">{view.last_error}</p>
      )}
      <div className="relay_facts">
        <div className="relay_fact">
          <span className="field_label">{t("ui.overlay.relay_address")}</span>
          <span className="relay_fact_value">{view.url || "—"}</span>
        </div>
        <div className="relay_fact">
          <span className="field_label">{t("ui.overlay.relay_host_key")}</span>
          <span className="relay_fact_row">
            <span className="relay_fact_value">
              {view.host_key_fingerprint || "—"}
            </span>
            {view.host_key_fingerprint !== "" && (
              <button
                type="button"
                className="button button--small"
                disabled={isBusy}
                onClick={askForget}
              >
                {t("ui.overlay.relay_forget_host_key")}
              </button>
            )}
          </span>
        </div>
      </div>
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      {confirm.modal}
    </section>
  );
}

/** The settings as the form edits them; the ports stay text until applied. */
interface RelayDraft {
  host: string;
  sshPort: string;
  account: string;
  credentialKind: CredentialKind;
  keyId: string;
  loginId: string;
  publicPort: string;
}

function draftOf(view: RelayView): RelayDraft {
  return {
    host: view.host,
    sshPort: String(view.ssh_port),
    account: view.account,
    credentialKind: view.login_id !== "" ? "login" : "key",
    keyId: view.key_id,
    loginId: view.login_id,
    publicPort: String(view.public_port),
  };
}

/** Where the relay goes: the server, the account, the credential and the ports. */
function RelaySettingsPanel({ view, onChanged }: RelayPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { draft, setDraft, isDirty, reset } = useDraft(view, draftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (draft === null) {
    return null;
  }

  const change = (patch: Partial<RelayDraft>) => {
    setError(null);
    setDraft((current) => ({ ...current, ...patch }));
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: RelaySetRequest = {
      host: draft.host.trim(),
      ssh_port: Number(draft.sshPort),
      account: draft.account.trim(),
      key_id: draft.credentialKind === "key" ? draft.keyId || null : null,
      login_id: draft.credentialKind === "login" ? draft.loginId || null : null,
      public_port: Number(draft.publicPort),
    };
    try {
      onChanged(await apiPost<RelayView>(`${RELAY_PATH}/set`, request));
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
      <div className="settings_group_title">
        <h2>{t("ui.overlay.settings_title")}</h2>
      </div>
      <div className="relay_fields">
        <label className="field">
          <span className="field_label">{t("ui.overlay.relay_host")}</span>
          <input
            className="input"
            value={draft.host}
            spellCheck={false}
            placeholder="203.0.113.5"
            onChange={(event) => change({ host: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.overlay.relay_ssh_port")}</span>
          <input
            className="input"
            inputMode="numeric"
            value={draft.sshPort}
            onChange={(event) => change({ sshPort: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.overlay.relay_account")}</span>
          <input
            className="input"
            value={draft.account}
            spellCheck={false}
            onChange={(event) => change({ account: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">
            {t("ui.overlay.relay_public_port")}
          </span>
          <input
            className="input"
            inputMode="numeric"
            value={draft.publicPort}
            onChange={(event) => change({ publicPort: event.target.value })}
          />
        </label>
        <Picker
          options={[
            { id: "key", name: t("ui.install_agent.kind_key") },
            { id: "login", name: t("ui.install_agent.kind_login") },
          ]}
          value={draft.credentialKind}
          onChange={(id) => change({ credentialKind: id as CredentialKind })}
          label={t("ui.install_agent.credential")}
          hint={t("ui.overlay.relay_credential_hint")}
        />
      </div>
      {draft.credentialKind === "key" ? (
        <VaultPicker
          kind="ssh_key"
          value={draft.keyId === "" ? null : draft.keyId}
          onChange={(id) => change({ keyId: id ?? "" })}
          label={t("ui.install_agent.key")}
          hint={t("ui.install_agent.key_hint")}
        />
      ) : (
        <VaultPicker
          kind="login"
          value={draft.loginId === "" ? null : draft.loginId}
          onChange={(id) => change({ loginId: id ?? "" })}
          label={t("ui.install_agent.login")}
          hint={t("ui.install_agent.login_hint")}
        />
      )}
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.relay_apply")}
        hint={t("ui.overlay.relay_apply_hint")}
        warning={
          view.state === "connected"
            ? t("ui.overlay.relay_apply_warning")
            : undefined
        }
        error={error}
        onReset={reset}
        onApply={() => void apply()}
      />
    </section>
  );
}
