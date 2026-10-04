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
 * The output box under a module's tab on the Modules page.
 *
 * The lines the agent sends up while the module installs or uninstalls, and
 * after such a task fails; the tail of the module's own journal on the
 * machine the rest of the time, polled while it shows. The page mounts one
 * per device and module, so the box never holds another module's text.
 */

/** How much of the module's journal the box shows. */
const JOURNAL_LINES = 200;

/** The states in which the module's own journal has something to say. */
const JOURNAL_STATES = ["installed", "stopped", "running", "failed"];

interface ModuleLogProps {
  deviceId: string;
  row: DeviceModuleView;
  isAgentOnline: boolean;
}

export function ModuleLog({ deviceId, row, isAgentOnline }: ModuleLogProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const task = useTaskStream(row.task_id === "" ? null : row.task_id);
  const isTaskShown =
    row.task_id !== "" &&
    (task.isRunning || (task.exitCode !== null && task.exitCode !== 0));
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
        <span className="section_label">
          {isJournalShown
            ? t("ui.journal.label", { lines: JOURNAL_LINES })
            : t("ui.modules.output")}
        </span>
        {isTaskShown && (
          <StatusDot
            tone={taskTone(task.isRunning, task.exitCode)}
            isPulsing={task.isRunning}
            label={t(taskKey(task.isRunning, task.exitCode))}
          />
        )}
        {isJournalShown && journalText !== null && (
          <StatusDot tone="ok" isPulsing label={t("state.live")} />
        )}
      </div>
      <pre className="modules_log_output" ref={logRef}>
        {isTaskShown ? (
          stripAnsi(task.lines.join("\n"))
        ) : isJournalShown ? (
          journalText === null ? (
            <span className="faint">
              {journal.isLoading ? "" : t("ui.journal.unavailable")}
            </span>
          ) : journalText.trim().length > 0 ? (
            stripAnsi(journalText)
          ) : (
            <span className="faint">
              {t(
                hasNoInstances(row)
                  ? "ui.modules.no_instances"
                  : "ui.journal.empty",
              )}
            </span>
          )
        ) : (
          <span className="faint">{t("ui.modules.output_empty")}</span>
        )}
      </pre>
      {isTaskShown && task.error !== null && (
        <span className="field_error">{task.error}</span>
      )}
    </div>
  );
}

/** Whether the module runs one unit per instance and nobody has added one:
 * the machine reports none and the hub holds no configuration for it. */
function hasNoInstances(row: DeviceModuleView): boolean {
  const instances = row.details.instances;
  return (
    Array.isArray(instances) &&
    instances.length === 0 &&
    !row.is_configured &&
    row.state !== "failed"
  );
}

function taskTone(isRunning: boolean, exitCode: number | null): StatusTone {
  if (isRunning) {
    return "warn";
  }
  if (exitCode === 0) {
    return "ok";
  }
  return exitCode === null ? "idle" : "error";
}

function taskKey(isRunning: boolean, exitCode: number | null): string {
  if (isRunning) {
    return "ui.modules.task_running";
  }
  return exitCode === 0 ? "ui.modules.task_done" : "ui.modules.task_failed";
}
