import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { apiPost, apiPut, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { ApplyResult, ProxySettings, SocksPort } from "../api_types";

import "./socks_ports_panel.css";

/**
 * The SOCKS5 listeners an application is pointed at by hand.
 *
 * A listener is a port and one question about it: does what arrives there
 * leave through an exit node, or straight out the uplink. Both are useful at
 * once — a work machine's remote desktop wants to look like it is on this
 * network, while everything else on it wants the exit node — so this is a list
 * rather than a pair of switches.
 *
 * A box that diverts nothing transparently has these ports as the whole of its
 * proxy, which is what the setup wizard is asking about when it offers one.
 */

const PORT_MIN = 1;
const PORT_MAX = 65535;

interface SocksPortsPanelProps {
  /**
   * The settings as the gateway holds them, never the page's draft: applying
   * this box lays its own field over what the box already has, so a
   * half-finished edit in another box is not written by pressing this one.
   */
  applied: ProxySettings;
  onApplied: (settings: ProxySettings) => void;
}

export function SocksPortsPanel({ applied, onApplied }: SocksPortsPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [ports, setPorts] = useState<SocksPort[]>(applied.socks_ports);
  const [draftPort, setDraftPort] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Keyed on the listeners alone. The whole settings object is replaced on
  // every keystroke elsewhere on the page, and resetting on that would throw
  // away a row somebody had just added.
  useEffect(() => {
    setPorts(applied.socks_ports);
  }, [applied.socks_ports]);

  const isDirty = JSON.stringify(ports) !== JSON.stringify(applied.socks_ports);
  const problem = validate(draftPort, ports);

  const add = () => {
    if (problem !== null) {
      return;
    }
    setNotice(null);
    setPorts([...ports, { port: Number(draftPort), is_proxied: false }]);
    setDraftPort("");
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await apiPut<ProxySettings>("/proxy", {
        ...applied,
        socks_ports: ports,
      });
      const result = await apiPost<ApplyResult>("/proxy/apply");
      onApplied(saved);
      if (result.is_applied) {
        setNotice(result.message);
      } else {
        setError(result.message);
      }
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
        <h2>{t("ui.proxy.ports_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.proxy.ports_hint")}</p>

      {ports.length === 0 && (
        <div className="placeholder">
          <span className="faint">{t("ui.proxy.ports_empty")}</span>
        </div>
      )}
      {ports.length > 0 && (
        <ul className="socks_rows">
          {ports.map((entry, index) => (
            <li className="socks_row" key={entry.port}>
              <span className="socks_row_port mono">{entry.port}</span>
              <div className="socks_row_choice">
                <button
                  type="button"
                  className={`socks_choice ${entry.is_proxied ? "" : "socks_choice--on"}`}
                  aria-pressed={!entry.is_proxied}
                  onClick={() => setPorts(retarget(ports, index, false))}
                >
                  {t("ui.proxy.port_direct")}
                </button>
                <button
                  type="button"
                  className={`socks_choice ${entry.is_proxied ? "socks_choice--on" : ""}`}
                  aria-pressed={entry.is_proxied}
                  onClick={() => setPorts(retarget(ports, index, true))}
                >
                  {t("ui.proxy.port_exit")}
                </button>
              </div>
              <span className="socks_row_note">
                {entry.is_proxied
                  ? t("ui.proxy.port_exit_note")
                  : t("ui.proxy.port_direct_note")}
              </span>
              <button
                type="button"
                className="button button--ghost button--small"
                aria-label={t("ui.proxy.port_remove", { port: entry.port })}
                onClick={() => setPorts(ports.filter((_, at) => at !== index))}
              >
                <Icon name="close" size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="socks_add">
        <input
          className="input socks_add_port"
          value={draftPort}
          placeholder={t("ui.proxy.port_placeholder")}
          inputMode="numeric"
          onChange={(event) => setDraftPort(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <button
          type="button"
          className="button button--small"
          disabled={problem !== null}
          onClick={add}
        >
          <Icon name="plus" size={13} />
          {t("ui.proxy.port_add")}
        </button>
        {draftPort.length > 0 && problem !== null && (
          <span className="field_error">{problem}</span>
        )}
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.proxy.apply_ports")}
        hint={t("ui.proxy.apply_ports_hint")}
        warning={t("ui.proxy.warning_restart")}
        error={error}
        notice={notice}
        onReset={() => setPorts(applied.socks_ports)}
        onApply={() => void apply()}
      />
    </section>
  );
}

function retarget(
  ports: SocksPort[],
  index: number,
  is_proxied: boolean,
): SocksPort[] {
  return ports.map((entry, at) =>
    at === index ? { ...entry, is_proxied } : entry,
  );
}

/** Why this port cannot be added yet, or null when it can. */
function validate(draft: string, ports: SocksPort[]): string | null {
  if (draft.trim().length === 0) {
    return "";
  }
  const port = Number(draft);
  if (!Number.isInteger(port) || port < PORT_MIN || port > PORT_MAX) {
    return t("ui.proxy.port_range", { min: PORT_MIN, max: PORT_MAX });
  }
  if (ports.some((entry) => entry.port === port)) {
    return t("ui.proxy.port_taken", { port });
  }
  return null;
}
