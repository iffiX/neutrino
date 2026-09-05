import { useEffect, useState } from "react";

import { Icon } from "./icon";
import { JournalPanel } from "./journal_panel";
import { StatusDot } from "./status_dot";
import { stripAnsi } from "../strip_ansi";
import { useTaskStream } from "../use_task_stream";
import type { TaskStreamState } from "../use_task_stream";
import type { ModuleActionName, ModuleView } from "../api_types";

import "./module_card.css";

/**
 * One systemd unit the gateway manages.
 *
 * Two states matter for each and are easy to conflate, so both are always
 * shown: whether it is running now, and whether it comes back after a reboot.
 *
 * A core unit has no Stop and no Disable. The gateway does not route without
 * it, so those buttons would only ever be a way to break the box — and the API
 * refuses them too, because the panel is not the only thing that can ask.
 *
 * Installable modules add Install and Uninstall, both running as streamed
 * background jobs whose log appears in the card. Uninstalling keeps the
 * module's data unless the red checkbox surrenders it — and that checkbox
 * demands the module's name typed back, because "delete every repository" is
 * a sentence someone should have to finish.
 */

interface ModuleCardProps {
  module: ModuleView;
  isBusy: boolean;
  isJournalOpen: boolean;
  /** The task streaming for this module, or null. */
  taskId: string | null;
  onAction: (action: ModuleActionName) => void;
  onToggleJournal: () => void;
  onInstall: () => void;
  onUninstall: (isDataKept: boolean) => void;
  /** Called once a task finishes, so the page refetches reality. */
  onTaskFinished: () => void;
  /** Called when the finished task's log is closed by hand. */
  onDismissTask: () => void;
}

export function ModuleCard({
  module,
  isBusy,
  isJournalOpen,
  taskId,
  onAction,
  onToggleJournal,
  onInstall,
  onUninstall,
  onTaskFinished,
  onDismissTask,
}: ModuleCardProps) {
  const [isConfirmingRemoval, setIsConfirmingRemoval] = useState(false);
  // The stream lives here rather than in the log component, because the
  // card's buttons follow it: while a task runs they stand back, and the
  // moment it finishes they render for whatever reality the task left —
  // Install right below an uninstall's log. A page reload clears the log
  // and only the buttons remain.
  const task = useTaskStream(taskId);
  const [reportedTaskId, setReportedTaskId] = useState<string | null>(null);
  useEffect(() => {
    // A socket that gave up counts as finished here. Whatever the job did
    // before it dropped is on the box, and the list is the only thing that
    // says so.
    if (
      taskId !== null &&
      !task.isRunning &&
      (task.exitCode !== null || task.error !== null) &&
      reportedTaskId !== taskId
    ) {
      setReportedTaskId(taskId);
      onTaskFinished();
    }
  }, [
    taskId,
    task.isRunning,
    task.exitCode,
    task.error,
    reportedTaskId,
    onTaskFinished,
  ]);
  const isTaskRunning = taskId !== null && task.isRunning;

  return (
    <article
      key={module.name}
      className={`module_card ${
        !module.is_installed
          ? "module_card--missing"
          : module.is_active
            ? "module_card--active"
            : ""
      }`}
    >
      <div className="module_card_head">
        <div className="module_card_identity">
          <span className="module_card_name">
            <StatusDot
              tone={
                !module.is_installed
                  ? "idle"
                  : module.is_active
                    ? "ok"
                    : "error"
              }
              isPulsing={module.is_active}
            />
            {module.name}
          </span>
          <span className="module_card_unit">{module.unit}</span>
        </div>
        <div className="module_card_badges">
          {!module.is_installed ? (
            <span className="badge">not installed</span>
          ) : (
            <>
              <span
                className={`badge ${module.is_active ? "badge--ok" : "badge--error"}`}
              >
                {module.is_active ? "active" : "inactive"}
              </span>
              <span
                className={`badge ${module.is_enabled ? "badge--accent" : ""}`}
              >
                {module.is_enabled ? "enabled" : "disabled"}
              </span>
            </>
          )}
        </div>
      </div>

      {!module.is_installed && module.is_installable && !isTaskRunning && (
        <div className="module_card_install">
          <button
            type="button"
            className="button button--primary button--small"
            disabled={isBusy || !module.is_machine_supported}
            title={module.unsupported_reason ?? undefined}
            onClick={onInstall}
          >
            <Icon name="download" size={12} />
            Install
          </button>
          <span className="module_card_note">
            {module.is_machine_supported
              ? module.install_note
              : module.unsupported_reason}
          </span>
        </div>
      )}

      {module.is_installed && (
        <div className="module_card_actions">
          <button
            type="button"
            className="button button--small"
            disabled={isBusy || module.is_active}
            onClick={() => void onAction("start")}
          >
            <Icon name="play" size={12} />
            Start
          </button>
          {/* Core units have no Stop or Disable: the gateway does
                not route without them, so offering it would only be
                offering a way to break the box. */}
          {!module.is_core && (
            <button
              type="button"
              className="button button--small"
              disabled={isBusy || !module.is_active}
              onClick={() => void onAction("stop")}
            >
              <Icon name="stop" size={12} />
              Stop
            </button>
          )}
          <button
            type="button"
            className="button button--small"
            disabled={isBusy}
            onClick={() => void onAction("restart")}
          >
            <Icon name="refresh" size={12} />
            Restart
          </button>
          {/* Enabling a core unit is still offered when something has left one
              disabled, because that is a way back rather than a way out. */}
          {(!module.is_core || !module.is_enabled) && (
            <button
              type="button"
              className="button button--small"
              disabled={isBusy}
              onClick={() =>
                void onAction(module.is_enabled ? "disable" : "enable")
              }
            >
              <Icon name="power" size={12} />
              {module.is_enabled ? "Disable" : "Enable"}
            </button>
          )}
          {!module.is_core && module.is_installable && (
            <button
              type="button"
              className="button button--ghost button--small module_card_remove"
              disabled={isBusy || isTaskRunning}
              onClick={() => setIsConfirmingRemoval((current) => !current)}
            >
              <Icon name="trash" size={12} />
              Uninstall
            </button>
          )}
          <button
            type="button"
            className="button button--ghost button--small module_card_journal_toggle"
            onClick={() => onToggleJournal()}
          >
            <Icon
              name={isJournalOpen ? "chevron_down" : "chevron_right"}
              size={12}
            />
            Journal
          </button>
        </div>
      )}

      {isConfirmingRemoval && !isTaskRunning && (
        <UninstallConfirm
          module={module}
          onCancel={() => setIsConfirmingRemoval(false)}
          onConfirm={(isDataKept) => {
            setIsConfirmingRemoval(false);
            onUninstall(isDataKept);
          }}
        />
      )}

      {taskId !== null && <TaskLog task={task} onDismiss={onDismissTask} />}

      <JournalPanel
        moduleName={module.name}
        isOpen={module.is_installed && isJournalOpen}
      />
    </article>
  );
}

