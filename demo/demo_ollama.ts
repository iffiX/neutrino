import { secondsAgo } from "./demo_fixtures";
import { DemoRefusal } from "./demo_proxy";
import type {
  DeviceGpuInfo,
  DeviceMetricsView,
  ModuleDeviceState,
  OllamaDeviceView,
  OllamaGpuSetting,
  OllamaModel,
  OllamaPull,
  OllamaResourcesView,
} from "../hub/frontend/src/api_types";

/**
 * One machine's Ollama in the fake hub: its settings, its models and its
 * pulls. A pull runs at a home line's speed, one at a time, a load takes a
 * few seconds, and a model in memory takes the room the used GPUs have
 * left before it takes system memory.
 */

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;
const PULL_TICK_MS = 1000;
const PULL_PREPARE_MS = 1500;
const PULL_BYTES_PER_S = 42_000_000;
const PULL_SPEED_SPREAD = 0.3;
const LOAD_MS = 2600;
// What a GPU holds before any model: the desktop and the driver.
const GPU_IDLE_MB = 480;
// A model in memory: its file, plus its context and the runner.
const MEMORY_PER_FILE_BYTE = 1.18;
const MEMORY_OVERHEAD_BYTES = 0.45 * GIB;
const MODEL_NAME = /^[A-Za-z0-9._:/-]{1,200}$/;
// The bits each weight takes in a quantization, for a pulled model's size.
const QUANT_BITS: [RegExp, string, number][] = [
  [/q8_0/i, "Q8_0", 8.5],
  [/q6_k/i, "Q6_K", 6.6],
  [/q5_k_m/i, "Q5_K_M", 5.7],
  [/f16|fp16/i, "F16", 16],
];
const DEFAULT_QUANT = "Q4_K_M";
const DEFAULT_QUANT_BITS = 4.85;
const DEFAULT_BILLIONS = 4;
/** The tokens a sample model was trained for, where its sample names none. */
const DEFAULT_TRAINED_CONTEXT = 32768;

/** A pulled model as the demo holds it. */
export interface DemoOllamaModel {
  name: string;
  parameterSize: string;
  quantization: string;
  sizeBytes: number;
  modifiedAt: string;
  isLoaded: boolean;
  isLoading: boolean;
  /** Whether a Load keeps it, so a restart loads it again. */
  isKept: boolean;
  vramBytes: number;
  /** The tokens it was trained for; it loads at no more. */
  trainedContext: number;
}

/** A pull in the queue, as the demo holds it. */
export interface DemoOllamaPull {
  name: string;
  state: "queued" | "running";
  completedBytes: number;
  totalBytes: number;
  speedBytes: number;
  preparedAt: number;
}

/** What the hub's row says of the module on the machine. */
export interface DemoOllamaRow {
  state: ModuleDeviceState;
  deviceId: string;
  host: string;
  version: string;
  /** What the machine last reported of the module. */
  details: Record<string, unknown>;
  isRunning: boolean;
  /** The machine's last report; null while it is offline. */
  metrics: DeviceMetricsView | null;
}

interface DemoOllamaOptions {
  /** The machine's GPUs, as its report names them. */
  gpus: DeviceGpuInfo[];
  memoryTotalMb: number;
  models: DemoOllamaModel[];
  pulls: DemoOllamaPull[];
  /** Called when the list of models changes by itself: a pull ending. */
  onModelsChange: () => void;
}

/** One sample model, pulled `days` ago, in memory when `isLoaded`,
 * trained for `trainedContext` tokens. */
export function sampleModel(
  name: string,
  parameterSize: string,
  quantization: string,
  sizeBytes: number,
  days: number,
  isLoaded: boolean = false,
  trainedContext: number = DEFAULT_TRAINED_CONTEXT,
): DemoOllamaModel {
  return {
    name,
    parameterSize,
    quantization,
    sizeBytes,
    modifiedAt: secondsAgo(86400 * days),
    isLoaded,
    isLoading: false,
    isKept: isLoaded,
    vramBytes: isLoaded ? memoryOf(sizeBytes) : 0,
    trainedContext,
  };
}

