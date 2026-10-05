import { useEffect } from "react";

import { EasyTierSection } from "../components/easytier_panels";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { OverlayModePanel } from "../components/overlay_mode_panel";
import { DirectSection } from "../components/direct_panels";
import { RelaySection } from "../components/relay_panels";
import { NetbirdCard } from "../edition";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { usePageMemory } from "../use_page_memory";
import { HUB_EVENT_CONFIG } from "../use_hub_events";
import type { OverlayChoiceView } from "../api_types";

import "./overlay_page.css";

/**
 * How this box is reached from outside: which overlays it runs, and the
 * settings of the one picked below the switches.
 */

/** The engines by the key `config/` names them. */
const PROVIDER_NETBIRD = "netbird";
const PROVIDER_EASYTIER = "easytier";
const PROVIDER_RELAY = "relay";
const PROVIDER_DIRECT = "direct";

// What moves the switches: any write to the hub's own configuration.
const OVERLAY_INVALIDATE_ON = [{ type: HUB_EVENT_CONFIG }];

/** How often the switches are read; clients come and go on their own. */
const OVERLAY_RELOAD_MS = 10000;

export function OverlayPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<OverlayChoiceView>("/hub/overlay", {
    invalidateOn: OVERLAY_INVALIDATE_ON,
  });
  const [picked, setPicked] = usePageMemory<string>("overlay.engine", "");

  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, OVERLAY_RELOAD_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const choice = resource.data;

  if (resource.error !== null && choice === null) {
    return (
      <div className="page">
        <h1>{t("ui.overlay.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (choice === null) {
    return (
      <div className="page">
        <h1>{t("ui.overlay.title")}</h1>
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  const selected =
    picked !== ""
      ? picked
      : (choice.kinds.find((kind) => kind.is_enabled)?.key ??
        choice.kinds[0]?.key ??
        PROVIDER_EASYTIER);
  const isEnabled = (key: string) =>
    choice.kinds.some((kind) => kind.key === key && kind.is_enabled);

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.overlay.title")}</h1>
        </div>
      </div>

      <OverlayModePanel
        choice={choice}
        selected={selected}
        onSelect={setPicked}
        onApplied={resource.setData}
      />

      {choice.route_conflicts.length > 0 && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {choice.route_conflicts.map((conflict) => (
              <div key={`${conflict.code}-${conflict.params.route}`}>
                {t(`code.${conflict.code}`, conflict.params)}{" "}
                {conflict.is_withdrawn
                  ? t("ui.overlay.route_withdrawn")
                  : t("ui.overlay.route_kept")}
              </div>
            ))}
          </div>
        </div>
      )}

      {NetbirdCard !== null &&
        selected === PROVIDER_NETBIRD &&
        isEnabled(PROVIDER_NETBIRD) && <NetbirdCard />}

      {selected === PROVIDER_EASYTIER && isEnabled(PROVIDER_EASYTIER) && (
        <EasyTierSection />
      )}

      {selected === PROVIDER_DIRECT && isEnabled(PROVIDER_DIRECT) && (
        <DirectSection />
      )}

      {selected === PROVIDER_RELAY && isEnabled(PROVIDER_RELAY) && (
        <RelaySection />
      )}
    </div>
  );
}
