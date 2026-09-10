import { useEffect, useState } from "react";

import { DeviceEnrollmentNotice } from "../components/device_enrollment_notice";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import type { StatusTone } from "../components/status_dot";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { formatTimeAgo } from "../format_duration";
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

const WORDING = {
  title: "Clients",
  badge: (online: number, total: number) => `${online} of ${total} online`,
  newLink: "New client link",
  namePlaceholder: "whose program this is, e.g. alice-laptop",
  createLink: "Create link",
  cancel: "Cancel",
  enrollmentTitle: (name: string) =>
    `Paste this link into the client program for ${name}.`,
  enrollmentHint:
    "Open the client, choose Join a hub, and paste the link. It works for {minutes} minutes.",
  headerName: "Name",
  headerHostname: "Hostname",
  headerPlatform: "Platform",
  headerVersion: "Version",
  headerStatus: "Status",
  headerLastSeen: "Last seen",
  online: "online",
  offline: "offline",
  neverConnected: "never connected",
  disabled: "disabled",
  disable: "Disable",
  enable: "Enable",
  delete: "Delete",
  deleteTitle: (name: string) => `Delete ${name}`,
  deleteBody:
    "Its gateway key is revoked and its program loses this hub; it needs a new link to come back.",
  empty: "No clients yet",
  emptyHint: "Create a link for a person's client program.",
} as const;

const CLIENTS_PATH = "/clients";
const INVALIDATE_ON = [{ type: HUB_EVENT_CLIENTS }];

type ClientPresence = "online" | "offline" | "never";

const PRESENCE_TONES: Record<ClientPresence, StatusTone> = {
  online: "ok",
  offline: "warn",
  never: "idle",
};

const PRESENCE_LABELS: Record<ClientPresence, string> = {
  online: WORDING.online,
  offline: WORDING.offline,
  never: WORDING.neverConnected,
};

export function ClientsPage() {
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
      title: WORDING.deleteTitle(client.name),
      body: WORDING.deleteBody,
      confirmLabel: WORDING.delete,
      onConfirm: () => void handleDelete(client),
    });

  const onlineCount = clients.filter((client) => client.is_online).length;

  if (resource.error !== null && clients.length === 0) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>{WORDING.title}</h1>
            <span className="badge">
              {WORDING.badge(onlineCount, clients.length)}
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
              {WORDING.newLink}
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
            placeholder={WORDING.namePlaceholder}
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
              {WORDING.cancel}
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy || name.trim().length === 0}
              onClick={() => void handleCreateLink()}
            >
              <Icon name="check" size={14} />
              {WORDING.createLink}
            </button>
          </div>
        </div>
      )}

      {enrollment !== null && (
        <DeviceEnrollmentNotice
          link={enrollment.view.link}
          expiresInS={secondsUntil(enrollment.view.expires_at)}
          title={WORDING.enrollmentTitle(enrollment.name)}
          hint={WORDING.enrollmentHint}
          onDismiss={() => setEnrollment(null)}
        />
      )}

      {clients.length === 0 ? (
        resource.isLoading && resource.data === null ? (
          <div className="skeleton" style={{ height: 160 }} />
        ) : (
          <div className="placeholder">
            <span>{WORDING.empty}</span>
            <span className="faint">{WORDING.emptyHint}</span>
          </div>
        )
      ) : (
        <div className="card clients_table_scroll">
          <table className="clients_table">
            <thead>
              <tr>
                <th>{WORDING.headerName}</th>
                <th>{WORDING.headerHostname}</th>
                <th>{WORDING.headerPlatform}</th>
                <th>{WORDING.headerVersion}</th>
                <th>{WORDING.headerStatus}</th>
                <th>{WORDING.headerLastSeen}</th>
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
  const presence = presenceOf(client);
  return (
    <tr className={client.is_disabled ? "clients_row--disabled" : ""}>
      <td>
        <div className="clients_name">
          {client.name}
          {client.is_disabled && (
            <span className="badge badge--warn">{WORDING.disabled}</span>
          )}
        </div>
      </td>
      <td className="mono">{client.hostname || "—"}</td>
      <td>{client.platform_os || "—"}</td>
      <td className="mono">{client.version || "—"}</td>
      <td>
        <StatusDot
          tone={PRESENCE_TONES[presence]}
          label={PRESENCE_LABELS[presence]}
        />
      </td>
      <td className="mono">
        {client.is_online ? WORDING.online : formatTimeAgo(client.last_seen)}
      </td>
      <td className="clients_actions">
        <button
          type="button"
          className="button button--small button--ghost"
          disabled={isBusy}
          onClick={onToggle}
        >
          {client.is_disabled ? WORDING.enable : WORDING.disable}
        </button>
        <button
          type="button"
          className="button button--small button--ghost button--danger"
          disabled={isBusy}
          onClick={onDelete}
        >
          <Icon name="trash" size={13} />
          {WORDING.delete}
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
