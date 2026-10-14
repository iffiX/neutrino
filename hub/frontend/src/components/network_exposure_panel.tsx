import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { interruptionWarning } from "../network_warnings";
import { useDraftSeeding } from "../use_draft_seeding";
import type {
  ExposedRole,
  InterfaceView,
  NetworkOptions,
  NetworkView,
  OverlayView,
  SegmentView,
} from "../api_types";

import "./network_exposure_panel.css";

/**
 * Which segments' hosts reach the hub's own ports.
 *
 * Each interface gives two chips, its IPv4 segment and its IPv6 segment,
 * each naming the networks it holds now and the interface it is on; each
 * overlay gives one. On Linux the answer lands in the nftables input chain,
 * and in firewalld where it runs; on macOS and Windows in the system
 * firewall.
 *
 * Joining an overlay is joining your own network, so its chip starts on,
 * and closing a chip says first how many devices that would cut off.
 */

const KIND_ICONS: Record<string, IconName> = {
  wifi: "wifi",
  modem: "globe",
  vlan: "network",
  ethernet: "link",
};

type Family = "ipv4" | "ipv6";

const FAMILIES: Family[] = ["ipv4", "ipv6"];

type Chosen = Record<Family, string[]>;

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
  const [chosen, setChosen] = useState<Chosen>(applied);
  const [chosenOverlays, setChosenOverlays] =
    useState<string[]>(appliedOverlays);
  const [roles, setRoles] = useState<Record<string, ExposedRole>>({});
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The page polls, and a chip turned off but not applied stays off until
  // Apply or Reset says otherwise.
  const isReseedable = useDraftSeeding(
    choicePayload(chosen, chosenOverlays),
    choicePayload(applied, appliedOverlays),
  );

  useEffect(() => {
    const fresh = exposedNames(network);
    const freshOverlays = exposedProviders(network);
    if (!isReseedable(choicePayload(fresh, freshOverlays))) {
      return;
    }
    setChosen(fresh);
    setChosenOverlays(freshOverlays);
  }, [network, isReseedable]);

  const isLinux = network.hub_os === "linux";
  // A trunk carries no traffic of its own; what answers is each VLAN on it.
  const offered = network.interfaces.filter(
    (entry) => entry.settings.role !== "split",
  );
  const isChosen = (name: string) =>
    FAMILIES.some((family) => chosen[family].includes(name));
  // A router stops a port whose role is disabled, so one with a segment
  // turned on here takes a role in the same row.
  const roleless = offered
    .filter(
      (entry) =>
        network.is_addressing_owned &&
        entry.settings.role === "disabled" &&
        isChosen(entry.settings.name),
    )
    .map((entry) => entry.settings.name);
  const chosenRoles: Record<string, ExposedRole> = {};
  for (const name of roleless) {
    const role = roles[name];
    if (role !== undefined) {
      chosenRoles[name] = role;
    }
  }
  const isRoleMissing = roleless.some((name) => roles[name] === undefined);
  const isDirty =
    FAMILIES.some((family) => !sameSet(chosen[family], applied[family])) ||
    !sameSet(chosenOverlays, appliedOverlays) ||
    Object.keys(chosenRoles).length > 0;
  const closing = offered.flatMap((entry) =>
    FAMILIES.filter(
      (family) =>
        applied[family].includes(entry.settings.name) &&
        !chosen[family].includes(entry.settings.name),
    ).map((family) => ({ entry, family })),
  );
  const closingOverlays = network.overlays.filter(
    (overlay) =>
      overlay.is_exposed && !chosenOverlays.includes(overlay.provider),
  );
  const openedUplinks = offered.filter(
    (entry) => entry.settings.role === "wan" && isChosen(entry.settings.name),
  );
  // An overlay closes the same way a segment does and costs the same thing,
  // so it is named in the same line rather than only in the count.
  const closingNames = [
    ...closing.map(({ entry, family }) =>
      segmentLabel(entry.settings.name, family),
    ),
    ...closingOverlays.map((overlay) => overlay.title),
  ];
  const cutOff = [
    ...closing.map(({ entry, family }) => ({
      label: segmentLabel(entry.settings.name, family),
      count: segmentOf(entry, family).device_count,
    })),
    ...closingOverlays.map((overlay) => ({
      label: overlay.title,
      count: overlay.device_count,
    })),
  ].filter((entry) => entry.count > 0);

  const toggle = (family: Family, name: string) => {
    setNotice(null);
    setChosen((current) => ({
      ...current,
      [family]: current[family].includes(name)
        ? current[family].filter((kept) => kept !== name)
        : [...current[family], name],
    }));
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
        ipv4_exposed_interfaces: chosen.ipv4,
        ipv6_exposed_interfaces: chosen.ipv6,
        exposed_overlays: chosenOverlays,
        interface_roles: chosenRoles,
      };
      onApplied(await apiPost<NetworkView>("/hub/network/set", options));
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
          <div key={entry.settings.name} className="exposure_row">
            {FAMILIES.map((family) => (
              <SegmentChip
                key={family}
                entry={entry}
                family={family}
                isOn={chosen[family].includes(entry.settings.name)}
                onToggle={() => toggle(family, entry.settings.name)}
              />
            ))}
            {roleless.includes(entry.settings.name) && (
              <RolePicker
                entry={entry}
                role={roles[entry.settings.name]}
                onPick={(role) =>
                  setRoles((current) => ({
                    ...current,
                    [entry.settings.name]: role,
                  }))
                }
              />
            )}
          </div>
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
        hint={t(
          isLinux
            ? "ui.network.apply_exposure_hint"
            : "ui.network.apply_exposure_hint_system",
        )}
        warning={exposureWarning(closingNames, openedUplinks, cutOff)}
        blockedHint={
          isDirty && isRoleMissing ? t("ui.network.apply_exposure_hint") : null
        }
        error={error}
        notice={notice}
        onReset={() => {
          setChosen(applied);
          setChosenOverlays(appliedOverlays);
          setRoles({});
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

interface SegmentChipProps {
  entry: InterfaceView;
  family: Family;
  isOn: boolean;
  onToggle: () => void;
}

/** One segment of one interface: its networks, its interface, its role. */
function SegmentChip({ entry, family, isOn, onToggle }: SegmentChipProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { settings, link } = entry;
  const { networks } = segmentOf(entry, family);
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
        {networks.length > 0
          ? networks.join(", ")
          : t(`state.no_${family}_address`)}
      </span>
      {(settings.role === "lan" || settings.role === "wan") && (
        <span className="badge">{settings.role}</span>
      )}
      {entry.is_unsaved && (
        <span className="badge badge--accent">
          {t("ui.network.unsaved_interface")}
        </span>
      )}
    </button>
  );
}

interface RolePickerProps {
  entry: InterfaceView;
  role: ExposedRole | undefined;
  onPick: (role: ExposedRole) => void;
}

/** The roles a router gives a port in one step: WAN, and LAN for a wire. */
function RolePicker({ entry, role, onPick }: RolePickerProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const offered: ExposedRole[] =
    entry.link.kind === "ethernet" ? ["wan", "lan"] : ["wan"];
  return (
    <div className="exposure_roles" role="group">
      {offered.map((value) => (
        <button
          key={value}
          type="button"
          className={`exposure_role ${role === value ? "exposure_role--on" : ""}`}
          aria-pressed={role === value}
          onClick={() => onPick(value)}
        >
          {t(`ui.network.role_${value}`)}
        </button>
      ))}
    </div>
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
 * What applying costs: the devices a closed segment is carrying, the
 * sessions on it, and an uplink's networks being opened. All three are the
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

/** One segment named for a sentence: its interface and its family. */
function segmentLabel(name: string, family: Family): string {
  return t(`ui.network.segment_${family}`, { name });
}

function segmentOf(entry: InterfaceView, family: Family): SegmentView {
  return family === "ipv4" ? entry.ipv4_segment : entry.ipv6_segment;
}

function exposedNames(network: NetworkView): Chosen {
  return {
    ipv4: network.interfaces
      .filter((entry) => entry.settings.is_ipv4_exposed)
      .map((entry) => entry.settings.name),
    ipv6: network.interfaces
      .filter((entry) => entry.settings.is_ipv6_exposed)
      .map((entry) => entry.settings.name),
  };
}

function exposedProviders(network: NetworkView): string[] {
  return network.overlays
    .filter((overlay) => overlay.is_exposed)
    .map((overlay) => overlay.provider);
}

/** Every chip's answer, in an order two of them can be compared in. */
function choicePayload(chosen: Chosen, overlays: string[]): string {
  return JSON.stringify({
    ipv4: [...chosen.ipv4].sort(),
    ipv6: [...chosen.ipv6].sort(),
    overlays: [...overlays].sort(),
  });
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((name) => b.includes(name));
}
