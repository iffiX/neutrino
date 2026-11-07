import {
  LINUX_COMMANDS,
  SGR_FAINT,
  SGR_RESET,
  textCells,
  WINDOWS_COMMANDS,
} from "./demo_shell_commands";
import type {
  DemoCommand,
  DemoCommandContext,
  DemoCommandResult,
  DemoShellMachine,
} from "./demo_shell_commands";
import { demoWord } from "./demo_words";
import { DemoFileTree } from "./demo_shell_files";
import { decodeKeys, DemoLineEditor } from "./demo_shell_line";
import { DemoPing, DemoPython, DemoTop, DemoVim } from "./demo_shell_programs";
import type { DemoProgram, DemoProgramHost } from "./demo_shell_programs";

/**
 * A demo machine's shell, behind a terminal's byte stream: the prompt, the
 * line being typed, and the commands over a small file tree. Nothing leaves the
 * browser.
 */

const HOME_MARK = "~";
const PROMPT_USER = "\x1b[1;32m";
const PROMPT_PATH = "\x1b[1;34m";
const DEFAULT_COLS = 80;
const DEFAULT_ROWS = 24;
const WORD_GROUP = /(?:"[^"]*"|'[^']*'|[^\s"'])+/g;
const OPERATORS = /(\|\||&&|;|\|)/;
const PING_DEFAULT_TARGET = "hub";
const VIM_DEFAULT_FILE = "untitled.txt";

interface DemoStage {
  args: string[];
  redirect: { path: string; isAppend: boolean } | null;
}

interface DemoPipeline {
  /** The word that joins it to the one before: `;`, `&&` or `||`. */
  join: string;
  stages: DemoStage[];
}

function pipelines(line: string): DemoPipeline[] {
  const parts = line.split(OPERATORS);
  const found: DemoPipeline[] = [];
  let join = ";";
  let stages: DemoStage[] = [];
  for (const part of parts) {
    if (part === "|") {
      continue;
    }
    if (part === ";" || part === "&&" || part === "||") {
      found.push({ join, stages });
      join = part;
      stages = [];
      continue;
    }
    if (part.trim() !== "") {
      stages.push(stageOf(part));
    }
  }
  if (stages.length > 0) {
    found.push({ join, stages });
  }
  return found.filter((pipeline) => pipeline.stages.length > 0);
}

function stageOf(text: string): DemoStage {
  const redirect = /(>>?)\s*(\S+)\s*$/.exec(text);
  const words = (
    redirect === null ? text : text.slice(0, redirect.index)
  ).match(WORD_GROUP);
  return {
    args: words ?? [],
    redirect:
      redirect === null
        ? null
        : { path: redirect[2] ?? "", isAppend: redirect[1] === ">>" },
  };
}

/** The bash or PowerShell behind one terminal. */
export class DemoShell implements DemoProgramHost {
  readonly context: DemoCommandContext;
  private readonly editor: DemoLineEditor;
  private readonly isWindows: boolean;
  private readonly commands: Record<string, DemoCommand>;
  private columnCount = DEFAULT_COLS;
  private rowCount = DEFAULT_ROWS;
  private program: DemoProgram | null = null;
  private lastCode = 0;
  private isEnded = false;

  constructor(
    machine: DemoShellMachine,
    private readonly send: (text: string) => void,
    private readonly onEnd: () => void,
  ) {
    this.isWindows = machine.platformOs === "windows";
    this.commands = this.isWindows ? WINDOWS_COMMANDS : LINUX_COMMANDS;
    const tree = new DemoFileTree(
      machine.account,
      machine.hostname,
      machine.platformOs,
    );
    this.context = {
      machine,
      tree,
      cwd: tree.home,
      previousCwd: tree.home,
      cols: DEFAULT_COLS,
      history: [],
      isTerminal: true,
      variables: new Map([
        ["USER", machine.account],
        ["HOME", tree.home],
        ["HOSTNAME", machine.hostname],
        ["SHELL", "/bin/bash"],
        ["LANG", machine.language === "en" ? "en_US.UTF-8" : "zh_CN.UTF-8"],
        ["TERM", "xterm-256color"],
        ["PATH", "/usr/local/bin:/usr/bin:/bin"],
      ]),
    };
    this.editor = new DemoLineEditor(
      (text) => this.write(text),
      () => this.columnCount,
      {
        onSubmit: (line) => this.run(line),
        onInterrupt: () => {
          this.lastCode = 130;
          this.prompt();
        },
        onEof: () => this.exit(),
        onClear: () => {
          this.write("\x1b[2J\x1b[H");
          this.prompt();
        },
        complete: (before) => this.complete(before),
      },
    );
    this.context.history = this.editor.history;
  }

  /** Prints the greeting and the first prompt. */
  start(): void {
    this.write(this.isWindows ? this.windowsGreeting() : this.linuxGreeting());
    this.prompt();
  }

