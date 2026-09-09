import { useState } from "react";

import { Icon } from "../components/icon";
import { ShellTerminal } from "../components/shell_terminal";

import "./terminals_page.css";

/**
 * Shells on the gateway itself.
 *
 * The Devices tab already has terminals, but those reach other machines over
 * SSH; reaching this box that way would mean connecting to itself. So these run
 * directly on a pty here.
 *
 * Tabs stay mounted while hidden, and the page itself stays mounted while
 * other pages show — the shell hosts it beside the router outlet. Unmounting
 * either would close sockets and kill the shells, so a running build survives
 * both switching tabs here and visiting any other page.
 */

interface ShellTab {
  id: number;
  title: string;
}

export function TerminalsPage() {
  const [tabs, setTabs] = useState<ShellTab[]>([{ id: 1, title: "Shell 1" }]);
  const [activeId, setActiveId] = useState<number | null>(1);
  const [nextId, setNextId] = useState(2);

  const openTab = () => {
    const tab = { id: nextId, title: `Shell ${nextId}` };
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

  return (
    <div className="page terminal_page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>Terminals</h1>
          <span className="badge badge--warn">root</span>
        </div>
        <div className="page_actions">
          <button type="button" className="button" onClick={openTab}>
            <Icon name="plus" size={14} />
            New terminal
          </button>
        </div>
      </div>

      {tabs.length === 0 ? (
        <div className="placeholder">
          <span>No terminals open</span>
          <span className="faint">Runs as root on the gateway.</span>
          <button
            type="button"
            className="button button--primary"
            onClick={openTab}
          >
            <Icon name="terminal" size={14} />
            New terminal
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
                  title={`Close ${tab.title}`}
                  aria-label={`Close ${tab.title}`}
                >
                  <Icon name="close" size={12} />
                </button>
              </div>
            ))}
          </div>

          {tabs.map((tab) => (
            <ShellTerminal
              key={tab.id}
              socketPath="/ws/terminal"
              isVisible={tab.id === activeId}
              onExit={() => closeTab(tab.id)}
            />
          ))}
        </>
      )}
    </div>
  );
}
