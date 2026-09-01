import { useState } from "react";

import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { SignalBars } from "./signal_bars";
import { Spinner } from "./spinner";
import { apiGet, apiPost, describeError } from "../api_client";
import type { NetworkView, WifiNetwork, WifiScan } from "../api_types";

import "./wifi_scan_panel.css";

/**
 * Picking a Wi-Fi network for an interface in the WAN role.
 *
 * Scanning and joining are their own actions rather than part of saving the
 * role, because they fail on their own terms: a wrong passphrase should leave
 * the role alone and say what went wrong, not roll the whole form back.
 *
 * Both take long enough to need a spinner — a scan is a few seconds of radio
 * time, and an association plus DHCP can be twenty. A button that simply sits
 * there for twenty seconds reads as broken.
 */

interface WifiScanPanelProps {
  interfaceName: string;
  joinedSsid: string | null;
  onJoined: (view: NetworkView) => void;
}

export function WifiScanPanel({
  interfaceName,
  joinedSsid,
  onJoined,
}: WifiScanPanelProps) {
  const [networks, setNetworks] = useState<WifiNetwork[] | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [selected, setSelected] = useState<WifiNetwork | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [joiningSsid, setJoiningSsid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scan = async () => {
    setIsScanning(true);
    setError(null);
    try {
      const result = await apiGet<WifiScan>(
        `/network/interfaces/${interfaceName}/wifi/scan`,
      );
      setNetworks(result.networks);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsScanning(false);
    }
  };

  const join = async (network: WifiNetwork, secret: string | null) => {
    setJoiningSsid(network.ssid);
    setError(null);
    try {
      const view = await apiPost<NetworkView>(
        `/network/interfaces/${interfaceName}/wifi/join`,
        { ssid: network.ssid, passphrase: secret },
      );
      onJoined(view);
      setSelected(null);
      setPassphrase("");
      void scan();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setJoiningSsid(null);
    }
  };

  const handlePick = (network: WifiNetwork) => {
    if (network.is_active) {
      return;
    }
    // A known network already has its passphrase in `config/`, and an open one
    // never had one, so neither needs to ask.
    if (network.is_saved || network.security.trim().length === 0) {
      void join(network, null);
      return;
    }
    setSelected(network);
    setPassphrase("");
  };

  return (
    <div className="wifi_scan">
      <div className="wifi_scan_header">
        <div className="wifi_scan_current">
          {joinedSsid === null ? (
            <span className="muted">Not joined to any network.</span>
          ) : (
            <>
              <Icon name="wifi" size={14} />
              <span>
                Joined <strong>{joinedSsid}</strong>
              </span>
            </>
          )}
        </div>
        <button
          type="button"
          className="button button--small"
          onClick={() => void scan()}
          disabled={isScanning || joiningSsid !== null}
        >
          {isScanning ? (
            <Spinner size={12} />
          ) : (
            <Icon name="search" size={13} />
          )}
          {isScanning ? "Scanning…" : "Scan for networks"}
        </button>
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {networks === null ? (
        <p className="field_hint">
          Scan for networks; joining sets this interface to WAN.
        </p>
      ) : networks.length === 0 ? (
        <p className="field_hint">Nothing in range.</p>
      ) : (
        <ul className="wifi_scan_list">
          {networks.map((network) => (
            <li key={network.ssid}>
              <button
                type="button"
                className={`wifi_scan_row ${network.is_active ? "wifi_scan_row--active" : ""}`}
                onClick={() => handlePick(network)}
                disabled={joiningSsid !== null}
              >
                <SignalBars percent={network.signal_percent} isLabelled />
                <span className="wifi_scan_ssid">{network.ssid}</span>
                <span className="wifi_scan_tags">
                  {network.security.trim().length === 0 ? (
                    <span className="badge badge--warn">open</span>
                  ) : (
                    <span className="badge">{network.security}</span>
                  )}
                  {network.is_saved && !network.is_active && (
                    <span className="badge">saved</span>
                  )}
                  {network.is_active && (
                    <span className="badge badge--ok">joined</span>
                  )}
                </span>
                {joiningSsid === network.ssid && <Spinner size={13} />}
              </button>

              {selected?.ssid === network.ssid && (
                <div className="wifi_scan_join">
                  <label className="field">
                    <span className="field_label">
                      Passphrase for {network.ssid}
                    </span>
                    <PasswordInput
                      value={passphrase}
                      onChange={setPassphrase}
                      placeholder="network passphrase"
                      autoFocus
                    />
                  </label>
                  <div className="button_row">
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      onClick={() => setSelected(null)}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="button button--primary button--small"
                      onClick={() => void join(network, passphrase)}
                      disabled={passphrase.length === 0 || joiningSsid !== null}
                    >
                      {joiningSsid === network.ssid ? (
                        <Spinner size={12} />
                      ) : (
                        <Icon name="link" size={13} />
                      )}
                      {joiningSsid === network.ssid ? "Joining…" : "Join"}
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
