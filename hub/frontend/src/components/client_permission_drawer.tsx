import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { ToggleSwitch } from "./toggle_switch";
import { describeError } from "../api_client";
import { t, useLanguage } from "../i18n";

import "./device_drawer.css";

/**
 * The kinds one client, or the default, is allowed: a switch per kind and
 * one apply bar. A client's drawer adds a switch that follows the default.
 */

/** The order the switches stand in; a kind not named here comes last. */
const KIND_DISPLAY_ORDER = [
  "overlay",
  "web",
  "port",
  "ai",
  "file",
  "terminal",
  "rdp",
];

interface ClientPermissionDrawerProps {
  title: string;
  hint?: string;
  applyHint: string;
  /** Every kind the hub knows. */
  kinds: string[];
  /** The kinds the default allows. */
  defaultKinds: string[];
  /** The stored set; null follows the default. */
  applied: string[] | null;
  /** Whether the drawer edits one client, and so offers following the default. */
  canFollowDefault: boolean;
  onApply: (kinds: string[] | null) => Promise<void>;
  onClose: () => void;
}

export function ClientPermissionDrawer({
  title,
  hint,
  applyHint,
  kinds,
  defaultKinds,
  applied,
  canFollowDefault,
  onApply,
  onClose,
}: ClientPermissionDrawerProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isFollowing, setIsFollowing] = useState(applied === null);
  const [draft, setDraft] = useState<string[]>(applied ?? defaultKinds);
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
  const wanted = isFollowing ? null : ordered(kinds, draft);
  const isDirty =
    wanted === null || applied === null
      ? wanted !== applied
      : wanted.join(",") !== ordered(kinds, applied).join(",");

  const toggle = (kind: string, isOn: boolean) => {
    setDraft((current) =>
      isOn ? [...current, kind] : current.filter((entry) => entry !== kind),
    );
  };

  const reset = () => {
    setIsFollowing(applied === null);
    setDraft(applied ?? defaultKinds);
    setError(null);
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await onApply(wanted);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

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
                if (!isOn) {
                  setDraft(defaultKinds);
                }
              }}
              label={t("ui.clients.permission_follow")}
              description={t("ui.clients.permission_follow_description")}
              isDisabled={isBusy}
            />
          )}
          <div className="device_drawer_section">
            {displayed(kinds).map((kind) => (
              <ToggleSwitch
                key={kind}
                isOn={shown.includes(kind)}
                onChange={(isOn) => toggle(kind, isOn)}
                label={t(`ui.clients.kind_${kind}`)}
                isDisabled={isBusy || isFollowing}
              />
            ))}
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

function displayed(kinds: string[]): string[] {
  const rank = (kind: string) => {
    const index = KIND_DISPLAY_ORDER.indexOf(kind);
    return index < 0 ? KIND_DISPLAY_ORDER.length : index;
  };
  return [...kinds].sort((left, right) => rank(left) - rank(right));
}