/** A sample pull, running with `share` of its bytes fetched. */
export function samplePull(name: string, share: number): DemoOllamaPull {
  const total = pulledFacts(name).sizeBytes;
  return {
    name,
    state: "running",
    completedBytes: Math.round(total * share),
    totalBytes: total,
    speedBytes: PULL_BYTES_PER_S,
    preparedAt: 0,
  };
}

/** What a model takes in memory once loaded. */
function memoryOf(sizeBytes: number): number {
  return Math.round(sizeBytes * MEMORY_PER_FILE_BYTE + MEMORY_OVERHEAD_BYTES);
}

/** What one GPU can give the models, in bytes. */
function gpuSpace(gpu: DeviceGpuInfo): number {
  return Math.max(0, (gpu.memory_total_mb ?? 0) - GPU_IDLE_MB) * MIB;
}

/** A pulled model's facts, read from its name: its parameters from a size
 * such as `7b` or `360M`, its quantization from its tag. */
function pulledFacts(name: string): {
  parameterSize: string;
  quantization: string;
  sizeBytes: number;
} {
  const own = name.slice(name.lastIndexOf("/") + 1);
  const size = /(\d+(?:\.\d+)?)([bm])(?![a-z])/i.exec(own);
  const amount = size === null ? DEFAULT_BILLIONS : Number(size[1]);
  const isMillions = size?.[2]?.toLowerCase() === "m";
  const billions = isMillions ? amount / 1000 : amount;
  const quant = QUANT_BITS.find(([pattern]) => pattern.test(own));
  const bits = quant?.[2] ?? DEFAULT_QUANT_BITS;
  return {
    parameterSize: isMillions ? `${amount}M` : `${amount}B`,
    quantization: quant?.[1] ?? DEFAULT_QUANT,
    sizeBytes: Math.round((billions * 1e9 * bits) / 8),
  };
}

export class DemoOllama {
  keepAlive = "30m";
  contextLength = 65536;
  gpus: OllamaGpuSetting[] | null = null;
  private readonly machineGpus: DeviceGpuInfo[];
  private readonly memoryTotalMb: number;
  private readonly models: DemoOllamaModel[];
  private readonly pulls: DemoOllamaPull[];
  private readonly onModelsChange: () => void;
  private tickedAt = Date.now();

  constructor({
    gpus,
    memoryTotalMb,
    models,
    pulls,
    onModelsChange,
  }: DemoOllamaOptions) {
    this.machineGpus = gpus;
    this.memoryTotalMb = memoryTotalMb;
    this.models = models;
    this.pulls = pulls;
    this.onModelsChange = onModelsChange;
    window.setInterval(() => this.tickPulls(), PULL_TICK_MS);
  }

  /** The names the machine's Ollama lists. */
  modelNames(): string[] {
    return this.models.map((model) => model.name);
  }

  /** The view the panel's Ollama tab draws. */
  view(row: DemoOllamaRow): OllamaDeviceView {
    const models = row.isRunning ? this.modelRows() : [];
    return {
      ...row.state,
      device_id: row.deviceId,
      host: row.host,
      version: row.version,
      details: row.details,
      is_running: row.isRunning,
      keep_alive: this.keepAlive,
      context_length: this.contextLength,
      gpus: this.gpus,
      resources: this.resources(row.metrics),
      models,
      total_bytes: models.reduce((sum, model) => sum + model.size_bytes, 0),
      pulls: this.pulls.map((pull) => this.pullRow(pull)),
    };
  }

