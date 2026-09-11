import { useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { DeviceChipStrip } from "../components/device_chip_strip";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ShellTerminal } from "../components/shell_terminal";
import { StatusDot } from "../components/status_dot";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_DEVICES } from "../use_hub_events";
import type { DeviceChip } from "../components/device_chip_strip";
import type { TerminalState } from "../components/shell_terminal";
import type { StatusTone } from "../components/status_dot";
import type { DevicesOnlineResponse } from "../api_types";

import "./terminals_page.css";

/**
 * Shells on the machines whose agent is answering, the hub box among them.
 *
 * Every shell runs through the same agent channel, so the box this panel is
 * on is one more chip in the strip rather than a case of its own.
 *
 * The terminal window that used to pop out over the page is the page's own
 * lower panel now, and its header bar carries one tab per open shell.
 *
 * Tabs stay mounted while hidden, and the page itself stays mounted while
 * other pages show — the shell hosts it beside the router outlet. Unmounting
 * either would close sockets and kill the shells, so a running build survives
 * both switching tabs here and visiting any other page. A machine that goes
 * offline leaves its tab standing until the shell itself ends.
 */

/** The account every shell opens as, which is a name rather than a word. */
const TERMINAL_ACCOUNT = "root";

/** What one shell's state is called. */
const STATE_KEYS: Record<TerminalState, string> = {
  connecting: "state.connecting",
  open: "state.open",
  closed: "state.closed",
};

// What moves the list of machines: an agent's channel opening or ending.
const INVALIDATE_ON = [{ type: HUB_EVENT_DEVICES }];

/** The query a page link carries to open on one machine. */
const DEVICE_QUERY = "device";

/** Where that link lands, which is the only place the query means anything. */
const PAGE_PATH = "/terminals";

interface ShellTab {
  id: number;
  deviceId: string;
  title: string;
}

export function TerminalsPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DevicesOnlineResponse>("/devices/online", {
    invalidateOn: INVALIDATE_ON,
  });
  const [searchParams] = useSearchParams();
  const pathname = useLocation().pathname;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<ShellTab[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [states, setStates] = useState<Record<number, TerminalState>>({});
  const [nextId, setNextId] = useState(1);

  // The page is mounted for the whole session, so a link arriving with a
  // machine on it is a change of query rather than a first render.
  const askedDeviceId = searchParams.get(DEVICE_QUERY);
  useEffect(() => {
    if (pathname === PAGE_PATH && askedDeviceId !== null) {
      setSelectedId(askedDeviceId);
    }
  }, [pathname, askedDeviceId]);

  const devices = resource.data?.devices ?? [];
  const chips: DeviceChip[] = devices.map((device) => ({
    key: device.device_id,
    label: device.name,
    hostname: device.hostname,
    isOnline: true,
  }));
  const selectedDevice =
    devices.find((device) => device.device_id === selectedId) ?? null;
  const activeState = activeId === null ? null : (states[activeId] ?? null);

  const openTab = () => {
    if (selectedDevice === null) {
      return;
    }
    const tab = {
      id: nextId,
      deviceId: selectedDevice.device_id,
      title: selectedDevice.name,
    };
    setTabs((current) => [...current, tab]);
    setActiveId(tab.id);
    setNextId((current) => current + 1);
  };

  const closeTab = (id: number) => {
    const index = tabs.findIndex((tab) => tab.id === id);
    const remaining = tabs.filter((tab) => tab.id !== id);
    setTabs(remaining);
    // Fall back to whichever tab took its place, else the one before it.
    setActiveId((active) =>
      active === id
        ? ((remaining[index] ?? remaining[index - 1])?.id ?? null)
        : active,
    );
    setStates((current) => {
      const rest = { ...current };
      delete rest[id];
      return rest;
    });
  };

  const noteState = (id: number, state: TerminalState) => {
    setStates((current) => ({ ...current, [id]: state }));
  };

  if (resource.error !== null && devices.length === 0) {
    return (
      <div className="page">
        <h1>{t("ui.terminals.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page terminal_page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.terminals.title")}</h1>
          <span className="badge badge--warn">{TERMINAL_ACCOUNT}</span>
        </div>
      </div>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.terminals.pick")}</h2>
          <div className="agent_service_actions">
            <button
              type="button"
              className="button button--primary button--commit"
              disabled={selectedDevice === null}
              onClick={openTab}
            >
              <Icon name="plus" size={14} />
              {t("ui.terminals.new_terminal")}
            </button>
          </div>
        </div>
        <p className="field_hint">{t("ui.terminals.pick_hint")}</p>
        {resource.isLoading && devices.length === 0 ? (
          <div className="skeleton" style={{ height: 48 }} />
        ) : devices.length === 0 ? (
          <div className="placeholder">
            <span>{t("ui.terminals.no_devices")}</span>
            <span className="faint">{t("ui.terminals.no_devices_hint")}</span>
          </div>
        ) : (
          <DeviceChipStrip
            chips={chips}
            selected={selectedId}
            onSelect={setSelectedId}
            isMulti={false}
          />
        )}
      </section>

      {tabs.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.terminals.no_tabs")}</span>
          <span className="faint">{t("ui.terminals.no_tabs_hint")}</span>
          <button
            type="button"
            className="button button--primary"
            disabled={selectedDevice === null}
            onClick={openTab}
          >
            <Icon name="terminal" size={14} />
            {t("ui.terminals.new_terminal")}
          </button>
        </div>
      ) : (
        <section className="terminal_panel">
          <div className="terminal_panel_head">
            <div
              className="terminal_tabs"
              role="tablist"
              aria-label={t("ui.terminals.tabs_label")}
            >
              {tabs.map((tab) => (
                <div
                  key={tab.id}
                  className={`terminal_tab ${tab.id === activeId ? "terminal_tab--on" : ""}`}
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={tab.id === activeId}
                    className="terminal_tab_label"
                    onClick={() => setActiveId(tab.id)}
                  >
                    <Icon name="terminal" size={13} />
                    {tab.title}
                  </button>
                  <button
                    type="button"
                    className="terminal_tab_close"
                    onClick={() => closeTab(tab.id)}
                    title={t("ui.terminals.close", { title: tab.title })}
                    aria-label={t("ui.terminals.close", { title: tab.title })}
                  >
                    <Icon name="close" size={12} />
                  </button>
                </div>
              ))}
            </div>
            {activeState !== null && (
              <div className="terminal_panel_actions">
                <StatusDot
                  tone={toneFor(activeState)}
                  label={t(STATE_KEYS[activeState])}
                />
              </div>
            )}
          </div>

          <div className="terminal_panel_surface">
            {tabs.map((tab) => (
              <ShellTerminal
                key={tab.id}
                socketPath={`/ws/agent_shell/${tab.deviceId}`}
                isVisible={tab.id === activeId}
                onExit={() => closeTab(tab.id)}
                onStateChange={(state) => noteState(tab.id, state)}
              />
            ))}
          </div>

          <div className="terminal_panel_status">
            {activeState === "closed"
              ? t("ui.terminals.lost")
              : t("ui.terminals.keystrokes")}
          </div>
        </section>
      )}
    </div>
  );
}

/** What one shell's state looks like as a dot. */
function toneFor(state: TerminalState): StatusTone {
  if (state === "open") {
    return "ok";
  }
  return state === "connecting" ? "warn" : "error";
}
