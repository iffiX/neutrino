import { useEffect, useState } from "react";
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
import { HUB_EVENT_DEVICE_REPORT, HUB_EVENT_DEVICES } from "../use_hub_events";
import type { PersistFlags, TerminalState } from "../components/shell_terminal";
import type { StatusTone } from "../components/status_dot";
import type {
  ClientListView,
  DevicesOnlineResponse,
  TerminalSessionListView,
  TerminalSessionStopRequest,
  TerminalSessionView,
} from "../api_types";

import "./terminals_page.css";

/**
 * Shells on the machines whose agent is answering, the hub box among them.
 *
 * The tabs come from the hub's session list, which names every session of
 * every online machine: a listed session with no tab gets one, and a tab
 * whose session left the list reads Ended and keeps its output. The first tab
 * attaches as the page opens, the others when first picked; a session another
 * viewer opened and did not share is listed but never attached. Two switches
 * set whether the current session outlives its sockets and whether other
 * viewers see it; only the session's owner flips them. Tabs stay mounted while
 * hidden, and the page itself stays mounted while other pages show.
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

// What moves the session list: a machine's report naming other sessions, or
// a machine coming or going.
const SESSIONS_INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICE_REPORT },
  { type: HUB_EVENT_DEVICES },
];

/** The query a page link carries to open on one machine. */
const DEVICE_QUERY = "device";

/** Where that link lands, which is the only place the query means anything. */
const PAGE_PATH = "/terminals";

/** Where the machines' sessions are listed and ended. */
const SESSION_PATH = "/agent/terminal/session";

/** Where the clients' names are read, to say who opened a session. */
const CLIENT_PATH = "/hub/client";

/** The prefix of the owner the hub stamps on a client's session. */
const CLIENT_OWNER_PREFIX = "client:";

/** The flags a tab shows before the machine has listed its session. */
const NEW_FLAGS: PersistFlags = { is_persistent: false, is_shared: false };

interface ShellTab {
  /** The session the tab names, generated here or read from the list. */
  sessionId: string;
  deviceId: string;
  title: string;
  /** Whether the tab has a socket; a listed session attaches when picked. */
  isAttached: boolean;
  /** Whether the panel may attach: its own session or a shared one. */
  isAttachable: boolean;
  /** Whether the session is one the machine listed, attached with its kept
   * output rather than started. */
  isResumed: boolean;
  /** Whether the machine has listed the session since the tab opened. */
  isListed: boolean;
  /** Whether the session left the list or its shell exited. */
  isEnded: boolean;
}

