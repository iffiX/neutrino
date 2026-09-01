import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { apiPut, describeError } from "../api_client";
import { interruptionWarning } from "../network_warnings";
import type { InterfaceView, NetworkOptions, NetworkView } from "../api_types";

import "./network_exposure_panel.css";

/**
 * Which interfaces the services on this box answer on.
 *
 * One answer per interface and no port list: every service binds every address
 * and settles its own port in its own tab, so the interface is what is left to
 * decide. It lands in the nftables input chain.
 *
 * The overlay is not listed and cannot be closed. It is how a box that answers
 * nowhere else is reached at all.
 */

const KIND_ICONS: Record<string, IconName> = {
  wifi: "wifi",
  modem: "globe",
  vlan: "nodes",
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
  const applied = exposedNames(network);
  const [chosen, setChosen] = useState<string[]>(applied);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setChosen(exposedNames(network));
  }, [network]);

  const isDirty = !sameSet(chosen, applied);
  // A trunk carries no traffic of its own; what answers is each VLAN on it.
  const offered = network.interfaces.filter(
    (entry) => entry.settings.role !== "split",
  );
  const closing = applied.filter((name) => !chosen.includes(name));
  const openedUplinks = offered.filter(
    (entry) =>
      entry.settings.role === "wan" && chosen.includes(entry.settings.name),
  );

  const toggle = (name: string) => {
    setNotice(null);
    setChosen((current) =>
      current.includes(name)
        ? current.filter((kept) => kept !== name)
        : [...current, name],
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
      };
      onApplied(await apiPut<NetworkView>("/network", options));
      setNotice("Applied to the firewall.");
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
        <h2>Exposure</h2>
      </div>
      <p className="field_hint">
        The interfaces on which this box accepts connections to its own
        services: the panel, SSH, DNS, the shares. The overlay accepts them
        whatever is set here.
      </p>

      <div className="exposure_chips">
        {offered.map((entry) => (
          <ExposureChip
            key={entry.settings.name}
            entry={entry}
            isOn={chosen.includes(entry.settings.name)}
            onToggle={() => toggle(entry.settings.name)}
          />
        ))}
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label="Apply exposure"
        hint="Reloads the firewall input chain."
        warning={exposureWarning(closing, openedUplinks)}
        error={error}
        notice={notice}
        onReset={() => setChosen(applied)}
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
        {link.ipv4_address ?? "no address"}
      </span>
      {settings.role !== "disabled" && (
        <span className="badge">{settings.role}</span>
      )}
    </button>
  );
}

/**
 * What applying costs: sessions on an interface being closed, and an uplink
 * being opened onto the internet. Both are the press's cost rather than what
 * the control does, which is what the description above it carries.
 */
function exposureWarning(
  closing: string[],
  openedUplinks: InterfaceView[],
): string | undefined {
  return interruptionWarning(
    closing.length === 0
      ? null
      : `${closing.join(", ")} stops accepting connections.`,
    openedUplinks.length === 0
      ? null
      : `${openedUplinks.map((entry) => entry.settings.name).join(", ")} faces ` +
          "the internet, and exposing it accepts connections there on every " +
          "port this box listens on.",
  );
}

function exposedNames(network: NetworkView): string[] {
  return network.interfaces
    .filter((entry) => entry.settings.is_exposed)
    .map((entry) => entry.settings.name);
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((name) => b.includes(name));
}
