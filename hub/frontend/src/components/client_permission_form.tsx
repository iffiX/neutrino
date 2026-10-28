import { useState } from "react";

import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { ToggleSwitch } from "./toggle_switch";
import { describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { PermissionRowView } from "../api_types";

import "./client_permission_form.css";

/**
 * One permission: a switch per kind, a device filter beside each kind but
 * the overlay and the panel, and at the foot **Choose per app**, which lists
 * each kind's rows with a switch of their own. A client's form adds a switch
 * that follows the default. The Clients page draws a client's in its row,
 * the default's in a dialog, both with Cancel and the save, and the link
 * dialog's with no buttons, reporting each change up.
 */

/** The order the switches stand in; a kind not named here comes last. */
const KIND_DISPLAY_ORDER = [
  "overlay",
  "panel",
  "web",
  "port",
  "ai",
  "file",
  "terminal",
  "ssh",
  "rdp",
];

/** The kinds that belong to the hub alone and take no device filter. */
const HUB_KINDS = ["overlay", "panel"];

/** The kind that signs a client in to the panel without the password. */
const KIND_PANEL = "panel";

/** Device ids by kind; a kind with no list allows every device. */
export type PermissionDevices = Record<string, string[]>;

/** Row id to on or off; a row not named follows its kind. */
export type PermissionEntries = Record<string, boolean>;

/** A whole permission: the kinds that are on, their lists and the rows. */
export interface PermissionValue {
  kinds: string[];
  devices: PermissionDevices;
  entries: PermissionEntries;
}

/** One managed device the filter can name. */
export interface PermissionDeviceChoice {
  id: string;
  name: string;
}

interface ClientPermissionFormProps {
  /** What saving does, in one line; the link dialog has none. */
  hint?: string;
  /** Every kind the hub knows. */
  kinds: string[];
  /** The rows the fine mode lists, by kind. */
  rows: Record<string, PermissionRowView[]>;
  /** The default permission. */
  defaultValue: PermissionValue;
  /** The stored permission; null follows the default. */
  applied: PermissionValue | null;
  /** The managed devices a filter may name. */
  devices: PermissionDeviceChoice[];
  /** Whether the form edits one client, and so offers following the default. */
  canFollowDefault: boolean;
  /** Saves the permission, null to follow the default; absent, the form has
   * no buttons. */
  onSave?: (value: PermissionValue | null) => Promise<void>;
  onCancel?: () => void;
  /** Reports the permission after each change, null while it follows the
   * default. */
  onChange?: (value: PermissionValue | null) => void;
}

export function ClientPermissionForm({
  hint,
  kinds,
  rows,
  defaultValue,
  applied,
  devices,
  canFollowDefault,
  onSave,
  onCancel,
  onChange,
}: ClientPermissionFormProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const start = applied ?? defaultValue;
  const [isFollowing, setIsFollowing] = useState(applied === null);
  const [draft, setDraft] = useState<PermissionValue>(start);
  const [isFineMode, setIsFineMode] = useState(hasRows(start));
  // Which kind's device list is open, if any.
  const [filtering, setFiltering] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shown = isFollowing ? defaultValue : draft;
  const wanted = isFollowing ? null : wantedOf(kinds, draft, isFineMode);
  const isDirty =
    wanted === null || applied === null
      ? wanted !== applied
      : JSON.stringify(wanted) !==
        JSON.stringify(wantedOf(kinds, applied, true));
  const isClearingRows = !isFollowing && !isFineMode && hasRows(draft);

  const change = (next: PermissionValue, nextFineMode: boolean) => {
    setDraft(next);
    onChange?.(wantedOf(kinds, next, nextFineMode));
  };

  const toggle = (kind: string, isOn: boolean) =>
    change(
      {
        ...draft,
        kinds: isOn
          ? [...draft.kinds, kind]
          : draft.kinds.filter((entry) => entry !== kind),
      },
      isFineMode,
    );

  const toggleDevice = (kind: string, deviceId: string, isOn: boolean) => {
    const chosen = draft.devices[kind] ?? [];
    change(
      {
        ...draft,
        devices: {
          ...draft.devices,
          [kind]: isOn
            ? [...chosen, deviceId]
            : chosen.filter((entry) => entry !== deviceId),
        },
      },
      isFineMode,
    );
  };

  const setRow = (rowId: string, isOn: boolean | null) => {
    const entries = { ...draft.entries };
    if (isOn === null) {
      delete entries[rowId];
    } else {
      entries[rowId] = isOn;
    }
    change({ ...draft, entries }, isFineMode);
  };

  const follow = (isOn: boolean) => {
    setIsFollowing(isOn);
    setFiltering(null);
    if (isOn) {
      onChange?.(null);
      return;
    }
    setIsFineMode(hasRows(defaultValue));
    change(defaultValue, hasRows(defaultValue));
  };

  const switchFineMode = (isOn: boolean) => {
    setIsFineMode(isOn);
    if (!isFollowing) {
      onChange?.(wantedOf(kinds, draft, isOn));
    }
  };

  const save = async () => {
    if (onSave === undefined) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      await onSave(wanted);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const isKindLocked = isBusy || isFollowing;

  return (
    <div className="inline_form client_permission_form">
      {canFollowDefault && (
        <ToggleSwitch
          isOn={isFollowing}
          onChange={follow}
          label={t("ui.clients.permission_follow")}
          description={t("ui.clients.permission_follow_description")}
          isDisabled={isBusy}
        />
      )}
      <div className="client_permission_kinds">
        {displayed(kinds).map((kind) => {
          const isOn = shown.kinds.includes(kind);
          const chosen = shown.devices[kind] ?? [];
          const kindRows = rows[kind];
          return (
            <div key={kind} className="client_permission_kind">
              <div className="client_permission_row">
                <ToggleSwitch
                  isOn={isOn}
                  onChange={(next) => toggle(kind, next)}
                  label={t(`ui.clients.kind_${kind}`)}
                  description={
                    kind === KIND_PANEL
                      ? t("ui.clients.kind_panel_description")
                      : undefined
                  }
                  isDisabled={isKindLocked}
                />
                {!HUB_KINDS.includes(kind) && (
                  <button
                    type="button"
                    className="button button--small button--ghost client_permission_filter"
                    aria-expanded={filtering === kind}
                    aria-label={t("ui.clients.filter_label", {
                      kind: t(`ui.clients.kind_${kind}`),
                    })}
                    disabled={isKindLocked || !isOn}
                    onClick={() =>
                      setFiltering(filtering === kind ? null : kind)
                    }
                  >
                    <span className="client_permission_filter_text">
                      {filterLabel(chosen, devices)}
                    </span>
                    <Icon name="chevron_down" size={12} />
                  </button>
                )}
              </div>
              {filtering === kind && isOn && !isKindLocked && (
                <div className="client_permission_devices">
                  {devices.map((device) => (
                    <label key={device.id} className="client_permission_device">
                      <input
                        type="checkbox"
                        checked={chosen.includes(device.id)}
                        onChange={(event) =>
                          toggleDevice(kind, device.id, event.target.checked)
                        }
                      />
                      <span>{device.name}</span>
                    </label>
                  ))}
                  {devices.length === 0 && (
                    <p className="field_hint">
                      {t("ui.clients.filter_no_devices")}
                    </p>
                  )}
                  <p className="field_hint">{t("ui.clients.filter_hint")}</p>
                </div>
              )}
              {isFineMode && kindRows !== undefined && (
                <div className="client_permission_apps">
                  {kindRows.length === 0 && (
                    <p className="field_hint">{t("ui.clients.rows_empty")}</p>
                  )}
                  {kindRows.map((row) => (
                    <PermissionAppRow
                      key={row.id}
                      row={row}
                      isOn={isRowPermitted(shown, kind, row)}
                      isStored={row.id in shown.entries}
                      isDisabled={isKindLocked}
                      onSet={(next) => setRow(row.id, next)}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <ToggleSwitch
        isOn={isFineMode}
        onChange={switchFineMode}
        label={t("ui.clients.fine_mode")}
        description={t("ui.clients.fine_mode_description")}
        isDisabled={isBusy}
      />
      {isClearingRows && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.clients.fine_mode_clear_warning")}
          </div>
        </div>
      )}
      {hint !== undefined && <p className="field_hint">{hint}</p>}
      {error !== null && <span className="field_error">{error}</span>}
      {onSave !== undefined && (
        <div className="inline_form_actions">
          <button
            type="button"
            className="button button--ghost"
            disabled={isBusy}
            onClick={onCancel}
          >
            {t("ui.clients.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={!isDirty || isBusy}
            onClick={() => void save()}
          >
            {isBusy ? <Spinner size={13} /> : <Icon name="check" size={14} />}
            {t("ui.clients.permission_apply")}
          </button>
        </div>
      )}
    </div>
  );
}

interface PermissionAppRowProps {
  row: PermissionRowView;
  /** What the hub's judging gives the row now. */
  isOn: boolean;
  /** Whether the row is set on its own and no longer follows its kind. */
  isStored: boolean;
  isDisabled: boolean;
  /** Sets the row on or off, or null to follow its kind again. */
  onSet: (isOn: boolean | null) => void;
}

function PermissionAppRow({
  row,
  isOn,
  isStored,
  isDisabled,
  onSet,
}: PermissionAppRowProps) {
  return (
    <div className="client_permission_app">
      <div className="client_permission_app_name">
        <span>{row.title}</span>
        {row.device_name !== "" && row.device_name !== row.title && (
          <span className="faint">{row.device_name}</span>
        )}
      </div>
      {isStored && (
        <button
          type="button"
          className="button button--small button--ghost"
          disabled={isDisabled}
          onClick={() => onSet(null)}
        >
          {t("ui.clients.follow_kind")}
        </button>
      )}
      <ToggleSwitch
        isOn={isOn}
        onChange={onSet}
        ariaLabel={row.title}
        isDisabled={isDisabled}
      />
    </div>
  );
}

function hasRows(value: PermissionValue): boolean {
  return Object.keys(value.entries).length > 0;
}

/** Whether a permission allows one row under one kind, as the hub judges it. */
function isRowPermitted(
  value: PermissionValue,
  kind: string,
  row: PermissionRowView,
): boolean {
  const stored = value.entries[row.id];
  if (stored !== undefined) {
    return stored;
  }
  const chosen = value.devices[kind] ?? [];
  return (
    value.kinds.includes(kind) &&
    (chosen.length === 0 || chosen.includes(row.device_id))
  );
}

/** A permission as the routes take it: kinds in order, the filter without
 * the hub's kinds or an empty list, and the rows while the fine mode is on. */
function wantedOf(
  kinds: string[],
  value: PermissionValue,
  isFineMode: boolean,
): PermissionValue {
  const devices: PermissionDevices = {};
  for (const kind of kinds) {
    const chosen = [...new Set(value.devices[kind] ?? [])].sort();
    if (!HUB_KINDS.includes(kind) && chosen.length > 0) {
      devices[kind] = chosen;
    }
  }
  const entries: PermissionEntries = {};
  if (isFineMode) {
    const stored = Object.entries(value.entries).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    for (const [rowId, isOn] of stored) {
      entries[rowId] = isOn;
    }
  }
  return {
    kinds: kinds.filter((kind) => value.kinds.includes(kind)),
    devices,
    entries,
  };
}

/** "All agents", or the names of the devices a kind is narrowed to. */
function filterLabel(
  chosen: string[],
  devices: PermissionDeviceChoice[],
): string {
  if (chosen.length === 0) {
    return t("ui.clients.filter_all");
  }
  return chosen
    .map((id) => devices.find((device) => device.id === id)?.name ?? id)
    .join(", ");
}

function displayed(kinds: string[]): string[] {
  const rank = (kind: string) => {
    const index = KIND_DISPLAY_ORDER.indexOf(kind);
    return index < 0 ? KIND_DISPLAY_ORDER.length : index;
  };
  return [...kinds].sort((left, right) => rank(left) - rank(right));
}
