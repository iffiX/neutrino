import { useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import { StringListEditor } from "../components/string_list_editor";
import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  describeError,
} from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_SERVICES } from "../use_hub_events";
import { useConfirm } from "../use_confirm";
import type {
  DeclaredServiceCreate,
  PublishedService,
  PublishedServiceType,
  ServiceSharesResponse,
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

const GROUP_ORDER: PublishedServiceType[] = ["web", "port", "ai", "file"];
const GROUP_TITLE_KEYS: Record<PublishedServiceType, string> = {
  web: "ui.services.group_web",
  port: "ui.services.group_port",
  ai: "ui.services.group_ai",
  file: "ui.services.group_file",
};

// One fixed word set per source: a module row is the module's own state, a
// declared row is what the last probe measured.
const MODULE_STATE_KEYS: Record<"ok" | "error", string> = {
  ok: "ui.services.state_serving",
  error: "state.not_serving",
};
const DECLARED_STATE_KEYS: Record<
  "ok" | "error" | "idle" | "unchecked",
  string
> = {
  ok: "state.reachable",
  error: "state.unreachable",
  idle: "state.checking",
  unchecked: "state.not_checked",
};

// The probe's detail_code, worded. A file service is measured against the
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
const SOURCE_KEYS: Record<PublishedService["source"], string> = {
  module: "state.module",
  declared: "ui.services.source_declared",
};
// Who published the row: the hub's own module in the accent, the operator's
// own entry in the secondary. Health is the dot's and the state word's.
const SOURCE_TONES: Record<PublishedService["source"], string> = {
  module: "badge--accent",
  declared: "badge--secondary",
};

/** The example a share field shows, which is a name rather than a word. */
const SHARES_PLACEHOLDER = "media";

/** The example a host field shows. */
const HOST_PLACEHOLDER = "192.168.100.7";

/** The port a file service takes when the field is left blank. */
const FILE_PORT_PLACEHOLDER = "445";

const KIND_KEYS: Record<DeclaredServiceCreate["kind"], string> = {
  web: "ui.services.kind_web",
  port: "ui.services.kind_port",
  file: "ui.services.kind_file",
};

// The API's declared_service_invalid params.field, worded.
const DECLARED_INVALID_KEYS: Record<string, string> = {
  kind: "ui.services.invalid_kind",
  name: "ui.services.invalid_name",
  host: "ui.services.invalid_host",
  port: "ui.services.invalid_port",
  scheme: "ui.services.invalid_scheme",
  path: "ui.services.invalid_path",
  shares: "ui.services.invalid_shares",
};

// What moves this list: the hub composing it differently, and any write
// under config/, since a module's own settings decide what it publishes.
const INVALIDATE_ON = [
  { type: HUB_EVENT_SERVICES },
  { type: HUB_EVENT_CONFIG },
];

export function ServicesPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ServicesResponse>("/services", {
    invalidateOn: INVALIDATE_ON,
  });
  const [services, setServices] = useState<PublishedService[]>([]);
  const [isDeclaring, setIsDeclaring] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setServices(resource.data.services);
    }
  }, [resource.data]);

  const handleChanged = (next: PublishedService[]) => {
    setServices(next);
    resource.setData({ services: next });
  };

  if (resource.error !== null && resource.data === null) {
    return (
      <div className="page">
        <h1>{t("ui.services.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (resource.data === null) {
    return (
      <div className="page">
        <h1>{t("ui.services.title")}</h1>
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
          <h1>{t("ui.services.title")}</h1>
          <span className="badge">
            {t("ui.services.badge", {
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
              {t("ui.services.declare")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t(GROUP_TITLE_KEYS[type])}</h2>
      </div>
      {services.length === 0 ? (
        <p className="field_hint faint">{t("ui.services.group_empty")}</p>
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tone: "ok" | "error" | "idle" =
    service.is_healthy === true
      ? "ok"
      : service.is_healthy === false
        ? "error"
        : "idle";
  // A declared row with no health but a code was measured and could not be
  // judged, which is not the same as one still waiting for its first probe.
  const declaredState =
    tone === "idle" && service.detail_code !== null ? "unchecked" : tone;
  const stateLabel = t(
    service.source === "module"
      ? MODULE_STATE_KEYS[tone === "idle" ? "error" : tone]
      : DECLARED_STATE_KEYS[declaredState],
  );
  const detailKey =
    service.detail_code === null
      ? undefined
      : DECLARED_DETAIL_KEYS[service.detail_code];

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
      title: t("ui.services.delete_title", { name: service.title }),
      body: t("ui.services.delete_body"),
      confirmLabel: t("ui.services.delete"),
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
        {detailKey !== undefined && (
          <span className="published_row_detail">{t(detailKey)}</span>
        )}
        {error !== null && <span className="field_error">{error}</span>}
      </div>
      <span className="published_row_state">{stateLabel}</span>
      <span className={`badge ${SOURCE_TONES[service.source]}`}>
        {t(SOURCE_KEYS[service.source])}
      </span>
      {service.record_id !== null && (
        <div className="published_row_actions">
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={isBusy}
            onClick={() => void handleProbe()}
          >
            <Icon name="bolt" size={13} />
            {t("ui.services.test")}
          </button>
          <button
            type="button"
            className="button button--ghost button--small button--danger"
            disabled={isBusy}
            onClick={handleDelete}
          >
            <Icon name="trash" size={13} />
            {t("ui.services.delete")}
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<DeclaredServiceCreate["kind"]>("web");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [scheme, setScheme] = useState("http");
  const [path, setPath] = useState("/");
  const [shares, setShares] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [scanNotice, setScanNotice] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isPortReady =
    port.trim().length === 0 ? kind === "file" : isValidPort(port.trim());
  const isReady =
    name.trim().length > 0 &&
    host.trim().length > 0 &&
    isPortReady &&
    (kind !== "file" || shares.length > 0);

  const handleScan = async () => {
    setIsScanning(true);
    setScanNotice(null);
    setScanError(null);
    try {
      const found = await apiGet<ServiceSharesResponse>(
        `/services/shares?host=${encodeURIComponent(host.trim())}`,
      );
      setShares((current) => [
        ...current,
        ...found.shares.filter((entry) => !current.includes(entry)),
      ]);
      if (found.shares.length === 0) {
        setScanNotice(t("ui.services.scan_empty"));
      }
    } catch (cause: unknown) {
      // A refused anonymous listing is a degradation, not a failure: the
      // share name is simply typed by hand.
      if (scanFailureReason(cause) === "list_refused") {
        setScanNotice(t("code.list_refused"));
      } else {
        setScanError(describeDeclaredError(cause));
      }
    } finally {
      setIsScanning(false);
    }
  };

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
      shares: kind === "file" ? shares : null,
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
      <div className="section_label">{t("ui.services.form_title")}</div>
      <div className="declared_form_row">
        <label className="field">
          <span className="field_label">{t("ui.services.field_name")}</span>
          <input
            className="input"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.services.field_kind")}</span>
          <select
            className="input"
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as DeclaredServiceCreate["kind"])
            }
          >
            {(Object.keys(KIND_KEYS) as DeclaredServiceCreate["kind"][]).map(
              (option) => (
                <option key={option} value={option}>
                  {t(KIND_KEYS[option])}
                </option>
              ),
            )}
          </select>
        </label>
      </div>
      <div className="declared_form_row">
        <label className="field">
          <span className="field_label">{t("ui.services.field_host")}</span>
          <input
            className="input"
            value={host}
            placeholder={HOST_PLACEHOLDER}
            spellCheck={false}
            onChange={(event) => setHost(event.target.value)}
          />
          <span className="field_hint">{t("ui.services.host_hint")}</span>
        </label>
        <label className="field">
          <span className="field_label">{t("ui.services.field_port")}</span>
          <input
            className="input"
            value={port}
            placeholder={kind === "file" ? FILE_PORT_PLACEHOLDER : ""}
            inputMode="numeric"
            onChange={(event) => setPort(event.target.value)}
          />
          {kind === "file" && (
            <span className="field_hint">
              {t("ui.services.port_hint_file")}
            </span>
          )}
        </label>
      </div>
      {kind === "web" && (
        <div className="declared_form_row">
          <label className="field">
            <span className="field_label">{t("ui.services.field_scheme")}</span>
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
            <span className="field_label">{t("ui.services.field_path")}</span>
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
        <div className="declared_shares">
          <StringListEditor
            label={t("ui.services.field_shares")}
            values={shares}
            onChange={setShares}
            description={t("ui.services.shares_hint")}
            placeholder={SHARES_PLACEHOLDER}
            emptyText={t("ui.services.shares_empty")}
          />
          <div className="declared_shares_scan">
            <button
              type="button"
              className="button button--ghost button--small"
              disabled={host.trim().length === 0 || isScanning}
              onClick={() => void handleScan()}
            >
              <Icon name="refresh" size={12} />
              {isScanning ? t("ui.services.scanning") : t("ui.services.scan")}
            </button>
            {scanNotice !== null && (
              <span className="field_hint">{scanNotice}</span>
            )}
            {scanError !== null && (
              <span className="field_error">{scanError}</span>
            )}
          </div>
        </div>
      )}
      <label className="field">
        <span className="field_label">
          {t("ui.services.field_description")}
        </span>
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
          {t("ui.services.cancel")}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? t("ui.services.saving") : t("ui.services.save")}
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

/** The reason inside a failed share scan, or null for any other failure. */
function scanFailureReason(cause: unknown): string | null {
  if (
    cause instanceof ApiError &&
    typeof cause.detail === "object" &&
    cause.detail !== null
  ) {
    const detail = cause.detail as Record<string, unknown>;
    if (detail.code === "share_scan_failed") {
      const params = (detail.params ?? {}) as Record<string, unknown>;
      return String(params.reason ?? "");
    }
  }
  return null;
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
      return t("code.declared_service_unknown");
    }
    if (detail.code === "declared_service_invalid") {
      const params = (detail.params ?? {}) as Record<string, unknown>;
      const key = DECLARED_INVALID_KEYS[String(params.field)];
      if (key !== undefined) {
        return t(key);
      }
    }
    if (detail.code === "share_scan_failed") {
      const params = (detail.params ?? {}) as Record<string, unknown>;
      const key = DECLARED_DETAIL_KEYS[String(params.reason)];
      if (key !== undefined) {
        return t(key);
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
