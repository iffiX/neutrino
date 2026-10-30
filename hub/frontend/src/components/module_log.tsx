import { useEffect, useRef } from "react";

import { StatusDot } from "./status_dot";
import { apiPath } from "../api_client";
import { t, useLanguage } from "../i18n";
import { stripAnsi } from "../strip_ansi";
import { usePolledResource } from "../use_polled_resource";
import { useTaskStream } from "../use_task_stream";
import type { StatusTone } from "./status_dot";
import type { DeviceModuleView, ServiceJournal } from "../api_types";

/**
 * A module tab's log box, under its title `Log · last 200 lines`.
 *
 * The lines the agent sends up while the module's task runs, after a task
 * fails, over a module whose install failed, and over one still installing,
 * as while it waits on a restart; the tail of the module's own journal on
 * the machine the rest of the time, polled while it shows.
 * The page mounts one per device and module, so the box never holds another
 * module's text.
 */

/** How much of the module's journal the box shows. */
const JOURNAL_LINES = 200;

/** The states in which the module's own journal has something to say. */
const JOURNAL_STATES = ["installed", "stopped", "running", "failed"];

/** A module whose last install failed: its install's lines fill the box. */
const INSTALL_FAILED_STATE = "install_failed";

/** A module whose install goes on, as one waiting on a restart: its
 * install's lines stay in the box. */
const INSTALLING_STATE = "installing";

interface ModuleLogProps {
  deviceId: string;
  row: DeviceModuleView;
  isAgentOnline: boolean;
}

export function ModuleLog({ deviceId, row, isAgentOnline }: ModuleLogProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const task = useTaskStream(row.task_id === "" ? null : row.task_id);
  // Whether the machine reports the module's task as running.
  const isReportedRunning = row.task !== null && row.task.is_running;
  // A finished task over a module whose install failed ended in a failure,
  // whatever its own exit status.
  const isTaskFailed =
    !task.isRunning &&
    (row.state === INSTALL_FAILED_STATE ||
      (task.exitCode !== null && task.exitCode !== 0));
  // The install goes on while the module reads installing, after a task
  // that ended with no failure.
  const isInstallGoing =
    task.isRunning ||
    isReportedRunning ||
    (!isTaskFailed && row.state === INSTALLING_STATE);
  // Over a module in a state with a journal, a task replaying takes the box
  // only while the machine reports the task running or once it ends in a
  // failure; until then the journal shows.
  const isTaskShown =
    row.task_id !== "" &&
    (isReportedRunning ||
      (task.isRunning
        ? !JOURNAL_STATES.includes(row.state)
        : isTaskFailed || isInstallGoing));
  const isJournalShown =
    !isTaskShown && isAgentOnline && JOURNAL_STATES.includes(row.state);
  const journal = usePolledResource<ServiceJournal>(
    isJournalShown
      ? apiPath("/agent/module/journal", {
          device_id: deviceId,
          module: row.name,
          lines: JOURNAL_LINES,
        })
      : null,
  );
  const journalText = journal.data?.text ?? null;
  const logRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const node = logRef.current;
    if (node !== null) {
      node.scrollTop = node.scrollHeight;
    }
  }, [task.lines, journalText]);

  return (
    <div className="modules_log">
      <div className="modules_log_head">
        <span className="section_label">{t("ui.modules.log_title")}</span>
        {isTaskShown && (
          <StatusDot
            tone={taskTone(isInstallGoing, task.exitCode, isTaskFailed)}
            isPulsing={isInstallGoing}
            label={t(taskKey(isInstallGoing, task.exitCode, isTaskFailed))}
          />
        )}
      </div>
      {isJournalShown && journalText === null && journal.isLoading ? (
        <div className="skeleton modules_log_loading" />
      ) : (
        <pre className="modules_log_output" ref={logRef}>
          {isTaskShown ? (
            stripAnsi(task.lines.join("\n"))
          ) : isJournalShown ? (
            journalText === null ? (
              <span className="faint">{t("ui.journal.unavailable")}</span>
            ) : journalText.trim().length > 0 ? (
              stripAnsi(journalText)
            ) : (
              <span className="faint">{t("ui.journal.empty")}</span>
            )
          ) : (
            <span className="faint">{t("ui.modules.output_empty")}</span>
          )}
        </pre>
      )}
      {isTaskShown && task.error !== null && (
        <span className="field_error">{task.error}</span>
      )}
    </div>
  );
}

function taskTone(
  isRunning: boolean,
  exitCode: number | null,
  isFailed: boolean,
): StatusTone {
  if (isRunning) {
    return "warn";
  }
  if (isFailed) {
    return "error";
  }
  return exitCode === 0 ? "ok" : "idle";
}

function taskKey(
  isRunning: boolean,
  exitCode: number | null,
  isFailed: boolean,
): string {
  if (isRunning) {
    return "ui.modules.task_running";
  }
  return exitCode === 0 && !isFailed
    ? "ui.modules.task_done"
    : "ui.modules.task_failed";
}
