import { StatusDot } from "./status_dot";
import { codeParams } from "../code_params";
import { hasWord, t, useLanguage } from "../i18n";
import { withModuleTitle } from "../module_title";
import type { StatusTone } from "./status_dot";
import type { ModuleTask, ModuleTaskStep, ModuleTaskWait } from "../api_types";

import "./module_task_steps.css";

/**
 * A module tab's step list, under its state line: the steps of the module's
 * last task, one line each in the plan's order.
 *
 * A step is done, running, waiting with the words of its wait under it, not
 * yet run, or failed in the error tone with its code's words under it. A
 * finished task's steps stay until the next task starts.
 */

/** The wait the tab's notice words beside **Restart now**. Its step reads
 * waiting with no words under it. */
export const REBOOT_REQUIRED_CODE = "reboot_required";

/** Where one step of the plan stands. */
type StepStatus = "done" | "running" | "waiting" | "pending" | "failed";

/** The step that installs one artifact. One with no words of its own reads
 * `ui.modules.step.artifact_alone` in a plan with one of them, and names its
 * artifact in a plan with several. */
const ARTIFACT_STEP = "artifact";

/** The steps that may read their artifact's own words,
 * `ui.modules.step.<step>.<module>.<artifact>`, each by the param that
 * names the artifact. */
const ARTIFACT_PARAMS: Record<string, string> = {
  artifact: "name",
  pull: "image",
};

/** The dot each step wears; the running step's alone pulses. */
const STEP_TONES: Record<StepStatus, StatusTone> = {
  done: "ok",
  running: "warn",
  waiting: "warn",
  pending: "idle",
  failed: "error",
};

interface ModuleTaskStepsProps {
  /** The module whose task this is. */
  module: string;
  task: ModuleTask;
  /** Whether the module's last task ended in a failure at its `index` step. */
  isFailed: boolean;
  /** The failure's words, under the failed step. */
  failure: string;
  /** Each module's title as its manifest gives it, by name. */
  manifestTitles: Record<string, string>;
}

export function ModuleTaskSteps({
  module,
  task,
  isFailed,
  failure,
  manifestTitles,
}: ModuleTaskStepsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const artifactCount = task.steps.filter(
    (step) => step.name === ARTIFACT_STEP,
  ).length;
  return (
    <ol className="module_steps">
      {task.steps.map((step, at) => {
        const status = stepStatus(task, at + 1, isFailed);
        const detail =
          status === "waiting"
            ? task.wait.code === REBOOT_REQUIRED_CODE
              ? ""
              : waitWords(task.wait, manifestTitles)
            : status === "failed"
              ? failure
              : "";
        return (
          <li
            className={`module_step module_step--${status}`}
            key={`${at}:${step.name}`}
          >
            <StatusDot
              tone={STEP_TONES[status]}
              isPulsing={status === "running"}
            />
            <span className="module_step_name">
              {stepWords(step, module, artifactCount)}
            </span>
            {detail !== "" && (
              <span className="module_step_detail">{detail}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** Where the step at a 1-based position stands in the task. */
function stepStatus(
  task: ModuleTask,
  position: number,
  isFailed: boolean,
): StepStatus {
  if (position < task.index) {
    return "done";
  }
  if (position > task.index) {
    return "pending";
  }
  if (task.is_running) {
    return task.wait.code === "" ? "running" : "waiting";
  }
  return isFailed ? "failed" : "done";
}

/** A step's words with its params, or its artifact's own words where the
 * catalog has them; a step the catalog lacks reads as its name.
 * `artifactCount` counts the plan's `artifact` steps. */
function stepWords(
  step: ModuleTaskStep,
  module: string,
  artifactCount: number,
): string {
  const param = ARTIFACT_PARAMS[step.name];
  if (param !== undefined) {
    const own = `ui.modules.step.${step.name}.${module}.${String(step.params[param] ?? "")}`;
    if (hasWord(own)) {
      return t(own);
    }
  }
  if (step.name === ARTIFACT_STEP && artifactCount === 1) {
    return t("ui.modules.step.artifact_alone");
  }
  const key = `ui.modules.step.${step.name}`;
  return hasWord(key) ? t(key, codeParams(step.params)) : step.name;
}

/** What a step waits for, in the code catalog's words; a code the catalog
 * lacks reads as itself. */
function waitWords(
  wait: ModuleTaskWait,
  manifestTitles: Record<string, string>,
): string {
  const key = `code.${wait.code}`;
  if (!hasWord(key)) {
    return wait.code;
  }
  return t(key, withModuleTitle(codeParams(wait.params), manifestTitles));
}
