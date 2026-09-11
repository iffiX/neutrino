/**
 * The shape every warning on the Network page takes.
 *
 * One per section and never two: what the press changes, then what it
 * interrupts. What a control *does* belongs to the section's own description
 * and to the apply bar's hint — a warning carries the cost alone, which is
 * what keeps it worth reading.
 */

import { t } from "./i18n";

/**
 * Compose a warning from the mechanisms that apply, or nothing when none do.
 *
 * @param mechanisms One sentence each, null where that mechanism is not in
 *   play. They are joined in the order given.
 * @returns The warning, or undefined when there is nothing to warn about.
 */
export function interruptionWarning(
  ...mechanisms: (string | null)[]
): string | undefined {
  const said = mechanisms.filter((line): line is string => line !== null);
  if (said.length === 0) {
    return undefined;
  }
  return `${said.join(" ")} ${t("ui.network.warning_interruption")}`;
}
