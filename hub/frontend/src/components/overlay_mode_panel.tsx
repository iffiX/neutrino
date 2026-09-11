import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { interruptionWarning } from "../network_warnings";
import { useDraftSeeding } from "../use_draft_seeding";
import type { OverlayChoiceView, OverlayKindView } from "../api_types";

import "./overlay_mode_panel.css";

/**
 * Which overlay this box is on.
 *
 * First on the page and alone in its section, because what is drawn below it
 * is the chosen engine's own screen. An engine this hub cannot run yet keeps
 * its card and says so on it, so the list is what exists rather than what
 * happens to work today.
 */

const KIND_SUMMARY_KEYS: Record<string, string> = {
  none: "ui.overlay.summary_none",
  netbird: "ui.overlay.summary_netbird",
  easytier: "ui.overlay.summary_easytier",
};

const KIND_ICONS: Record<string, IconName> = {
  none: "blocked",
  netbird: "mesh",
  easytier: "nodes",
};

const KIND_ICON_OTHER: IconName = "mesh";

interface OverlayModePanelProps {
  choice: OverlayChoiceView;
  onApplied: (view: OverlayChoiceView) => void;
}

export function OverlayModePanel({ choice, onApplied }: OverlayModePanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [chosen, setChosen] = useState<string>(choice.provider);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // An engine picked but not applied stays picked.
  const isReseedable = useDraftSeeding(chosen, choice.provider);

  useEffect(() => {
    if (!isReseedable(choice.provider)) {
      return;
    }
    setChosen(choice.provider);
  }, [choice, isReseedable]);

  const isDirty = chosen !== choice.provider;
  const leaving =
    choice.kinds.find((kind) => kind.key === choice.provider) ?? null;

  const apply = async () => {
    if (!isDirty) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPut<OverlayChoiceView>("/overlay", { provider: chosen }),
      );
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
          return (
            <button
              key={kind.key}
              type="button"
              className={`overlay_choice ${kind.key === chosen ? "overlay_choice--on" : ""}`}
              aria-pressed={kind.key === chosen}
              disabled={blocked !== null}
              onClick={() => {
                setError(null);
                setChosen(kind.key);
              }}
            >
              <span className="overlay_choice_head">
                <Icon
                  name={KIND_ICONS[kind.key] ?? KIND_ICON_OTHER}
                  size={15}
                />
                <strong>{kindLabel(kind)}</strong>
                {kind.key === choice.provider && (
                  <span className="badge">{t("state.active")}</span>
                )}
              </span>
              {summaryKey !== undefined && (
                <span className="overlay_choice_summary">{t(summaryKey)}</span>
              )}
              {blocked !== null && (
                <span className="overlay_choice_blocked">{blocked}</span>
              )}
            </button>
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
        onReset={() => setChosen(choice.provider)}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** The product's own name, or the panel's word for the engine that is none. */
function kindLabel(kind: OverlayKindView): string {
  return kind.title === "" ? t("ui.overlay.kind_none") : kind.title;
}

/** Why this card cannot be picked, or null when it can. */
function unavailableReason(kind: OverlayKindView): string | null {
  if (!kind.is_integrated) {
    return t("ui.overlay.not_integrated");
  }
  if (!kind.is_supported) {
    return t("ui.overlay.not_supported");
  }
  return null;
}

/**
 * The one thing switching engine can cost: the way into this box from
 * outside. Leaving an engine that is not running takes nothing away.
 */
function departureWarning(leaving: OverlayKindView | null): string | undefined {
  if (leaving === null || !leaving.is_active) {
    return undefined;
  }
  return interruptionWarning(
    t("ui.overlay.warning_leaving", { title: kindLabel(leaving) }),
  );
}
