import { useContext, useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ServiceCard } from "../components/service_card";
import { InstallConsentModal } from "../components/install_consent_modal";
import { StatusDot } from "../components/status_dot";
import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  describeError,
} from "../api_client";
import { ServicesContext } from "../services_context";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type {
  DeclaredServiceCreate,
  DeclaredServiceKind,
  DeclaredServiceProbeView,
  DeclaredServiceView,
  DeclaredShareView,
  ServiceAccountsResponse,
  ServiceActionName,
  ServiceInstallPlanView,
  ServiceView,
  TaskListResponse,
} from "../api_types";

import "./services_page.css";

/**
 * The systemd units that make up the gateway.
 *
 * Split the way the sidebar is. Core is what makes this a gateway and cannot
 * be turned off; Optional is what it also happens to host, each off until
 * asked for. Enabling an optional service is what makes its page appear.
 *
 * The list itself is the shell's shared copy, and every action's result is
 * folded back into it — that shared write is what moves the sidebar in the
 * same render as the card.
 *
 * The Declared section below the units is the other kind of service: one
 * running on a machine the hub does not manage, declared here so the hub can
 * watch it. The same shared copy carries those too.
 */

// What the Declared section says, all of it, so it can be translated.
const DECLARED_TITLE = "Declared";
const DECLARED_HINT =
  "Services on machines the hub does not run, declared here and watched.";
const DECLARED_BADGE = "{healthy} of {total} healthy";
const DECLARED_ADD_LABEL = "Declare service";
const DECLARED_EMPTY = "Nothing is declared yet.";
const DECLARED_FORM_NEW = "New declared service";
const DECLARED_FORM_EDIT = "Edit {name}";
const DECLARED_FIELD_NAME = "Name";
const DECLARED_FIELD_KIND = "Kind";
const DECLARED_FIELD_HOST = "Host";
const DECLARED_FIELD_PORT = "Port";
const DECLARED_FIELD_SCHEME = "Scheme";
const DECLARED_FIELD_PATH = "Path";
const DECLARED_PORT_HINT = "Left blank, a Samba service gets 445.";
const DECLARED_SHARES_LABEL = "Shares";
const DECLARED_SHARES_HINT =
  "Each share may name a service account devices sign in with.";
const DECLARED_SHARE_NAME_PLACEHOLDER = "share name";
const DECLARED_SHARE_GUEST_OPTION = "guest (no account)";
const DECLARED_ADD_SHARE_LABEL = "Add share";
const DECLARED_SHARE_COUNT = "{count} share(s)";
const DECLARED_SAVE_LABEL = "Save service";
const DECLARED_SAVING_LABEL = "Saving…";
const DECLARED_CANCEL_LABEL = "Cancel";
const DECLARED_PROBE_LABEL = "Probe";
const DECLARED_EDIT_LABEL = "Edit";
const DECLARED_DELETE_LABEL = "Delete";
const DECLARED_DELETE_TITLE = "Delete {name}";
const DECLARED_DELETE_BODY =
  "The declaration is removed; the machine it points at is untouched.";

const DECLARED_KIND_LABELS: Record<DeclaredServiceKind, string> = {
  samba: "Samba",
  http: "HTTP",
  docker_engine: "Docker engine",
  generic_tcp: "TCP",
};

const DECLARED_STATE_LABELS: Record<"ok" | "error" | "idle", string> = {
  ok: "healthy",
  error: "unreachable",
  idle: "not probed",
};

// The probe's detail_code, worded.
const DECLARED_DETAIL_WORDING: Record<string, string> = {
  connect_failed: "Nothing answered the connection.",
  ping_rejected: "Answered, but not as a Docker engine.",
  server_error: "Answered with a server error.",
};

// The API's declared_service_invalid params.field, worded.
const DECLARED_INVALID_WORDING: Record<string, string> = {
  kind: "The kind is not one the hub knows.",
  name: "The service needs a name.",
  host: "The service needs a host.",
  port: "The port is a number from 1 to 65535.",
  scheme: "The scheme is http or https.",
  path: "The path starts with a slash.",
  shares: "Each share needs a name of its own.",
  service_account_id: "A share names a service account that is gone.",
};
const DECLARED_UNKNOWN_WORDING = "That service is already gone; reload.";

