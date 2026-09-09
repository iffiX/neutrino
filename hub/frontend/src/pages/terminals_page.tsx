import { useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { DeviceChipStrip } from "../components/device_chip_strip";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ShellTerminal } from "../components/shell_terminal";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_DEVICES } from "../use_hub_events";
import type { DeviceChip } from "../components/device_chip_strip";
import type { DevicesOnlineResponse } from "../api_types";

import "./terminals_page.css";

/**
 * Shells on the machines whose agent is answering, the hub box among them.
 *
 * Every shell runs through the same agent channel, so the box this panel is
 * on is one more chip in the strip rather than a case of its own.
 *
 * Tabs stay mounted while hidden, and the page itself stays mounted while
 * other pages show — the shell hosts it beside the router outlet. Unmounting
 * either would close sockets and kill the shells, so a running build survives
 * both switching tabs here and visiting any other page. A machine that goes
 * offline leaves its tab standing until the shell itself ends.
 */

const WORDING = {
  title: "Terminals",
  root: "root",
  pick: "Which machine",
  pickHint: "A new terminal opens on this machine.",
  newTerminal: "New terminal",
  noDevices: "No machine is answering",
  noDevicesHint: "Install the agent on a machine from the Devices page.",
  noTabs: "No terminals open",
  noTabsHint: "Pick a machine above and open a terminal on it.",
  close: "Close {title}",
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
  const resource = useApiResource<DevicesOnlineResponse>("/devices/online", {
    invalidateOn: INVALIDATE_ON,
  });
  const [searchParams] = useSearchParams();
  const pathname = useLocation().pathname;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<ShellTab[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
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
    setTabs((current) => {
      const remaining = current.filter((tab) => tab.id !== id);
      setActiveId((active) => {
        if (active !== id) {
          return active;
        }
        // Fall back to whichever tab took its place, else the one before it.
        const index = current.findIndex((tab) => tab.id === id);
        const next = remaining[index] ?? remaining[index - 1];
        return next?.id ?? null;
      });
      return remaining;
    });
  };

  if (resource.error !== null && devices.length === 0) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  return (
    <div className="page terminal_page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{WORDING.title}</h1>
          <span className="badge badge--warn">{WORDING.root}</span>
        </div>
        <div className="page_actions">
          <button
            type="button"
            className="button"
            disabled={selectedDevice === null}
            onClick={openTab}
          >
            <Icon name="plus" size={14} />
            {WORDING.newTerminal}
          </button>
        </div>
      </div>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{WORDING.pick}</h2>
        </div>
        <p className="field_hint">{WORDING.pickHint}</p>
        {resource.isLoading && devices.length === 0 ? (
          <div className="skeleton" style={{ height: 48 }} />
        ) : devices.length === 0 ? (
          <div className="placeholder">
            <span>{WORDING.noDevices}</span>
            <span className="faint">{WORDING.noDevicesHint}</span>
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
          <span>{WORDING.noTabs}</span>
          <span className="faint">{WORDING.noTabsHint}</span>
          <button
            type="button"
            className="button button--primary"
            disabled={selectedDevice === null}
            onClick={openTab}
          >
            <Icon name="terminal" size={14} />
            {WORDING.newTerminal}
          </button>
        </div>
      ) : (
        <>
          <div className="terminal_tabs" role="tablist" aria-label="Terminals">
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
                  title={WORDING.close.replace("{title}", tab.title)}
                  aria-label={WORDING.close.replace("{title}", tab.title)}
                >
                  <Icon name="close" size={12} />
                </button>
              </div>
            ))}
          </div>

          {tabs.map((tab) => (
            <ShellTerminal
              key={tab.id}
              socketPath={`/ws/agent_shell/${tab.deviceId}`}
              isVisible={tab.id === activeId}
              onExit={() => closeTab(tab.id)}
            />
          ))}
        </>
      )}
    </div>
  );
}
