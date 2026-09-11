import { ModuleStateBadge } from "./module_state_badge";
import { StatusDot } from "./status_dot";
import { t, useLanguage } from "../i18n";

import "./device_chip_strip.css";

/**
 * A row of machines to pick from, the way the Network page picks interfaces.
 *
 * Multi-select stages: a chip's on-state is the draft, and a chip whose draft
 * differs from what is applied lights amber, so which machines an Apply would
 * change is readable without comparing two lists. Single-select is plain
 * selection and stages nothing.
 *
 * An offline machine is drawn greyed and cannot be picked: every state under
 * these chips is its agent's report, and there is nothing to act on until it
 * answers.
 */

export interface DeviceChip {
  key: string;
  label: string;
  hostname: string;
  isOnline: boolean;
  /** What is applied for this machine; a draft that differs lights the chip. */
  isChecked?: boolean;
  /** Where the module stands on it, badged where that is worth a word. */
  state?: string;
}

interface DeviceChipStripProps {
  chips: DeviceChip[];
  /** The draft: the picked keys when multi, the picked key when not. */
  selected: string[] | string | null;
  onSelect: (key: string) => void;
  isMulti: boolean;
}

export function DeviceChipStrip({
  chips,
  selected,
  onSelect,
  isMulti,
}: DeviceChipStripProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div
      className="device_chip_strip"
      role={isMulti ? "group" : "tablist"}
      aria-label={t("ui.device_chip_strip.label")}
    >
      {chips.map((chip) => {
        const isOn = isSelected(selected, chip.key);
        const isStaged =
          chip.isChecked !== undefined && chip.isChecked !== isOn;
        return (
          <button
            key={chip.key}
            type="button"
            className={`device_chip ${isOn ? "device_chip--on" : ""} ${
              isStaged ? "device_chip--staged" : ""
            }`}
            disabled={!chip.isOnline}
            aria-pressed={isMulti ? isOn : undefined}
            aria-selected={isMulti ? undefined : isOn}
            role={isMulti ? undefined : "tab"}
            onClick={() => onSelect(chip.key)}
          >
            <span className="device_chip_head">
              <StatusDot tone={chip.isOnline ? "ok" : "idle"} />
              <span className="device_chip_name">{chip.label}</span>
              {chip.state !== undefined && (
                <ModuleStateBadge state={chip.state} />
              )}
            </span>
            <span className="device_chip_host">
              {chip.isOnline ? chip.hostname : t("state.offline")}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Whether one chip is in the draft, whichever shape the draft takes. */
function isSelected(selected: string[] | string | null, key: string): boolean {
  return Array.isArray(selected) ? selected.includes(key) : selected === key;
}