  /**
   * Takes what the terminal sent: the keys for the line being typed or for the
   * program running.
   *
   * Args:
   *   data: The terminal's text.
   */
  input(data: string): void {
    if (this.isEnded) {
      return;
    }
    if (this.program !== null) {
      this.program.input(data);
      return;
    }
    for (const key of decodeKeys(data)) {
      this.editor.key(key);
      if (this.program !== null || this.isEnded) {
        return;
      }
    }
  }

  /** Takes a new size of the terminal. */
  resize(cols: number, rows: number): void {
    this.columnCount = cols;
    this.rowCount = rows;
    this.context.cols = cols;
    this.program?.resize();
  }

  /** Stops what runs, as a Ctrl+C the Clear of the page sends. */
  interrupt(): void {
    if (this.program !== null) {
      this.program.input("\x03");
      return;
    }
    this.lastCode = 130;
    this.prompt();
  }

  /** Prints a new prompt under a line the Clear of the page dropped. */
  reprompt(): void {
    if (this.program === null && !this.isEnded) {
      this.prompt();
    }
  }

  /** Stops the timers of a program still running. */
  stop(): void {
    this.isEnded = true;
    this.program?.stop();
    this.program = null;
  }

  /** Writes text with its line ends as a terminal takes them. */
  write(text: string): void {
    this.send(text);
  }

  /** Implements `DemoProgramHost.cols`. */
  cols(): number {
    return this.columnCount;
  }

  /** Implements `DemoProgramHost.rows`. */
  rows(): number {
    return this.rowCount;
  }

  /** Implements `DemoProgramHost.finish`. */
  finish(code: number): void {
    this.program = null;
    this.lastCode = code;
    this.prompt();
  }

  private linuxGreeting(): string {
    const { machine } = this.context;
    return (
      `Welcome to Ubuntu 24.04.1 LTS (GNU/Linux 6.8.0-45-generic x86_64)\r\n\r\n` +
      `Last login: ${new Date(Date.now() - 86400000).toDateString()} on ${machine.hostname}\r\n` +
      `${SGR_FAINT}${demoWord(machine.language, "shell_hint_linux")}${SGR_RESET}\r\n`
    );
  }

  private windowsGreeting(): string {
    return (
      `PowerShell 7.4.5\r\n` +
      `${SGR_FAINT}${demoWord(this.context.machine.language, "shell_hint_windows")}${SGR_RESET}\r\n\r\n`
    );
  }

  private promptPath(): string {
    const { cwd, tree } = this.context;
    if (cwd === tree.home) {
      return HOME_MARK;
    }
    return cwd.startsWith(`${tree.home}/`)
      ? `${HOME_MARK}${cwd.slice(tree.home.length)}`
      : cwd;
  }

  private prompt(): void {
    const { machine, cwd } = this.context;
    if (this.isWindows) {
      const text = `PS C:${cwd.replaceAll("/", "\\")}> `;
      this.editor.begin(text, textCells(text));
      return;
    }
    const plain = `${machine.account}@${machine.hostname}:${this.promptPath()}$ `;
    this.editor.begin(
      `${PROMPT_USER}${machine.account}@${machine.hostname}${SGR_RESET}:${PROMPT_PATH}${this.promptPath()}${SGR_RESET}$ `,
      textCells(plain),
    );
  }

  private exit(): void {
    this.write("logout\r\n");
    this.stop();
    this.onEnd();
  }

  private expand(word: string): string {
    if (word.startsWith("'")) {
      return word.slice(1, -1);
    }
    const unquoted = word.replaceAll('"', "");
    return unquoted
      .replace(/\$\?/g, String(this.lastCode))
      .replace(
        /\$(\w+)/g,
        (_whole, name: string) => this.context.variables.get(name) ?? "",
      );
  }

  /** Splits a word with `*` into the names of the working folder it matches. */
  private glob(word: string): string[] {
    if (!word.includes("*") || word.includes("/")) {
      return [word];
    }
    const entry = this.context.tree.find(this.context.cwd);
    if (entry?.kind !== "folder") {
      return [word];
    }
    const pattern = new RegExp(
      `^${word.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replaceAll("*", ".*")}$`,
    );
    const names = [...entry.entries.keys()]
      .filter((name) => !name.startsWith(".") && pattern.test(name))
      .sort();
    return names.length > 0 ? names : [word];
  }

  private words(args: string[]): string[] {
    return args.flatMap((word) =>
      word.startsWith("'") || word.startsWith('"')
        ? [this.expand(word)]
        : this.glob(this.expand(word)),
    );
  }

  private startProgram(args: string[]): boolean {
    const [name, ...rest] = args;
    if (this.isWindows) {
      return false;
    }
    if (name === "top" || name === "htop") {
      this.program = new DemoTop(this);
      return true;
    }
    if (name === "ping") {
      const countAt = rest.indexOf("-c");
      const count = countAt >= 0 ? Number(rest[countAt + 1]) : 0;
      const target =
        rest.filter(
          (word, index) =>
            !word.startsWith("-") && (countAt < 0 || index !== countAt + 1),
        )[0] ?? PING_DEFAULT_TARGET;
      this.program = new DemoPing(this, target, count);
      return true;
    }
    if (name === "vim" || name === "vi" || name === "nano") {
      this.program = new DemoVim(this, rest[0] ?? VIM_DEFAULT_FILE);
      return true;
    }
    if ((name === "python3" || name === "python") && rest.length === 0) {
      this.program = new DemoPython(this);
      return true;
    }
    return false;
  }

