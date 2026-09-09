import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import type { IconName } from "./icon";
import type { StatusTone } from "./status_dot";

import "./tab_strip.css";

/**
 * The row of tabs a page puts directly above the panels one of them owns.
 *
 * The Network page picks an interface this way and the Agent service pages
 * pick a machine, so the strip lives here rather than once per page: a second
 * look for the same act is a second thing to learn.
 */

export interface StripTab {
  key: string;
  icon?: IconName;
  name: string;
  /** The pill beside the name, where a tab has a kind worth a word. */
  tag?: string;
  tagTone?: "accent" | "secondary";
  dotTone?: StatusTone;
}

interface TabStripProps {
  /** What this strip picks from, for a reader who cannot see it. */
  label: string;
  tabs: StripTab[];
  selected: string | null;
  onSelect: (key: string) => void;
}

export function TabStrip({ label, tabs, selected, onSelect }: TabStripProps) {
  return (
    <div className="tab_strip" role="tablist" aria-label={label}>
      {tabs.map((tab) => {
        const isOn = tab.key === selected;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={isOn}
            className={`tab_strip_tab ${isOn ? "tab_strip_tab--on" : ""}`}
            onClick={() => onSelect(tab.key)}
          >
            {tab.icon !== undefined && <Icon name={tab.icon} size={14} />}
            <span className="tab_strip_name">{tab.name}</span>
            {tab.tag !== undefined && (
              <span
                className={`tab_strip_tag ${
                  tab.tagTone === undefined
                    ? ""
                    : `tab_strip_tag--${tab.tagTone}`
                }`}
              >
                {tab.tag}
              </span>
            )}
            {tab.dotTone !== undefined && <StatusDot tone={tab.dotTone} />}
          </button>
        );
      })}
    </div>
  );
}
