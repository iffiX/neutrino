import { demoMetrics } from "./demo_traffic";
import { demoWord } from "./demo_words";
import { decodeKeys, DemoLineEditor } from "./demo_shell_line";
import {
  SGR_FOLDER,
  SGR_RESET,
  textCells,
  uptimeLine,
} from "./demo_shell_commands";
import type { DemoCommandContext } from "./demo_shell_commands";
import type { DemoKey } from "./demo_shell_line";

/**
 * The programs of a demo shell that hold the terminal until they end: top,
 * ping, vim and the Python prompt.
 */

/** A program running on the terminal. */
export interface DemoProgram {
  input(data: string): void;
  resize(): void;
  stop(): void;
}

/** What a program has of its shell. */
export interface DemoProgramHost {
  context: DemoCommandContext;
  write(text: string): void;
  cols(): number;
  rows(): number;
  /** Hands the terminal back to the shell. */
  finish(code: number): void;
}

const SCREEN_ALTERNATE_ON = "\x1b[?1049h\x1b[2J\x1b[H";
const SCREEN_ALTERNATE_OFF = "\x1b[?1049l";
const REVERSE = "\x1b[7m";
const TOP_REFRESH_MS = 1000;
const PING_INTERVAL_MS = 1000;
const MEMORY_TOTAL_MIB = 65536;

/** A live table of the machine's programs, until `q` or Ctrl+C. */
export class DemoTop implements DemoProgram {
  private readonly timer: number;

  constructor(private readonly host: DemoProgramHost) {
    host.write(`${SCREEN_ALTERNATE_ON}\x1b[?25l`);
    this.render();
    this.timer = window.setInterval(() => this.render(), TOP_REFRESH_MS);
  }

  input(data: string): void {
    for (const key of decodeKeys(data)) {
      if (key.text === "q" || key.name === "ctrl_c") {
        this.stop();
        this.host.write(`\x1b[?25h${SCREEN_ALTERNATE_OFF}`);
        this.host.finish(0);
        return;
      }
    }
  }

  resize(): void {
    this.render();
  }

  stop(): void {
    window.clearInterval(this.timer);
  }

  private render(): void {
    const { context } = this.host;
    const metrics = demoMetrics(context.machine.metricsSeed);
    const cpu = metrics.cpu_percent ?? 0;
    const memory = metrics.memory_percent ?? 0;
    const usedMib = (MEMORY_TOTAL_MIB * memory) / 100;
    const clock = Date.now() / 1000;
    const hasGpus = (metrics.gpus ?? []).length > 0;
    const running = [
      ...(hasGpus
        ? [
            {
              pid: 6128,
              user: context.machine.account,
              name: "python3",
              cpu: 96 + 3 * Math.sin(clock),
              memory: 11.2,
            },
            {
              pid: 1921,
              user: "root",
              name: "Xorg",
              cpu: 4 + 2 * Math.sin(clock / 2),
              memory: 0.8,
            },
            {
              pid: 2377,
              user: context.machine.account,
              name: "gnome-shell",
              cpu: 3 + Math.sin(clock / 3),
              memory: 1.4,
            },
          ]
        : []),
      ...(metrics.processes ?? []).map((row) => ({
        pid: row.pid,
        user: row.user,
        name: row.name,
        cpu: row.cpu_percent,
        memory: row.memory_percent,
      })),
    ];
    const cols = this.host.cols();
    const lines = [
      `top - ${uptimeLine(context)}`,
      `Tasks: 318 total,   2 running, 316 sleeping`,
      `%Cpu(s): ${cpu.toFixed(1)} us,  2.1 sy, ${(97.9 - cpu).toFixed(1)} id`,
      `MiB Mem : ${MEMORY_TOTAL_MIB} total, ${usedMib.toFixed(0)} used`,
      `MiB Swap:  8192 total,     0 used`,
      "",
      `${REVERSE}${"    PID USER     %CPU %MEM COMMAND".padEnd(cols).slice(0, cols)}${SGR_RESET}`,
      ...running.map(
        (row) =>
          `${String(row.pid).padStart(7)} ${row.user.padEnd(8).slice(0, 8)} ${row.cpu.toFixed(1).padStart(4)} ${row.memory.toFixed(1).padStart(4)} ${row.name}`,
      ),
    ];
    const shown = lines
      .slice(0, this.host.rows() - 1)
      .map((line) => (line.includes(REVERSE) ? line : line.slice(0, cols)));
    const hint = demoWord(context.machine.language, "shell_quit_top");
    this.host.write(`\x1b[H\x1b[J${shown.join("\r\n")}\r\n\r\n${hint}`);
  }
}

