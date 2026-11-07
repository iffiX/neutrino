import { demoMetrics } from "./demo_traffic";
import { demoWord } from "./demo_words";
import { humanSize } from "./demo_shell_files";
import type {
  DemoEntry,
  DemoFile,
  DemoFileTree,
  DemoFolder,
} from "./demo_shell_files";

/**
 * The commands of a demo machine's shell, as functions over its file tree:
 * the words go in, the text a real machine would print comes out.
 */

/** The machine a shell runs on. */
export interface DemoShellMachine {
  hostname: string;
  account: string;
  platformOs: string;
  address: string;
  /** Which machine's numbers `demoMetrics` gives. */
  metricsSeed: number;
  /** The language of what the demo itself says in the shell. */
  language: string;
}

/** What a command reads and changes of its shell. */
export interface DemoCommandContext {
  machine: DemoShellMachine;
  tree: DemoFileTree;
  cwd: string;
  previousCwd: string;
  cols: number;
  history: string[];
  variables: Map<string, string>;
  /** Whether the command prints to the screen rather than into a pipe. */
  isTerminal: boolean;
}

/** What one command gives back. */
export interface DemoCommandResult {
  out: string;
  code: number;
}

export type DemoCommand = (
  args: string[],
  stdin: string,
  context: DemoCommandContext,
) => DemoCommandResult;

export const SGR_RESET = "\x1b[0m";
export const SGR_FOLDER = "\x1b[1;34m";
export const SGR_EXECUTABLE = "\x1b[1;32m";
export const SGR_MATCH = "\x1b[1;31m";
export const SGR_FAINT = "\x1b[2m";

const GPU_WIDE_COLS = 79;
const GPU_NARROW_WIDTH = 44;
const DF_WIDE_COLS = 44;
const MEMORY_TOTAL_GIB = 64;
const SWAP_TOTAL_GIB = 8;
const DISK_TOTAL_GIB = 1800;
const DATA_DISK_TOTAL_GIB = 3700;

function ok(out = ""): DemoCommandResult {
  return { out, code: 0 };
}

function failed(out: string, code = 1): DemoCommandResult {
  return { out, code };
}

/** The cells a character takes on the screen. */
export function charCells(character: string): number {
  const code = character.codePointAt(0) ?? 0;
  const isWide =
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6);
  return isWide ? 2 : 1;
}

/** The cells a text takes on the screen. */
export function textCells(text: string): number {
  let cells = 0;
  for (const character of text) {
    cells += charCells(character);
  }
  return cells;
}

function flagsAndNames(args: string[]): {
  flags: string;
  names: string[];
} {
  const flags = args
    .filter((arg) => arg.startsWith("-") && arg !== "-")
    .map((arg) => arg.replace(/^--?/, ""))
    .join("");
  return { flags, names: args.filter((arg) => !arg.startsWith("-")) };
}

function paint(
  name: string,
  entry: DemoEntry,
  context: DemoCommandContext,
): string {
  if (!context.isTerminal) {
    return name;
  }
  if (entry.kind === "folder") {
    return `${SGR_FOLDER}${name}${SGR_RESET}`;
  }
  return entry.isExecutable ? `${SGR_EXECUTABLE}${name}${SGR_RESET}` : name;
}

/** Names in as many columns as fit, filled top to bottom as `ls` does. */
function columns(names: string[], paints: string[], cols: number): string {
  const widths = names.map(textCells);
  for (let across = names.length; across > 1; across -= 1) {
    const down = Math.ceil(names.length / across);
    const columnWidths: number[] = [];
    for (let column = 0; column < across; column += 1) {
      columnWidths.push(
        Math.max(0, ...widths.slice(column * down, (column + 1) * down)),
      );
    }
    const total =
      columnWidths.reduce((sum, width) => sum + width, 0) + 2 * (across - 1);
    if (total > cols) {
      continue;
    }
    const lines: string[] = [];
    for (let row = 0; row < down; row += 1) {
      let line = "";
      for (let column = 0; column < across; column += 1) {
        const index = column * down + row;
        if (index >= names.length) {
          continue;
        }
        const isLast = index + down >= names.length;
        const gap = isLast
          ? 0
          : (columnWidths[column] ?? 0) - (widths[index] ?? 0) + 2;
        line += `${paints[index]}${" ".repeat(gap)}`;
      }
      lines.push(line);
    }
    return `${lines.join("\n")}\n`;
  }
  return paints.map((paint) => `${paint}\n`).join("");
}