  /** Puts a pull at the end of the queue; a name already there stays. */
  pull(name: string): void {
    const trimmed = name.trim();
    if (!MODEL_NAME.test(trimmed)) {
      throw new DemoRefusal("ollama_model_name_invalid", { name: trimmed });
    }
    if (this.pulls.some((pull) => pull.name === trimmed)) {
      return;
    }
    this.pulls.push({
      name: trimmed,
      state: "queued",
      completedBytes: 0,
      totalBytes: 0,
      speedBytes: 0,
      preparedAt: 0,
    });
  }

  /** Ends a running pull, or takes a waiting one off the queue. */
  cancel(name: string): void {
    const at = this.pulls.findIndex((pull) => pull.name === name);
    if (at < 0) {
      throw new DemoRefusal("ollama_pull_unknown", { name });
    }
    this.pulls.splice(at, 1);
  }

  /** Keeps a model in memory until its unload, loaded after a few seconds. */
  load(name: string): void {
    const model = this.model(name);
    model.isKept = true;
    if (model.isLoaded || model.isLoading) {
      return;
    }
    model.isLoading = true;
    window.setTimeout(() => this.finishLoad(model), LOAD_MS);
  }

  /** Takes a model out of memory and out of the kept models. */
  unload(name: string): void {
    const model = this.model(name);
    model.isKept = false;
    model.isLoaded = false;
    model.isLoading = false;
    model.vramBytes = 0;
  }

  /** Deletes a model from the machine. */
  remove(name: string): void {
    const model = this.model(name);
    this.models.splice(this.models.indexOf(model), 1);
  }

  /**
   * Restarts the server with the stored settings: every model leaves
   * memory, and the kept ones load again once it is back.
   *
   * Args:
   *   backMs: How long the server takes to come back.
   */
  restart(backMs: number): void {
    for (const model of this.models) {
      const isBack = model.isKept && (model.isLoaded || model.isLoading);
      model.isLoaded = false;
      model.isLoading = isBack;
      model.vramBytes = 0;
      if (isBack) {
        window.setTimeout(() => this.finishLoad(model), backMs + LOAD_MS);
      }
    }
  }

  private model(name: string): DemoOllamaModel {
    const model = this.models.find((held) => held.name === name);
    if (model === undefined) {
      throw new DemoRefusal("ollama_model_unknown", { name });
    }
    return model;
  }

  private finishLoad(model: DemoOllamaModel): void {
    if (!model.isLoading || !this.models.includes(model)) {
      return;
    }
    model.isLoading = false;
    model.isLoaded = true;
    model.vramBytes = Math.min(memoryOf(model.sizeBytes), this.gpuRoom());
  }

  /** Whether the server uses the GPU at a place, by the stored settings. */
  private isGpuUsed(gpu: DeviceGpuInfo, place: number): boolean {
    const held = this.gpus?.[place];
    return (
      this.gpus === null ||
      (held !== undefined && held.vendor === gpu.vendor && held.is_used)
    );
  }

  /** What the used GPUs can give the models, in bytes. */
  private usedGpuSpace(): number {
    return this.machineGpus.reduce(
      (sum, gpu, place) =>
        sum + (this.isGpuUsed(gpu, place) ? gpuSpace(gpu) : 0),
      0,
    );
  }

  /** What the used GPUs have left for one more model, in bytes. */
  private gpuRoom(): number {
    return Math.max(0, this.usedGpuSpace() - this.loadedVram());
  }

  private loadedVram(): number {
    return this.models.reduce(
      (sum, model) => sum + (model.isLoaded ? model.vramBytes : 0),
      0,
    );
  }

  /**
   * The machine's GPUs as its report reads them: each used GPU holds its
   * part of the models in memory, by its space.
   *
   * Args:
   *   gpus: The GPUs as the machine's sample report names them.
   *   isRunning: Whether the server answers and holds its models.
   *
   * Returns:
   *   The GPUs with their memory in use.
   */
  gpuReadings(gpus: DeviceGpuInfo[], isRunning: boolean): DeviceGpuInfo[] {
    const space = this.usedGpuSpace();
    const vram = isRunning ? this.loadedVram() : 0;
    return gpus.map((gpu, place) => {
      const share =
        this.isGpuUsed(gpu, place) && space > 0
          ? (vram * gpuSpace(gpu)) / space
          : 0;
      return {
        ...gpu,
        memory_used_mb: GPU_IDLE_MB + Math.round(share / MIB),
      };
    });
  }

