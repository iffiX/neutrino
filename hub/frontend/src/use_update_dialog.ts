/**
 * The one dialog an update of the hub runs in, held above the session gate.
 *
 * The Settings page opens it, and it outlives that page: the update restarts
 * the panel, which signs the session out and reloads the page. From the
 * moment the staging task is known until the dialog is closed, the update's
 * versions are kept in the tab's session storage, and a page loaded
 * meanwhile opens the dialog again, following the update from the public
 * display read.
 */

import { useSyncExternalStore } from "react";

const UPDATE_DIALOG_STORAGE_KEY = "neutrino.hub_update";

/** What the dialog installs, and what it installs over. */
export interface UpdateDialogTarget {
  from: string;
  version: string;
  isRollbackAvailable: boolean;
}

export interface UpdateDialogState {
  target: UpdateDialogTarget;
  /** Whether the system's own installer installs this hub's package. */
  isInstallerFamily: boolean;
  /** The staging task streamed; null before Install is pressed. */
  taskId: string | null;
  /** Whether the dialog was opened again on a page loaded mid-update. */
  isResumed: boolean;
}

/** The versions kept in session storage while an update is under way. */
interface StoredUpdate {
  from_version: string;
  to_version: string;
}

const listeners = new Set<() => void>();

let current: UpdateDialogState | null = readStoredUpdate();

/**
 * Open the dialog on a release, or on a staging task already running.
 *
 * Args:
 *   target: The versions the dialog is about.
 *   isInstallerFamily: Whether the system's own installer installs this
 *     hub's package.
 *   taskId: The staging task to stream, or null to ask first.
 */
export function openUpdateDialog(
  target: UpdateDialogTarget,
  isInstallerFamily: boolean,
  taskId: string | null,
): void {
  if (taskId !== null) {
    storeUpdate(target);
  }
  publish({ target, isInstallerFamily, taskId, isResumed: false });
}

/**
 * Stream the staging task the dialog's Install started.
 *
 * Args:
 *   taskId: The task the install route answered with.
 */
export function followUpdateTask(taskId: string): void {
  if (current === null) {
    return;
  }
  storeUpdate(current.target);
  publish({ ...current, taskId });
}

/** Close the dialog and forget the update it followed. */
export function closeUpdateDialog(): void {
  try {
    window.sessionStorage.removeItem(UPDATE_DIALOG_STORAGE_KEY);
  } catch {
    // A tab without storage has nothing kept to remove.
  }
  publish(null);
}

/** The dialog's state, re-rendering the component when it changes. */
export function useUpdateDialog(): UpdateDialogState | null {
  return useSyncExternalStore(subscribe, currentState, currentState);
}

function currentState(): UpdateDialogState | null {
  return current;
}

function publish(next: UpdateDialogState | null): void {
  current = next;
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

function storeUpdate(target: UpdateDialogTarget): void {
  const stored: StoredUpdate = {
    from_version: target.from,
    to_version: target.version,
  };
  try {
    window.sessionStorage.setItem(
      UPDATE_DIALOG_STORAGE_KEY,
      JSON.stringify(stored),
    );
  } catch {
    // A tab without storage follows the update until it is reloaded.
  }
}

function readStoredUpdate(): UpdateDialogState | null {
  let parsed: unknown;
  try {
    const raw = window.sessionStorage.getItem(UPDATE_DIALOG_STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null;
  }
  const stored = parsed as Record<string, unknown>;
  if (
    typeof stored.from_version !== "string" ||
    typeof stored.to_version !== "string"
  ) {
    return null;
  }
  return {
    target: {
      from: stored.from_version,
      version: stored.to_version,
      isRollbackAvailable: true,
    },
    isInstallerFamily: false,
    taskId: null,
    isResumed: true,
  };
}
