import { useState } from "react";

import { DeclareServiceModal } from "../components/declare_service_modal";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import type { StatusTone } from "../components/status_dot";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { moduleTitle } from "../module_title";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { HUB_EVENT_CONFIG, HUB_EVENT_SERVICES } from "../use_hub_events";
import type {
  AppEntryView,
  AppSource,
  AppView,
  DeclaredAppRequest,
  PublishedService,
  PublishedServicePayload,
  PublishedServiceType,
  ServiceListView,
} from "../api_types";

import "./services_page.css";

/**
 * What the hub publishes to clients.
 *
 * **Apps** first: one row per app, one program on one machine, its entries
 * each a chip with the local address a client forwards it at, or a declared
 * share's address, and its status dot, and at the row's right the chip of
 * where it comes from. A module the hub manages is one app however many
 * containers it runs; a container the hub does not manage is one app of its
 * own. An app declared here carries Test and Delete. The entries of no app
 * follow in their own sections: the AI gateway, the machines' file shares
 * and the shared desktops. A machine's SSH server is no app, and the hub
 * sends none of its entries here. **Declare service** opens the dialog that
 * declares an app with its entries.
 */

/** The sections of the entries that belong to no app, in order. */
const SECTION_ORDER: PublishedServiceType[] = ["ai", "file", "rdp"];
const SECTION_TITLE_KEYS: Record<string, string> = {
  ai: "ui.services.group_ai",
  file: "ui.services.group_file",
  rdp: "ui.services.group_rdp",
};

/** The tones an entry's health takes. */
type HealthTone = Extract<StatusTone, "ok" | "error" | "idle">;

/** Who answers for an app, the hub's own module in the accent. */
const APP_SOURCE_KEYS: Record<AppSource, string> = {
  module: "ui.app_source.module",
  declared: "ui.app_source.declared",
  manual: "ui.app_source.manual",
};
const APP_SOURCE_TONES: Record<AppSource, string> = {
  module: "badge--accent",
  declared: "badge--secondary",
  manual: "badge--secondary",
};

/** The word of each entry's type on its chip. */
const ENTRY_TYPE_KEYS: Record<PublishedServiceType, string> = {
  web: "ui.services.kind_web",
  port: "ui.services.kind_port",
  ssh: "ui.services.kind_ssh",
  ai: "ui.services.group_ai",
  file: "ui.services.kind_file",
  rdp: "ui.services.group_rdp",
};

// One fixed word set per kind of row: a module row is the module's own
// state, a machine row is a machine saying it shares its desktop.
const MODULE_STATE_KEYS: Record<"ok" | "error", string> = {
  ok: "ui.services.state_serving",
  error: "state.not_serving",
};
const DEVICE_STATE_KEY = "state.shared";
// A declared entry's word: what its last probe measured, or that the hub
// has not probed it yet, or never does, as a UDP port.
const DECLARED_STATE_KEYS: Record<
  "ok" | "error" | "idle" | "unchecked",
  string
> = {
  ok: "state.reachable",
  error: "state.unreachable",
  idle: "state.checking",
  unchecked: "state.not_checked",
};

// The probe's detail_code, worded. A file entry is measured against the
// server's own list of exports, so a share that is not on it reads
// differently from a server that never answered, and differently again from
// a hub that has no client to ask with.
const DECLARED_DETAIL_KEYS: Record<string, string> = {
  connect_failed: "code.connect_failed",
  server_error: "code.server_error",
  share_missing: "code.share_missing",
  tool_missing: "code.tool_missing",
  list_refused: "code.list_refused",
  share_unverified: "code.share_unverified",
};
// Where an entry of no app comes from, as the hub names it.
const DESCRIPTION_KEYS: Record<string, string> = {
  ai_gateway: "ui.services.description_ai_gateway",
  container: "ui.services.description_container",
  declared: "ui.services.description_declared",
  device_share: "ui.services.description_device_share",
  gitea_module: "ui.services.description_gitea_module",
  samba_module: "ui.services.description_samba_module",
  vscode_module: "ui.services.description_vscode_module",
  cloudcli_module: "ui.services.description_cloudcli_module",
  code_server_module: "ui.services.description_code_server_module",
  codeg_module: "ui.services.description_codeg_module",
  hermes_webui_module: "ui.services.description_hermes_webui_module",
  ssh_server_module: "ui.services.description_ssh_server_module",
};
// The module a description names by the module's title.
const DESCRIPTION_MODULES: Record<string, string> = {
  samba_module: "samba",
};