function stamp(name: string): string {
  let seed = 0;
  for (const character of name) {
    seed = (seed * 31 + (character.codePointAt(0) ?? 0)) % 9973;
  }
  const hour = String(8 + (seed % 14)).padStart(2, "0");
  const minute = String(seed % 60).padStart(2, "0");
  return `Oct ${String(1 + (seed % 30)).padStart(2)} ${hour}:${minute}`;
}

function longLine(
  name: string,
  entry: DemoEntry,
  isHuman: boolean,
  context: DemoCommandContext,
): string {
  const owner = context.machine.account;
  const isFolder = entry.kind === "folder";
  const mode = isFolder
    ? "drwxr-xr-x"
    : entry.isExecutable
      ? "-rwxr-xr-x"
      : "-rw-r--r--";
  const bytes = isFolder ? 4096 : entry.size;
  const size = isHuman ? humanSize(bytes) : String(bytes);
  return `${mode} 1 ${owner} ${owner} ${size.padStart(isHuman ? 5 : 8)} ${stamp(name)} ${paint(name, entry, context)}\n`;
}

const ls: DemoCommand = (args, _stdin, context) => {
  const { flags, names } = flagsAndNames(args);
  const isLong = flags.includes("l");
  const isAll = flags.includes("a");
  const isHuman = flags.includes("h");
  const targets = names.length > 0 ? names : ["."];
  let out = "";
  let code = 0;
  targets.forEach((target, index) => {
    const path = context.tree.resolve(context.cwd, target);
    const entry = context.tree.find(path);
    if (entry === null) {
      out += `ls: cannot access '${target}': No such file or directory\n`;
      code = 2;
      return;
    }
    if (entry.kind === "file") {
      out += isLong
        ? longLine(target, entry, isHuman, context)
        : `${paint(target, entry, context)}\n`;
      return;
    }
    if (targets.length > 1) {
      out += `${index > 0 ? "\n" : ""}${target}:\n`;
    }
    const listed = [...entry.entries.entries()]
      .filter(([name]) => isAll || !name.startsWith("."))
      .sort(([left], [right]) => left.localeCompare(right));
    if (isLong) {
      out += `total ${listed.length * 4}\n`;
      for (const [name, item] of listed) {
        out += longLine(name, item, isHuman, context);
      }
    } else if (listed.length > 0) {
      const namesOnly = listed.map(([name]) => name);
      const paints = listed.map(([name, item]) => paint(name, item, context));
      out += context.isTerminal
        ? columns(namesOnly, paints, context.cols)
        : paints.map((line) => `${line}\n`).join("");
    }
  });
  return { out, code };
};

const cd: DemoCommand = (args, _stdin, context) => {
  const target = args[0] ?? "~";
  const path =
    target === "-"
      ? context.previousCwd
      : context.tree.resolve(context.cwd, target);
  const entry = context.tree.find(path);
  if (entry === null) {
    return failed(`bash: cd: ${target}: No such file or directory\n`);
  }
  if (entry.kind !== "folder") {
    return failed(`bash: cd: ${target}: Not a directory\n`);
  }
  context.previousCwd = context.cwd;
  context.cwd = path;
  return ok(target === "-" ? `${path}\n` : "");
};

function readFile(
  name: string,
  program: string,
  context: DemoCommandContext,
): DemoFile | string {
  const entry = context.tree.find(context.tree.resolve(context.cwd, name));
  if (entry === null) {
    return `${program}: ${name}: No such file or directory\n`;
  }
  if (entry.kind === "folder") {
    return `${program}: ${name}: Is a directory\n`;
  }
  return entry;
}

const cat: DemoCommand = (args, stdin, context) => {
  const { names } = flagsAndNames(args);
  if (names.length === 0) {
    return ok(stdin);
  }
  let out = "";
  let code = 0;
  for (const name of names) {
    const read = readFile(name, "cat", context);
    if (typeof read === "string") {
      out += read;
      code = 1;
    } else {
      out += read.text;
    }
  }
  return { out, code };
};