/** One line a second to a host, until Ctrl+C or its count. */
export class DemoPing implements DemoProgram {
  private readonly timer: number;
  private readonly address: string;
  private readonly times: number[] = [];
  private readonly started = Date.now();

  constructor(
    private readonly host: DemoProgramHost,
    private readonly target: string,
    private readonly count: number,
  ) {
    let seed = 0;
    for (const character of target) {
      seed = (seed * 7 + (character.codePointAt(0) ?? 0)) % 250;
    }
    this.address = /^\d+\.\d+\.\d+\.\d+$/.test(target)
      ? target
      : `203.0.113.${seed + 1}`;
    host.write(`PING ${target} (${this.address}) 56(84) bytes of data.\r\n`);
    this.tick();
    this.timer = window.setInterval(() => this.tick(), PING_INTERVAL_MS);
  }

  input(data: string): void {
    for (const key of decodeKeys(data)) {
      if (key.name === "ctrl_c") {
        this.host.write("^C");
        this.end();
        return;
      }
    }
  }

  resize(): void {}

  stop(): void {
    window.clearInterval(this.timer);
  }

  private tick(): void {
    const time = 11 + Math.random() * 6;
    this.times.push(time);
    this.host.write(
      `64 bytes from ${this.address}: icmp_seq=${this.times.length} ttl=57 time=${time.toFixed(1)} ms\r\n`,
    );
    if (this.times.length === this.count) {
      this.end();
    }
  }

  private end(): void {
    this.stop();
    const sent = this.times.length;
    const average = this.times.reduce((sum, time) => sum + time, 0) / sent;
    this.host.write(
      `\r\n--- ${this.target} ping statistics ---\r\n` +
        `${sent} packets transmitted, ${sent} received, 0% packet loss, time ${Date.now() - this.started}ms\r\n` +
        `rtt min/avg/max = ${Math.min(...this.times).toFixed(1)}/${average.toFixed(1)}/${Math.max(...this.times).toFixed(1)} ms\r\n`,
    );
    this.host.finish(0);
  }
}

type VimMode = "normal" | "insert" | "command";

/** A small vim: move, insert, Esc, `:w`, `:q`. */
export class DemoVim implements DemoProgram {
  private lines: string[];
  private row = 0;
  private col = 0;
  private top = 0;
  private mode: VimMode = "normal";
  private command = "";
  private message: string;
  private isDirty = false;
  private isDone = false;
  private pending = "";
  private readonly path: string;

  constructor(
    private readonly host: DemoProgramHost,
    private readonly name: string,
  ) {
    const { tree, cwd } = host.context;
    this.path = tree.resolve(cwd, name);
    const entry = tree.find(this.path);
    const text = entry?.kind === "file" ? entry.text : "";
    this.lines = text === "" ? [""] : text.replace(/\n$/, "").split("\n");
    this.message =
      entry === null
        ? `"${name}" [New]`
        : `"${name}" ${this.lines.length}L, ${text.length}B`;
    host.write(SCREEN_ALTERNATE_ON);
    this.render();
  }

  input(data: string): void {
    for (const key of decodeKeys(data)) {
      this.key(key);
      if (this.isDone) {
        return;
      }
    }
    this.render();
  }

  resize(): void {
    this.render();
  }

  stop(): void {}

