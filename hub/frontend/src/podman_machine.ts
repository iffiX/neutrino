import { t } from "./i18n";
import type { PodmanMachine } from "./api_types";

/** The systems whose containers run in an account's Podman machine. */
export const MACHINE_RUN_OS = ["windows", "darwin"];

/** A Podman machine's three numbers. */
export type MachineSize = Pick<
  PodmanMachine,
  "cpus" | "memory_gib" | "disk_gib"
>;

/** Describes a disk limit the machine refuses, null for one it takes. */
export function machineDiskError(
  diskGib: number,
  currentDisk: number,
  isWindows: boolean,
): string | null {
  if (isWindows && diskGib < 1) {
    return t("code.machine_disk_invalid", { disk_gib: diskGib });
  }
  if (diskGib !== 0 && diskGib < currentDisk) {
    return t("code.machine_disk_shrink", {
      disk_gib: diskGib,
      current_gib: currentDisk,
    });
  }
  return null;
}