function sliced(
  args: string[],
  stdin: string,
  context: DemoCommandContext,
  program: string,
  pick: (lines: string[], count: number) => string[],
): DemoCommandResult {
  const numberFlag = args.findIndex((arg) => arg === "-n");
  const count = numberFlag >= 0 ? Number(args[numberFlag + 1]) : 10;
  const names = args.filter(
    (arg, index) =>
      !arg.startsWith("-") && (numberFlag < 0 || index !== numberFlag + 1),
  );
  let text = stdin;
  if (names[0] !== undefined) {
    const read = readFile(names[0], program, context);
    if (typeof read === "string") {
      return failed(read);
    }
    text = read.text;
  }
  const lines = text.replace(/\n$/, "").split("\n");
  return ok(`${pick(lines, count).join("\n")}\n`);
}

const grep: DemoCommand = (args, stdin, context) => {
  const { flags, names } = flagsAndNames(args);
  const pattern = names[0];
  if (pattern === undefined) {
    return failed("Usage: grep [OPTION]... PATTERNS [FILE]...\n", 2);
  }
  const isFolded = flags.includes("i");
  const texts: [string, string][] = [];
  for (const name of names.slice(1)) {
    const read = readFile(name, "grep", context);
    if (typeof read === "string") {
      return failed(read, 2);
    }
    texts.push([name, read.text]);
  }
  if (names.length === 1) {
    texts.push(["", stdin]);
  }
  const needle = isFolded ? pattern.toLowerCase() : pattern;
  let out = "";
  for (const [name, text] of texts) {
    for (const line of text.split("\n")) {
      const at = (isFolded ? line.toLowerCase() : line).indexOf(needle);
      if (at < 0) {
        continue;
      }
      const shown = context.isTerminal
        ? `${line.slice(0, at)}${SGR_MATCH}${line.slice(at, at + needle.length)}${SGR_RESET}${line.slice(at + needle.length)}`
        : line;
      out += `${texts.length > 1 ? `${name}:` : ""}${shown}\n`;
    }
  }
  return { out, code: out === "" ? 1 : 0 };
};

const wc: DemoCommand = (args, stdin, context) => {
  const { flags, names } = flagsAndNames(args);
  let text = stdin;
  if (names[0] !== undefined) {
    const read = readFile(names[0], "wc", context);
    if (typeof read === "string") {
      return failed(read);
    }
    text = read.text;
  }
  const lines = text.split("\n").length - 1;
  const words = text.split(/\s+/).filter((word) => word !== "").length;
  const bytes = new TextEncoder().encode(text).length;
  const tail = names[0] === undefined ? "" : ` ${names[0]}`;
  if (flags.includes("l")) {
    return ok(`${lines}${tail}\n`);
  }
  if (flags.includes("w")) {
    return ok(`${words}${tail}\n`);
  }
  return ok(
    `${String(lines).padStart(7)} ${String(words).padStart(7)} ${String(bytes).padStart(7)}${tail}\n`,
  );
};

const mkdir: DemoCommand = (args, _stdin, context) => {
  const { names } = flagsAndNames(args);
  for (const name of names) {
    const path = context.tree.resolve(context.cwd, name);
    const parent = context.tree.parentOf(path);
    if (parent === null) {
      return failed(
        `mkdir: cannot create directory '${name}': No such file or directory\n`,
      );
    }
    if (context.tree.find(path) !== null) {
      return failed(`mkdir: cannot create directory '${name}': File exists\n`);
    }
    const made: DemoFolder = { kind: "folder", entries: new Map() };
    parent.entries.set(context.tree.nameOf(path), made);
  }
  return ok();
};

const touch: DemoCommand = (args, _stdin, context) => {
  for (const name of flagsAndNames(args).names) {
    const path = context.tree.resolve(context.cwd, name);
    if (context.tree.find(path) === null && !context.tree.write(path, "")) {
      return failed(
        `touch: cannot touch '${name}': No such file or directory\n`,
      );
    }
  }
  return ok();
};

const rm: DemoCommand = (args, _stdin, context) => {
  const { flags, names } = flagsAndNames(args);
  for (const name of names) {
    const path = context.tree.resolve(context.cwd, name);
    const entry = context.tree.find(path);
    if (entry === null) {
      return failed(`rm: cannot remove '${name}': No such file or directory\n`);
    }
    if (entry.kind === "folder" && !flags.includes("r")) {
      return failed(`rm: cannot remove '${name}': Is a directory\n`);
    }
    context.tree.parentOf(path)?.entries.delete(context.tree.nameOf(path));
  }
  return ok();
};