  private key(key: DemoKey): void {
    if (this.mode === "insert") {
      this.insertKey(key);
    } else if (this.mode === "command") {
      this.commandKey(key);
    } else {
      this.normalKey(key);
    }
  }

  private current(): string {
    return this.lines[this.row] ?? "";
  }

  private clampCol(): void {
    const chars = [...this.current()].length;
    const last = this.mode === "insert" ? chars : Math.max(0, chars - 1);
    this.col = Math.max(0, Math.min(this.col, last));
  }

  private moveRow(step: number): void {
    this.row = Math.max(0, Math.min(this.lines.length - 1, this.row + step));
    this.clampCol();
  }

  private normalKey(key: DemoKey): void {
    const pressed = key.text !== "" ? key.text : key.name;
    const wasPending = this.pending;
    this.pending = "";
    switch (pressed) {
      case "h":
      case "left":
        this.col -= 1;
        this.clampCol();
        break;
      case "l":
      case "right":
        this.col += 1;
        this.clampCol();
        break;
      case "j":
      case "down":
        this.moveRow(1);
        break;
      case "k":
      case "up":
        this.moveRow(-1);
        break;
      case "0":
        this.col = 0;
        break;
      case "$":
        this.col = [...this.current()].length;
        this.clampCol();
        break;
      case "G":
        this.moveRow(this.lines.length);
        break;
      case "g":
        if (wasPending === "g") {
          this.moveRow(-this.lines.length);
        } else {
          this.pending = "g";
        }
        break;
      case "d":
        if (wasPending === "d") {
          this.deleteLine();
        } else {
          this.pending = "d";
        }
        break;
      case "x":
        this.deleteChar();
        break;
      case "i":
        this.enterInsert(this.col);
        break;
      case "a":
        this.enterInsert(this.col + 1);
        break;
      case "A":
        this.enterInsert([...this.current()].length);
        break;
      case "I":
        this.enterInsert(0);
        break;
      case "o":
        this.lines.splice(this.row + 1, 0, "");
        this.row += 1;
        this.enterInsert(0);
        this.isDirty = true;
        break;
      case "O":
        this.lines.splice(this.row, 0, "");
        this.enterInsert(0);
        this.isDirty = true;
        break;
      case ":":
        this.mode = "command";
        this.command = "";
        this.message = "";
        break;
      default:
        break;
    }
  }

  private enterInsert(col: number): void {
    this.mode = "insert";
    this.col = col;
    this.clampCol();
    this.message = "";
  }

  private deleteLine(): void {
    this.lines.splice(this.row, 1);
    if (this.lines.length === 0) {
      this.lines = [""];
    }
    this.moveRow(0);
    this.isDirty = true;
  }

  private deleteChar(): void {
    const chars = [...this.current()];
    if (chars.length > 0) {
      chars.splice(this.col, 1);
      this.lines[this.row] = chars.join("");
      this.clampCol();
      this.isDirty = true;
    }
  }

  private insertKey(key: DemoKey): void {
    const chars = [...this.current()];
    if (key.text !== "") {
      chars.splice(this.col, 0, key.text);
      this.lines[this.row] = chars.join("");
      this.col += 1;
      this.isDirty = true;
      return;
    }
    switch (key.name) {
      case "escape":
      case "ctrl_c":
        this.mode = "normal";
        this.col -= 1;
        this.clampCol();
        break;
      case "enter":
        this.lines[this.row] = chars.slice(0, this.col).join("");
        this.lines.splice(this.row + 1, 0, chars.slice(this.col).join(""));
        this.row += 1;
        this.col = 0;
        this.isDirty = true;
        break;
      case "backspace":
        this.backspace(chars);
        break;
      case "tab":
        chars.splice(this.col, 0, " ", " ", " ", " ");
        this.lines[this.row] = chars.join("");
        this.col += 4;
        this.isDirty = true;
        break;
      case "left":
        this.col -= 1;
        this.clampCol();
        break;
      case "right":
        this.col += 1;
        this.clampCol();
        break;
      case "up":
        this.moveRow(-1);
        break;
      case "down":
        this.moveRow(1);
        break;
      default:
        break;
    }
  }

