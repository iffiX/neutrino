import { Fragment, useEffect, useState } from "react";

import { ClientLinkModal } from "../components/client_link_modal";
import { ClientPermissionForm } from "../components/client_permission_form";
import type {
  PermissionDeviceChoice,
  PermissionValue,
} from "../components/client_permission_form";
import { DialogFrame } from "../components/dialog_frame";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import type { StatusTone } from "../components/status_dot";
import { apiPost, describeError } from "../api_client";
import {
  clientPermissionOf,
  defaultPermissionOf,
} from "../client_permission_value";
import { toDeviceLabel } from "../device_level";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { HUB_EVENT_CLIENTS } from "../use_hub_events";
import type {
  ClientDefaultPermissionRequest,
  ClientListView,
  ClientPermissionRequest,
  ClientUpdate,
  ClientView,
  DeviceView,
  DevicesResponse,
} from "../api_types";

import "./clients_page.css";

/**
 * The people's programs enrolled with this hub, in the Clients panel.
 *
 * A client is a program a person runs, enrolled once by name: the header's
 * New client link names it and its permission in a dialog and shows its
 * link and QR there, and the row waits to join from that moment until the
 * link expires. Presence, hostname and version come from its live session.
 * A client's name and permission are edited in its row, lit while the edit
 * is open; the default permission is a dialog from the panel's header. The
 * switch and the delete write at once.
 */

const CLIENTS_PATH = "/hub/client";
const DEVICES_PATH = "/hub/device";
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

/** The columns the rename form takes: the name, hostname, platform and
 * version, so the name and its buttons fit on one line. */
const RENAME_COLUMN_SPAN = 4;

/** Every column of the table, which a client's permission row spans. */
const COLUMN_COUNT = 7;

/** The columns a waiting row's line spans: the hostname, platform and
 * version. */
const WAITING_COLUMN_SPAN = 3;

/** How often a waiting row's minutes are counted down between reads. */
const WAITING_TICK_MS = 15_000;

