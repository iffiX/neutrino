import { t, useLanguage } from "../i18n";
import { machineDiskError } from "../podman_machine";
import type { MachineSize } from "../podman_machine";

import "./containers_machine_fields.css";

/**
 * A Podman machine's CPUs, memory and disk limit: the three fields of the Run
 * settings and of the account dialog before an Install. The disk limit's
 * least value is the disk's size now, at least 1 on Windows.
 */

interface ContainersMachineFieldsProps {
  size: MachineSize;
  /** The disk's size now in whole GiB, 0 while the account has no machine. */
  currentDisk: number;
  /** Whether the machine is Windows, whose disk limit is at least 1. */
  isWindows: boolean;
  /** The memory the hint under **Memory** advises, null for no hint. */
  memoryNeedGib: number | null;
  isDisabled: boolean;
  /** Takes the number a field changed. */
  onChange: (change: Partial<MachineSize>) => void;
}

export function ContainersMachineFields({
  size,
  currentDisk,
  isWindows,
  memoryNeedGib,
  isDisabled,
  onChange,
}: ContainersMachineFieldsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const leastDisk = isWindows ? Math.max(1, currentDisk) : currentDisk;
  const diskError = machineDiskError(size.disk_gib, currentDisk, isWindows);

  return (
    <div className="containers_run_numbers">
      <label className="field">
        <span className="field_label">{t("ui.containers.run_cpus")}</span>
        <input
          className="input"
          type="number"
          min={0}
          value={size.cpus}
          disabled={isDisabled}
          onChange={(event) => {
            onChange({ cpus: wholeNumber(event.target.value) });
          }}
        />
      </label>
      <label className="field">
        <span className="field_label">{t("ui.containers.run_memory")}</span>
        <input
          className="input"
          type="number"
          min={0}
          value={size.memory_gib}
          disabled={isDisabled}
          onChange={(event) => {
            onChange({ memory_gib: wholeNumber(event.target.value) });
          }}
        />
        {memoryNeedGib !== null && (
          <span className="field_hint">
            {t("ui.containers.run_memory_need", { need: memoryNeedGib })}
          </span>
        )}
      </label>
      <label className="field">
        <span className="field_label">{t("ui.containers.run_disk")}</span>
        <input
          className="input"
          type="number"
          min={leastDisk}
          value={size.disk_gib}
          disabled={isDisabled}
          onChange={(event) => {
            onChange({ disk_gib: wholeNumber(event.target.value) });
          }}
        />
        {diskError !== null ? (
          <span className="field_error">{diskError}</span>
        ) : (
          currentDisk > 0 && (
            <span className="field_hint">
              {t("ui.containers.run_disk_hint", { current: currentDisk })}
            </span>
          )
        )}
      </label>
    </div>
  );
}

/** A number field's text as a count: a whole number, 0 for none. */
function wholeNumber(text: string): number {
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) || value < 0 ? 0 : value;
}
