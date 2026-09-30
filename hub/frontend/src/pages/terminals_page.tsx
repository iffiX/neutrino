import { useEffect, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { apiPath, apiPost, describeError } from "../api_client";
import { DevicePick } from "../components/device_pick";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ShellTerminal } from "../components/shell_terminal";
import { StatusDot } from "../components/status_dot";
import { ToggleSwitch } from "../components/toggle_switch";
import { hasWord, t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_DEVICES } from "../use_hub_events";
import type { TerminalState } from "../components/shell_terminal";
import type { StatusTone } from "../components/status_dot";
import type {
  DevicesOnlineResponse,
  TerminalSessionListView,
  TerminalSessionStopRequest,
  TerminalSessionView,
} from "../api_types";

import "./terminals_page.css";

/**
 * Shells on the machines whose agent is answering, the hub box among them.
 *
 * Every shell runs through the same agent channel, so the box this panel is
 * on is one more chip in the strip rather than a case of its own. The page's
 * lower panel carries one tab per shell in its header bar.
 *
 * Tabs stay mounted while hidden, and the page itself stays mounted while
 * other pages show — the shell hosts it beside the router outlet. Every
 * shell is a session the page names by an id it generates. The switch at the
 * panel's foot keeps the current tab's session on its machine when its socket
 * closes; it is off for a new tab. On load the strip shows every kept session
 * of the online machines in the order they were opened, and a click attaches
 * to one. The × on a kept session ends it on the second press.
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

/** Where the machines' sessions are listed and ended. */
const SESSION_PATH = "/agent/terminal/session";

interface ShellTab {
  id: number;
  deviceId: string;
  title: string;
  /** The session the tab names, generated here or read from the list. */
  sessionId: string;
  /** Whether the session stays on its machine when the socket closes. */
  isPersistent: boolean;
  /** Whether the tab has a socket; a kept session attaches on its first click. */
  isAttached: boolean;
  /** Whether the session is one the machine listed, attached with its kept
   * output rather than started. */
  isResumed: boolean;
}

