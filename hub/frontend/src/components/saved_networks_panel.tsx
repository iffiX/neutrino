import { useEffect, useState } from "react";

import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiDelete, apiGet, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useConfirm } from "../use_confirm";
import type { SavedNetwork, SavedNetworkList } from "../api_types";

import "./saved_networks_panel.css";

/**
 * The wireless networks the box knows how to join.
 *
 * One list for the whole box rather than one per radio: the supplicant on each
 * radio holds all of them and picks whichever is in range, so which radio a
 * network was added from is not a thing anybody has to think about.
 *
 * A network read out of whatever managed this machine before says so, because
 * a passphrase the panel never asked for is worth explaining.
 */

export function SavedNetworksPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [networks, setNetworks] = useState<SavedNetwork[] | null>(null);
  const [forgetting, setForgetting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();

  useEffect(() => {
    let isCurrent = true;
    void (async () => {
      try {
        const result = await apiGet<SavedNetworkList>("/network/wifi_networks");
        if (isCurrent) {
          setNetworks(result.networks);
        }
      } catch (cause: unknown) {
        if (isCurrent) {
          setError(describeError(cause));
        }
      }
    })();
    return () => {
      isCurrent = false;
    };
  }, []);

  const forget = (ssid: string) =>
    confirm.ask({
      title: t("ui.network.saved_forget_title", { ssid }),
      body: t("ui.network.saved_forget_body"),
      confirmLabel: t("ui.network.saved_forget"),
      onConfirm: () => void forgetNow(ssid),
    });

  const forgetNow = async (ssid: string) => {
    setForgetting(ssid);
    setError(null);
    try {
      const result = await apiDelete<SavedNetworkList>(
        `/network/wifi_networks/${encodeURIComponent(ssid)}`,
      );
      setNetworks(result.networks);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setForgetting(null);
    }
  };

  if (networks !== null && networks.length === 0 && error === null) {
    return null;
  }

  return (
    <section className="settings_group saved_networks">
      <div className="settings_group_title">
        <h2>{t("ui.network.saved_title")}</h2>
        <p className="field_hint">{t("ui.network.saved_hint")}</p>
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {networks === null ? (
        <div className="skeleton" style={{ height: 72 }} />
      ) : (
        <ul className="saved_networks_list">
          {networks.map((network) => (
            <li key={network.ssid} className="saved_networks_row">
              <Icon name="wifi" size={14} />
              <span className="saved_networks_ssid">{network.ssid}</span>
              <span className="saved_networks_tags">
                {!network.has_secret && (
                  <span
                    className="badge badge--warn"
                    title={t("ui.network.saved_needs_passphrase_title")}
                  >
                    {t("ui.network.saved_needs_passphrase")}
                  </span>
                )}
                {network.is_hidden && (
                  <span className="badge">{t("state.hidden")}</span>
                )}
                {network.source.startsWith("inherited:") && (
                  <span
                    className="badge"
                    title={t("ui.network.saved_inherited_title", {
                      source: network.source.slice("inherited:".length),
                    })}
                  >
                    {t("state.inherited")}
                  </span>
                )}
              </span>
              <button
                type="button"
                className="button button--ghost button--small"
                onClick={() => forget(network.ssid)}
                disabled={forgetting !== null}
              >
                {forgetting === network.ssid ? (
                  <Spinner size={12} />
                ) : (
                  <Icon name="trash" size={13} />
                )}
                {t("ui.network.saved_forget")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {confirm.modal}
    </section>
  );
}
