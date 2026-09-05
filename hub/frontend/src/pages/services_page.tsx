import { useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import { ApiError, apiDelete, apiPost, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type {
  DeclaredServiceCreate,
  PublishedService,
  PublishedServiceType,
  ServicesResponse,
} from "../api_types";

import "./services_page.css";

/**
 * What the hub publishes: the typed service list, grouped by type.
 *
 * Module-declared rows are read-only — they exist while their module serves,
 * and their health is the module's own. Declared rows are the manual
 * declarations, created and deleted here and probed for health. The same
 * list, resolved per caller, is what every device's catalog carries.
 */

const PAGE_TITLE = "Services";
const HEALTH_BADGE = "{healthy} of {total} healthy";
const DECLARE_LABEL = "Declare service";

const GROUP_ORDER: PublishedServiceType[] = ["web", "port", "ai", "file"];
const GROUP_TITLES: Record<PublishedServiceType, string> = {
  web: "Web",
  port: "Ports",
  ai: "AI",
  file: "Files",
};
const GROUP_EMPTY = "Nothing published.";

// One fixed word set per source: a module row is the module's own state, a
// declared row is what the last probe measured.
const MODULE_STATE_LABELS: Record<"ok" | "error", string> = {
  ok: "serving",
  error: "not serving",
};
const DECLARED_STATE_LABELS: Record<"ok" | "error" | "idle", string> = {
  ok: "reachable",
  error: "unreachable",
  idle: "checking…",
};
const SOURCE_LABELS: Record<PublishedService["source"], string> = {
  module: "module",
  declared: "declared",
};

const FORM_TITLE = "New declared service";
const FIELD_NAME = "Name";
const FIELD_KIND = "Kind";
const FIELD_HOST = "Host";
const FIELD_PORT = "Port";
const FIELD_SCHEME = "Scheme";
const FIELD_PATH = "Path";
const FIELD_SHARE = "Share";
const FIELD_DESCRIPTION = "Description";
const HOST_HINT =
  "A loopback or hub-held host is served to each machine as the address it reaches the hub on.";
const PORT_HINT_FILE = "Left blank, a file service gets 445.";
const SAVE_LABEL = "Declare";
const SAVING_LABEL = "Declaring…";
const CANCEL_LABEL = "Cancel";
const TEST_LABEL = "Test";
const DELETE_LABEL = "Delete";
const DELETE_TITLE = "Delete {name}";
const DELETE_BODY =
  "The declaration is removed, every row it published with it; the machine it points at is untouched.";

const KIND_LABELS: Record<DeclaredServiceCreate["kind"], string> = {
  web: "Web",
  port: "Port",
  file: "File",
};

// The API's declared_service_invalid params.field, worded.
const DECLARED_INVALID_WORDING: Record<string, string> = {
  kind: "The kind is not one the hub knows.",
  name: "The service needs a name.",
  host: "The service needs a host.",
  port: "The port is a number from 1 to 65535.",
  scheme: "The scheme is http or https.",
  path: "The path starts with a slash.",
  shares: "The share needs a name.",
};
const DECLARED_UNKNOWN_WORDING = "That service is already gone; reload.";

const REFRESH_INTERVAL_MS = 5000;

export function ServicesPage() {
  const resource = useApiResource<ServicesResponse>("/services");
  const [services, setServices] = useState<PublishedService[]>([]);
  const [isDeclaring, setIsDeclaring] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setServices(resource.data.services);
    }
  }, [resource.data]);

  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const handleChanged = (next: PublishedService[]) => {
    setServices(next);
    resource.setData({ services: next });
  };

  if (resource.error !== null && resource.data === null) {
    return (
      <div className="page">
        <h1>{PAGE_TITLE}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (resource.data === null) {
    return (
      <div className="page">
        <h1>{PAGE_TITLE}</h1>
        <div className="skeleton" style={{ height: 420 }} />
      </div>
    );
  }

  const healthyCount = services.filter(
    (service) => service.is_healthy === true,
  ).length;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{PAGE_TITLE}</h1>
          <span className="badge">
            {fill(HEALTH_BADGE, {
              healthy: healthyCount,
              total: services.length,
            })}
          </span>
        </div>
        {!isDeclaring && (
          <div className="page_actions">
            <button
              type="button"
              className="button"
              onClick={() => setIsDeclaring(true)}
            >
              <Icon name="plus" size={14} />
              {DECLARE_LABEL}
            </button>
          </div>
        )}
      </div>

      {isDeclaring && (
        <DeclareForm
          onSaved={(next) => {
            handleChanged(next);
            setIsDeclaring(false);
          }}
          onCancel={() => setIsDeclaring(false)}
        />
      )}

      {GROUP_ORDER.map((type) => (
        <ServiceGroup
          key={type}
          type={type}
          services={services.filter((service) => service.type === type)}
          onChanged={handleChanged}
        />
      ))}
    </div>
  );
}