export function ServicesPage() {
  const resource = useContext(ServicesContext);

  const [services, setServices] = useState<ServiceView[]>([]);
  const [declared, setDeclared] = useState<DeclaredServiceView[]>([]);
  const [openJournals, setOpenJournals] = useState<string[]>([]);
  const [busyServices, setBusyServices] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  // Install/uninstall task ids by service name. Kept after finishing so the
  // log stays readable; replaced when the next task starts.
  const [tasks, setTasks] = useState<Record<string, string>>({});
  // The module whose install is waiting on a person, with what it would do.
  const [pendingConsent, setPendingConsent] =
    useState<ServiceInstallPlanView | null>(null);

  useEffect(() => {
    if (resource?.data != null) {
      setServices(resource.data.services);
      setDeclared(resource.data.declared);
    }
  }, [resource?.data]);

  // A task id lives in the browser and the job it names does not, so a reload
  // during an install used to leave the module reading "not installed" with a
  // live Install button beside a package manager still running. The panel is
  // asked what it is doing instead.
  useEffect(() => {
    let isMounted = true;
    void apiGet<TaskListResponse>("/services/tasks")
      .then((response) => {
        if (!isMounted) {
          return;
        }
        const adopted: Record<string, string> = {};
        for (const task of response.tasks) {
          const [verb, name] = task.label.split(" ");
          if (
            name !== undefined &&
            (verb === "install" || verb === "uninstall")
          ) {
            adopted[name] = task.id;
          }
        }
        setTasks((current) => ({ ...adopted, ...current }));
      })
      .catch(() => undefined);
    return () => {
      isMounted = false;
    };
  }, []);

  const reload = resource?.reload;
  useEffect(() => {
    if (reload === undefined) {
      return;
    }
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const handleAction = async (name: string, action: ServiceActionName) => {
    setActionError(null);
    setBusyServices((current) => [...current, name]);
    try {
      const updated = await apiPost<ServiceView>(`/services/${name}/${action}`);
      const merge = (current: ServiceView[]) =>
        current.map((service) => (service.name === name ? updated : service));
      setServices(merge);
      // Into the shared copy too, so the sidebar sees the change now.
      if (resource?.data != null) {
        resource.setData({
          ...resource.data,
          services: merge(resource.data.services),
        });
      }
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyServices((current) => current.filter((item) => item !== name));
    }
  };

  const handleToggleJournal = (name: string) => {
    setOpenJournals((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  };

  const startTask = async (name: string, path: string, body?: unknown) => {
    setActionError(null);
    try {
      const started = await apiPost<{ task_id: string }>(path, body);
      setTasks((current) => ({ ...current, [name]: started.task_id }));
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    }
  };

  // Installing asks the module what it would do before it does it. A module
  // that only installs packages says nothing and the install starts; one that
  // would compile a kernel module or add a repository outside the
  // distribution puts that in front of a person first.
  const handleInstall = async (name: string) => {
    setActionError(null);
    try {
      const plan = await apiGet<ServiceInstallPlanView>(
        `/services/${name}/install_plan`,
      );
      if (plan.is_consent_needed) {
        setPendingConsent(plan);
        return;
      }
    } catch (cause: unknown) {
      setActionError(describeError(cause));
      return;
    }
    await startTask(name, `/services/${name}/install`, { is_consented: false });
  };

  const handleConsented = async () => {
    const plan = pendingConsent;
    setPendingConsent(null);
    if (plan === null) {
      return;
    }
    await startTask(plan.name, `/services/${plan.name}/install`, {
      is_consented: true,
    });
  };

  const handleDismissTask = (name: string) => {
    setTasks(({ [name]: _, ...rest }) => rest);
  };

  const handleDeclaredChanged = (next: DeclaredServiceView[]) => {
    setDeclared(next);
    // Into the shared copy too, so the next poll starts from this state.
    if (resource?.data != null) {
      resource.setData({ ...resource.data, declared: next });
    }
  };

  const handleTaskFinished = () => {
    // The log stays on screen; reality is refetched so the card, the other
    // cards, and the sidebar all catch up with what the task did.
    resource?.reload();
  };

  if (resource !== null && resource.error !== null && services.length === 0) {
    return (
      <div className="page">
        <h1>Services</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  const activeCount = services.filter((service) => service.is_active).length;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>Services</h1>
          {/* A count, not a description: it changes, so it earns its place
              beside the title rather than being repeated prose. */}
          <span className="badge">
            {activeCount} of {services.length} running
          </span>
        </div>
      </div>

      {actionError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{actionError}</div>
        </div>
      )}

      {resource?.isLoading === true && services.length === 0 ? (
        <div className="services_grid">
          <div className="skeleton" style={{ height: 160 }} />
          <div className="skeleton" style={{ height: 160 }} />
          <div className="skeleton" style={{ height: 160 }} />
        </div>
      ) : (
        <>
          <ServiceSection
            title="Core"
            hint="Required for routing; state and logs only, no off switch."
            services={services.filter((service) => service.is_core)}
            busyServices={busyServices}
            openJournals={openJournals}
            tasks={tasks}
            onAction={handleAction}
            onToggleJournal={handleToggleJournal}
            onInstall={(name) => void handleInstall(name)}
            onUninstall={(name, isDataKept) =>
              void startTask(name, `/services/${name}/uninstall`, {
                is_data_kept: isDataKept,
              })
            }
            onTaskFinished={handleTaskFinished}
            onDismissTask={handleDismissTask}
          />
          <ServiceSection
            title="Optional"
            hint="Off by default; enabling one adds its page to the sidebar."
            services={services.filter((service) => !service.is_core)}
            busyServices={busyServices}
            openJournals={openJournals}
            tasks={tasks}
            onAction={handleAction}
            onToggleJournal={handleToggleJournal}
            onInstall={(name) => void handleInstall(name)}
            onUninstall={(name, isDataKept) =>
              void startTask(name, `/services/${name}/uninstall`, {
                is_data_kept: isDataKept,
              })
            }
            onTaskFinished={handleTaskFinished}
            onDismissTask={handleDismissTask}
          />
          <DeclaredSection
            declared={declared}
            onChanged={handleDeclaredChanged}
          />
        </>
      )}
      {pendingConsent !== null && (
        <InstallConsentModal
          name={pendingConsent.name}
          consents={pendingConsent.consents}
          onConfirm={() => void handleConsented()}
          onCancel={() => setPendingConsent(null)}
        />
      )}
    </div>
  );
}

interface ServiceSectionProps {
  title: string;
  hint: string;
  services: ServiceView[];
  busyServices: string[];
  openJournals: string[];
  tasks: Record<string, string>;
  onAction: (name: string, action: ServiceActionName) => void;
  onToggleJournal: (name: string) => void;
  onInstall: (name: string) => void;
  onUninstall: (name: string, isDataKept: boolean) => void;
  onTaskFinished: () => void;
  onDismissTask: (name: string) => void;
}

function ServiceSection({
  title,
  hint,
  services,
  busyServices,
  openJournals,
  tasks,
  onAction,
  onToggleJournal,
  onInstall,
  onUninstall,
  onTaskFinished,
  onDismissTask,
}: ServiceSectionProps) {
  if (services.length === 0) {
    return null;
  }
  const runningCount = services.filter((service) => service.is_active).length;
  return (
    <section className="services_section">
      <div className="settings_group_title">
        <h2>{title}</h2>
        <span className="badge">
          {runningCount} of {services.length} running
        </span>
      </div>
      <p className="field_hint">{hint}</p>
      <div className="services_grid">
        {services.map((service) => (
          <ServiceCard
            key={service.name}
            service={service}
            isBusy={busyServices.includes(service.name)}
            isJournalOpen={openJournals.includes(service.name)}
            taskId={tasks[service.name] ?? null}
            onAction={(action) => onAction(service.name, action)}
            onToggleJournal={() => onToggleJournal(service.name)}
            onInstall={() => onInstall(service.name)}
            onUninstall={(isDataKept) => onUninstall(service.name, isDataKept)}
            onTaskFinished={() => onTaskFinished()}
            onDismissTask={() => onDismissTask(service.name)}
          />
        ))}
      </div>
    </section>
  );
}

interface DeclaredSectionProps {
  declared: DeclaredServiceView[];
  onChanged: (declared: DeclaredServiceView[]) => void;
}

function DeclaredSection({ declared, onChanged }: DeclaredSectionProps) {
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const handleSaved = (saved: DeclaredServiceView) => {
    const exists = declared.some((service) => service.id === saved.id);
    onChanged(
      exists
        ? declared.map((service) => (service.id === saved.id ? saved : service))
        : [saved, ...declared],
    );
    setIsAdding(false);
    setEditingId(null);
  };

  const handleDeleted = (serviceId: string) => {
    onChanged(declared.filter((service) => service.id !== serviceId));
  };

  const handleProbed = (serviceId: string, probe: DeclaredServiceProbeView) => {
    onChanged(
      declared.map((service) =>
        service.id === serviceId ? { ...service, probe } : service,
      ),
    );
  };

  const healthyCount = declared.filter(
    (service) => service.probe.is_healthy === true,
  ).length;

  return (
    <section className="services_section">
      <div className="settings_group_title">
        <h2>{DECLARED_TITLE}</h2>
        <span className="badge">
          {fill(DECLARED_BADGE, {
            healthy: healthyCount,
            total: declared.length,
          })}
        </span>
        {!isAdding && (
          <button
            type="button"
            className="button declared_section_action"
            onClick={() => setIsAdding(true)}
          >
            <Icon name="plus" size={14} />
            {DECLARED_ADD_LABEL}
          </button>
        )}
      </div>
      <p className="field_hint">{DECLARED_HINT}</p>

      {isAdding && (
        <DeclaredServiceForm
          onSaved={handleSaved}
          onCancel={() => setIsAdding(false)}
        />
      )}

      {declared.length === 0 && !isAdding ? (
        <p className="field_hint faint">{DECLARED_EMPTY}</p>
      ) : (
        <div className="services_grid">
          {declared.map((service) =>
            editingId === service.id ? (
              <DeclaredServiceForm
                key={service.id}
                initial={service}
                onSaved={handleSaved}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <DeclaredServiceCard
                key={service.id}
                service={service}
                onEdit={() => setEditingId(service.id)}
                onDeleted={handleDeleted}
                onProbed={handleProbed}
              />
            ),
          )}
        </div>
      )}
    </section>
  );
}

interface DeclaredServiceFormProps {
  initial?: DeclaredServiceView;
  onSaved: (service: DeclaredServiceView) => void;
  onCancel: () => void;
}

function DeclaredServiceForm({
  initial,
  onSaved,
  onCancel,
}: DeclaredServiceFormProps) {
  const accounts = useApiResource<ServiceAccountsResponse>(
    "/credentials/service_accounts",
  );
  const [name, setName] = useState(initial?.name ?? "");
  const [kind, setKind] = useState<DeclaredServiceKind>(
    initial?.kind ?? "samba",
  );
  const [host, setHost] = useState(initial?.host ?? "");
  const [port, setPort] = useState(
    initial !== undefined ? String(initial.port) : "",
  );
  const [scheme, setScheme] = useState(initial?.scheme ?? "http");
  const [path, setPath] = useState(initial?.path ?? "/");
  const [shares, setShares] = useState<DeclaredShareView[]>(
    initial?.shares ?? [],
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEditing = initial !== undefined;
  const isPortReady =
    port.trim().length === 0 ? kind === "samba" : isValidPort(port.trim());
  const isReady =
    name.trim().length > 0 && host.trim().length > 0 && isPortReady;

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    const payload: DeclaredServiceCreate = {
      name: name.trim(),
      kind,
      host: host.trim(),
      port: port.trim().length > 0 ? Number(port.trim()) : null,
      scheme: kind === "http" ? scheme : null,
      path: kind === "http" ? path.trim() : null,
      shares:
        kind === "samba"
          ? shares.map((share) => ({
              name: share.name.trim(),
              service_account_id: share.service_account_id,
            }))
          : [],
    };
    try {
      const saved = isEditing
        ? await apiPut<DeclaredServiceView>(
            `/services/declared/${initial.id}`,
            payload,
          )
        : await apiPost<DeclaredServiceView>("/services/declared", payload);
      onSaved(saved);
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  const handleShareChanged = (index: number, share: DeclaredShareView) => {
    setShares((current) =>
      current.map((existing, at) => (at === index ? share : existing)),
    );
  };

  const handleShareRemoved = (index: number) => {
    setShares((current) => current.filter((_, at) => at !== index));
  };

  return (
    <div className="declared_form">
      <div className="section_label">
        {isEditing
          ? fill(DECLARED_FORM_EDIT, { name: initial.name })
          : DECLARED_FORM_NEW}
      </div>
      <div className="declared_form_row">
        <label className="field">
          <span className="field_label">{DECLARED_FIELD_NAME}</span>
          <input
            className="input"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{DECLARED_FIELD_KIND}</span>
          <select
            className="input"
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as DeclaredServiceKind)
            }
          >
            {(Object.keys(DECLARED_KIND_LABELS) as DeclaredServiceKind[]).map(
              (option) => (
                <option key={option} value={option}>
                  {DECLARED_KIND_LABELS[option]}
                </option>
              ),
            )}
          </select>
        </label>
      </div>
      <div className="declared_form_row">
        <label className="field">
          <span className="field_label">{DECLARED_FIELD_HOST}</span>
          <input
            className="input"
            value={host}
            placeholder="192.168.100.7"
            spellCheck={false}
            onChange={(event) => setHost(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{DECLARED_FIELD_PORT}</span>
          <input
            className="input"
            value={port}
            placeholder={kind === "samba" ? "445" : ""}
            inputMode="numeric"
            onChange={(event) => setPort(event.target.value)}
          />
          {kind === "samba" && (
            <span className="field_hint">{DECLARED_PORT_HINT}</span>
          )}
        </label>
      </div>
      {kind === "http" && (
        <div className="declared_form_row">
          <label className="field">
            <span className="field_label">{DECLARED_FIELD_SCHEME}</span>
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
            <span className="field_label">{DECLARED_FIELD_PATH}</span>
            <input
              className="input"
              value={path}
              spellCheck={false}
              onChange={(event) => setPath(event.target.value)}
            />
          </label>
        </div>
      )}
      {kind === "samba" && (
        <div className="field">
          <span className="field_label">{DECLARED_SHARES_LABEL}</span>
          {shares.map((share, index) => (
            <div key={index} className="declared_share_row">
              <input
                className="input"
                value={share.name}
                placeholder={DECLARED_SHARE_NAME_PLACEHOLDER}
                spellCheck={false}
                onChange={(event) =>
                  handleShareChanged(index, {
                    ...share,
                    name: event.target.value,
                  })
                }
              />
              <select
                className="input"
                value={share.service_account_id ?? ""}
                onChange={(event) =>
                  handleShareChanged(index, {
                    ...share,
                    service_account_id:
                      event.target.value.length > 0 ? event.target.value : null,
                  })
                }
              >
                <option value="">{DECLARED_SHARE_GUEST_OPTION}</option>
                {(accounts.data?.service_accounts ?? []).map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} ({account.username})
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => handleShareRemoved(index)}
              >
                <Icon name="trash" size={13} />
              </button>
            </div>
          ))}
          <div>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() =>
                setShares((current) => [
                  ...current,
                  { name: "", service_account_id: null },
                ])
              }
            >
              <Icon name="plus" size={13} />
              {DECLARED_ADD_SHARE_LABEL}
            </button>
          </div>
          <span className="field_hint">{DECLARED_SHARES_HINT}</span>
        </div>
      )}
      {error !== null && <span className="field_error">{error}</span>}
      <div className="declared_form_actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={onCancel}
        >
          {DECLARED_CANCEL_LABEL}
        </button>
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isSaving}
          onClick={() => void handleSubmit()}
        >
          <Icon name="check" size={14} />
          {isSaving ? DECLARED_SAVING_LABEL : DECLARED_SAVE_LABEL}
        </button>
      </div>
    </div>
  );
}

interface DeclaredServiceCardProps {
  service: DeclaredServiceView;
  onEdit: () => void;
  onDeleted: (serviceId: string) => void;
  onProbed: (serviceId: string, probe: DeclaredServiceProbeView) => void;
}

function DeclaredServiceCard({
  service,
  onEdit,
  onDeleted,
  onProbed,
}: DeclaredServiceCardProps) {
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleProbe = async () => {
    setIsBusy(true);
    setError(null);
    try {
      const probe = await apiPost<DeclaredServiceProbeView>(
        `/services/declared/${service.id}/probe`,
      );
      onProbed(service.id, probe);
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const deleteService = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiDelete(`/services/declared/${service.id}`);
      onDeleted(service.id);
    } catch (cause: unknown) {
      setError(describeDeclaredError(cause));
      setIsBusy(false);
    }
  };

  const handleDelete = () =>
    confirm.ask({
      title: fill(DECLARED_DELETE_TITLE, { name: service.name }),
      body: DECLARED_DELETE_BODY,
      confirmLabel: DECLARED_DELETE_LABEL,
      onConfirm: () => void deleteService(),
    });

  const tone: "ok" | "error" | "idle" =
    service.probe.is_healthy === true
      ? "ok"
      : service.probe.is_healthy === false
        ? "error"
        : "idle";
  const detail =
    service.probe.detail_code !== null
      ? DECLARED_DETAIL_WORDING[service.probe.detail_code]
      : undefined;

  return (
    <div className="declared_card">
      <div className="declared_card_head">
        <StatusDot tone={tone} />
        <span className="declared_card_name">{service.name}</span>
        <span className="declared_kind">
          {DECLARED_KIND_LABELS[service.kind]}
        </span>
      </div>
      <div className="declared_card_address">{declaredAddress(service)}</div>
      <div className="declared_card_meta">
        <span className="muted">{DECLARED_STATE_LABELS[tone]}</span>
        {service.kind === "samba" && (
          <span className="muted">
            {fill(DECLARED_SHARE_COUNT, { count: service.shares.length })}
          </span>
        )}
      </div>
      {detail !== undefined && <span className="field_hint">{detail}</span>}
      {error !== null && <span className="field_error">{error}</span>}
      <div className="declared_card_actions">
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={isBusy}
          onClick={() => void handleProbe()}
        >
          <Icon name="bolt" size={13} />
          {DECLARED_PROBE_LABEL}
        </button>
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={isBusy}
          onClick={onEdit}
        >
          <Icon name="edit" size={13} />
          {DECLARED_EDIT_LABEL}
        </button>
        <button
          type="button"
          className="button button--ghost button--small button--danger"
          disabled={isBusy}
          onClick={handleDelete}
        >
          <Icon name="trash" size={13} />
          {DECLARED_DELETE_LABEL}
        </button>
      </div>
      {confirm.modal}
    </div>
  );
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

function isValidPort(value: string): boolean {
  if (!/^\d{1,5}$/.test(value)) {
    return false;
  }
  const port = Number(value);
  return port >= 1 && port <= 65535;
}

function declaredAddress(service: DeclaredServiceView): string {
  if (service.kind === "http") {
    return `${service.scheme}://${service.host}:${service.port}${service.path ?? ""}`;
  }
  return `${service.host}:${service.port}`;
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
