import { useContext, useEffect, useState } from "react";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ModuleCard } from "../components/module_card";
import { InstallConsentModal } from "../components/install_consent_modal";
import { apiGet, apiPost, describeError } from "../api_client";
import { ModulesContext } from "../modules_context";
import type {
  ModuleActionName,
  ModuleInstallPlanView,
  ModuleView,
  TaskListResponse,
} from "../api_types";

import "./modules_page.css";

/**
 * The systemd units that make up the gateway — what is installed on the hub.
 *
 * Split the way the sidebar is. Core is what makes this a gateway and cannot
 * be turned off; Optional is what it also happens to host, each off until
 * asked for. Enabling an optional module is what makes its page appear.
 *
 * The list itself is the shell's shared copy, and every action's result is
 * folded back into it — that shared write is what moves the sidebar in the
 * same render as the card.
 */

const WORDING = {
  title: "Modules",
  runningBadge: "{active} of {total} running",
  coreTitle: "Core",
  coreHint: "Required for routing; state and logs only, no off switch.",
  optionalTitle: "Optional",
  optionalHint: "Off by default; enabling one adds its page to the sidebar.",
};

const REFRESH_INTERVAL_MS = 5000;

export function ModulesPage() {
  const resource = useContext(ModulesContext);

  const [modules, setModules] = useState<ModuleView[]>([]);
  const [openJournals, setOpenJournals] = useState<string[]>([]);
  const [busyModules, setBusyModules] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  // Install/uninstall task ids by module name. Kept after finishing so the
  // log stays readable; replaced when the next task starts.
  const [tasks, setTasks] = useState<Record<string, string>>({});
  // The module whose install is waiting on a person, with what it would do.
  const [pendingConsent, setPendingConsent] =
    useState<ModuleInstallPlanView | null>(null);

  useEffect(() => {
    if (resource?.data != null) {
      setModules(resource.data.modules);
    }
  }, [resource?.data]);

  // A task id lives in the browser and the job it names does not, so a reload
  // during an install used to leave the module reading "not installed" with a
  // live Install button beside a package manager still running. The panel is
  // asked what it is doing instead.
  useEffect(() => {
    let isMounted = true;
    void apiGet<TaskListResponse>("/modules/tasks")
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
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const handleAction = async (name: string, action: ModuleActionName) => {
    setActionError(null);
    setBusyModules((current) => [...current, name]);
    try {
      const updated = await apiPost<ModuleView>(`/modules/${name}/${action}`);
      const merge = (current: ModuleView[]) =>
        current.map((module) => (module.name === name ? updated : module));
      setModules(merge);
      // Into the shared copy too, so the sidebar sees the change now.
      if (resource?.data != null) {
        resource.setData({
          ...resource.data,
          modules: merge(resource.data.modules),
        });
      }
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setBusyModules((current) => current.filter((item) => item !== name));
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
      const plan = await apiGet<ModuleInstallPlanView>(
        `/modules/${name}/install_plan`,
      );
      if (plan.is_consent_needed) {
        setPendingConsent(plan);
        return;
      }
    } catch (cause: unknown) {
      setActionError(describeError(cause));
      return;
    }
    await startTask(name, `/modules/${name}/install`, { is_consented: false });
  };

  const handleConsented = async () => {
    const plan = pendingConsent;
    setPendingConsent(null);
    if (plan === null) {
      return;
    }
    await startTask(plan.name, `/modules/${plan.name}/install`, {
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

  if (resource !== null && resource.error !== null && modules.length === 0) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  const activeCount = modules.filter((module) => module.is_active).length;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{WORDING.title}</h1>
          {/* A count, not a description: it changes, so it earns its place
              beside the title rather than being repeated prose. */}
          <span className="badge">
            {fill(WORDING.runningBadge, {
              active: activeCount,
              total: modules.length,
            })}
          </span>
        </div>
      </div>

      {actionError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{actionError}</div>
        </div>
      )}

      {resource?.isLoading === true && modules.length === 0 ? (
        <div className="modules_grid">
          <div className="skeleton" style={{ height: 160 }} />
          <div className="skeleton" style={{ height: 160 }} />
          <div className="skeleton" style={{ height: 160 }} />
        </div>
      ) : (
        <>
          <ModuleSection
            title={WORDING.coreTitle}
            hint={WORDING.coreHint}
            modules={modules.filter((module) => module.is_core)}
            busyModules={busyModules}
            openJournals={openJournals}
            tasks={tasks}
            onAction={handleAction}
            onToggleJournal={handleToggleJournal}
            onInstall={(name) => void handleInstall(name)}
            onUninstall={(name, isDataKept) =>
              void startTask(name, `/modules/${name}/uninstall`, {
                is_data_kept: isDataKept,
              })
            }
            onTaskFinished={handleTaskFinished}
            onDismissTask={handleDismissTask}
          />
          <ModuleSection
            title={WORDING.optionalTitle}
            hint={WORDING.optionalHint}
            modules={modules.filter((module) => !module.is_core)}
            busyModules={busyModules}
            openJournals={openJournals}
            tasks={tasks}
            onAction={handleAction}
            onToggleJournal={handleToggleJournal}
            onInstall={(name) => void handleInstall(name)}
            onUninstall={(name, isDataKept) =>
              void startTask(name, `/modules/${name}/uninstall`, {
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

interface ModuleSectionProps {
  title: string;
  hint: string;
  modules: ModuleView[];
  busyModules: string[];
  openJournals: string[];
  tasks: Record<string, string>;
  onAction: (name: string, action: ModuleActionName) => void;
  onToggleJournal: (name: string) => void;
  onInstall: (name: string) => void;
  onUninstall: (name: string, isDataKept: boolean) => void;
  onTaskFinished: () => void;
  onDismissTask: (name: string) => void;
}

function ModuleSection({
  title,
  hint,
  modules,
  busyModules,
  openJournals,
  tasks,
  onAction,
  onToggleJournal,
  onInstall,
  onUninstall,
  onTaskFinished,
  onDismissTask,
}: ModuleSectionProps) {
  if (modules.length === 0) {
    return null;
  }
  const runningCount = modules.filter((module) => module.is_active).length;
  return (
    <section className="modules_section">
      <div className="settings_group_title">
        <h2>{title}</h2>
        <span className="badge">
          {fill(WORDING.runningBadge, {
            active: runningCount,
            total: modules.length,
          })}
        </span>
      </div>
      <p className="field_hint">{hint}</p>
      <div className="modules_grid">
        {modules.map((module) => (
          <ModuleCard
            key={module.name}
            module={module}
            isBusy={busyModules.includes(module.name)}
            isJournalOpen={openJournals.includes(module.name)}
            taskId={tasks[module.name] ?? null}
            onAction={(action) => onAction(module.name, action)}
            onToggleJournal={() => onToggleJournal(module.name)}
            onInstall={() => onInstall(module.name)}
            onUninstall={(isDataKept) => onUninstall(module.name, isDataKept)}
            onTaskFinished={() => onTaskFinished()}
            onDismissTask={() => onDismissTask(module.name)}
          />
        ))}
      </div>
    </section>
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