function clockText(): string {
  return new Date().toTimeString().slice(0, 8);
}

function uptimeWords(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${days} days, ${hours}:${String(minutes).padStart(2, "0")}`;
}

/** The first line `uptime` and `top` print. */
export function uptimeLine(context: DemoCommandContext): string {
  const metrics = demoMetrics(context.machine.metricsSeed);
  const load = (metrics.load_average ?? [])
    .map((value) => value.toFixed(2))
    .join(", ");
  return `${clockText()} up ${uptimeWords(metrics.uptime_s ?? 0)},  1 user,  load average: ${load}`;
}

const free: DemoCommand = (args, _stdin, context) => {
  const metrics = demoMetrics(context.machine.metricsSeed);
  const used = (MEMORY_TOTAL_GIB * (metrics.memory_percent ?? 0)) / 100;
  const cache = MEMORY_TOTAL_GIB * 0.12;
  const free = MEMORY_TOTAL_GIB - used - cache;
  const available = free + cache;
  const isHuman = args.some((arg) => arg.includes("h"));
  const gib = (value: number): string =>
    isHuman
      ? `${value.toFixed(value < 10 ? 1 : 0)}Gi`
      : String(Math.round(value * 1048576));
  if (context.cols >= 80) {
    const cell = (text: string): string => text.padStart(12);
    return ok(
      `${"".padEnd(7)}${["total", "used", "free", "shared", "buff/cache", "available"].map(cell).join("")}\n` +
        `Mem:   ${[MEMORY_TOTAL_GIB, used, free, 0.4, cache, available].map((value) => cell(gib(value))).join("")}\n` +
        `Swap:  ${[SWAP_TOTAL_GIB, 0, SWAP_TOTAL_GIB].map((value) => cell(gib(value))).join("")}\n`,
    );
  }
  const cell = (text: string): string => text.padStart(9);
  return ok(
    `${"".padEnd(5)}${["total", "used", "free", "avail"].map(cell).join("")}\n` +
      `Mem: ${[MEMORY_TOTAL_GIB, used, free, available].map((value) => cell(gib(value))).join("")}\n` +
      `Swap:${[SWAP_TOTAL_GIB, 0, SWAP_TOTAL_GIB].map((value) => cell(gib(value))).join("")}\n`,
  );
};

const df: DemoCommand = (_args, _stdin, context) => {
  const metrics = demoMetrics(context.machine.metricsSeed);
  const percent = Math.round(metrics.disk_percent ?? 0);
  const row = (
    name: string,
    totalGib: number,
    share: number,
    mount: string,
  ): string[] => [
    name,
    humanSize(totalGib * 1073741824),
    humanSize(totalGib * share * 1073741824),
    humanSize(totalGib * (1 - share) * 1073741824),
    `${Math.round(share * 100)}%`,
    mount,
  ];
  const rows = [
    [
      "Filesystem",
      "Size",
      "Used",
      "Avail",
      "Use%",
      context.cols < DF_WIDE_COLS ? "Mount" : "Mounted on",
    ],
    ["tmpfs", "6.3G", "2.1M", "6.3G", "1%", "/run"],
    row("/dev/sda2", DISK_TOTAL_GIB, percent / 100, "/"),
    row("/dev/sdb1", DATA_DISK_TOTAL_GIB, 0.34, "/data"),
    ["tmpfs", "32G", "128M", "32G", "1%", "/dev/shm"],
  ];
  const widths = [0, 1, 2, 3, 4].map((column) =>
    Math.max(...rows.map((cells) => (cells[column] ?? "").length)),
  );
  const out = rows
    .map((cells) =>
      cells
        .map((cell, column) => {
          const width = widths[column] ?? 0;
          return column === 0
            ? cell.padEnd(width)
            : column === 5
              ? cell
              : cell.padStart(width);
        })
        .join(" "),
    )
    .join("\n");
  return ok(`${out}\n`);
};

const GPU_PROCESSES = [
  { gpu: 0, pid: 1921, name: "/usr/lib/xorg/Xorg", memory: 1420 },
  { gpu: 0, pid: 2377, name: "gnome-shell", memory: 860 },
  { gpu: 0, pid: 4410, name: "code", memory: 1000 },
  { gpu: 1, pid: 6128, name: "python3", memory: 7120 },
];

function wideGpuTable(context: DemoCommandContext): string {
  const gpus = demoMetrics(context.machine.metricsSeed).gpus ?? [];
  const rule = `+${"-".repeat(31)}+${"-".repeat(22)}+${"-".repeat(22)}+`;
  const lines = [
    new Date().toDateString(),
    `+${"-".repeat(77)}+`,
    "| NVIDIA-SMI 550.120              Driver Version: 550.120      CUDA Version: 12.4|",
    `|${"-".repeat(31)}+${"-".repeat(22)}+${"-".repeat(22)}+`,
    "| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |",
    "| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |",
    `|${"=".repeat(31)}+${"=".repeat(22)}+${"=".repeat(22)}|`,
  ];
  gpus.forEach((gpu, index) => {
    const name = `NVIDIA ${gpu.name.replace("GeForce ", "")}`.padEnd(18);
    const memory =
      `${gpu.memory_used_mb}MiB / ${gpu.memory_total_mb}MiB`.padStart(20);
    const power = `${String(Math.round(gpu.power_w ?? 0)).padStart(3)}W / ${index === 0 ? 200 : 170}W`;
    const util = `${Math.round(gpu.utilization_percent ?? 0)}%`.padStart(6);
    lines.push(
      `|${String(index).padStart(4)}  ${name} Off  | 00000000:0${index + 1}:00.0  ${index === 0 ? "On" : "Off"}|${"N/A".padStart(21)} |`,
      `|${`${30 + index * 12}%`.padStart(4)}   ${gpu.temperature_c ?? 0}C    P2  ${power}  | ${memory} |${util}      Default |`,
      rule,
    );
  });
  lines.push(
    "",
    `+${"-".repeat(77)}+`,
    "| Processes:                                                                  |",
    "|  GPU   PID   Type   Process name                              GPU Memory |",
    `|${"=".repeat(77)}|`,
  );
  for (const row of GPU_PROCESSES) {
    lines.push(
      `|${String(row.gpu).padStart(5)} ${String(row.pid).padStart(5)}      G   ${row.name.padEnd(38)} ${`${row.memory}MiB`.padStart(9)}  |`,
    );
  }
  lines.push(`+${"-".repeat(77)}+`);
  return `${lines.join("\n")}\n`;
}

function narrowGpuTable(context: DemoCommandContext): string {
  const gpus = demoMetrics(context.machine.metricsSeed).gpus ?? [];
  const width = Math.min(context.cols, GPU_NARROW_WIDTH) - 2;
  const rule = `+${"-".repeat(width)}+`;
  const row = (left: string, right: string): string =>
    `|${` ${left}`.padEnd(width - right.length - 1)}${right} |`;
  const lines = ["NVIDIA-SMI 550.120  CUDA 12.4", rule];
  gpus.forEach((gpu, index) => {
    lines.push(
      row(
        `${index} ${gpu.name.replace("GeForce ", "")}`,
        `${gpu.temperature_c ?? 0}C P2`,
      ),
      row(
        `${gpu.memory_used_mb}/${gpu.memory_total_mb}MiB`,
        `${Math.round(gpu.power_w ?? 0)}W ${Math.round(gpu.utilization_percent ?? 0)}%`,
      ),
      rule,
    );
  });
  lines.push("GPU   PID  Name          Memory");
  for (const process of GPU_PROCESSES) {
    const name = process.name.split("/").pop() ?? process.name;
    lines.push(
      `${String(process.gpu).padStart(3)} ${String(process.pid).padStart(5)}  ${name.padEnd(12)} ${`${process.memory}MiB`.padStart(7)}`,
    );
  }
  return `${lines.join("\n")}\n`;
}

const nvidiaSmi: DemoCommand = (args, _stdin, context) => {
  const gpus = demoMetrics(context.machine.metricsSeed).gpus ?? [];
  if (gpus.length === 0) {
    return failed("bash: nvidia-smi: command not found\n", 127);
  }
  if (args.includes("-L")) {
    return ok(
      gpus
        .map(
          (gpu, index) =>
            `GPU ${index}: NVIDIA ${gpu.name} (UUID: GPU-demo-${index})\n`,
        )
        .join(""),
    );
  }
  return ok(
    context.cols >= GPU_WIDE_COLS
      ? wideGpuTable(context)
      : narrowGpuTable(context),
  );
};

const python: DemoCommand = (args, _stdin, context) => {
  if (args.includes("--version") || args.includes("-V")) {
    return ok("Python 3.12.3\n");
  }
  if (args[0] === "train.py") {
    return ok(`${demoWord(context.machine.language, "shell_model_idle")}\n`);
  }
  return failed(
    `python3: can't open file '${args[0] ?? ""}': [Errno 2] No such file or directory\n`,
    2,
  );
};

