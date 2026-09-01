import { useEffect, useState } from "react";

import { Icon } from "./icon";
import { JournalPanel } from "./journal_panel";
import { StatusDot } from "./status_dot";
import { useTaskStream } from "../use_task_stream";
import type { TaskStreamState } from "../use_task_stream";
import type { ServiceActionName, ServiceView } from "../api_types";

import "./service_card.css";

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

interface ServiceCardProps {
  service: ServiceView;
  isBusy: boolean;
  isJournalOpen: boolean;
  /** The task streaming for this service, or null. */
  taskId: string | null;
  onAction: (action: ServiceActionName) => void;
  onToggleJournal: () => void;
  onInstall: () => void;
  onUninstall: (isDataKept: boolean) => void;
  /** Called once a task finishes, so the page refetches reality. */
  onTaskFinished: () => void;
  /** Called when the finished task's log is closed by hand. */
  onDismissTask: () => void;
}

export function ServiceCard({
  service,
  isBusy,
  isJournalOpen,
  taskId,
  onAction,
  onToggleJournal,
  onInstall,
  onUninstall,
  onTaskFinished,
  onDismissTask,
}: ServiceCardProps) {
  const [isConfirmingRemoval, setIsConfirmingRemoval] = useState(false);
  // The stream lives here rather than in the log component, because the
  // card's buttons follow it: while a task runs they stand back, and the
  // moment it finishes they render for whatever reality the task left —
  // Install right below an uninstall's log. A page reload clears the log
  // and only the buttons remain.
  const task = useTaskStream(taskId);
  const [reportedTaskId, setReportedTaskId] = useState<string | null>(null);
  useEffect(() => {
    if (
      taskId !== null &&
      !task.isRunning &&
      task.exitCode !== null &&
      reportedTaskId !== taskId
    ) {
      setReportedTaskId(taskId);
      onTaskFinished();
    }
  }, [taskId, task.isRunning, task.exitCode, reportedTaskId, onTaskFinished]);
  const isTaskRunning = taskId !== null && task.isRunning;

  return (
    <article
      key={service.name}
      className={`service_card ${
        !service.is_installed
          ? "service_card--missing"
          : service.is_active
            ? "service_card--active"
            : ""
      }`}
    >
      <div className="service_card_head">
        <div className="service_card_identity">
          <span className="service_card_name">
            <StatusDot
              tone={
                !service.is_installed
                  ? "idle"
                  : service.is_active
                    ? "ok"
                    : "error"
              }
              isPulsing={service.is_active}
            />
            {service.name}
          </span>
          <span className="service_card_unit">{service.unit}</span>
        </div>
        <div className="service_card_badges">
          {!service.is_installed ? (
            <span className="badge">not installed</span>
          ) : (
            <>
              <span
                className={`badge ${service.is_active ? "badge--ok" : "badge--error"}`}
              >
                {service.is_active ? "active" : "inactive"}
              </span>
              <span
                className={`badge ${service.is_enabled ? "badge--accent" : ""}`}
              >
                {service.is_enabled ? "enabled" : "disabled"}
              </span>
            </>
          )}
        </div>
      </div>

      {!service.is_installed && service.is_installable && !isTaskRunning && (
        <div className="service_card_install">
          <button
            type="button"
            className="button button--primary button--small"
            disabled={isBusy || !service.is_machine_supported}
            title={service.unsupported_reason ?? undefined}
            onClick={onInstall}
          >
            <Icon name="download" size={12} />
            Install
          </button>
          <span className="service_card_note">
            {service.is_machine_supported
              ? service.install_note
              : service.unsupported_reason}
          </span>
        </div>
      )}

      {service.is_installed && (
        <div className="service_card_actions">
          <button
            type="button"
            className="button button--small"
            disabled={isBusy || service.is_active}
            onClick={() => void onAction("start")}
          >
            <Icon name="play" size={12} />
            Start
          </button>
          {/* Core units have no Stop or Disable: the gateway does
                not route without them, so offering it would only be
                offering a way to break the box. */}
          {!service.is_core && (
            <button
              type="button"
              className="button button--small"
              disabled={isBusy || !service.is_active}
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
          {(!service.is_core || !service.is_enabled) && (
            <button
              type="button"
              className="button button--small"
              disabled={isBusy}
              onClick={() =>
                void onAction(service.is_enabled ? "disable" : "enable")
              }
            >
              <Icon name="power" size={12} />
              {service.is_enabled ? "Disable" : "Enable"}
            </button>
          )}
          {!service.is_core && service.is_installable && (
            <button
              type="button"
              className="button button--ghost button--small service_card_remove"
              disabled={isBusy || isTaskRunning}
              onClick={() => setIsConfirmingRemoval((current) => !current)}
            >
              <Icon name="trash" size={12} />
              Uninstall
            </button>
          )}
          <button
            type="button"
            className="button button--ghost button--small service_card_journal_toggle"
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
          service={service}
          onCancel={() => setIsConfirmingRemoval(false)}
          onConfirm={(isDataKept) => {
            setIsConfirmingRemoval(false);
            onUninstall(isDataKept);
          }}
        />
      )}

      {taskId !== null && <TaskLog task={task} onDismiss={onDismissTask} />}

      <JournalPanel
        serviceName={service.name}
        isOpen={service.is_installed && isJournalOpen}
      />
    </article>
  );
}

interface UninstallConfirmProps {
  service: ServiceView;
  onCancel: () => void;
  onConfirm: (isDataKept: boolean) => void;
}

function UninstallConfirm({
  service,
  onCancel,
  onConfirm,
}: UninstallConfirmProps) {
  const [isDeletingData, setIsDeletingData] = useState(false);
  const [typedName, setTypedName] = useState("");

  // Deleting data must be typed out; merely removing the software must not.
  const isArmed = !isDeletingData || typedName === service.name;

  return (
    <div className="service_card_confirm">
      <p className="service_card_note">
        Removes the software; configuration is kept.
      </p>
      <label className="service_card_confirm_data">
        <input
          type="checkbox"
          checked={isDeletingData}
          onChange={(event) => setIsDeletingData(event.target.checked)}
        />
        <span>Also delete {service.data_description}. Not recoverable.</span>
      </label>
      {isDeletingData && (
        <input
          className="input"
          placeholder={`type "${service.name}" to confirm deleting its data`}
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
    <div className="service_card_task">
      <div className="service_card_task_lines">
        {task.lines.map((line, index) => (
          <div key={index}>{line}</div>
        ))}
        {task.isRunning && <div className="faint">working…</div>}
      </div>
      {!task.isRunning && (task.exitCode !== null || task.error !== null) && (
        <div className="service_card_task_footer">
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