export function TerminalsPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<DevicesOnlineResponse>("/hub/device/online", {
    invalidateOn: INVALIDATE_ON,
  });
  const listing = useApiResource<TerminalSessionListView>(SESSION_PATH, {
    invalidateOn: SESSIONS_INVALIDATE_ON,
  });
  const clients = useApiResource<ClientListView>(CLIENT_PATH);
  const [searchParams] = useSearchParams();
  const pathname = useLocation().pathname;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<ShellTab[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [states, setStates] = useState<Record<string, TerminalState>>({});
  const [closeReasons, setCloseReasons] = useState<Record<string, string>>({});
  // A flip shows at once and holds until the list reports the same values.
  const [pendingFlags, setPendingFlags] = useState<
    Record<string, PersistFlags>
  >({});
  // Each flip is a new object, which the terminal sends once.
  const [persistRequests, setPersistRequests] = useState<
    Record<string, PersistFlags>
  >({});
  // Sessions whose tab was closed while they stay listed: not reopened.
  const [dismissedIds, setDismissedIds] = useState<string[]>([]);
  // Ending a session takes two presses on its ×; the first only arms it.
  const [armedId, setArmedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The page is mounted for the whole session, so a link arriving with a
  // machine on it is a change of query rather than a first render.
  const askedDeviceId = searchParams.get(DEVICE_QUERY);
  useEffect(() => {
    if (pathname === PAGE_PATH && askedDeviceId !== null) {
      setSelectedId(askedDeviceId);
    }
  }, [pathname, askedDeviceId]);

  const listed = listing.data?.sessions ?? null;

  // Every read of the list is merged into the tabs, and settles the flips
  // the machine has now taken.
  useEffect(() => {
    if (listed === null) {
      return;
    }
    setTabs((current) => mergeTabs(current, listed, dismissedIds));
    setPendingFlags((current) => settledFlags(current, listed));
  }, [listed, dismissedIds]);

  const rows: Record<string, TerminalSessionView> = {};
  for (const row of listed ?? []) {
    rows[row.session_id] = row;
  }

  const attach = (sessionId: string) => {
    setActiveId(sessionId);
    setTabs((current) => withAttached(current, sessionId));
  };

  // The first tab attaches as the page opens.
  const firstSessionId = tabs[0]?.sessionId ?? null;
  const isActiveShown = tabs.some((tab) => tab.sessionId === activeId);
  useEffect(() => {
    if (!isActiveShown && firstSessionId !== null) {
      setActiveId(firstSessionId);
      setTabs((current) => withAttached(current, firstSessionId));
    }
  }, [isActiveShown, firstSessionId]);

  const devices = resource.data?.devices ?? [];
  const selectedDevice =
    devices.find((device) => device.device_id === selectedId) ?? null;
  const activeTab = tabs.find((tab) => tab.sessionId === activeId) ?? null;
  const activeRow = activeTab === null ? undefined : rows[activeTab.sessionId];
  const activeState =
    activeTab === null || !activeTab.isAttached
      ? null
      : (states[activeTab.sessionId] ?? "connecting");
  const activeReason =
    activeTab === null ? "" : (closeReasons[activeTab.sessionId] ?? "");
  const activeFlags =
    activeTab === null
      ? NEW_FLAGS
      : shownFlags(activeTab, activeRow, pendingFlags);
  const isActiveOwned =
    activeTab !== null && isOwned(activeTab, activeRow) && !activeTab.isEnded;
  const canFlip = isActiveOwned && activeState === "open";
  const ownerName =
    activeRow === undefined || activeRow.is_owned
      ? ""
      : nameOfOwner(activeRow.owner, clients.data);

  const openTab = () => {
    if (selectedDevice === null) {
      return;
    }
    const tab: ShellTab = {
      sessionId: newSessionId(),
      deviceId: selectedDevice.device_id,
      title: selectedDevice.name,
      isAttached: true,
      isAttachable: true,
      isResumed: false,
      isListed: false,
      isEnded: false,
    };
    setTabs((current) => [...current, tab]);
    setActiveId(tab.sessionId);
  };

  const selectTab = (sessionId: string) => {
    setArmedId(null);
    setNotice(null);
    attach(sessionId);
  };

  const dropTab = (sessionId: string) => {
    const index = tabs.findIndex((tab) => tab.sessionId === sessionId);
    const remaining = tabs.filter((tab) => tab.sessionId !== sessionId);
    setTabs(remaining);
    if (rows[sessionId] !== undefined) {
      setDismissedIds((current) => [...current, sessionId]);
    }
    // Fall back to whichever tab took its place, else the one before it.
    if (activeId === sessionId) {
      const next = remaining[index] ?? remaining[index - 1];
      if (next !== undefined) {
        attach(next.sessionId);
      } else {
        setActiveId(null);
      }
    }
  };

  // An ended tab and a plain session of this page's own close with the tab;
  // any other session is ended on its machine, after a second press.
  const closeTab = async (tab: ShellTab) => {
    if (isPlainTab(tab, rows[tab.sessionId], pendingFlags)) {
      dropTab(tab.sessionId);
      return;
    }
    if (armedId !== tab.sessionId) {
      setArmedId(tab.sessionId);
      setNotice(null);
      return;
    }
    setArmedId(null);
    const request: TerminalSessionStopRequest = {
      device_id: tab.deviceId,
      session_id: tab.sessionId,
    };
    try {
      await apiPost<TerminalSessionListView>(`${SESSION_PATH}/stop`, request);
      dropTab(tab.sessionId);
    } catch (cause: unknown) {
      setNotice(describeError(cause));
    }
  };

  const flip = (sessionId: string, flags: PersistFlags) => {
    setNotice(null);
    setPendingFlags((current) => ({ ...current, [sessionId]: flags }));
    setPersistRequests((current) => ({
      ...current,
      [sessionId]: { ...flags },
    }));
  };

  const noteRefused = (sessionId: string, code: string) => {
    setPendingFlags((current) => withoutKey(current, sessionId));
    setNotice(describeCode(code));
  };

  const noteExit = (sessionId: string) => {
    setTabs((current) =>
      current.map((tab) =>
        tab.sessionId === sessionId ? { ...tab, isEnded: true } : tab,
      ),
    );
  };

  const noteState = (sessionId: string, state: TerminalState) => {
    setStates((current) => ({ ...current, [sessionId]: state }));
  };

  const noteCloseReason = (sessionId: string, reason: string) => {
    setCloseReasons((current) => ({ ...current, [sessionId]: reason }));
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
              {tabs.map((tab) => (
                <TerminalTab
                  key={tab.sessionId}
                  tab={tab}
                  row={rows[tab.sessionId]}
                  flags={shownFlags(tab, rows[tab.sessionId], pendingFlags)}
                  isOn={tab.sessionId === activeId}
                  isArmed={armedId === tab.sessionId}
                  isPlain={isPlainTab(tab, rows[tab.sessionId], pendingFlags)}
                  onSelect={() => selectTab(tab.sessionId)}
                  onClose={() => void closeTab(tab)}
                />
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
            {tabs
              .filter((tab) => tab.isAttached)
              .map((tab) => (
                <ShellTerminal
                  key={tab.sessionId}
                  socketPath={apiPath("/ws/agent/terminal", {
                    device_id: tab.deviceId,
                    session_id: tab.sessionId,
                    is_resumed: tab.isResumed ? "true" : undefined,
                  })}
                  isVisible={tab.sessionId === activeId}
                  persistFlags={persistRequests[tab.sessionId] ?? null}
                  onExit={() => noteExit(tab.sessionId)}
                  onRefused={(code) => noteRefused(tab.sessionId, code)}
                  onStateChange={(state) => noteState(tab.sessionId, state)}
                  onCloseReason={(reason) =>
                    noteCloseReason(tab.sessionId, reason)
                  }
                />
              ))}
            {activeTab !== null &&
              !activeTab.isAttached &&
              !activeTab.isEnded && (
                <div className="placeholder">
                  <span>{t("ui.terminals.private", { owner: ownerName })}</span>
                  <span className="faint">
                    {t("ui.terminals.private_hint")}
                  </span>
                </div>
              )}
          </div>

          <div className="terminal_panel_status">
            <span className="terminal_panel_status_text">
              {notice !== null
                ? notice
                : activeTab !== null && activeTab.isEnded
                  ? t("ui.terminals.ended_hint")
                  : activeState === "closed"
                    ? closedText(activeReason)
                    : t("ui.terminals.keystrokes")}
            </span>
            {activeTab !== null && (
              <div className="terminal_panel_switches">
                {!isActiveOwned && ownerName !== "" && (
                  <span className="terminal_panel_owner">
                    {t("ui.terminals.opened_by", { owner: ownerName })}
                  </span>
                )}
                <ToggleSwitch
                  isOn={activeFlags.is_persistent}
                  label={t("ui.terminals.persistent")}
                  isDisabled={!canFlip}
                  onChange={(isOn) =>
                    flip(activeTab.sessionId, {
                      ...activeFlags,
                      is_persistent: isOn,
                    })
                  }
                />
                <ToggleSwitch
                  isOn={activeFlags.is_shared}
                  label={t("ui.terminals.shared")}
                  isDisabled={!canFlip}
                  onChange={(isOn) =>
                    flip(activeTab.sessionId, {
                      ...activeFlags,
                      is_shared: isOn,
                    })
                  }
                />
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

interface TerminalTabProps {
  tab: ShellTab;
  row: TerminalSessionView | undefined;
  flags: PersistFlags;
  isOn: boolean;
  isArmed: boolean;
  /** Whether × closes the tab rather than ending the session. */
  isPlain: boolean;
  onSelect: () => void;
  onClose: () => void;
}

function TerminalTab({
  tab,
  row,
  flags,
  isOn,
  isArmed,
  isPlain,
  onSelect,
  onClose,
}: TerminalTabProps) {
  const closeLabel = t(
    isPlain
      ? "ui.terminals.close"
      : isArmed
        ? "ui.terminals.end_again"
        : "ui.terminals.end",
    { title: tab.title },
  );
  const attachedCount = row?.attached_count ?? 0;
  return (
    <div className={`terminal_tab ${isOn ? "terminal_tab--on" : ""}`}>
      <button
        type="button"
        role="tab"
        aria-selected={isOn}
        className="terminal_tab_label"
        onClick={onSelect}
      >
        <Icon name="terminal" size={13} />
        {tab.isEnded ? t("ui.terminals.ended") : tab.title}
        {!tab.isEnded && flags.is_persistent && (
          <span className="badge">{t("ui.terminals.badge_kept")}</span>
        )}
        {!tab.isEnded && flags.is_shared && (
          <span className="badge">{t("ui.terminals.badge_shared")}</span>
        )}
        {!tab.isEnded && attachedCount > 1 && (
          <span className="badge">
            {t("ui.terminals.badge_attached", { count: attachedCount })}
          </span>
        )}
      </button>
      <button
        type="button"
        className={`terminal_tab_close ${isArmed ? "terminal_tab_close--armed" : ""}`}
        onClick={onClose}
        title={closeLabel}
        aria-label={closeLabel}
      >
        <Icon name="close" size={12} />
      </button>
    </div>
  );
}

/** The tabs after one read of the list: listed sessions with no tab added at
 * the end, and tabs whose session left the list marked ended. */
function mergeTabs(
  current: ShellTab[],
  listed: TerminalSessionView[],
  dismissedIds: string[],
): ShellTab[] {
  const merged = current.map((tab) => {
    const row = listed.find((entry) => entry.session_id === tab.sessionId);
    if (row !== undefined) {
      return {
        ...tab,
        isListed: true,
        isAttachable: row.is_owned || row.is_shared,
      };
    }
    return tab.isListed && !tab.isEnded ? { ...tab, isEnded: true } : tab;
  });
  const held = new Set(current.map((tab) => tab.sessionId));
  for (const row of listed) {
    if (held.has(row.session_id) || dismissedIds.includes(row.session_id)) {
      continue;
    }
    merged.push({
      sessionId: row.session_id,
      deviceId: row.device_id,
      title: row.device_name,
      isAttached: false,
      isAttachable: row.is_owned || row.is_shared,
      isResumed: true,
      isListed: true,
      isEnded: false,
    });
  }
  return merged;
}

/** The flips the list does not yet report, the others dropped. */
function settledFlags(
  pending: Record<string, PersistFlags>,
  listed: TerminalSessionView[],
): Record<string, PersistFlags> {
  const kept: Record<string, PersistFlags> = {};
  for (const [sessionId, flags] of Object.entries(pending)) {
    const row = listed.find((entry) => entry.session_id === sessionId);
    const isSettled =
      row !== undefined &&
      row.is_persistent === flags.is_persistent &&
      row.is_shared === flags.is_shared;
    if (!isSettled) {
      kept[sessionId] = flags;
    }
  }
  return kept;
}

/** The flags a tab shows: a flip not yet reported, else the list's. */
function shownFlags(
  tab: ShellTab,
  row: TerminalSessionView | undefined,
  pending: Record<string, PersistFlags>,
): PersistFlags {
  const flipped = pending[tab.sessionId];
  if (flipped !== undefined) {
    return flipped;
  }
  if (row === undefined) {
    return NEW_FLAGS;
  }
  return { is_persistent: row.is_persistent, is_shared: row.is_shared };
}

/** Whether this panel opened the tab's session; a session not listed yet is
 * one the page itself just opened. */
function isOwned(tab: ShellTab, row: TerminalSessionView | undefined): boolean {
  return row === undefined ? !tab.isListed : row.is_owned;
}

/** Whether × closes the tab: an ended session, or a plain one of the page's
 * own, which ends with its socket. */
function isPlainTab(
  tab: ShellTab,
  row: TerminalSessionView | undefined,
  pending: Record<string, PersistFlags>,
): boolean {
  if (tab.isEnded) {
    return true;
  }
  const flags = shownFlags(tab, row, pending);
  return isOwned(tab, row) && !flags.is_persistent && !flags.is_shared;
}

/** The tabs with one attached, when the panel may attach to its session. */
function withAttached(tabs: ShellTab[], sessionId: string): ShellTab[] {
  return tabs.map((tab) =>
    tab.sessionId === sessionId && tab.isAttachable && !tab.isEnded
      ? { ...tab, isAttached: true }
      : tab,
  );
}

/** Who opened a session, by the client's name where the hub stamped one. */
function nameOfOwner(owner: string, clients: ClientListView | null): string {
  if (!owner.startsWith(CLIENT_OWNER_PREFIX)) {
    return owner;
  }
  const clientId = owner.slice(CLIENT_OWNER_PREFIX.length);
  const client = clients?.clients.find((entry) => entry.id === clientId);
  return client?.name ?? owner;
}

function withoutKey<T>(record: Record<string, T>, key: string) {
  const rest = { ...record };
  delete rest[key];
  return rest;
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

/** A code's word, else the code itself. */
function describeCode(code: string): string {
  const key = `code.${code}`;
  return hasWord(key) ? t(key) : code;
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