const LINUX_RELEASE = "6.8.0-45-generic";
const LINUX_VERSION =
  "#45-Ubuntu SMP PREEMPT_DYNAMIC Fri Aug 30 12:02:04 UTC 2024";

const uname: DemoCommand = (args, _stdin, context) => {
  const arch = context.machine.hostname === "mini" ? "aarch64" : "x86_64";
  const flags = flagsAndNames(args).flags;
  if (flags.includes("a")) {
    return ok(
      `Linux ${context.machine.hostname} ${LINUX_RELEASE} ${LINUX_VERSION} ${arch} ${arch} ${arch} GNU/Linux\n`,
    );
  }
  const parts: string[] = [];
  if (flags.includes("s") || flags === "") {
    parts.push("Linux");
  }
  if (flags.includes("n")) {
    parts.push(context.machine.hostname);
  }
  if (flags.includes("r")) {
    parts.push(LINUX_RELEASE);
  }
  if (flags.includes("m")) {
    parts.push(arch);
  }
  return ok(`${parts.join(" ")}\n`);
};

const ps: DemoCommand = (_args, _stdin, context) => {
  const processes = demoMetrics(context.machine.metricsSeed).processes ?? [];
  const rows = processes
    .map(
      (row) =>
        `${row.user.padEnd(9)}${String(row.pid).padStart(6)}${row.cpu_percent.toFixed(1).padStart(5)}${row.memory_percent.toFixed(1).padStart(5)} ${row.name}\n`,
    )
    .join("");
  return ok(`USER        PID %CPU %MEM COMMAND\n${rows}`);
};

