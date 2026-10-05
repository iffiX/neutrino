import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { ToggleSwitch } from "./toggle_switch";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { interruptionWarning } from "../network_warnings";
import { useDraftSeeding } from "../use_draft_seeding";
import type {
  OverlayChoiceRequest,
  OverlayChoiceView,
  OverlayKindView,
} from "../api_types";

import "./overlay_mode_panel.css";

/**
 * Which overlays this box runs.
 *
 * One card per engine. The switch on a card turns the engine on or off in
 * the draft, and the apply bar makes the draft real; pressing the card
 * itself only picks which engine's settings show below. An engine this hub
 * cannot run yet keeps its card and says so on it.
 */

const KIND_SUMMARY_KEYS: Record<string, string> = {
  netbird: "ui.overlay.summary_netbird",
  easytier: "ui.overlay.summary_easytier",
  relay: "ui.overlay.summary_relay",
  direct: "ui.overlay.summary_direct",
};

const KIND_ICONS: Record<string, IconName> = {
  netbird: "mesh",
  easytier: "nodes",
  relay: "server",
  direct: "globe",
};

/** The rows whose names are words rather than a product's, by their key. */
const KIND_TITLE_KEYS: Record<string, string> = {
  relay: "ui.overlay.relay_title",
  direct: "ui.overlay.direct_title",
};
const KIND_RELAY = "relay";

const KIND_ICON_OTHER: IconName = "mesh";

interface OverlayModePanelProps {
  choice: OverlayChoiceView;
  selected: string;
  onSelect: (key: string) => void;
  onApplied: (view: OverlayChoiceView) => void;
}

/** Each engine's key and whether it runs, as one comparable string. */
function enabledSignature(enabled: Record<string, boolean>): string {
  return Object.keys(enabled)
    .sort()
    .map((key) => `${key}:${enabled[key] ? 1 : 0}`)
    .join(" ");
}

function storedEnabled(choice: OverlayChoiceView): Record<string, boolean> {
  return Object.fromEntries(
    choice.kinds.map((kind) => [kind.key, kind.is_enabled]),
  );
}

export function OverlayModePanel({
  choice,
  selected,
  onSelect,
  onApplied,
}: OverlayModePanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const stored = storedEnabled(choice);
  const [enabled, setEnabled] = useState<Record<string, boolean>>(stored);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A switch flipped but not applied stays flipped.
  const storedSignature = enabledSignature(stored);
  const isReseedable = useDraftSeeding(
    enabledSignature(enabled),
    storedSignature,
  );
  useEffect(() => {
    if (!isReseedable(storedSignature)) {
      return;
    }
    setEnabled(storedEnabled(choice));
  }, [choice, storedSignature, isReseedable]);

  const isDirty = enabledSignature(enabled) !== storedSignature;
  const leaving = choice.kinds.filter(
    (kind) => kind.is_enabled && enabled[kind.key] === false,
  );

  const apply = async () => {
    if (!isDirty) {
      return;
    }
    setIsBusy(true);
    setError(null);
    const request: OverlayChoiceRequest = {};
    for (const kind of choice.kinds) {
      if (enabled[kind.key] !== kind.is_enabled) {
        request[kind.key as keyof OverlayChoiceRequest] = {
          is_enabled: enabled[kind.key] === true,
        };
      }
    }
    try {
      onApplied(await apiPost<OverlayChoiceView>("/hub/overlay/set", request));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.engine_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.overlay.engine_hint")}</p>

      <div className="overlay_choices">
        {choice.kinds.map((kind) => {
          const blocked = unavailableReason(kind);
          const summaryKey = KIND_SUMMARY_KEYS[kind.key];
          const isOn = enabled[kind.key] === true;
          return (
            <div
              key={kind.key}
              className={`overlay_choice ${kind.key === selected ? "overlay_choice--on" : ""}`}
            >
              <button
                type="button"
                className="overlay_choice_select"
                aria-pressed={kind.key === selected}
                onClick={() => onSelect(kind.key)}
              >
                <span className="overlay_choice_head">
                  <Icon
                    name={KIND_ICONS[kind.key] ?? KIND_ICON_OTHER}
                    size={15}
                  />
                  <strong>{kindTitle(kind)}</strong>
                  {kind.is_active && (
                    <span className="badge">{t("state.active")}</span>
                  )}
                </span>
                {summaryKey !== undefined && (
                  <span className="overlay_choice_summary">
                    {t(summaryKey)}
                  </span>
                )}
                {blocked !== null && (
                  <span className="overlay_choice_blocked">{blocked}</span>
                )}
              </button>
              <ToggleSwitch
                isOn={isOn}
                label={t("ui.overlay.engine_switch")}
                isDisabled={isBusy || (blocked !== null && !isOn)}
                onChange={(isNowOn) => {
                  setError(null);
                  setEnabled({ ...enabled, [kind.key]: isNowOn });
                  onSelect(kind.key);
                }}
              />
            </div>
          );
        })}
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_engine")}
        hint={t("ui.overlay.apply_engine_hint")}
        warning={departureWarning(leaving)}
        error={error}
        onReset={() => setEnabled(storedEnabled(choice))}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What a card is called: an engine's own name, or the word for Direct
 * and the relay. */
function kindTitle(kind: OverlayKindView): string {
  const titleKey = KIND_TITLE_KEYS[kind.key];
  return titleKey === undefined ? kind.title : t(titleKey);
}

/** Why this card's engine cannot be turned on, or null when it can. */
function unavailableReason(kind: OverlayKindView): string | null {
  if (kind.key === KIND_RELAY) {
    return kind.is_installed ? null : t("code.relay_ssh_missing");
  }
  if (!kind.is_integrated) {
    return t("ui.overlay.not_integrated");
  }
  if (!kind.is_supported) {
    return t("ui.overlay.not_supported");
  }
  return null;
}

/**
 * What turning engines off costs: the clients connected through each, and
 * the way into this box from outside where that engine runs now.
 */
function departureWarning(leaving: OverlayKindView[]): string | undefined {
  const lines: string[] = [];
  for (const kind of leaving) {
    if (kind.client_count > 0) {
      lines.push(
        t("ui.overlay.warning_clients", {
          count: kind.client_count,
          title: kindTitle(kind),
        }),
      );
    }
    if (kind.is_active) {
      lines.push(t("ui.overlay.warning_leaving", { title: kindTitle(kind) }));
    }
  }
  if (lines.length === 0) {
    return undefined;
  }
  return interruptionWarning(...lines);
}
