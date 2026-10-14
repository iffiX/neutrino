import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiGet, apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { stripAnsi } from "../strip_ansi";
import { useTaskStream } from "../use_task_stream";
import {
  closeUpdateDialog,
  followUpdateTask,
  useUpdateDialog,
} from "../use_update_dialog";
import type { UpdateDialogState } from "../use_update_dialog";
import type {
  AuthState,
  HubUpdateProgress,
  HubUpdateRequest,
  HubUpdateStage,
  PanelDisplay,
  TaskStarted,
} from "../api_types";

import "./update_dialog.css";

/**
 * The dialog an update of the hub runs in, from the confirmation to its end.
 *
 * It asks, then streams the staging task. When the stream ends the install
 * restarts the panel, and the dialog keeps the staging lines and reads the
 * update's stage from the public display route, signed in or not, until the
 * stage is final, then shows one line with the result. It is drawn above the
 * session gate, so the sign-out the restart brings leaves it open, and a page
 * loaded meanwhile opens it again.
 */

/** How often the display route is read once the staging has handed over. */
const DISPLAY_POLL_INTERVAL_MS = 2000;
/** How long the panel goes unanswered before the dialog says so. */
const UNANSWERED_LIMIT_MS = 10 * 60_000;

const FINAL_STAGES: ReadonlySet<HubUpdateStage> = new Set([
  "installed",
  "rolled_back",
  "failed",
]);

/** A progress line the download writes: digits and a percent sign. */
const PERCENT_LINE = /^\d+%$/;

type UpdateDialogPhase =
  "ask" | "staging" | "staging_failed" | "following" | "finished";

/** How the panel answered the last read of the display route. */
type PanelReach = "answering" | "restarting" | "unanswered";

export function UpdateDialog() {
  const dialog = useUpdateDialog();
  if (dialog === null) {
    return null;
  }
  return <UpdateDialogModal dialog={dialog} />;
}

interface UpdateDialogModalProps {
  dialog: UpdateDialogState;
}