/** The id every container app starts with, whose declaration is the
 * Containers module's and not this page's. */
const CONTAINER_APP_PREFIX = "podman_";

/** The loopback address a client's forward of a port entry listens on. */
const LOOPBACK_HOST = "127.0.0.1";
/** A web entry's url: its scheme, and its path and query. */
const WEB_URL_PATTERN = /^([a-z][a-z0-9+.-]*):\/\/[^/?#]*([^#]*)/i;
/** A url's host, an IPv6 address in its brackets. */
const URL_HOST_PATTERN = /^[a-z][a-z0-9+.-]*:\/\/(\[[^\]]+\]|[^/:?#]+)/i;

/** The declared apps' errors the page words itself. */
const DECLARED_ERROR_KEYS: Record<string, string> = {
  declared_service_unknown: "code.declared_service_unknown",
};

// What moves this list: the hub composing it differently, and any write
// under config/, since a module's own settings decide what it publishes.
const INVALIDATE_ON = [
  { type: HUB_EVENT_SERVICES },
  { type: HUB_EVENT_CONFIG },
];

const SERVICE_PATH = "/hub/service";

export function ServicesPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ServiceListView>(SERVICE_PATH, {
    invalidateOn: INVALIDATE_ON,
  });
  const [isDeclaring, setIsDeclaring] = useState(false);
  const view = resource.data;

  if (resource.error !== null && view === null) {
    return (
      <div className="page">
        <h1>{t("ui.services.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (view === null) {
    return (
      <div className="page">
        <h1>{t("ui.services.title")}</h1>
        <div className="skeleton" style={{ height: 420 }} />
      </div>
    );
  }

  // An entry the hub never probes holds no health, so the badge counts it
  // neither way.
  const judged = [
    ...view.apps.flatMap((app) => app.entries),
    ...view.services,
  ].filter((entry) => entry.is_healthy !== null);
  const healthyCount = judged.filter(
    (entry) => entry.is_healthy === true,
  ).length;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>{t("ui.services.title")}</h1>
            <span className="badge">
              {t("ui.services.badge", {
                healthy: healthyCount,
                total: judged.length,
              })}
            </span>
          </div>
        </div>
        <div className="page_actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIsDeclaring(true)}
          >
            <Icon name="plus" size={14} />
            {t("ui.services.declare")}
          </button>
        </div>
      </div>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.services.apps_title")}</h2>
        </div>
        {view.apps.length === 0 ? (
          <p className="field_hint faint">{t("ui.services.group_empty")}</p>
        ) : (
          <div className="published_rows">
            {view.apps.map((app) => (
              <AppRow key={app.id} app={app} onChanged={resource.setData} />
            ))}
          </div>
        )}
      </section>

      {SECTION_ORDER.map((type) => (
        <ServiceSection
          key={type}
          type={type}
          services={view.services.filter((service) => service.type === type)}
        />
      ))}

      {isDeclaring && (
        <DeclareServiceModal
          onDeclared={(next) => {
            resource.setData(next);
            setIsDeclaring(false);
          }}
          onClose={() => setIsDeclaring(false)}
        />
      )}
    </div>
  );
}

interface AppRowProps {
  app: AppView;
  onChanged: (view: ServiceListView) => void;
}

/** One app: its title, its machine, its entries, and where it comes from. */
function AppRow({ app, onChanged }: AppRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isDeclared =
    app.source === "declared" && !app.id.startsWith(CONTAINER_APP_PREFIX);
  const details = app.entries
    .map((entry) =>
      entry.detail_code === null
        ? undefined
        : DECLARED_DETAIL_KEYS[entry.detail_code],
    )
    .filter((key): key is string => key !== undefined);

  const post = async (verb: "probe" | "remove") => {
    setIsBusy(true);
    setError(null);
    const request: DeclaredAppRequest = { app_id: app.id };
    try {
      onChanged(
        await apiPost<ServiceListView>(
          `${SERVICE_PATH}/declaration/${verb}`,
          request,
        ),
      );
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askDelete = () =>
    confirm.ask({
      title: t("ui.services.delete_title", { name: app.title }),
      body: t("ui.services.delete_body"),
      confirmLabel: t("ui.services.delete"),
      onConfirm: () => void post("remove"),
    });

  return (
    <div className="published_row app_row">
      <div className="app_row_head">
        <span className="published_row_title">{app.title}</span>
        <span className="app_row_machine mono">
          {app.device_name || hostOf(app)}
        </span>
        <span className="app_row_end">
          {isDeclared && (
            <span className="published_row_actions">
              <button
                type="button"
                className="button button--ghost button--small"
                disabled={isBusy}
                onClick={() => void post("probe")}
              >
                <Icon name="bolt" size={13} />
                {t("ui.services.test")}
              </button>
              <button
                type="button"
                className="button button--ghost button--small button--danger"
                disabled={isBusy}
                onClick={askDelete}
              >
                <Icon name="trash" size={13} />
                {t("ui.services.delete")}
              </button>
            </span>
          )}
          <span className={`badge ${APP_SOURCE_TONES[app.source]}`}>
            {t(APP_SOURCE_KEYS[app.source])}
          </span>
        </span>
      </div>
      {app.description !== "" && (
        <span className="published_row_description">{app.description}</span>
      )}
      <div className="app_row_entries">
        {app.entries.map((entry) => (
          <EntryChip
            key={entry.id}
            entry={entry}
            address={entryAddress(app.local_name, entry)}
            stateWord={isDeclared ? declaredStateWord(entry) : null}
          />
        ))}
      </div>
      {details.map((key, index) => (
        <span key={index} className="published_row_detail">
          {t(key)}
        </span>
      ))}
      {error !== null && <span className="field_error">{error}</span>}
      {confirm.modal}
    </div>
  );
}

interface EntryChipProps {
  entry: AppEntryView;
  /** Where the entry is; empty on an entry with no local port and no
   * share. */
  address: string;
  /** A declared entry's state word; null where the dot says it alone. */
  stateWord: string | null;
}

/** One entry: its type, where it is, and its health as a dot. */
function EntryChip({ entry, address, stateWord }: EntryChipProps) {
  return (
    <span
      className="badge app_entry"
      title={address === "" ? undefined : address}
    >
      <StatusDot tone={toneOf(entry.is_healthy)} isPulsing={false} />
      <span>{t(ENTRY_TYPE_KEYS[entry.type])}</span>
      {address !== "" && (
        <span className="app_entry_address mono">{address}</span>
      )}
      {stateWord !== null && <span className="faint">{stateWord}</span>}
    </span>
  );
}

/** A declared entry's word: a probe that answered or did not, one still to
 * come, or none: a UDP port, and an entry the probe could not judge. */
function declaredStateWord(entry: AppEntryView): string {
  const tone = toneOf(entry.is_healthy);
  const isNeverProbed =
    entry.type === "port" && entry.payload.protocol === "udp";
  const state =
    tone === "idle" && (entry.detail_code !== null || isNeverProbed)
      ? "unchecked"
      : tone;
  return t(DECLARED_STATE_KEYS[state]);
}

interface ServiceSectionProps {
  type: PublishedServiceType;
  services: PublishedService[];
}

function ServiceSection({ type, services }: ServiceSectionProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t(SECTION_TITLE_KEYS[type] ?? "")}</h2>
      </div>
      {services.length === 0 ? (
        <p className="field_hint faint">{t("ui.services.group_empty")}</p>
      ) : (
        <div className="published_rows">
          {services.map((service) => (
            <ServiceRow key={service.id} service={service} />
          ))}
        </div>
      )}
    </section>
  );
}

interface ServiceRowProps {
  service: PublishedService;
}

/** One entry of no app, read only. */
function ServiceRow({ service }: ServiceRowProps) {
  const tone = toneOf(service.is_healthy);
  const stateLabel = t(
    service.source === "device"
      ? DEVICE_STATE_KEY
      : MODULE_STATE_KEYS[tone === "ok" ? "ok" : "error"],
  );
  const description = describeService(service);
  return (
    <div className="published_row">
      <StatusDot tone={tone} />
      <div className="published_row_body">
        <div className="published_row_head">
          <span className="published_row_title">{service.title}</span>
          <span className="published_row_payload">
            {payloadLine(service.type, service.payload)}
          </span>
        </div>
        {description !== "" && (
          <span className="published_row_description">{description}</span>
        )}
      </div>
      <span className="published_row_state">{stateLabel}</span>
      {service.source !== "device" && (
        <span className="badge badge--accent">{t(APP_SOURCE_KEYS.module)}</span>
      )}
    </div>
  );
}

function toneOf(isHealthy: boolean | null): HealthTone {
  if (isHealthy === true) {
    return "ok";
  }
  return isHealthy === false ? "error" : "idle";
}

/** Where an entry of no app comes from, in this panel's words. */
function describeService(service: PublishedService): string {
  const key = DESCRIPTION_KEYS[service.description_code];
  if (key === undefined) {
    return service.description;
  }
  const name = DESCRIPTION_MODULES[service.description_code];
  return name === undefined
    ? t(key, service.description_params)
    : t(key, {
        ...service.description_params,
        module: moduleTitle(name, name),
      });
}

/** A payload, spelled the way its type reads. */
function payloadLine(
  type: PublishedServiceType,
  payload: PublishedServicePayload,
): string {
  if (type === "ai") {
    return payload.endpoint ?? "";
  }
  if (type === "file") {
    return `//${payload.host ?? ""}/${payload.share ?? ""}`;
  }
  return `${payload.host ?? ""}:${payload.port ?? ""}`;
}

/** Where an app's entry is: the address a client forwards it at, as its
 * Apps page shows it, the page's own scheme and path at the local name for
 * a web entry and the loopback for a port entry; and the share for a
 * declared file entry, which has no local port. */
function entryAddress(localName: string, entry: AppEntryView): string {
  if (entry.type === "file") {
    return payloadLine(entry.type, entry.payload);
  }
  if (entry.local_port <= 0) {
    return "";
  }
  if (entry.type === "web") {
    const url = WEB_URL_PATTERN.exec(entry.payload.url ?? "");
    const scheme = url?.[1]?.toLowerCase() ?? "http";
    const path = url?.[2] || "/";
    return `${scheme}://${localName}:${entry.local_port}${path}`;
  }
  const address = `${LOOPBACK_HOST}:${entry.local_port}`;
  return entry.type === "port" && entry.payload.protocol === "udp"
    ? `${address}/udp`
    : address;
}

/** The host an app with no machine the hub knows is at. */
function hostOf(app: AppView): string {
  const payload = app.entries[0]?.payload;
  if (payload?.url === undefined) {
    return payload?.host ?? "";
  }
  return URL_HOST_PATTERN.exec(payload.url)?.[1] ?? payload.url;
}

/** Wording for a failed call on a declared app, coded refusals spelled out. */
function describeDeclaredError(cause: unknown): string {
  const message = describeError(cause);
  if (
    typeof cause === "object" &&
    cause !== null &&
    "code" in cause &&
    typeof cause.code === "string"
  ) {
    const key = DECLARED_ERROR_KEYS[cause.code];
    if (key !== undefined) {
      return t(key);
    }
  }
  return message;
}