const ip: DemoCommand = (_args, _stdin, context) =>
  ok(
    `1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536\n    inet 127.0.0.1/8 scope host lo\n` +
      `2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n    inet ${context.machine.address}/24 scope global eth0\n`,
  );

const envList: DemoCommand = (_args, _stdin, context) =>
  ok(
    [...context.variables.entries()]
      .map(([name, value]) => `${name}=${value}\n`)
      .join(""),
  );

const NO_PATH_COMMANDS = new Set(["cd", "history", "help", "exit", "logout"]);

const which: DemoCommand = (args) =>
  ok(
    args
      .filter((name) => name in LINUX_COMMANDS && !NO_PATH_COMMANDS.has(name))
      .map((name) => `/usr/bin/${name}\n`)
      .join(""),
  );

const historyList: DemoCommand = (_args, _stdin, context) =>
  ok(
    context.history
      .map((line, index) => `${String(index + 1).padStart(5)}  ${line}\n`)
      .join(""),
  );

const HELP_WORDS = [
  "ls",
  "cd",
  "pwd",
  "cat",
  "echo",
  "grep",
  "df -h",
  "free -h",
  "nvidia-smi",
  "top",
  "ping",
  "vim",
  "python3",
];

const help: DemoCommand = (_args, _stdin, context) =>
  ok(
    `${demoWord(context.machine.language, "shell_help")}\n  ${HELP_WORDS.join("  ")}\n`,
  );

