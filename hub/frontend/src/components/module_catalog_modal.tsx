import { useState } from "react";

import { DialogFrame } from "./dialog_frame";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { ModuleIcon } from "./module_icon";
import { apiPath, apiPost, describeError } from "../api_client";
import { hasWord, t, useLanguage } from "../i18n";
import { moduleTitle } from "../module_title";
import { useApiResource } from "../use_api_resource";
import type {
  DeviceAnnotation,
  DevicesResponse,
  ModuleCatalogEntry,
  ModuleCatalogView,
} from "../api_types";

import "./module_catalog_modal.css";

/**
 * **+ Add module**: the module catalog, a dialog in the install dialog's
 * frame, wider. A search box beside the title and a row of activity filters
 * narrow a grid of cards; each card is a module's icon, its name, one line
 * on it, its activity and a check at its top right. Checking a card adds
 * its tab to the machine page and unchecking takes it away, at once.
 *
 * The modules the agent carries are checked and locked, and so is a module
 * the machine has; a module the machine cannot run is greyed out, and one
 * the hub has no manifest of yet has no check.
 */

const CATALOG_PATH = "/agent/module/catalog";

/** The filter that shows every card. */
const ALL_CATEGORIES = "all";

/** The states in which nothing of the module is on the machine. */
const NOTHING_STATES = ["absent", "unknown", ""];

interface ModuleCatalogModalProps {
  deviceId: string;
  /** Called after a card was checked or unchecked. */
  onChanged: () => void;
  onClose: () => void;
}

export function ModuleCatalogModal({
  deviceId,
  onChanged,
  onClose,
}: ModuleCatalogModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<ModuleCatalogView>(
    apiPath(CATALOG_PATH, { device_id: deviceId }),
  );
  const [category, setCategory] = useState(ALL_CATEGORIES);
  const [search, setSearch] = useState("");
  const [busyName, setBusyName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = resource.data;

  const toggle = async (entry: ModuleCatalogEntry) => {
    if (view === null) {
      return;
    }
    const shown = view.modules
      .filter((held) => held.is_available && held.is_shown)
      .map((held) => held.name);
    const next = entry.is_shown
      ? shown.filter((name) => name !== entry.name)
      : [...shown, entry.name];
    setBusyName(entry.name);
    setError(null);
    const request: DeviceAnnotation = {
      device_id: deviceId,
      shown_module: next,
    };
    try {
      await apiPost<DevicesResponse>("/hub/device/set", request);
      resource.setData({
        ...view,
        modules: view.modules.map((held) =>
          held.name === entry.name
            ? { ...held, is_shown: !entry.is_shown }
            : held,
        ),
      });
      onChanged();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setBusyName(null);
    }
  };

  const entries = view?.modules ?? [];
  const searched = entries.filter((entry) => matchesSearch(entry, search));
  const shown = searched.filter(
    (entry) => category === ALL_CATEGORIES || entry.category === category,
  );
  const categories = (view?.categories ?? []).filter((id) =>
    entries.some((entry) => entry.category === id),
  );

  return (
    <DialogFrame
      title={t("ui.module_catalog.title")}
      icon="plus"
      className="dialog--wide"
      hasHeadClose={false}
      headAction={
        <input
          className="input module_catalog_search"
          placeholder={t("ui.module_catalog.search")}
          aria-label={t("ui.module_catalog.search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      }
      foot={
        <button type="button" className="button" onClick={onClose}>
          {t("ui.module_catalog.close")}
        </button>
      }
      onClose={onClose}
    >
      {resource.error !== null && view === null ? (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      ) : view === null ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : (
        <>
          <div className="module_catalog_filters">
            {[ALL_CATEGORIES, ...categories].map((id) => (
              <button
                key={id}
                type="button"
                className={`module_catalog_filter ${category === id ? "module_catalog_filter--on" : ""}`}
                onClick={() => setCategory(id)}
              >
                {t(`ui.module_catalog.category_${id}`)}
                {id !== ALL_CATEGORIES &&
                  ` · ${searched.filter((entry) => entry.category === id).length}`}
              </button>
            ))}
          </div>
          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}
          {shown.length === 0 ? (
            <div className="placeholder">
              <span>{t("ui.module_catalog.no_matches")}</span>
              <span className="faint">
                {t("ui.module_catalog.no_matches_hint")}
              </span>
            </div>
          ) : (
            <div className="module_catalog_grid">
              {shown.map((entry) => (
                <CatalogCard
                  key={entry.name}
                  entry={entry}
                  isBusy={busyName === entry.name}
                  onToggle={() => void toggle(entry)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </DialogFrame>
  );
}

interface CatalogCardProps {
  entry: ModuleCatalogEntry;
  isBusy: boolean;
  onToggle: () => void;
}

function CatalogCard({ entry, isBusy, onToggle }: CatalogCardProps) {
  const isPresent = !NOTHING_STATES.includes(entry.state);
  const isLocked = entry.is_carried || isPresent;
  const isCheckable = entry.is_available && entry.is_supported;
  const isChecked = entry.is_carried || isPresent || entry.is_shown;
  const lineKey = `ui.module_catalog.${entry.name}`;
  const className = [
    "module_catalog_card",
    isChecked && isCheckable ? "module_catalog_card--on" : "",
    isCheckable ? "" : "module_catalog_card--fixed",
    entry.is_supported ? "" : "module_catalog_card--off",
  ]
    .filter((name) => name !== "")
    .join(" ");
  return (
    <label className={className}>
      {isCheckable && (
        <input
          type="checkbox"
          className="module_catalog_check"
          checked={isChecked}
          disabled={isLocked || isBusy}
          onChange={onToggle}
        />
      )}
      {isPresent && (
        <span className="module_catalog_state badge">
          {t(hasWord(`state.${entry.state}`) ? `state.${entry.state}` : "")}
        </span>
      )}
      <span className="module_catalog_icon">
        <ModuleIcon name={entry.name} size={22} />
      </span>
      <span className="module_catalog_name">
        {moduleTitle(entry.name, entry.title)}
      </span>
      {hasWord(lineKey) && (
        <span className="module_catalog_line">{t(lineKey)}</span>
      )}
      <span className="module_catalog_tag badge">
        {t(`ui.module_catalog.category_${entry.category}`)}
      </span>
    </label>
  );
}

/** Whether a card's name or line holds the typed text. */
function matchesSearch(entry: ModuleCatalogEntry, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (needle === "") {
    return true;
  }
  const lineKey = `ui.module_catalog.${entry.name}`;
  return [
    moduleTitle(entry.name, entry.title),
    hasWord(lineKey) ? t(lineKey) : "",
  ].some((text) => text.toLowerCase().includes(needle));
}
