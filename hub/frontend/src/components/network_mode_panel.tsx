import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import type { IconName } from "./icon";
import { apiPut, describeError } from "../api_client";
import { interruptionWarning } from "../network_warnings";
import type { NetworkMode, NetworkModeKey, NetworkView } from "../api_types";

import "./network_mode_panel.css";

/**
 * What this whole machine is.
 *
 * First on the page and alone in its section, because everything below it
 * follows from the answer: a server has no uplink to rank and no network to
 * serve, and a page shaped like a router's would be describing a box that is
 * not one.
 *
 * The mode is the only thing this writes. What each interface is for stays
 * where it was — the roles below — and the mode takes one away only where the
 * new shape cannot hold it.
 */

const MODE_LABELS: Record<NetworkModeKey, string> = {
  server: "Server",
  side_gateway: "Side gateway",
  router: "Router",
};

const MODE_ICONS: Record<NetworkModeKey, IconName> = {
  server: "server",
  side_gateway: "link",
  router: "router",
};

interface NetworkModePanelProps {
  network: NetworkView;
  onApplied: (view: NetworkView) => void;
}

export function NetworkModePanel({
  network,
  onApplied,
}: NetworkModePanelProps) {
  const [chosen, setChosen] = useState<NetworkModeKey>(network.mode);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setChosen(network.mode);
  }, [network]);

  const isDirty = chosen !== network.mode;
  const becoming = network.modes.find((mode) => mode.key === chosen) ?? null;

  const apply = async () => {
    if (!isDirty) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      onApplied(await apiPut<NetworkView>("/network/mode", { mode: chosen }));
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
        <h2>Mode</h2>
      </div>
      <p className="field_hint">
        What this machine is. Every section below it follows from the answer.
      </p>

      <div className="mode_choices">
        {network.modes.map((mode) => (
          <button
            key={mode.key}
            type="button"
            className={`mode_choice ${mode.key === chosen ? "mode_choice--on" : ""}`}
            aria-pressed={mode.key === chosen}
            onClick={() => {
              setError(null);
              setChosen(mode.key);
            }}
          >
            <span className="mode_choice_head">
              <Icon name={MODE_ICONS[mode.key]} size={15} />
              <strong>{MODE_LABELS[mode.key]}</strong>
              {mode.key === network.mode && (
                <span className="badge">active</span>
              )}
            </span>
            <span className="mode_choice_summary">{mode.summary}</span>
          </button>
        ))}
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label="Apply mode"
        hint="Rewrites the interface roles and reloads the firewall."
        warning={handoverWarning(network, becoming)}
        error={error}
        onReset={() => setChosen(network.mode)}
        onApply={() => void apply()}
      />
    </section>
  );
}

/**
 * The one thing switching mode can cost: which side of the machine drives the
 * interfaces. Between server and side gateway nothing about addressing changes, so
 * there is nothing to warn about.
 */
function handoverWarning(
  network: NetworkView,
  becoming: NetworkMode | null,
): string | undefined {
  if (
    becoming === null ||
    becoming.is_addressing_owned === network.is_addressing_owned
  ) {
    return undefined;
  }
  return interruptionWarning(
    becoming.is_addressing_owned
      ? "Interface management passes to Neutrino and addresses are reassigned."
      : "Interface management returns to this machine's network manager.",
  );
}
