import { useContext, useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ServiceCard } from "../components/service_card";
import { InstallConsentModal } from "../components/install_consent_modal";
import { apiGet, apiPost, describeError } from "../api_client";
import { ServicesContext } from "../services_context";
import type {
  ServiceActionName,
  ServiceInstallPlanView,
  ServiceView,
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
 */

export function ServicesPage() {
  const resource = useContext(ServicesContext);

  const [services, setServices] = useState<ServiceView[]>([]);
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
    }
  }, [resource?.data]);

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
        resource.setData({ services: merge(resource.data.services) });
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
        `/services/${name}/install-plan`,
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