export function ClientsPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ClientListView>(CLIENTS_PATH, {
    invalidateOn: INVALIDATE_ON,
  });
  const devicesResource = useApiResource<DevicesResponse>(DEVICES_PATH);
  const confirm = useConfirm();

  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLinkOpen, setIsLinkOpen] = useState(false);
  const [isDefaultOpen, setIsDefaultOpen] = useState(false);
  // The client whose name is being edited in its row, and the name typed.
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  // The client whose permission is open in its row.
  const [permissionOf, setPermissionOf] = useState<string | null>(null);
  // When the list was last read, and the clock the waiting rows count by.
  const [readAt, setReadAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  const clients = resource.data?.clients ?? [];
  const hasWaiting = clients.some(
    (client) => client.link_expires_in_s !== null,
  );

  useEffect(() => {
    setReadAt(Date.now());
    setNow(Date.now());
  }, [resource.data]);

  useEffect(() => {
    if (!hasWaiting) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), WAITING_TICK_MS);
    return () => window.clearInterval(timer);
  }, [hasWaiting]);

  const handleToggle = async (client: ClientView) => {
    setIsBusy(true);
    setError(null);
    try {
      const next = await apiPost<ClientListView>(
        `${CLIENTS_PATH}/${client.is_disabled ? "enable" : "disable"}`,
        { client_id: client.id },
      );
      resource.setData(next);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleRename = async (client: ClientView) => {
    const wanted = newName.trim();
    if (wanted.length === 0 || wanted === client.name) {
      setRenamingId(null);
      return;
    }
    setIsBusy(true);
    setError(null);
    const update: ClientUpdate = { client_id: client.id, name: wanted };
    try {
      resource.setData(
        await apiPost<ClientListView>(`${CLIENTS_PATH}/set`, update),
      );
      setRenamingId(null);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const startRename = (client: ClientView) => {
    setRenamingId(client.id);
    setNewName(client.name);
  };

  const handleDelete = async (client: ClientView) => {
    setIsBusy(true);
    setError(null);
    try {
      resource.setData(
        await apiPost<ClientListView>(`${CLIENTS_PATH}/remove`, {
          client_id: client.id,
        }),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const saveDefaultPermission = async (value: PermissionValue | null) => {
    const request: ClientDefaultPermissionRequest = {
      kinds: value?.kinds ?? [],
      devices: value?.devices ?? null,
      entries: value?.entries ?? null,
    };
    resource.setData(
      await apiPost<ClientListView>(
        `${CLIENTS_PATH}/default_permission/set`,
        request,
      ),
    );
    setIsDefaultOpen(false);
  };

  const savePermission = async (
    clientId: string,
    value: PermissionValue | null,
  ) => {
    const request: ClientPermissionRequest = {
      client_id: clientId,
      kinds: value?.kinds ?? null,
      devices: value?.devices ?? null,
      entries: value?.entries ?? null,
    };
    resource.setData(
      await apiPost<ClientListView>(`${CLIENTS_PATH}/permission/set`, request),
    );
    setPermissionOf(null);
  };

  const askDelete = (client: ClientView) =>
    confirm.ask({
      title: t("ui.clients.delete_title", { name: client.name }),
      body:
        client.link_expires_in_s === null
          ? t("ui.clients.delete_body")
          : t("ui.clients.waiting_delete_body"),
      confirmLabel: t("ui.clients.delete"),
      onConfirm: () => void handleDelete(client),
    });

  const minutesLeft = (client: ClientView) =>
    Math.max(
      0,
      Math.ceil(((client.link_expires_in_s ?? 0) - (now - readAt) / 1000) / 60),
    );

  const managedDevices = (devicesResource.data?.devices ?? []).map(
    toDeviceChoice,
  );
  const onlineCount = clients.filter((client) => client.is_online).length;
  const listView = resource.data;

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
          <button
            type="button"
            className="button button--primary"
            disabled={listView === null}
            onClick={() => setIsLinkOpen(true)}
          >
            <Icon name="link" size={14} />
            {t("ui.clients.new_link")}
          </button>
        </div>
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.clients.panel_clients")}</h2>
          <button
            type="button"
            className="button clients_panel_action"
            disabled={listView === null}
            onClick={() => setIsDefaultOpen(true)}
          >
            <Icon name="lock" size={14} />
            {t("ui.clients.default_permission")}
          </button>
        </div>
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
          <div className="clients_table_scroll">
            <table className="clients_table">
              <colgroup>
                <col />
                <col className="clients_col--hostname" />
                <col className="clients_col--platform" />
                <col className="clients_col--version" />
                <col className="clients_col--status" />
                <col className="clients_col--seen" />
                <col className="clients_col--actions" />
              </colgroup>
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
                  <Fragment key={client.id}>
                    <ClientRow
                      client={client}
                      waitingMinutes={
                        client.link_expires_in_s === null
                          ? null
                          : minutesLeft(client)
                      }
                      isBusy={isBusy}
                      isRenaming={renamingId === client.id}
                      isPermissionOpen={permissionOf === client.id}
                      newName={newName}
                      onNewName={setNewName}
                      onRename={() => startRename(client)}
                      onRenameSave={() => void handleRename(client)}
                      onRenameCancel={() => setRenamingId(null)}
                      onToggle={() => void handleToggle(client)}
                      onPermission={() =>
                        setPermissionOf(
                          permissionOf === client.id ? null : client.id,
                        )
                      }
                      onDelete={() => askDelete(client)}
                    />
                    {listView !== null && permissionOf === client.id && (
                      <tr className="clients_permission_row">
                        <td colSpan={COLUMN_COUNT}>
                          <ClientPermissionForm
                            hint={t("ui.clients.permission_apply_hint")}
                            kinds={listView.permission_kinds}
                            rows={listView.permission_rows}
                            defaultValue={defaultPermissionOf(listView)}
                            applied={clientPermissionOf(client)}
                            devices={managedDevices}
                            canFollowDefault
                            onSave={(value) => savePermission(client.id, value)}
                            onCancel={() => setPermissionOf(null)}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {listView !== null && isLinkOpen && (
        <ClientLinkModal
          listView={listView}
          devices={managedDevices}
          onCreated={resource.reload}
          onClose={() => setIsLinkOpen(false)}
        />
      )}
      {listView !== null && isDefaultOpen && (
        <DialogFrame
          title={t("ui.clients.default_permission_title")}
          icon="lock"
          onClose={() => setIsDefaultOpen(false)}
        >
          <p className="field_hint">
            {t("ui.clients.default_permission_hint")}
          </p>
          <ClientPermissionForm
            hint={t("ui.clients.default_permission_apply_hint")}
            kinds={listView.permission_kinds}
            rows={listView.permission_rows}
            defaultValue={defaultPermissionOf(listView)}
            applied={defaultPermissionOf(listView)}
            devices={managedDevices}
            canFollowDefault={false}
            onSave={saveDefaultPermission}
            onCancel={() => setIsDefaultOpen(false)}
          />
        </DialogFrame>
      )}
      {confirm.modal}
    </div>
  );
}

interface ClientRowProps {
  client: ClientView;
  /** The minutes its link still works while it waits to join; null once it
   * joined. */
  waitingMinutes: number | null;
  isBusy: boolean;
  /** Whether the name cell holds the rename form. */
  isRenaming: boolean;
  /** Whether the row's permission is open under it. */
  isPermissionOpen: boolean;
  newName: string;
  onNewName: (name: string) => void;
  onRename: () => void;
  onRenameSave: () => void;
  onRenameCancel: () => void;
  onToggle: () => void;
  onPermission: () => void;
  onDelete: () => void;
}

function ClientRow({
  client,
  waitingMinutes,
  isBusy,
  isRenaming,
  isPermissionOpen,
  newName,
  onNewName,
  onRename,
  onRenameSave,
  onRenameCancel,
  onToggle,
  onPermission,
  onDelete,
}: ClientRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const presence = presenceOf(client);
  return (
    <tr
      className={[
        client.is_disabled ? "clients_row--disabled" : "",
        isRenaming || isPermissionOpen ? "clients_row--editing" : "",
      ]
        .filter((name) => name !== "")
        .join(" ")}
    >
      <td colSpan={isRenaming ? RENAME_COLUMN_SPAN : undefined}>
        {isRenaming ? (
          <div className="clients_rename">
            <input
              className="input"
              value={newName}
              aria-label={t("ui.clients.header_name")}
              autoFocus
              onChange={(event) => onNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  onRenameSave();
                } else if (event.key === "Escape") {
                  onRenameCancel();
                }
              }}
            />
            <div className="clients_add_actions">
              <button
                type="button"
                className="button button--small button--ghost"
                onClick={onRenameCancel}
              >
                {t("ui.clients.cancel")}
              </button>
              <button
                type="button"
                className="button button--small button--primary"
                disabled={isBusy || newName.trim().length === 0}
                onClick={onRenameSave}
              >
                <Icon name="check" size={13} />
                {t("ui.clients.save")}
              </button>
            </div>
          </div>
        ) : (
          <div className="clients_name">
            {client.name}
            {client.is_disabled && (
              <span className="badge badge--warn">
                {t("ui.clients.disabled")}
              </span>
            )}
            {client.permission !== null && (
              <span className="badge">{t("ui.clients.permission_custom")}</span>
            )}
          </div>
        )}
      </td>
      {!isRenaming && waitingMinutes !== null && (
        <td colSpan={WAITING_COLUMN_SPAN} className="faint">
          {t("ui.clients.waiting", { minutes: waitingMinutes })}
        </td>
      )}
      {!isRenaming && waitingMinutes === null && (
        <>
          <td className="mono">{client.hostname || NOTHING}</td>
          <td>{client.platform_os || NOTHING}</td>
          <td className="mono">{client.version || NOTHING}</td>
        </>
      )}
      <td>
        <StatusDot
          tone={PRESENCE_TONES[presence]}
          label={t(PRESENCE_KEYS[presence])}
        />
      </td>
      <td className="mono">
        {client.is_online ? t("state.online") : formatTimeAgo(client.last_seen)}
      </td>
      <td>
        <div className="clients_actions">
          {waitingMinutes === null && (
            <button
              type="button"
              className="button button--small button--ghost"
              disabled={isBusy || isRenaming}
              onClick={onRename}
            >
              {t("ui.clients.rename")}
            </button>
          )}
          <button
            type="button"
            className="button button--small button--ghost"
            disabled={isBusy}
            aria-expanded={isPermissionOpen}
            onClick={onPermission}
          >
            {t("ui.clients.permission")}
          </button>
          {waitingMinutes === null && (
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
          )}
          <button
            type="button"
            className="button button--small button--ghost button--danger"
            disabled={isBusy}
            onClick={onDelete}
          >
            <Icon name="trash" size={13} />
            {t("ui.clients.delete")}
          </button>
        </div>
      </td>
    </tr>
  );
}

/** One managed device as the permission filter names it. */
function toDeviceChoice(device: DeviceView): PermissionDeviceChoice {
  return { id: device.id, name: toDeviceLabel(device) };
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
