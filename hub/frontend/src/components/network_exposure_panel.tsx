import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { interruptionWarning } from "../network_warnings";
import { useDraftSeeding } from "../use_draft_seeding";
import type {
  InterfaceView,
  NetworkOptions,
  NetworkView,
  OverlayView,
} from "../api_types";

import "./network_exposure_panel.css";

/**
 * Which networks the services on this box answer on.
 *
 * One answer per network and no port list: every service binds every address
 * and settles its own port in its own tab, so the network is what is left to
 * decide. It lands in the nftables input chain.
 *
 * An overlay is one of them. Joining one is joining your own network, so it
 * starts open, and closing it says first how many devices that would cut off.
 */

const KIND_ICONS: Record<string, IconName> = {
  wifi: "wifi",
  modem: "globe",
  vlan: "network",
  ethernet: "link",
};

interface NetworkExposurePanelProps {
  network: NetworkView;
  onApplied: (view: NetworkView) => void;
}

export function NetworkExposurePanel({
  network,
  onApplied,
}: NetworkExposurePanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const applied = exposedNames(network);
  const appliedOverlays = exposedProviders(network);
  const [chosen, setChosen] = useState<string[]>(applied);
  const [chosenOverlays, setChosenOverlays] =
    useState<string[]>(appliedOverlays);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The page polls, and a chip turned off but not applied stays off until
  // Apply or Reset says otherwise.
  const isReseedable = useDraftSeeding(
    namesPayload([...chosen, ...chosenOverlays]),
    namesPayload([...applied, ...appliedOverlays]),
  );

  useEffect(() => {
    const fresh = exposedNames(network);
    const freshOverlays = exposedProviders(network);
    if (!isReseedable(namesPayload([...fresh, ...freshOverlays]))) {
      return;
    }
    setChosen(fresh);
    setChosenOverlays(freshOverlays);
  }, [network, isReseedable]);

  const isDirty =
    !sameSet(chosen, applied) || !sameSet(chosenOverlays, appliedOverlays);
  // A trunk carries no traffic of its own; what answers is each VLAN on it.
  const offered = network.interfaces.filter(
    (entry) => entry.settings.role !== "split",
  );
  const closing = applied.filter((name) => !chosen.includes(name));
  const closingOverlays = network.overlays.filter(
    (overlay) =>
      overlay.is_exposed && !chosenOverlays.includes(overlay.provider),
  );
  const openedUplinks = offered.filter(
    (entry) =>
      entry.settings.role === "wan" && chosen.includes(entry.settings.name),
  );
  // An overlay closes the same way an interface does and costs the same
  // thing, so it is named in the same line rather than only in the count.
  const closingNames = [
    ...closing,
    ...closingOverlays.map((overlay) => overlay.title),
  ];
  const cutOff = [
    ...offered
      .filter((entry) => closing.includes(entry.settings.name))
      .map((entry) => ({
        label: entry.settings.name,
        count: entry.link.device_count,
      })),
    ...closingOverlays.map((overlay) => ({
      label: overlay.title,
      count: overlay.device_count,
    })),
  ].filter((entry) => entry.count > 0);

  const toggle = (name: string) => {
    setNotice(null);
    setChosen((current) =>
      current.includes(name)
        ? current.filter((kept) => kept !== name)
        : [...current, name],
    );
  };

  const toggleOverlay = (provider: string) => {
    setNotice(null);
    setChosenOverlays((current) =>
      current.includes(provider)
        ? current.filter((kept) => kept !== provider)
        : [...current, provider],
    );
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      const options: NetworkOptions = {
        uplink_policy: network.uplink_policy,
        is_inter_lan_allowed: network.is_inter_lan_allowed,
        exposed_interfaces: chosen,
        exposed_overlays: chosenOverlays,
      };
      onApplied(await apiPut<NetworkView>("/network", options));
      setNotice(t("ui.network.exposure_applied"));
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
        <h2>{t("ui.network.exposure_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.network.exposure_hint")}</p>

      <div className="exposure_chips">
        {offered.map((entry) => (
          <ExposureChip
            key={entry.settings.name}
            entry={entry}
            isOn={chosen.includes(entry.settings.name)}
            onToggle={() => toggle(entry.settings.name)}
          />
        ))}
        {network.overlays.map((overlay) => (
          <OverlayChip
            key={overlay.provider}
            overlay={overlay}
            isOn={chosenOverlays.includes(overlay.provider)}
            onToggle={() => toggleOverlay(overlay.provider)}
          />
        ))}
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.network.apply_exposure")}
        hint={t("ui.network.apply_exposure_hint")}
        warning={exposureWarning(closingNames, openedUplinks, cutOff)}
        error={error}
        notice={notice}
        onReset={() => {
          setChosen(applied);
          setChosenOverlays(appliedOverlays);
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

interface ExposureChipProps {
  entry: InterfaceView;
  isOn: boolean;
  onToggle: () => void;
}

function ExposureChip({ entry, isOn, onToggle }: ExposureChipProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { settings, link } = entry;
  return (
    <button
      type="button"
      className={`exposure_chip ${isOn ? "exposure_chip--on" : ""}`}
      aria-pressed={isOn}
      onClick={onToggle}
    >
      <Icon name={KIND_ICONS[link.kind] ?? "link"} size={14} />
      <span className="exposure_chip_name mono">{settings.name}</span>
      <span className="exposure_chip_state mono">
        {link.ipv4_address ?? t("state.no_address")}
      </span>
      {settings.role !== "disabled" && (
        <span className="badge">{settings.role}</span>
      )}
    </button>
  );
}

interface OverlayChipProps {
  overlay: OverlayView;
  isOn: boolean;
  onToggle: () => void;
}

function OverlayChip({ overlay, isOn, onToggle }: OverlayChipProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <button
      type="button"
      className={`exposure_chip ${isOn ? "exposure_chip--on" : ""}`}
      aria-pressed={isOn}
      onClick={onToggle}
    >
      <Icon name="mesh" size={14} />
      <span className="exposure_chip_name mono">{overlay.title}</span>
      <span className="exposure_chip_state mono">
        {overlay.address === "" ? t("state.not_up") : overlay.address}
      </span>
      <span className="badge">{t("state.overlay")}</span>
    </button>
  );
}

/**
 * What applying costs: the devices a closed network is carrying, the sessions
 * on it, and an uplink being opened onto the internet. All three are the
 * press's cost rather than what the control does, which is what the
 * description above it carries.
 */
function exposureWarning(
  closing: string[],
  openedUplinks: InterfaceView[],
  cutOff: { label: string; count: number }[],
): string | undefined {
  return interruptionWarning(
    cutOff.length === 0 ? null : devicesCutOff(cutOff),
    closing.length === 0
      ? null
      : t("ui.network.warning_closing", { names: closing.join(", ") }),
    openedUplinks.length === 0
      ? null
      : t("ui.network.warning_uplink_exposed", {
          names: openedUplinks.map((entry) => entry.settings.name).join(", "),
        }),
  );
}

/** The devices reaching the hub across what is being closed, named by where. */
function devicesCutOff(cutOff: { label: string; count: number }[]): string {
  const total = cutOff.reduce((sum, entry) => sum + entry.count, 0);
  const where = cutOff.map((entry) => entry.label).join(", ");
  return total === 1
    ? t("ui.network.warning_cut_off_one", { where })
    : t("ui.network.warning_cut_off_many", { count: total, where });
}

function exposedNames(network: NetworkView): string[] {
  return network.interfaces
    .filter((entry) => entry.settings.is_exposed)
    .map((entry) => entry.settings.name);
}

function exposedProviders(network: NetworkView): string[] {
  return network.overlays
    .filter((overlay) => overlay.is_exposed)
    .map((overlay) => overlay.provider);
}

/** One set of interfaces, in an order two of them can be compared in. */
function namesPayload(names: string[]): string {
  return JSON.stringify([...names].sort());
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((name) => b.includes(name));
}