  private backspace(chars: string[]): void {
    if (this.col > 0) {
      chars.splice(this.col - 1, 1);
      this.lines[this.row] = chars.join("");
      this.col -= 1;
      this.isDirty = true;
    } else if (this.row > 0) {
      const above = this.lines[this.row - 1] ?? "";
      this.col = [...above].length;
      this.lines[this.row - 1] = above + chars.join("");
      this.lines.splice(this.row, 1);
      this.row -= 1;
      this.isDirty = true;
    }
  }

  private commandKey(key: DemoKey): void {
    if (key.text !== "") {
      this.command += key.text;
    } else if (key.name === "escape" || key.name === "ctrl_c") {
      this.mode = "normal";
    } else if (key.name === "backspace") {
      if (this.command === "") {
        this.mode = "normal";
      }
      this.command = this.command.slice(0, -1);
    } else if (key.name === "enter") {
      this.mode = "normal";
      this.runCommand(this.command.trim());
    }
  }

  private save(): void {
    this.host.context.tree.write(this.path, `${this.lines.join("\n")}\n`);
    this.isDirty = false;
    this.message = `"${this.name}" ${this.lines.length}L written`;
  }

  private quit(): void {
    this.isDone = true;
    this.host.write(SCREEN_ALTERNATE_OFF);
    this.host.finish(0);
  }

  private runCommand(command: string): void {
    if (command === "w") {
      this.save();
    } else if (command === "wq" || command === "x") {
      this.save();
      this.quit();
    } else if (command === "q!") {
      this.quit();
    } else if (command === "q") {
      if (this.isDirty) {
        this.message = "E37: No write since last change (add ! to override)";
      } else {
        this.quit();
      }
    } else if (command !== "") {
      this.message = `E492: Not an editor command: ${command}`;
    }
  }

  private render(): void {
    const cols = this.host.cols();
    const height = this.host.rows() - 1;
    if (this.row < this.top) {
      this.top = this.row;
    } else if (this.row >= this.top + height) {
      this.top = this.row - height + 1;
    }
    const rows: string[] = [];
    for (let at = 0; at < height; at += 1) {
      const line = this.lines[this.top + at];
      rows.push(
        line === undefined
          ? `${SGR_FOLDER}~${SGR_RESET}`
          : [...line].slice(0, cols).join(""),
      );
    }
    const foot =
      this.mode === "insert"
        ? "\x1b[1m-- INSERT --\x1b[0m"
        : this.mode === "command"
          ? `:${this.command}`
          : this.message;
    const cursorCol =
      textCells([...this.current()].slice(0, this.col).join("")) + 1;
    const cursorRow = this.row - this.top + 1;
    const place =
      this.mode === "command"
        ? `\x1b[${height + 1};${this.command.length + 2}H`
        : `\x1b[${cursorRow};${cursorCol}H`;
    this.host.write(`\x1b[H\x1b[J${rows.join("\r\n")}\r\n${foot}${place}`);
  }
}

const PYTHON_BANNER =
  'Python 3.12.3 (main, Sep 11 2024, 14:17:37) [GCC 13.2.0] on linux\r\nType "help", "copyright", "credits" or "license" for more information.\r\n';
const PYTHON_PROMPT = ">>> ";

const PYTHON_ANSWERS: Record<string, string> = {
  "torch.cuda.is_available()": "True",
  "torch.cuda.device_count()": "2",
  "torch.cuda.get_device_name(0)": "'NVIDIA GeForce RTX 4070'",
  "torch.cuda.get_device_name(1)": "'NVIDIA GeForce RTX 3060'",
  "torch.__version__": "'2.5.1+cu124'",
};

