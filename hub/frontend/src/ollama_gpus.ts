import { t } from "./i18n";
import type { DeviceGpuInfo } from "./api_types";

/** What the Ollama panels draw of a machine's GPUs. */

/** A GPU's name as the report gives it, else its number in the list. */
export function gpuName(gpu: DeviceGpuInfo, place: number): string {
  return gpu.name !== ""
    ? gpu.name
    : t("ui.ollama.gpu_number", { number: place + 1 });
}
