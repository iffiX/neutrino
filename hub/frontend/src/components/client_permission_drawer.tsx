import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { ToggleSwitch } from "./toggle_switch";
import { describeError } from "../api_client";
import { t, useLanguage } from "../i18n";

import "./client_permission_drawer.css";
import "./device_drawer.css";

/**
 * The kinds one client, or the default, is allowed: a switch per kind, a
 * device filter beside each kind but the overlay and the panel, and one
 * apply bar. A
 * client's drawer adds a switch that follows the default.
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
  "rdp",
];

/** The kinds that belong to the hub alone and take no device filter. */
const HUB_KINDS = ["overlay", "panel"];

/** Device ids by kind; a kind with no list allows every device. */
export type PermissionDevices = Record<string, string[]>;

/** One managed device the filter can name. */
export interface PermissionDeviceChoice {
  id: string;
  name: string;
}

interface ClientPermissionDrawerProps {
  title: string;
  hint?: string;
  applyHint: string;
  /** Every kind the hub knows. */
  kinds: string[];
  /** The kinds the default allows. */
  defaultKinds: string[];
  /** The default's device filter. */
  defaultDevices: PermissionDevices;
  /** The stored set; null follows the default. */
  applied: string[] | null;
  /** The stored device filter. */
  appliedDevices: PermissionDevices;
  /** The managed devices a filter may name. */
  devices: PermissionDeviceChoice[];
  /** Whether the drawer edits one client, and so offers following the default. */
  canFollowDefault: boolean;
  onApply: (
    kinds: string[] | null,
    devices: PermissionDevices | null,
  ) => Promise<void>;
  onClose: () => void;
}

export function ClientPermissionDrawer({
  title,
  hint,
  applyHint,
  kinds,
  defaultKinds,
  defaultDevices,
  applied,
  appliedDevices,
  devices,
  canFollowDefault,
  onApply,
  onClose,
}: ClientPermissionDrawerProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isFollowing, setIsFollowing] = useState(applied === null);
  const [draft, setDraft] = useState<string[]>(applied ?? defaultKinds);
  const [draftDevices, setDraftDevices] = useState<PermissionDevices>(
    applied === null ? defaultDevices : appliedDevices,
  );
  // Which kind's device list is open, if any.
  const [filtering, setFiltering] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const shown = isFollowing ? defaultKinds : draft;
  const shownDevices = isFollowing ? defaultDevices : draftDevices;
  const wanted = isFollowing ? null : ordered(kinds, draft);
  const wantedDevices = isFollowing ? null : filtersOf(kinds, draftDevices);
  const isDirty =
    wanted === null || applied === null
      ? wanted !== applied
      : wanted.join(",") !== ordered(kinds, applied).join(",") ||
        JSON.stringify(wantedDevices) !==
          JSON.stringify(filtersOf(kinds, appliedDevices));

  const toggle = (kind: string, isOn: boolean) => {
    setDraft((current) =>
      isOn ? [...current, kind] : current.filter((entry) => entry !== kind),
    );
  };

  const toggleDevice = (kind: string, deviceId: string, isOn: boolean) => {
    setDraftDevices((current) => {
      const chosen = current[kind] ?? [];
      return {
        ...current,
        [kind]: isOn
          ? [...chosen, deviceId]
          : chosen.filter((entry) => entry !== deviceId),
      };
    });
  };

  const reset = () => {
    setIsFollowing(applied === null);
    setDraft(applied ?? defaultKinds);
    setDraftDevices(applied === null ? defaultDevices : appliedDevices);
    setFiltering(null);
    setError(null);
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await onApply(wanted, wantedDevices);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const isKindLocked = isBusy || isFollowing;

  // A portal, so the drawer escapes the page's stacking context.
  return createPortal(
    <>
      <div className="device_drawer_backdrop" onClick={onClose} />
      <aside className="device_drawer" role="dialog" aria-modal="true">
        <div className="device_drawer_head">
          <span className="device_drawer_title">{title}</span>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={onClose}
            aria-label={t("ui.drawer.close")}
          >
            <Icon name="close" size={15} />
          </button>
        </div>
        <div className="device_drawer_body">
          {hint !== undefined && <p className="field_hint">{hint}</p>}
          {canFollowDefault && (
            <ToggleSwitch
              isOn={isFollowing}
              onChange={(isOn) => {
                setIsFollowing(isOn);
                setFiltering(null);
                if (!isOn) {
                  setDraft(defaultKinds);
                  setDraftDevices(defaultDevices);
                }
              }}
              label={t("ui.clients.permission_follow")}
              description={t("ui.clients.permission_follow_description")}
              isDisabled={isBusy}
            />
          )}
          <div className="device_drawer_section">
            {displayed(kinds).map((kind) => {
              const isOn = shown.includes(kind);
              const chosen = shownDevices[kind] ?? [];
              return (
                <div key={kind} className="client_permission_kind">
                  <div className="client_permission_row">
                    <ToggleSwitch
                      isOn={isOn}
                      onChange={(next) => toggle(kind, next)}
                      label={t(`ui.clients.kind_${kind}`)}
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
                        <label
                          key={device.id}
                          className="client_permission_device"
                        >
                          <input
                            type="checkbox"
                            checked={chosen.includes(device.id)}
                            onChange={(event) =>
                              toggleDevice(
                                kind,
                                device.id,
                                event.target.checked,
                              )
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
                      <p className="field_hint">
                        {t("ui.clients.filter_hint")}
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <ApplyBar
            isDirty={isDirty}
            isBusy={isBusy}
            label={t("ui.clients.permission_apply")}
            hint={applyHint}
            error={error}
            onReset={reset}
            onApply={() => void apply()}
          />
        </div>
      </aside>
    </>,
    document.body,
  );
}

function ordered(kinds: string[], chosen: string[]): string[] {
  return kinds.filter((kind) => chosen.includes(kind));
}

/** A device filter in kind order, without the hub's kinds or an empty list. */
function filtersOf(
  kinds: string[],
  devices: PermissionDevices,
): PermissionDevices {
  const filters: PermissionDevices = {};
  for (const kind of kinds) {
    const chosen = [...new Set(devices[kind] ?? [])].sort();
    if (!HUB_KINDS.includes(kind) && chosen.length > 0) {
      filters[kind] = chosen;
    }
  }
  return filters;
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