interface UninstallConfirmProps {
  module: ModuleView;
  onCancel: () => void;
  onConfirm: (isDataKept: boolean) => void;
}

function UninstallConfirm({
  module,
  onCancel,
  onConfirm,
}: UninstallConfirmProps) {
  const [isDeletingData, setIsDeletingData] = useState(false);
  const [typedName, setTypedName] = useState("");

  // Deleting data must be typed out; merely removing the software must not.
  const isArmed = !isDeletingData || typedName === module.name;

  return (
    <div className="module_card_confirm">
      <p className="module_card_note">
        Removes the software; configuration is kept.
      </p>
      <label className="module_card_confirm_data">
        <input
          type="checkbox"
          checked={isDeletingData}
          onChange={(event) => setIsDeletingData(event.target.checked)}
        />
        <span>Also delete {module.data_description}. Not recoverable.</span>
      </label>
      {isDeletingData && (
        <input
          className="input"
          placeholder={`type "${module.name}" to confirm deleting its data`}
          value={typedName}
          onChange={(event) => setTypedName(event.target.value)}
        />
      )}
      <div className="button_row">
        <button
          type="button"
          className="button button--small"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button--danger button--small"
          disabled={!isArmed}
          onClick={() => onConfirm(!isDeletingData)}
        >
          <Icon name="trash" size={12} />
          {isDeletingData ? "Uninstall and delete data" : "Uninstall"}
        </button>
      </div>
    </div>
  );
}

interface TaskLogProps {
  task: TaskStreamState;
  onDismiss: () => void;
}

function TaskLog({ task, onDismiss }: TaskLogProps) {
  return (
    <div className="module_card_task">
      <div className="module_card_task_lines">
        {task.lines.map((line, index) => (
          <div key={index}>{stripAnsi(line)}</div>
        ))}
        {task.isRunning && <div className="faint">working…</div>}
      </div>
      {!task.isRunning && (task.exitCode !== null || task.error !== null) && (
        <div className="module_card_task_footer">
          <span
            className={`badge ${task.exitCode === 0 ? "badge--ok" : "badge--error"}`}
          >
            {task.exitCode === 0 ? "done" : "failed"}
          </span>
          {task.error !== null && (
            <span className="field_error">{task.error}</span>
          )}
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onDismiss}
          >
            <Icon name="close" size={12} />
            Close
          </button>
        </div>
      )}
    </div>
  );
}
