import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { isIpv4Address } from "../ipv4_address";
import type { InterfaceView, NetworkView } from "../api_types";

import "./upstream_gateway_panel.css";

/**
 * The router of the network a side gateway sits on.
 *
 * One field, because one field is all this mode has. The box is already on the
 * network — that is how it was reached — and its address there belongs to
 * whatever handed it out. What it has to be told is where that network's own
 * router is, so what it forwards has somewhere to go.
 *
 * There is no masquerade switch. Traffic leaving by the wire it arrived on has
 * to carry this box's address or the router answers the device directly, the
 * reply never passes back through, and conntrack never sees the session.
 */

interface UpstreamGatewayPanelProps {
  network: NetworkView;
  onApplied: (view: NetworkView) => void;
}

export function UpstreamGatewayPanel({
  network,
  onApplied,
}: UpstreamGatewayPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const joined =
    network.interfaces.find((entry) => entry.settings.role === "lan") ?? null;
  const applied = joined?.settings.lan.upstream_gateway ?? "";
  const [gateway, setGateway] = useState(applied);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setGateway(applied);
  }, [applied]);

  if (joined === null) {
    return null;
  }

  const isDirty = gateway !== applied;
  const isValid = isIpv4Address(gateway);

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      const settings = structuredClone(joined.settings);
      settings.lan.upstream_gateway = gateway;
      onApplied(
        await apiPut<NetworkView>(
          `/network/interfaces/${settings.name}`,
          settings,
        ),
      );
      setNotice(t("ui.network.applied_to", { name: settings.name }));
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
        <h2>{t("ui.network.upstream_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.network.upstream_hint")}</p>

      <JoinedSummary entry={joined} />

      <div className="field_grid">
        <label className="field">
          <span className="field_label">{t("ui.network.field_address")}</span>
          <input
            className="input"
            value={gateway}
            placeholder="192.168.1.1"
            onChange={(event) => {
              setNotice(null);
              setGateway(event.target.value);
            }}
          />
          {isDirty && !isValid ? (
            <span className="field_error">
              {t("ui.network.error_not_ipv4")}
            </span>
          ) : (
            <span className="field_hint">
              {t("ui.network.upstream_address_hint")}
            </span>
          )}
        </label>
      </div>

      <ApplyBar
        isDirty={isDirty && isValid}
        isBusy={isBusy}
        label={t("ui.network.apply_upstream")}
        hint={t("ui.network.apply_upstream_hint")}
        error={error}
        notice={notice}
        onReset={() => setGateway(applied)}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** The port and what it holds, all of it read from the machine. */
function JoinedSummary({ entry }: { entry: InterfaceView }) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const rows: [string, string][] = [
    [t("ui.network.row_interface"), entry.settings.name],
    [t("ui.network.row_address"), entry.link.ipv4_address ?? t("state.none")],
    [
      t("ui.network.row_link"),
      entry.link.is_up ? t("state.up") : t("state.down"),
    ],
  ];
  return (
    <dl className="joined_rows">
      {rows.map(([key, value]) => (
        <div className="joined_row" key={key}>
          <dt>{key}</dt>
          <dd className="mono">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
