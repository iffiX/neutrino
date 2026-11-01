import { useCallback, useEffect, useState } from "react";

/**
 * Hold an apply open until the machine reports how it went.
 *
 * A module's apply returns once the hub has handed the change to the
 * machine; the outcome arrives later with the module's reported state. The
 * apply stays busy until that state settles, and it counts as applied only
 * when it settled without a failure. A report that never settles releases
 * the apply after two minutes with no outcome, and the module's own state
 * stands as the answer.
 *
 * A failure reported at the press belongs to the run before it. It ends the
 * apply only when the machine reports nothing else within five seconds.
 */

/** How long an apply waits for the machine's report. */
const SETTLE_LIMIT_MS = 120_000;

/** How long a failing report after a press counts as the run before it. */
const OLD_FAILURE_LIMIT_MS = 5_000;

/** The states a module passes through on its way to another. */
const TRANSIENT_STATES = ["installing", "uninstalling"];

/** The states a module asked to run settles in while it has no instance. */
const EMPTY_SETTLED_STATES = ["running", "stopped"];

/** What the machine reports of one instance of a module. */
export interface ReportedInstance {
  is_running: boolean;
  code: string;
}

/** What the machine reports of a module that runs one unit per instance. */
export interface ReportedModule {
  state: string;
  instances: ReportedInstance[];
}

export interface SettledApply {
  /** Whether an apply is waiting for the machine's report. */
  isSettling: boolean;
  /** Whether the last apply settled without a failure. */
  isApplied: boolean;
  /** Start waiting, the moment the hub took the change. */
  begin: () => void;
  /** Forget the last apply's outcome. */
  clear: () => void;
}

/**
 * Follow one apply to the machine's report.
 *
 * Args:
 *   report: The module as last reported, or null before the first load.
 *   want: What the hub asks of the module: `running`, `stopped`, or empty.
 *
 * Returns:
 *   Whether an apply is waiting, whether the last one was applied, and the
 *   presses that start and forget one.
 */
export function useSettledApply(
  report: ReportedModule | null,
  want: string,
): SettledApply {
  const [isSettling, setIsSettling] = useState(false);
  const [isApplied, setIsApplied] = useState(false);
  const [isFailureOld, setIsFailureOld] = useState(false);

  useEffect(() => {
    if (!isSettling || report === null) {
      return;
    }
    if (isFailing(report)) {
      if (!isFailureOld) {
        setIsSettling(false);
      }
      return;
    }
    setIsFailureOld(false);
    if (isSettled(report, want)) {
      setIsSettling(false);
      setIsApplied(true);
    }
  }, [isSettling, isFailureOld, report, want]);

  useEffect(() => {
    if (!isFailureOld) {
      return;
    }
    const timer = window.setTimeout(() => {
      setIsFailureOld(false);
    }, OLD_FAILURE_LIMIT_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [isFailureOld]);

  useEffect(() => {
    if (!isSettling) {
      return;
    }
    const timer = window.setTimeout(() => {
      setIsSettling(false);
    }, SETTLE_LIMIT_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [isSettling]);

  const begin = useCallback(() => {
    setIsApplied(false);
    setIsFailureOld(true);
    setIsSettling(true);
  }, []);

  const clear = useCallback(() => {
    setIsApplied(false);
    setIsFailureOld(false);
    setIsSettling(false);
  }, []);

  return { isSettling, isApplied, begin, clear };
}

/** The states of a module whose last step failed. */
export const FAILED_STATES = ["failed", "install_failed"];

/** Whether the machine reports the module or one of its instances failing. */
export function isFailing(report: ReportedModule): boolean {
  return (
    FAILED_STATES.includes(report.state) ||
    report.instances.some((instance) => instance.code !== "")
  );
}

/** Whether the module stands where the hub asks it to. */
function isSettled(report: ReportedModule, want: string): boolean {
  if (TRANSIENT_STATES.includes(report.state)) {
    return false;
  }
  if (want === "running") {
    if (report.instances.length === 0) {
      return EMPTY_SETTLED_STATES.includes(report.state);
    }
    return (
      report.state === "running" &&
      report.instances.every((instance) => instance.is_running)
    );
  }
  if (want === "stopped") {
    return report.state === "stopped";
  }
  return true;
}