  private notFound(name: string): string {
    return this.isWindows
      ? `${name}: The term '${name}' is not recognized as a name of a cmdlet, function, script file, or executable program.\n`
      : `bash: ${name}: command not found\n`;
  }

  private runStage(
    stage: DemoStage,
    stdin: string,
    isLast: boolean,
  ): DemoCommandResult {
    const args = this.words(stage.args);
    const [typed, ...rest] = args;
    if (typed === undefined) {
      return { out: stdin, code: 0 };
    }
    const name = this.isWindows ? typed.toLowerCase() : typed;
    const command = this.commands[name];
    if (command === undefined) {
      return { out: this.notFound(typed), code: 127 };
    }
    this.context.isTerminal = isLast && stage.redirect === null;
    const result = command(rest, stdin, this.context);
    this.context.isTerminal = true;
    return result;
  }

  private redirect(stage: DemoStage, text: string): DemoCommandResult | null {
    const target = stage.redirect;
    if (target === null) {
      return null;
    }
    const { tree, cwd } = this.context;
    const path = tree.resolve(cwd, target.path);
    const held = tree.find(path);
    if (held?.kind === "folder") {
      return { out: `bash: ${target.path}: Is a directory\n`, code: 1 };
    }
    const before = target.isAppend && held !== null ? held.text : "";
    if (!tree.write(path, before + text)) {
      return {
        out: `bash: ${target.path}: No such file or directory\n`,
        code: 1,
      };
    }
    return { out: "", code: 0 };
  }

  private runPipeline(pipeline: DemoPipeline): string {
    let text = "";
    let code = 0;
    pipeline.stages.forEach((stage, index) => {
      const isLast = index === pipeline.stages.length - 1;
      const result = this.runStage(stage, text, isLast);
      code = result.code;
      const written = this.redirect(stage, result.out);
      if (written !== null) {
        text = written.out;
        code = result.code === 0 ? written.code : result.code;
      } else {
        text = result.out;
      }
    });
    this.lastCode = code;
    return text;
  }

  private run(line: string): void {
    const text = line.trim();
    if (text === "") {
      this.prompt();
      return;
    }
    const groups = pipelines(text);
    const only = groups[0];
    const sole =
      groups.length === 1 && only?.stages.length === 1
        ? only.stages[0]
        : undefined;
    if (sole !== undefined) {
      const args = this.words(sole.args);
      if (args[0] === "exit" || args[0] === "logout") {
        this.exit();
        return;
      }
      if (args[0] === "clear" || args[0] === "cls") {
        this.write("\x1b[3J\x1b[2J\x1b[H");
        this.prompt();
        return;
      }
      if (this.startProgram(args)) {
        return;
      }
    }
    for (const group of groups) {
      if (group.join === "&&" && this.lastCode !== 0) {
        continue;
      }
      if (group.join === "||" && this.lastCode === 0) {
        continue;
      }
      const printed = this.runPipeline(group);
      if (printed !== "") {
        this.write(printed.replaceAll("\n", "\r\n"));
      }
    }
    this.prompt();
  }

  private complete(before: string): { added: string; choices: string[] } {
    const word = /(\S*)$/.exec(before)?.[1] ?? "";
    const isFirstWord = word.length === before.trimStart().length;
    const { tree, cwd } = this.context;
    const slash = word.lastIndexOf("/");
    const typedFolder = slash >= 0 ? word.slice(0, slash + 1) : "";
    const typedName = slash >= 0 ? word.slice(slash + 1) : word;
    let names: string[];
    if (isFirstWord && slash < 0) {
      names = [
        ...Object.keys(this.commands),
        "clear",
        "exit",
        ...(this.isWindows ? [] : ["top", "ping", "vim"]),
      ];
    } else {
      const folder = tree.find(tree.resolve(cwd, typedFolder || "."));
      names =
        folder?.kind === "folder"
          ? [...folder.entries.entries()].map(([name, entry]) =>
              entry.kind === "folder" ? `${name}/` : name,
            )
          : [];
    }
    const matches = [...new Set(names)]
      .filter(
        (name) =>
          name.startsWith(typedName) &&
          (typedName.startsWith(".") || !name.startsWith(".")),
      )
      .sort();
    if (matches.length === 0) {
      return { added: "", choices: [] };
    }
    const first = matches[0] ?? "";
    if (matches.length === 1) {
      const tail = first.slice(typedName.length);
      return { added: first.endsWith("/") ? tail : `${tail} `, choices: [] };
    }
    let shared = first;
    for (const name of matches) {
      while (!name.startsWith(shared)) {
        shared = shared.slice(0, -1);
      }
    }
    return { added: shared.slice(typedName.length), choices: matches };
  }
}