interface ServiceGroupProps {
  type: PublishedServiceType;
  services: PublishedService[];
  onChanged: (services: PublishedService[]) => void;
}

function ServiceGroup({ type, services, onChanged }: ServiceGroupProps) {
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{GROUP_TITLES[type]}</h2>
      </div>
      {services.length === 0 ? (
        <p className="field_hint faint">{GROUP_EMPTY}</p>
      ) : (
        <div className="published_rows">
          {services.map((service) => (
            <ServiceRow
              key={service.id}
              service={service}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}
    </section>
  );
}

interface ServiceRowProps {
  service: PublishedService;
  onChanged: (services: PublishedService[]) => void;
}

function ServiceRow({ service, onChanged }: ServiceRowProps) {
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tone: "ok" | "error" | "idle" =
    service.is_healthy === true
      ? "ok"
      : service.is_healthy === false
        ? "error"
        : "idle";
  const stateLabel =
    service.source === "module"
      ? MODULE_STATE_LABELS[tone === "idle" ? "error" : tone]
      : DECLARED_STATE_LABELS[tone];

  const handleProbe = async () => {
    if (service.record_id === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const answer = await apiPost<ServicesResponse>(
        `/services/declared/${service.record_id}/probe`,
      );
      onChanged(answer.services);
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const deleteRecord = async () => {
    if (service.record_id === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const answer = await apiDelete<ServicesResponse>(
        `/services/declared/${service.record_id}`,
      );
      onChanged(answer.services);
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
      setIsBusy(false);
    }
  };

  const handleDelete = () =>
    confirm.ask({
      title: fill(DELETE_TITLE, { name: service.title }),
      body: DELETE_BODY,
      confirmLabel: DELETE_LABEL,
      onConfirm: () => void deleteRecord(),
    });

  return (
    <div className="published_row">
      <StatusDot tone={tone} />
      <div className="published_row_body">
        <div className="published_row_head">
          <span className="published_row_title">{service.title}</span>
          <span className="published_row_payload">{payloadLine(service)}</span>
        </div>
        {service.description !== "" && (
          <span className="published_row_description">
            {service.description}
          </span>
        )}
        {error !== null && <span className="field_error">{error}</span>}
      </div>
      <span className="published_row_state">{stateLabel}</span>
      <span className="badge">{SOURCE_LABELS[service.source]}</span>
      {service.record_id !== null && (
        <div className="published_row_actions">
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={isBusy}
            onClick={() => void handleProbe()}
          >
            <Icon name="bolt" size={13} />
            {TEST_LABEL}
          </button>
          <button
            type="button"
            className="button button--ghost button--small button--danger"
            disabled={isBusy}
            onClick={handleDelete}
          >
            <Icon name="trash" size={13} />
            {DELETE_LABEL}
          </button>
        </div>
      )}
      {confirm.modal}
    </div>
  );
}

interface DeclareFormProps {
  onSaved: (services: PublishedService[]) => void;
  onCancel: () => void;
}

function DeclareForm({ onSaved, onCancel }: DeclareFormProps) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<DeclaredServiceCreate["kind"]>("web");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [scheme, setScheme] = useState("http");
  const [path, setPath] = useState("/");
  const [share, setShare] = useState("");
  const [description, setDescription] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPortReady =
    port.trim().length === 0 ? kind === "file" : isValidPort(port.trim());
  const isReady =
    name.trim().length > 0 &&
    host.trim().length > 0 &&
    isPortReady &&
    (kind !== "file" || share.trim().length > 0);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    const payload: DeclaredServiceCreate = {
      name: name.trim(),
      kind,
      host: host.trim(),
      port: port.trim().length > 0 ? Number(port.trim()) : null,
      scheme: kind === "web" ? scheme : null,
      path: kind === "web" ? path.trim() : null,
      share: kind === "file" ? share.trim() : null,
      description: description.trim(),
    };
    try {
      const answer = await apiPost<ServicesResponse>(
        "/services/declared",
        payload,
      );
      onSaved(answer.services);
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="declared_form">
      <div className="section_label">{FORM_TITLE}</div>
      <div className="declared_form_row">
        <label className="field">
          <span className="field_label">{FIELD_NAME}</span>
          <input
            className="input"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{FIELD_KIND}</span>
          <select
            className="input"
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as DeclaredServiceCreate["kind"])
            }
          >
            {(Object.keys(KIND_LABELS) as DeclaredServiceCreate["kind"][]).map(
              (option) => (
                <option key={option} value={option}>
                  {KIND_LABELS[option]}
                </option>
              ),
            )}
          </select>
        </label>
      </div>
      <div className="declared_form_row">
        <label className="field">
          <span className="field_label">{FIELD_HOST}</span>
          <input
            className="input"
            value={host}
            placeholder="192.168.100.7"
            spellCheck={false}
            onChange={(event) => setHost(event.target.value)}
          />
          <span className="field_hint">{HOST_HINT}</span>
        </label>
        <label className="field">
          <span className="field_label">{FIELD_PORT}</span>
          <input
            className="input"
            value={port}
            placeholder={kind === "file" ? "445" : ""}
            inputMode="numeric"
            onChange={(event) => setPort(event.target.value)}
          />
          {kind === "file" && (
            <span className="field_hint">{PORT_HINT_FILE}</span>
          )}
        </label>
      </div>
      {kind === "web" && (
        <div className="declared_form_row">
          <label className="field">
            <span className="field_label">{FIELD_SCHEME}</span>
            <select
              className="input"
              value={scheme}
              onChange={(event) => setScheme(event.target.value)}
            >
              <option value="http">http</option>
              <option value="https">https</option>
            </select>
          </label>
          <label className="field">
            <span className="field_label">{FIELD_PATH}</span>
            <input
              className="input"
              value={path}
              spellCheck={false}
              onChange={(event) => setPath(event.target.value)}
            />
          </label>
        </div>
      )}
      {kind === "file" && (
        <label className="field">
          <span className="field_label">{FIELD_SHARE}</span>
          <input
            className="input"
            value={share}
            placeholder="media"
            spellCheck={false}
            onChange={(event) => setShare(event.target.value)}
          />
        </label>
      )}
      <label className="field">
        <span className="field_label">{FIELD_DESCRIPTION}</span>
        <input
          className="input"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      {error !== null && <span className="field_error">{error}</span>}
      <div className="declared_form_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          {CANCEL_LABEL}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? SAVING_LABEL : SAVE_LABEL}
        </button>
      </div>
    </div>
  );
}

/** The payload, spelled the way its type reads. */
function payloadLine(service: PublishedService): string {
  if (service.type === "web") {
    return service.payload.url ?? "";
  }
  if (service.type === "ai") {
    return service.payload.endpoint ?? "";
  }
  if (service.type === "file") {
    return `//${service.payload.host ?? ""}/${service.payload.share ?? ""}`;
  }
  return `${service.payload.host ?? ""}:${service.payload.port ?? ""}`;
}

/** Put values into a wording constant, by name. */
function fill(
  wording: string,
  values: Record<string, string | number>,
): string {
  let filled = wording;
  for (const [name, value] of Object.entries(values)) {
    filled = filled.replace(`{${name}}`, String(value));
  }
  return filled;
}

/** Wording for a failed declared-service call, coded refusals spelled out. */
function describeDeclaredError(cause: unknown): string {
  if (
    cause instanceof ApiError &&
    typeof cause.detail === "object" &&
    cause.detail !== null
  ) {
    const detail = cause.detail as Record<string, unknown>;
    if (detail.code === "declared_service_unknown") {
      return DECLARED_UNKNOWN_WORDING;
    }
    if (detail.code === "declared_service_invalid") {
      const params = (detail.params ?? {}) as Record<string, unknown>;
      const wording = DECLARED_INVALID_WORDING[String(params.field)];
      if (wording !== undefined) {
        return wording;
      }
    }
  }
  return describeError(cause);
}

function isValidPort(value: string): boolean {
  if (!/^\d{1,5}$/.test(value)) {
    return false;
  }
  const port = Number(value);
  return port >= 1 && port <= 65535;
}
