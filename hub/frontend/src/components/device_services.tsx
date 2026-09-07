import { useCallback, useEffect, useState } from "react";

import { StatusDot } from "./status_dot";
import { apiGet, apiPost, describeError } from "../api_client";
import type {
  DeviceCommandResult,
  DeviceMountRecord,
  DeviceServiceAskStarted,
  DeviceServiceEntry,
  DeviceServicesView,
} from "../api_types";

import "./device_services.css";

/**
 * The services a device's agent runs, drawn the way its own page draws
 * them: one panel per type — Web, Ports, AI, Files, Remote desktop — the
 * same rows nested inside each, the same words.
 *
 * Every ask here is the page's own verb, queued for the agent and run
 * there in the privileged scope; how it went comes back among the command
 * results, refusals typed. What cannot be asked from here is greyed rather
 * than hidden: a port forward opens on the machine's own loopback, and a
 * desktop share's access password never crosses the wire in either
 * direction — both belong to the machine itself.
 */

const WORDING = {
  sectionTitle: "Services",
  waiting: "Waiting for the machine…",
  offline: "Agent offline.",
  empty: "Nothing published yet.",
  panelWeb: "Web",
  panelPorts: "Ports",
  panelAi: "AI",
  panelFiles: "Files",
  panelRdp: "Remote desktop",
  enabledUsers: "Enabled users",
  mountUser: "Mount for",
  apply: "Apply",
  open: "Open",
  mount: "Mount",
  unmount: "Unmount",
  config: "Config",
  usernameHint: "Share username",
  passwordHint: "Share password", // scan: allow
  pathHint: "Mount path",
  driveLetterHint: "Drive letter, like N:",
  unhealthy: "unreachable",
  rdpLocalShare: "Local share",
  rdpThisMachine: "This machine",
  rdpNotShared: "Not shared.",
  rdpShare: "Share",
  rdpUnshare: "Stop sharing",
  shareUser: "Share user",
  accessPasswordHint: "Access password", // scan: allow
};

// What each typed refusal says here.
const SERVICE_ERROR_WORDING: Record<string, string> = {
  no_target_user: "No such account on this machine.",
  control_scope_refused: "Not allowed for this account.",
  unknown_request: "The machine doesn't know this request.",
  agent_offline: "Agent offline.",
  module_missing: "Missing a required module.",
  mountpoint_not_empty: "That folder isn't empty.",
  mountpoint_invalid: "Give an absolute path, like /mnt/share.",
  mountpoint_not_drive_letter: "Give an unused drive letter, like N:.",
  cifs_missing: "Mount tooling missing.",
  credentials_missing: "Saved login is gone. Enter it again.",
  fs_refused: "No access to that folder.",
  no_logged_on_session: "That account isn't signed in.",
  unsupported_platform: "Not supported on this machine.",
  agent_internal: "Agent error. Check its log.",
};

// Where a mount record stands, in the page's own words.
const MOUNT_STATE_WORDING: Record<string, string> = {
  queued: "waiting for the agent…",
  mounting: "mounting…",
  pending: "waiting to mount…",
  mounted: "mounted",
  detached: "not mounted",
  failed: "failed",
};

// Where a share stands, in the page's own words.
const RDP_STATE_WORDING: Record<string, string> = {
  not_shared: "not shared",
  sharing: "shared",
  starting: "starting…",
  waiting_for_approval: "waiting for permission on this machine",
};

const MOUNT_BUSY_STATES = ["queued", "mounting", "pending"];

const REFRESH_INTERVAL_MS = 2000;

/** The staged mount form for one file entry. */
interface MountForm {
  account: string;
  username: string;
  password: string;
  path: string;
}

type FormsUpdate = (
  held: Record<string, MountForm>,
) => Record<string, MountForm>;