/** The commands of a Linux shell. */
export const LINUX_COMMANDS: Record<string, DemoCommand> = {
  cat,
  cd,
  df,
  free,
  grep,
  help,
  history: historyList,
  ip,
  ls,
  mkdir,
  ps,
  rm,
  touch,
  uname,
  wc,
  which,
  "nvidia-smi": nvidiaSmi,
  python,
  python3: python,
  ll: (args, stdin, context) => ls(["-l", ...args], stdin, context),
  la: (args, stdin, context) => ls(["-a", ...args], stdin, context),
  date: () => ok(`${new Date().toString().split(" GMT")[0]}\n`),
  echo: (args) => {
    const isBare = args[0] === "-n";
    const text = (isBare ? args.slice(1) : args).join(" ");
    return ok(isBare ? text : `${text}\n`);
  },
  env: envList,
  printenv: envList,
  head: (args, stdin, context) =>
    sliced(args, stdin, context, "head", (lines, count) =>
      lines.slice(0, count),
    ),
  tail: (args, stdin, context) =>
    sliced(args, stdin, context, "tail", (lines, count) => lines.slice(-count)),
  hostname: (_args, _stdin, context) => ok(`${context.machine.hostname}\n`),
  id: (_args, _stdin, context) => {
    const name = context.machine.account;
    return ok(
      `uid=1000(${name}) gid=1000(${name}) groups=1000(${name}),27(sudo)\n`,
    );
  },
  pwd: (_args, _stdin, context) => ok(`${context.cwd}\n`),
  uptime: (_args, _stdin, context) => ok(` ${uptimeLine(context)}\n`),
  whoami: (_args, _stdin, context) => ok(`${context.machine.account}\n`),
  sudo: (_args, _stdin, context) =>
    failed(`${context.machine.account} is not in the sudoers file.\n`),
};

function windowsPath(path: string): string {
  return `C:${path.replaceAll("/", "\\")}`;
}

const windowsList: DemoCommand = (args, _stdin, context) => {
  const { names } = flagsAndNames(args);
  const target = names[0] ?? ".";
  const path = context.tree.resolve(context.cwd, target);
  const entry = context.tree.find(path);
  if (entry === null || entry.kind === "file") {
    return failed(
      `Get-ChildItem: Cannot find path '${windowsPath(path)}' because it does not exist.\n`,
    );
  }
  const rows = [...entry.entries.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, item]) => {
      const size = item.kind === "file" ? String(item.size) : "";
      const mode = item.kind === "folder" ? "d----" : "-a---";
      const shown =
        item.kind === "folder" && context.isTerminal
          ? `${SGR_FOLDER}${name}${SGR_RESET}`
          : name;
      return `${mode}  ${size.padStart(6)} ${shown}\n`;
    })
    .join("");
  return ok(
    `\n    Directory: ${windowsPath(path)}\n\nMode   Length Name\n----   ------ ----\n${rows}\n`,
  );
};

const windowsPwd: DemoCommand = (_args, _stdin, context) =>
  ok(`\nPath\n----\n${windowsPath(context.cwd)}\n\n`);

const windowsCd: DemoCommand = (args, stdin, context) => {
  const result = cd(args, stdin, context);
  return result.code === 0
    ? ok()
    : failed(
        `Set-Location: Cannot find path '${args[0] ?? ""}' because it does not exist.\n`,
      );
};

const windowsCat: DemoCommand = (args, stdin, context) => {
  const result = cat(args, stdin, context);
  return result.code === 0
    ? result
    : failed(
        `Get-Content: Cannot find path '${args[0] ?? ""}' because it does not exist.\n`,
      );
};

/** The commands of a Windows PowerShell, with its usual short names. */
export const WINDOWS_COMMANDS: Record<string, DemoCommand> = {
  cat: windowsCat,
  type: windowsCat,
  "get-content": windowsCat,
  cd: windowsCd,
  "set-location": windowsCd,
  dir: windowsList,
  ls: windowsList,
  "get-childitem": windowsList,
  pwd: windowsPwd,
  "get-location": windowsPwd,
  date: () => ok(`\n${new Date().toString().split(" GMT")[0]}\n\n`),
  "get-date": () => ok(`\n${new Date().toString().split(" GMT")[0]}\n\n`),
  echo: (args) => ok(`${args.join(" ")}\n`),
  "write-output": (args) => ok(`${args.join(" ")}\n`),
  hostname: (_args, _stdin, context) => ok(`${context.machine.hostname}\n`),
  whoami: (_args, _stdin, context) =>
    ok(`${context.machine.hostname}\\${context.machine.account}\n`),
  python: (args, _stdin, context) =>
    args.includes("--version")
      ? ok("Python 3.12.7\n")
      : failed(
          `${demoWord(context.machine.language, "shell_python_only_version")}\n`,
        ),
  help: (_args, _stdin, context) =>
    ok(
      `${demoWord(context.machine.language, "shell_help")}\n  ls  cd  pwd  cat  echo  whoami  hostname\n`,
    ),
};