  /** The machine's GPUs and its memory, the models' part off the GPUs
   * added to the memory its report reads. */
  private resources(metrics: DeviceMetricsView | null): OllamaResourcesView {
    if (metrics === null) {
      return { gpus: [], memory_used_mb: null, memory_total_mb: null };
    }
    const offGpu = this.models.reduce(
      (sum, model) =>
        sum +
        (model.isLoaded ? memoryOf(model.sizeBytes) - model.vramBytes : 0),
      0,
    );
    const percent = metrics.memory_percent;
    return {
      gpus: metrics.gpus,
      memory_used_mb:
        percent === null
          ? null
          : Math.min(
              this.memoryTotalMb,
              Math.round((this.memoryTotalMb * percent) / 100) +
                Math.round(offGpu / MIB),
            ),
      memory_total_mb: this.memoryTotalMb,
    };
  }

  /** The models, the ones in memory first, each by name. */
  private modelRows(): OllamaModel[] {
    return this.models
      .map((model) => ({
        name: model.name,
        parameter_size: model.parameterSize,
        quantization: model.quantization,
        size_bytes: model.sizeBytes,
        modified_at: model.modifiedAt,
        is_loaded: model.isLoaded,
        is_loading: model.isLoading,
        memory_bytes: model.isLoaded ? memoryOf(model.sizeBytes) : 0,
        vram_bytes: model.isLoaded ? model.vramBytes : 0,
        context_length: model.isLoaded
          ? Math.min(this.contextLength, model.trainedContext)
          : 0,
      }))
      .sort(
        (a, b) =>
          Number(b.is_loaded) - Number(a.is_loaded) ||
          a.name.localeCompare(b.name),
      );
  }

  private pullRow(pull: DemoOllamaPull): OllamaPull {
    return {
      name: pull.name,
      state: pull.state,
      completed_bytes: Math.round(pull.completedBytes),
      total_bytes: pull.totalBytes,
      speed_bytes: Math.round(pull.speedBytes),
      code: "",
      params: {},
    };
  }

  /** Moves the running pull on, ends it into a model, and starts the next. */
  private tickPulls(): void {
    const now = Date.now();
    const elapsedS = (now - this.tickedAt) / 1000;
    this.tickedAt = now;
    const pull = this.pulls[0];
    if (pull === undefined) {
      return;
    }
    if (pull.state === "queued") {
      pull.state = "running";
      pull.preparedAt = now + PULL_PREPARE_MS;
      return;
    }
    if (pull.totalBytes === 0) {
      if (now >= pull.preparedAt) {
        pull.totalBytes = pulledFacts(pull.name).sizeBytes;
      }
      return;
    }
    pull.speedBytes =
      PULL_BYTES_PER_S *
      (1 - PULL_SPEED_SPREAD / 2 + PULL_SPEED_SPREAD * Math.random());
    pull.completedBytes = Math.min(
      pull.totalBytes,
      pull.completedBytes + pull.speedBytes * elapsedS,
    );
    if (pull.completedBytes < pull.totalBytes) {
      return;
    }
    this.pulls.shift();
    const facts = pulledFacts(pull.name);
    const held = this.models.find((model) => model.name === pull.name);
    if (held !== undefined) {
      held.modifiedAt = secondsAgo(0);
    } else {
      this.models.push(
        sampleModel(
          pull.name,
          facts.parameterSize,
          facts.quantization,
          pull.totalBytes,
          0,
        ),
      );
    }
    this.onModelsChange();
  }
}