/** The value of a plain arithmetic expression, or null for anything else. */
function arithmetic(text: string): number | null {
  const tokens = text.match(/\*\*|\/\/|\d+\.?\d*|[-+*/%()]|\S/g) ?? [];
  let at = 0;
  function atom(): number | null {
    const token = tokens[at];
    if (token === undefined) {
      return null;
    }
    at += 1;
    if (token === "(") {
      const inner = sum();
      at += 1;
      return inner;
    }
    if (token === "-") {
      const inner = atom();
      return inner === null ? null : -inner;
    }
    return /^\d/.test(token) ? Number(token) : null;
  }
  function power(): number | null {
    const base = atom();
    if (base !== null && tokens[at] === "**") {
      at += 1;
      const exponent = power();
      return exponent === null ? null : base ** exponent;
    }
    return base;
  }
  function product(): number | null {
    let value = power();
    while (value !== null && ["*", "/", "//", "%"].includes(tokens[at] ?? "")) {
      const operator = tokens[at];
      at += 1;
      const right = power();
      if (right === null) {
        return null;
      }
      value =
        operator === "*"
          ? value * right
          : operator === "/"
            ? value / right
            : operator === "%"
              ? value % right
              : Math.floor(value / right);
    }
    return value;
  }
  function sum(): number | null {
    let value = product();
    while (value !== null && (tokens[at] === "+" || tokens[at] === "-")) {
      const isAdd = tokens[at] === "+";
      at += 1;
      const right = product();
      if (right === null) {
        return null;
      }
      value = isAdd ? value + right : value - right;
    }
    return value;
  }
  const value = sum();
  return at === tokens.length ? value : null;
}

/** What the Python prompt prints for one line, or null when it prints nothing. */
function pythonAnswer(line: string): string | null {
  const text = line.trim();
  if (text === "" || /^(import|from)\s/.test(text)) {
    return null;
  }
  const answer = PYTHON_ANSWERS[text];
  if (answer !== undefined) {
    return answer;
  }
  const printed = /^print\((.*)\)$/.exec(text);
  if (printed !== null) {
    const shown = pythonAnswer(printed[1] ?? "") ?? "";
    return shown.replace(/^['"]|['"]$/g, "");
  }
  if (/^(['"]).*\1$/.test(text)) {
    return `'${text.slice(1, -1)}'`;
  }
  const value = arithmetic(text);
  if (value !== null) {
    return String(value);
  }
  const name = /^[A-Za-z_]\w*/.exec(text)?.[0] ?? text;
  return `Traceback (most recent call last):\n  File "<stdin>", line 1, in <module>\nNameError: name '${name}' is not defined`;
}

/** The Python prompt, until `exit()` or Ctrl+D. */
export class DemoPython implements DemoProgram {
  private readonly editor: DemoLineEditor;

  constructor(private readonly host: DemoProgramHost) {
    this.editor = new DemoLineEditor(
      (text) => host.write(text),
      () => host.cols(),
      {
        onSubmit: (line) => this.run(line),
        onInterrupt: () => {
          host.write("KeyboardInterrupt\r\n");
          this.prompt();
        },
        onEof: () => {
          host.write("\r\n");
          host.finish(0);
        },
        onClear: () => {
          host.write("\x1b[2J\x1b[H");
          this.prompt();
        },
        complete: () => ({ added: "    ", choices: [] }),
      },
    );
    host.write(PYTHON_BANNER);
    this.prompt();
  }

  input(data: string): void {
    for (const key of decodeKeys(data)) {
      this.editor.key(key);
    }
  }

  resize(): void {
    this.editor.redrawAfterResize();
  }

  stop(): void {}

  private prompt(): void {
    this.editor.begin(PYTHON_PROMPT, PYTHON_PROMPT.length);
  }

  private run(line: string): void {
    if (/^\s*(exit|quit)\(\)\s*$/.test(line)) {
      this.host.finish(0);
      return;
    }
    const answer = pythonAnswer(line);
    if (answer !== null) {
      this.host.write(`${answer.replaceAll("\n", "\r\n")}\r\n`);
    }
    this.prompt();
  }
}