export function TerminalsPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DevicesOnlineResponse>("/hub/device/online", {
    invalidateOn: INVALIDATE_ON,
  });
  const kept = useApiResource<TerminalSessionListView>(SESSION_PATH);
  const [searchParams] = useSearchParams();
  const pathname = useLocation().pathname;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<ShellTab[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [states, setStates] = useState<Record<number, TerminalState>>({});
  const [closeReasons, setCloseReasons] = useState<Record<number, string>>({});
  const [nextId, setNextId] = useState(1);
  // Ending a kept session takes two presses on its ×; the first only arms it.
  const [armedId, setArmedId] = useState<number | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const isRestoredRef = useRef(false);

  // The page is mounted for the whole session, so a link arriving with a
  // machine on it is a change of query rather than a first render.
  const askedDeviceId = searchParams.get(DEVICE_QUERY);
  useEffect(() => {
    if (pathname === PAGE_PATH && askedDeviceId !== null) {
      setSelectedId(askedDeviceId);
    }
  }, [pathname, askedDeviceId]);

  // The kept sessions become tabs once, when the page first reads them.
  const keptSessions = kept.data?.sessions ?? null;
  useEffect(() => {
    if (keptSessions === null || isRestoredRef.current) {
      return;
    }
    isRestoredRef.current = true;
    const restored = keptSessions.filter((session) => session.is_persistent);
    if (restored.length === 0) {
      return;
    }
    setTabs((current) => [
      ...restored
        .filter((session) =>
          current.every((tab) => tab.sessionId !== session.session_id),
        )
        .map((session, index) => keptTab(session, -(index + 1))),
      ...current,
    ]);
  }, [keptSessions]);

  const devices = resource.data?.devices ?? [];
  const selectedDevice =
    devices.find((device) => device.device_id === selectedId) ?? null;
  const activeTab = tabs.find((tab) => tab.id === activeId) ?? null;
  const activeState =
    activeTab === null || !activeTab.isAttached
      ? null
      : (states[activeTab.id] ?? "connecting");
  const activeReason =
    activeTab === null ? "" : (closeReasons[activeTab.id] ?? "");

  const openTab = () => {
    if (selectedDevice === null) {
      return;
    }
    const tab: ShellTab = {
      id: nextId,
      deviceId: selectedDevice.device_id,
      title: selectedDevice.name,
      sessionId: newSessionId(),
      isPersistent: false,
      isAttached: true,
      isResumed: false,
    };
    setTabs((current) => [...current, tab]);
    setActiveId(tab.id);
    setNextId((current) => current + 1);
  };

  const selectTab = (id: number) => {
    setActiveId(id);
    setArmedId(null);
    setTabs((current) =>
      current.map((tab) =>
        tab.id === id ? { ...tab, isAttached: true } : tab,
      ),
    );
  };

  const dropTab = (id: number) => {
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

  // A tab's session ends with its socket unless it is kept; a kept one is
  // ended on its machine, after a second press.
  const closeTab = async (tab: ShellTab) => {
    if (!tab.isPersistent) {
      dropTab(tab.id);
      return;
    }
    if (armedId !== tab.id) {
      setArmedId(tab.id);
      setStopError(null);
      return;
    }
    setArmedId(null);
    const request: TerminalSessionStopRequest = {
      device_id: tab.deviceId,
      session_id: tab.sessionId,
    };
    try {
      await apiPost<TerminalSessionListView>(`${SESSION_PATH}/stop`, request);
      dropTab(tab.id);
    } catch (cause: unknown) {
      setStopError(describeError(cause));
    }
  };

  const setPersistent = (id: number, isPersistent: boolean) => {
    setTabs((current) =>
      current.map((tab) => (tab.id === id ? { ...tab, isPersistent } : tab)),
    );
  };

  const noteState = (id: number, state: TerminalState) => {
    setStates((current) => ({ ...current, [id]: state }));
  };

  const noteCloseReason = (id: number, reason: string) => {
    setCloseReasons((current) => ({ ...current, [id]: reason }));
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

      <DevicePick
        devices={devices}
        isLoading={resource.isLoading}
        hint={t("ui.terminals.pick_hint")}
        selected={selectedId}
        onSelect={setSelectedId}
        actions={
          <button
            type="button"
            className="button button--primary button--commit"
            disabled={selectedDevice === null}
            onClick={openTab}
          >
            <Icon name="plus" size={14} />
            {t("ui.terminals.new_terminal")}
          </button>
        }
      />

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
              {tabs.map((tab) => {
                const isArmed = armedId === tab.id;
                const closeLabel = t(
                  !tab.isPersistent
                    ? "ui.terminals.close"
                    : isArmed
                      ? "ui.terminals.end_again"
                      : "ui.terminals.end",
                  { title: tab.title },
                );
                return (
                  <div
                    key={tab.id}
                    className={`terminal_tab ${tab.id === activeId ? "terminal_tab--on" : ""}`}
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-selected={tab.id === activeId}
                      className="terminal_tab_label"
                      onClick={() => selectTab(tab.id)}
                    >
                      <Icon name="terminal" size={13} />
                      {tab.title}
                    </button>
                    <button
                      type="button"
                      className={`terminal_tab_close ${isArmed ? "terminal_tab_close--armed" : ""}`}
                      onClick={() => void closeTab(tab)}
                      title={closeLabel}
                      aria-label={closeLabel}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </div>
                );
              })}
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
            {tabs
              .filter((tab) => tab.isAttached)
              .map((tab) => (
                <ShellTerminal
                  key={tab.id}
                  socketPath={apiPath("/ws/agent/terminal", {
                    device_id: tab.deviceId,
                    session_id: tab.sessionId,
                    is_resumed: tab.isResumed ? "true" : undefined,
                  })}
                  isVisible={tab.id === activeId}
                  isPersistent={tab.isPersistent}
                  onExit={() => dropTab(tab.id)}
                  onStateChange={(state) => noteState(tab.id, state)}
                  onCloseReason={(reason) => noteCloseReason(tab.id, reason)}
                />
              ))}
            {activeTab !== null && !activeTab.isAttached && (
              <div className="placeholder">
                <span>{t("ui.terminals.kept")}</span>
                <span className="faint">{t("ui.terminals.kept_hint")}</span>
              </div>
            )}
          </div>

          <div className="terminal_panel_status">
            <span className="terminal_panel_status_text">
              {stopError !== null
                ? stopError
                : activeState === "closed"
                  ? closedText(activeReason)
                  : t("ui.terminals.keystrokes")}
            </span>
            {activeTab !== null && (
              <ToggleSwitch
                isOn={activeTab.isPersistent}
                label={t("ui.terminals.persistent")}
                isDisabled={activeState !== "open"}
                onChange={(isOn) => setPersistent(activeTab.id, isOn)}
              />
            )}
          </div>
        </section>
      )}
    </div>
  );
}

/** A kept session as a tab that attaches on its first click. */
function keptTab(session: TerminalSessionView, id: number): ShellTab {
  return {
    id,
    deviceId: session.device_id,
    title: session.device_name,
    sessionId: session.session_id,
    isPersistent: true,
    isAttached: false,
    isResumed: true,
  };
}

/** A fresh session id: a uuid4 as 32 lowercase hex characters. */
function newSessionId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

/** What the foot says once a socket closed: the code's word, else the loss. */
function closedText(reason: string): string {
  const key = `code.${reason}`;
  return reason !== "" && hasWord(key) ? t(key) : t("ui.terminals.lost");
}

/** What one shell's state looks like as a dot. */
function toneFor(state: TerminalState): StatusTone {
  if (state === "open") {
    return "ok";
  }
  return state === "connecting" ? "warn" : "error";
}
