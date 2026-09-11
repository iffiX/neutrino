import { useEffect, useState } from "react";

import { DeviceEnrollmentNotice } from "../components/device_enrollment_notice";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import type { StatusTone } from "../components/status_dot";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { HUB_EVENT_CLIENTS } from "../use_hub_events";
import type {
  ClientEnrollmentView,
  ClientListView,
  ClientView,
} from "../api_types";

import "./clients_page.css";

/**
 * The people's programs enrolled with this hub.
 *
 * A client is a desktop program a person runs, enrolled once by name: the
 * page mints its link, and the row stands from that moment, connected or
 * not. Presence, hostname and version come from its live channel; the
 * switch and the delete write at once.
 */

const CLIENTS_PATH = "/clients";
const INVALIDATE_ON = [{ type: HUB_EVENT_CLIENTS }];

type ClientPresence = "online" | "offline" | "never";

const PRESENCE_TONES: Record<ClientPresence, StatusTone> = {
  online: "ok",
  offline: "warn",
  never: "idle",
};

const PRESENCE_KEYS: Record<ClientPresence, string> = {
  online: "state.online",
  offline: "state.offline",
  never: "state.never_connected",
};

/** What a column shows for a client that has not reported one. */
const NOTHING = "—";

export function ClientsPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ClientListView>(CLIENTS_PATH, {
    invalidateOn: INVALIDATE_ON,
  });
  const confirm = useConfirm();

  const [clients, setClients] = useState<ClientView[]>([]);
  const [isNaming, setIsNaming] = useState(false);
  const [name, setName] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [enrollment, setEnrollment] = useState<{
    name: string;
    view: ClientEnrollmentView;
  } | null>(null);

  useEffect(() => {
    if (resource.data !== null) {
      setClients(resource.data.clients);
    }
  }, [resource.data]);

  const handleCreateLink = async () => {
    const wanted = name.trim();
    if (wanted.length === 0) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const view = await apiPost<ClientEnrollmentView>(
        `${CLIENTS_PATH}/enrollment`,
        { name: wanted },
      );
      setEnrollment({ name: wanted, view });
      setName("");
      setIsNaming(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleToggle = async (client: ClientView) => {
    setIsBusy(true);
    setError(null);
    try {
      const next = await apiPut<ClientListView>(
        `${CLIENTS_PATH}/${client.id}`,
        {
          is_disabled: !client.is_disabled,
        },
      );
      resource.setData(next);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleDelete = async (client: ClientView) => {
    setIsBusy(true);
    setError(null);
    try {
      resource.setData(
        await apiDelete<ClientListView>(`${CLIENTS_PATH}/${client.id}`),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askDelete = (client: ClientView) =>
    confirm.ask({
      title: t("ui.clients.delete_title", { name: client.name }),
      body: t("ui.clients.delete_body"),
      confirmLabel: t("ui.clients.delete"),
      onConfirm: () => void handleDelete(client),
    });

  const onlineCount = clients.filter((client) => client.is_online).length;

  if (resource.error !== null && clients.length === 0) {
    return (
      <div className="page">
        <h1>{t("ui.clients.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>{t("ui.clients.title")}</h1>
            <span className="badge">
              {t("ui.clients.badge", {
                online: onlineCount,
                total: clients.length,
              })}
            </span>
          </div>
        </div>
        <div className="page_actions">
          {!isNaming && (
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy}
              onClick={() => setIsNaming(true)}
            >
              <Icon name="link" size={14} />
              {t("ui.clients.new_link")}
            </button>
          )}
        </div>
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {isNaming && (
        <div className="clients_add">
          <input
            className="input"
            placeholder={t("ui.clients.name_placeholder")}
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleCreateLink();
              }
            }}
          />
          <div className="clients_add_actions">
            <button
              type="button"
              className="button button--ghost"
              onClick={() => {
                setIsNaming(false);
                setName("");
              }}
            >
              {t("ui.clients.cancel")}
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy || name.trim().length === 0}
              onClick={() => void handleCreateLink()}
            >
              <Icon name="check" size={14} />
              {t("ui.clients.create_link")}
            </button>
          </div>
        </div>
      )}

      {enrollment !== null && (
        <DeviceEnrollmentNotice
          link={enrollment.view.link}
          expiresInS={secondsUntil(enrollment.view.expires_at)}
          title={t("ui.clients.enrollment_title", { name: enrollment.name })}
          hint={t("ui.clients.enrollment_hint")}
          onDismiss={() => setEnrollment(null)}
        />
      )}

      {clients.length === 0 ? (
        resource.isLoading && resource.data === null ? (
          <div className="skeleton" style={{ height: 160 }} />
        ) : (
          <div className="placeholder">
            <span>{t("ui.clients.empty")}</span>
            <span className="faint">{t("ui.clients.empty_hint")}</span>
          </div>
        )
      ) : (
        <div className="card clients_table_scroll">
          <table className="clients_table">
            <thead>
              <tr>
                <th>{t("ui.clients.header_name")}</th>
                <th>{t("ui.clients.header_hostname")}</th>
                <th>{t("ui.clients.header_platform")}</th>
                <th>{t("ui.clients.header_version")}</th>
                <th>{t("ui.clients.header_status")}</th>
                <th>{t("ui.clients.header_last_seen")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {clients.map((client) => (
                <ClientRow
                  key={client.id}
                  client={client}
                  isBusy={isBusy}
                  onToggle={() => void handleToggle(client)}
                  onDelete={() => askDelete(client)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {confirm.modal}
    </div>
  );
}

interface ClientRowProps {
  client: ClientView;
  isBusy: boolean;
  onToggle: () => void;
  onDelete: () => void;
}

function ClientRow({ client, isBusy, onToggle, onDelete }: ClientRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const presence = presenceOf(client);
  return (
    <tr className={client.is_disabled ? "clients_row--disabled" : ""}>
      <td>
        <div className="clients_name">
          {client.name}
          {client.is_disabled && (
            <span className="badge badge--warn">
              {t("ui.clients.disabled")}
            </span>
          )}
        </div>
      </td>
      <td className="mono">{client.hostname || NOTHING}</td>
      <td>{client.platform_os || NOTHING}</td>
      <td className="mono">{client.version || NOTHING}</td>
      <td>
        <StatusDot
          tone={PRESENCE_TONES[presence]}
          label={t(PRESENCE_KEYS[presence])}
        />
      </td>
      <td className="mono">
        {client.is_online ? t("state.online") : formatTimeAgo(client.last_seen)}
      </td>
      <td className="clients_actions">
        <button
          type="button"
          className="button button--small button--ghost"
          disabled={isBusy}
          onClick={onToggle}
        >
          {client.is_disabled
            ? t("ui.clients.enable")
            : t("ui.clients.disable")}
        </button>
        <button
          type="button"
          className="button button--small button--ghost button--danger"
          disabled={isBusy}
          onClick={onDelete}
        >
          <Icon name="trash" size={13} />
          {t("ui.clients.delete")}
        </button>
      </td>
    </tr>
  );
}

function presenceOf(client: ClientView): ClientPresence {
  if (client.is_online) {
    return "online";
  }
  if (client.hostname.length === 0 && client.version.length === 0) {
    return "never";
  }
  return "offline";
}

function secondsUntil(isoTimestamp: string): number {
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return 0;
  }
  return (parsed - Date.now()) / 1000;
}