function UpdateDialogModal({ dialog }: UpdateDialogModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { target, isInstallerFamily, taskId, isResumed } = dialog;
  const task = useTaskStream(taskId);
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [streamLines, setStreamLines] = useState<string[]>([]);
  const [hasStreamEnded, setHasStreamEnded] = useState(false);
  const [progress, setProgress] = useState<HubUpdateProgress | null>(null);
  const [reach, setReach] = useState<PanelReach>("answering");
  const [isSignedOut, setIsSignedOut] = useState(false);
  const wasRunning = useRef(false);
  const logRef = useRef<HTMLPreElement | null>(null);

  const isStagingFailed = task.exitCode !== null && task.exitCode !== 0;
  const isFollowing = isResumed || hasStreamEnded;
  const isFinished = progress !== null && FINAL_STAGES.has(progress.stage);
  const isInstalled = progress?.stage === "installed";
  const phase: UpdateDialogPhase = isFinished
    ? "finished"
    : isStagingFailed
      ? "staging_failed"
      : isFollowing
        ? "following"
        : taskId === null
          ? "ask"
          : "staging";
  const isDismissable =
    phase === "ask" ||
    phase === "staging_failed" ||
    phase === "finished" ||
    (phase === "following" && reach === "unanswered");

  // A reconnecting stream starts its replay from nothing; the box keeps the
  // last lines it had.
  useEffect(() => {
    if (task.lines.length > 0) {
      setStreamLines(task.lines);
    }
  }, [task.lines]);

  useEffect(() => {
    if (task.isRunning) {
      wasRunning.current = true;
      return;
    }
    if (!wasRunning.current) {
      return;
    }
    wasRunning.current = false;
    // The stream ends when the staging hands over, or when the restart takes
    // its socket; either way the update goes on without it.
    if (task.exitCode === null || task.exitCode === 0) {
      setHasStreamEnded(true);
    }
  }, [task.isRunning, task.exitCode]);

  useEffect(() => {
    if (!isFollowing || isFinished) {
      return;
    }
    let isCancelled = false;
    let isReading = false;
    let answeredAt = Date.now();
    const read = async () => {
      if (isReading) {
        if (Date.now() - answeredAt >= UNANSWERED_LIMIT_MS) {
          setReach("unanswered");
        }
        return;
      }
      isReading = true;
      try {
        const display = await apiGet<PanelDisplay>("/hub/display");
        if (isCancelled) {
          return;
        }
        answeredAt = Date.now();
        setReach("answering");
        const update = display.update ?? null;
        if (update === null) {
          closeUpdateDialog();
          return;
        }
        setProgress(update);
      } catch {
        if (!isCancelled) {
          setReach(
            Date.now() - answeredAt >= UNANSWERED_LIMIT_MS
              ? "unanswered"
              : "restarting",
          );
        }
      } finally {
        isReading = false;
      }
    };
    void read();
    const handle = window.setInterval(() => {
      void read();
    }, DISPLAY_POLL_INTERVAL_MS);
    return () => {
      isCancelled = true;
      window.clearInterval(handle);
    };
  }, [isFollowing, isFinished]);

  // The restart signs every session out; an installed update whose page lost
  // its session leads to the sign-in.
  useEffect(() => {
    if (!isInstalled) {
      return;
    }
    let isCancelled = false;
    apiGet<AuthState>("/hub/auth/session")
      .then((state) => {
        if (!isCancelled) {
          setIsSignedOut(!state.is_authenticated);
        }
      })
      .catch(() => {
        // An unanswered read leaves Close as the way out.
      });
    return () => {
      isCancelled = true;
    };
  }, [isInstalled]);

  useEffect(() => {
    const element = logRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [streamLines]);

  const finish = useCallback(() => {
    closeUpdateDialog();
    if (isSignedOut) {
      window.location.reload();
    }
  }, [isSignedOut]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isDismissable && !isStarting) {
        finish();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finish, isDismissable, isStarting]);

  const start = async () => {
    setStartError(null);
    setIsStarting(true);
    try {
      const request: HubUpdateRequest = { version: target.version };
      const started = await apiPost<TaskStarted>(
        "/hub/setting/release/install",
        request,
      );
      followUpdateTask(started.task_id);
    } catch (cause: unknown) {
      setStartError(describeError(cause));
    } finally {
      setIsStarting(false);
    }
  };

  const version = target.version;
  return (
    <div
      className="confirm_backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={t("ui.settings.update_confirm_title", { version })}
      onClick={(event) => {
        if (
          event.target === event.currentTarget &&
          isDismissable &&
          !isStarting
        ) {
          finish();
        }
      }}
    >
      <div className="confirm_modal">
        <div className="confirm_head">
          <Icon name="download" size={16} />
          <h2>{t("ui.settings.update_confirm_title", { version })}</h2>
        </div>

        {phase === "ask" && (
          <>
            <p className="confirm_body">
              {t(
                isInstallerFamily
                  ? "ui.settings.update_confirm_body_installer"
                  : "ui.settings.update_confirm_body",
                { from: target.from, version },
              )}
            </p>
            {!target.isRollbackAvailable && (
              <div className="update_modal_fields">
                <div className="notice notice--warn">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {t("ui.settings.update_confirm_no_rollback", {
                      from: target.from,
                      version,
                    })}
                  </div>
                </div>
              </div>
            )}
            {startError !== null && (
              <div className="update_modal_fields">
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">{startError}</div>
                </div>
              </div>
            )}
            <div className="confirm_foot">
              <button
                type="button"
                className="button"
                onClick={closeUpdateDialog}
                disabled={isStarting}
              >
                {t("ui.settings.cancel")}
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void start()}
                disabled={isStarting}
              >
                {isStarting ? (
                  <Spinner size={14} />
                ) : (
                  <Icon name="download" size={14} />
                )}
                {t("ui.settings.update_install_short")}
              </button>
            </div>
          </>
        )}

        {phase !== "ask" && (
          <div className="update_modal_fields update_dialog_progress">
            {streamLines.length > 0 && (
              <pre
                className="device_drawer_log_output update_dialog_log"
                ref={logRef}
              >
                {stripAnsi(joinPercentLines(streamLines).join("\n"))}
              </pre>
            )}
            {phase === "staging" && (
              <Spinner size={18} label={t("ui.settings.update_preparing")} />
            )}
            {phase === "staging_failed" && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">
                  {t("ui.settings.update_failed")}
                </div>
              </div>
            )}
            {phase === "following" &&
              (reach === "unanswered" ? (
                <div className="notice notice--warn">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {t("ui.settings.update_unanswered")}
                  </div>
                </div>
              ) : (
                <Spinner
                  size={18}
                  label={
                    reach === "restarting"
                      ? t("ui.settings.update_restarting")
                      : stageLabel(progress)
                  }
                />
              ))}
            {phase === "finished" && progress !== null && (
              <div className={`notice ${resultTone(progress.stage)}`}>
                <Icon
                  name={progress.stage === "installed" ? "check" : "alert"}
                  size={15}
                />
                <div className="notice_body">{resultLine(progress)}</div>
              </div>
            )}
          </div>
        )}

        {isDismissable && phase !== "ask" && (
          <div className="confirm_foot">
            {isSignedOut ? (
              <button
                type="button"
                className="button button--primary"
                onClick={finish}
              >
                {t("ui.settings.update_sign_in")}
              </button>
            ) : (
              <button type="button" className="button" onClick={finish}>
                {t("ui.settings.close")}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Lines as the box shows them: a run of percent lines on one row.
 *
 * Args:
 *   lines: The lines as streamed.
 *
 * Returns:
 *   The same lines, each run of consecutive percent lines joined by two
 *   spaces.
 */
function joinPercentLines(lines: readonly string[]): string[] {
  const joined: string[] = [];
  let isAfterPercent = false;
  for (const line of lines) {
    const trimmed = line.trim();
    const isPercent = PERCENT_LINE.test(trimmed);
    if (isPercent && isAfterPercent) {
      joined[joined.length - 1] += `  ${trimmed}`;
    } else {
      joined.push(isPercent ? trimmed : line);
    }
    isAfterPercent = isPercent;
  }
  return joined;
}

/** The status line for an update the panel answers about, not yet final. */
function stageLabel(progress: HubUpdateProgress | null): string {
  if (progress?.stage === "preparing") {
    return t("ui.settings.update_preparing");
  }
  return t("ui.settings.update_restarting");
}

/** The one line that ends the dialog, for an update in a final stage. */
function resultLine(progress: HubUpdateProgress): string {
  const values = { from: progress.from_version, to: progress.to_version };
  if (progress.stage === "installed") {
    return t("ui.settings.update_finished_installed", values);
  }
  if (progress.stage === "rolled_back") {
    return t("ui.settings.update_finished_rolled_back", values);
  }
  return t("ui.settings.update_finished_failed", values);
}

/** The notice tone of a final stage. */
function resultTone(stage: HubUpdateStage): string {
  if (stage === "installed") {
    return "notice--ok";
  }
  if (stage === "rolled_back") {
    return "notice--warn";
  }
  return "notice--error";
}