interface DeviceServicesProps {
  macAddress: string;
  isOnline: boolean;
  /** The queued-command outcomes off the device view, newest first; the
   * service asks' results are found among them by their id prefix. */
  commandResults: DeviceCommandResult[];
}

export function DeviceServices({
  macAddress,
  isOnline,
  commandResults,
}: DeviceServicesProps) {
  const [view, setView] = useState<DeviceServicesView | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The AI chips staged locally until Apply; null draws the machine's own.
  const [staged, setStaged] = useState<Record<string, boolean> | null>(null);
  const [forms, setForms] = useState<Record<string, MountForm>>({});
  // The one ask in flight: which button made it, and the queued command id
  // its answer will carry.
  const [asked, setAsked] = useState<{ id: string; key: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setView(
        await apiGet<DeviceServicesView>(`/devices/${macAddress}/services`),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  }, [macAddress]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const ask = async (
    serviceType: string,
    body: Record<string, unknown>,
    key: string,
  ) => {
    setError(null);
    try {
      const started = await apiPost<DeviceServiceAskStarted>(
        `/devices/${macAddress}/services/${serviceType}`,
        { body },
      );
      setAsked({ id: started.command_id, key });
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const outcome =
    asked === null
      ? undefined
      : commandResults.find((result) => result.id === asked.id);
  const pendingKey = asked !== null && outcome === undefined ? asked.key : null;
  const failure =
    outcome !== undefined && outcome.exit_code !== 0
      ? (SERVICE_ERROR_WORDING[outcome.code] ?? outcome.code)
      : null;

  if (view === null) {
    return (
      <div className="device_services">
        <span className="section_label">{WORDING.sectionTitle}</span>
        {error !== null && <span className="field_error">{error}</span>}
        <span className="field_hint">{WORDING.waiting}</span>
      </div>
    );
  }

  const ofType = (type: string) =>
    view.entries.filter((entry) => entry.type === type);
  const hasAny = view.entries.some((entry) => entry.type !== "rdp");

  return (
    <div className="device_services">
      <span className="section_label">{WORDING.sectionTitle}</span>
      {error !== null && <span className="field_error">{error}</span>}
      {!isOnline && <span className="field_hint">{WORDING.offline}</span>}
      {!hasAny && <span className="field_hint">{WORDING.empty}</span>}

      {ofType("web").length > 0 && <WebPanel entries={ofType("web")} />}
      {ofType("port").length > 0 && <PortsPanel entries={ofType("port")} />}
      {ofType("ai").length > 0 && (
        <AiPanel
          view={view}
          staged={staged}
          isOnline={isOnline}
          onStage={setStaged}
          pendingKey={pendingKey}
          onApply={(targets) => {
            setStaged(null);
            void ask("ai", { targets }, "ai");
          }}
        />
      )}
      {ofType("file").length > 0 && (
        <FilesPanel
          entries={ofType("file")}
          view={view}
          forms={forms}
          isOnline={isOnline}
          pendingKey={pendingKey}
          onForms={setForms}
          onAsk={(body, key) => void ask("file", body, key)}
        />
      )}
      <RdpPanel
        rdp={view.rdp}
        accounts={view.accounts}
        isOnline={isOnline}
        pendingKey={pendingKey}
        onAsk={(body) => void ask("rdp", body, "rdp")}
      />

      {failure !== null && <span className="field_error">{failure}</span>}
    </div>
  );
}

/** One panel, titled the way the agent's page titles its panels. */
function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="device_service_panel">
      <div className="device_service_panel_title">{title}</div>
      {children}
    </div>
  );
}

/** One entry row — the page's own `feat` row: dot, title, payload line. */
function EntryRow({
  entry,
  payloadText,
  children,
}: {
  entry: DeviceServiceEntry;
  payloadText: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className={`device_service_feat${entry.is_healthy ? "" : " device_service_feat--greyed"}`}
    >
      <StatusDot tone={entry.is_healthy ? "ok" : "idle"} />
      <div className="device_service_feat_body">
        <div className="device_service_feat_title">{entry.title}</div>
        <div className="device_service_feat_note">
          {payloadText}
          {entry.is_healthy ? "" : ` — ${WORDING.unhealthy}`}
        </div>
        {entry.description !== "" && (
          <div className="device_service_feat_note device_service_feat_note--muted">
            {entry.description}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}

function WebPanel({ entries }: { entries: DeviceServiceEntry[] }) {
  return (
    <Panel title={WORDING.panelWeb}>
      {entries.map((entry) => (
        <EntryRow
          key={entry.id}
          entry={entry}
          payloadText={String(entry.payload.url ?? "")}
        >
          <button
            type="button"
            className="button button--small button--ghost"
            disabled={!entry.is_healthy}
            onClick={() =>
              window.open(
                String(entry.payload.url ?? "#"),
                "_blank",
                "noopener",
              )
            }
          >
            {WORDING.open}
          </button>
        </EntryRow>
      ))}
    </Panel>
  );
}

function PortsPanel({ entries }: { entries: DeviceServiceEntry[] }) {
  return (
    <Panel title={WORDING.panelPorts}>
      {entries.map((entry) => (
        <EntryRow
          key={entry.id}
          entry={entry}
          payloadText={`${String(entry.payload.host ?? "")}:${String(entry.payload.port ?? "")}`}
        />
      ))}
    </Panel>
  );
}

function AiPanel({
  view,
  staged,
  isOnline,
  pendingKey,
  onStage,
  onApply,
}: {
  view: DeviceServicesView;
  staged: Record<string, boolean> | null;
  isOnline: boolean;
  pendingKey: string | null;
  onStage: (targets: Record<string, boolean>) => void;
  onApply: (targets: Record<string, boolean>) => void;
}) {
  const targets: Record<string, boolean> = {};
  for (const account of view.accounts) {
    targets[account] = staged?.[account] ?? !!view.ai_targets[account];
  }
  const isDirty =
    staged !== null &&
    view.accounts.some(
      (account) => targets[account] !== !!view.ai_targets[account],
    );
  return (
    <Panel title={WORDING.panelAi}>
      <div className="device_service_head_row">
        <span className="device_service_sub">{WORDING.enabledUsers}</span>
        <button
          type="button"
          className="button button--small button--ok"
          disabled={!isOnline || !isDirty || pendingKey === "ai"}
          onClick={() => onApply(targets)}
        >
          {pendingKey === "ai" ? "…" : WORDING.apply}
        </button>
      </div>
      <div className="device_service_chips">
        {view.accounts.map((account) => (
          <button
            key={account}
            type="button"
            className={`device_service_chip${targets[account] ? " device_service_chip--on" : ""}`}
            disabled={!isOnline}
            onClick={() =>
              onStage({ ...targets, [account]: !targets[account] })
            }
          >
            <StatusDot
              tone={view.ai_states[account]?.is_active ? "ok" : "idle"}
            />
            {account}
          </button>
        ))}
      </div>
    </Panel>
  );
}

function FilesPanel({
  entries,
  view,
  forms,
  isOnline,
  pendingKey,
  onForms,
  onAsk,
}: {
  entries: DeviceServiceEntry[];
  view: DeviceServicesView;
  forms: Record<string, MountForm>;
  isOnline: boolean;
  pendingKey: string | null;
  onForms: (update: FormsUpdate) => void;
  onAsk: (body: Record<string, unknown>, key: string) => void;
}) {
  return (
    <Panel title={WORDING.panelFiles}>
      {entries.map((entry) => {
        const records = view.mounts.filter(
          (record) => record.entry_id === entry.id,
        );
        const record: DeviceMountRecord | undefined = records[0];
        const form = forms[entry.id];
        const share = `//${String(entry.payload.host ?? "")}/${String(entry.payload.share ?? "")}`;
        return (
          <div key={entry.id} className="device_service_nest">
            <EntryRow entry={entry} payloadText={share}>
              <button
                type="button"
                className="button button--small button--ghost"
                disabled={!isOnline}
                onClick={() =>
                  onForms((held) => {
                    const next = { ...held };
                    if (form !== undefined) {
                      delete next[entry.id];
                    } else {
                      next[entry.id] = {
                        account: record?.account ?? view.accounts[0] ?? "",
                        username: record?.username ?? "",
                        password: "",
                        // The machine's own offer where it mounts at a drive
                        // letter; a path is the person's to choose.
                        path: record?.path ?? view.mount_location_suggestion,
                      };
                    }
                    return next;
                  })
                }
              >
                {WORDING.config}
              </button>
              <MountButton
                entry={entry}
                record={record}
                form={form}
                isOnline={isOnline}
                pendingKey={pendingKey}
                onAsk={onAsk}
              />
            </EntryRow>
            {records.map((mountRecord) => (
              <div key={mountRecord.record_id} className="device_service_rec">
                <StatusDot
                  tone={
                    mountRecord.is_attached
                      ? "ok"
                      : mountRecord.code !== ""
                        ? "error"
                        : "idle"
                  }
                />
                <span className="device_service_feat_note">
                  {`${mountRecord.path} · ${mountRecord.account} — `}
                  {mountRecord.code !== ""
                    ? (SERVICE_ERROR_WORDING[mountRecord.code] ??
                      mountRecord.code)
                    : (MOUNT_STATE_WORDING[mountRecord.state] ??
                      mountRecord.state)}
                </span>
              </div>
            ))}
            {form !== undefined && (
              <MountFormFields
                entryId={entry.id}
                form={form}
                accounts={view.accounts}
                onForms={onForms}
                shape={view.mount_location_shape}
              />
            )}
          </div>
        );
      })}
    </Panel>
  );
}

function MountFormFields({
  entryId,
  form,
  accounts,
  onForms,
  shape,
}: {
  entryId: string;
  form: MountForm;
  accounts: string[];
  onForms: (update: FormsUpdate) => void;
  shape: DeviceServicesView["mount_location_shape"];
}) {
  const set = (change: Partial<MountForm>) =>
    onForms((held) => ({ ...held, [entryId]: { ...form, ...change } }));
  return (
    <div className="device_service_form">
      <span className="device_service_sub">{WORDING.mountUser}</span>
      <div className="device_service_chips">
        {accounts.map((account) => (
          <button
            key={account}
            type="button"
            className={`device_service_chip${form.account === account ? " device_service_chip--on" : ""}`}
            onClick={() => set({ account })}
          >
            {account}
          </button>
        ))}
      </div>
      <input
        type="text"
        placeholder={WORDING.usernameHint}
        value={form.username}
        onChange={(event) => set({ username: event.target.value })}
      />
      <input
        type="password"
        placeholder={WORDING.passwordHint}
        value={form.password}
        onChange={(event) => set({ password: event.target.value })}
      />
      <input
        type="text"
        placeholder={
          shape === "drive_letter" ? WORDING.driveLetterHint : WORDING.pathHint
        }
        value={form.path}
        onChange={(event) => set({ path: event.target.value })}
      />
    </div>
  );
}

/**
 * The one button position beside Config, morphing the way the page's mount
 * button does: Mount submits the open form while no record stands, a
 * detached record remounts with its saved login, and anything else offers
 * Unmount.
 */
function MountButton({
  entry,
  record,
  form,
  isOnline,
  pendingKey,
  onAsk,
}: {
  entry: DeviceServiceEntry;
  record: DeviceMountRecord | undefined;
  form: MountForm | undefined;
  isOnline: boolean;
  pendingKey: string | null;
  onAsk: (body: Record<string, unknown>, key: string) => void;
}) {
  const key = record?.record_id ?? entry.id;
  const isPending = pendingKey === key;
  if (record === undefined) {
    return (
      <button
        type="button"
        className="button button--small button--ok"
        disabled={
          !isOnline ||
          isPending ||
          form === undefined ||
          form.path === "" ||
          form.account === ""
        }
        onClick={() => {
          if (form === undefined) {
            return;
          }
          onAsk(
            {
              action: "mount",
              id: entry.id,
              account: form.account,
              username: form.username,
              password: form.password,
              path: form.path,
            },
            key,
          );
        }}
      >
        {isPending ? "…" : WORDING.mount}
      </button>
    );
  }
  if (isPending || MOUNT_BUSY_STATES.includes(record.state)) {
    return (
      <button type="button" className="button button--small" disabled>
        {isPending ? "…" : MOUNT_STATE_WORDING[record.state]}
      </button>
    );
  }
  if (record.state === "detached") {
    return (
      <button
        type="button"
        className="button button--small button--ok"
        disabled={!isOnline}
        onClick={() =>
          onAsk({ action: "mount", record_id: record.record_id }, key)
        }
      >
        {WORDING.mount}
      </button>
    );
  }
  return (
    <button
      type="button"
      className="button button--small button--danger"
      disabled={!isOnline}
      onClick={() =>
        onAsk({ action: "unmount", record_id: record.record_id }, key)
      }
    >
      {WORDING.unmount}
    </button>
  );
}

function RdpPanel({
  rdp,
  accounts,
  isOnline,
  pendingKey,
  onAsk,
}: {
  rdp: Record<string, unknown>;
  accounts: string[];
  isOnline: boolean;
  pendingKey: string | null;
  onAsk: (body: Record<string, unknown>) => void;
}) {
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const isShared = !!rdp.is_shared;
  const state = String(rdp.state ?? "not_shared");
  const shared = String(rdp.account ?? "");
  const isPending = pendingKey === "rdp";
  const chosen = account || accounts[0] || "";
  const reach = isShared
    ? `${RDP_STATE_WORDING[state] ?? state} · :${String(rdp.port ?? "")}${
        shared !== "" ? ` · ${shared}` : ""
      }`
    : WORDING.rdpNotShared;
  return (
    <Panel title={WORDING.panelRdp}>
      <span className="device_service_sub">{WORDING.rdpLocalShare}</span>
      <div
        className={`device_service_feat${isShared ? "" : " device_service_feat--greyed"}`}
      >
        <StatusDot tone={state === "sharing" ? "ok" : "idle"} />
        <div className="device_service_feat_body">
          <div className="device_service_feat_title">
            {WORDING.rdpThisMachine}
          </div>
          <div className="device_service_feat_note">{reach}</div>
        </div>
        {isShared ? (
          <button
            type="button"
            className="button button--small button--danger"
            disabled={!isOnline || isPending}
            onClick={() => onAsk({ action: "unshare" })}
          >
            {isPending ? "…" : WORDING.rdpUnshare}
          </button>
        ) : (
          <button
            type="button"
            className="button button--small button--ok"
            disabled={
              !isOnline || isPending || password === "" || chosen === ""
            }
            onClick={() => {
              onAsk({ action: "share", account: chosen, password });
              setPassword("");
            }}
          >
            {isPending ? "…" : WORDING.rdpShare}
          </button>
        )}
      </div>
      {!isShared && (
        <div className="device_service_form">
          <span className="device_service_sub">{WORDING.shareUser}</span>
          <div className="device_service_chips">
            {accounts.map((name) => (
              <button
                key={name}
                type="button"
                className={`device_service_chip${chosen === name ? " device_service_chip--on" : ""}`}
                disabled={!isOnline}
                onClick={() => setAccount(name)}
              >
                {name}
              </button>
            ))}
          </div>
          <input
            type="password"
            placeholder={WORDING.accessPasswordHint}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
      )}
    </Panel>
  );
}
