import { textCells } from "./demo_shell_commands";

/**
 * What a demo shell does with the bytes the terminal sends: the keys they mean,
 * and the line being typed with its cursor, as readline keeps it.
 */

/** One key: `text` for a typed character, `name` for any other key. */
export interface DemoKey {
  name: string;
  text: string;
}

const CSI_KEYS: Record<string, string> = {
  A: "up",
  B: "down",
  C: "right",
  D: "left",
  F: "end",
  H: "home",
  Z: "backtab",
  "1~": "home",
  "3~": "delete",
  "4~": "end",
  "5~": "page_up",
  "6~": "page_down",
};

const CONTROL_KEYS: Record<number, string> = {
  9: "tab",
  13: "enter",
  10: "enter",
  127: "backspace",
  8: "backspace",
};

/**
 * Reads the keys out of the bytes a terminal sends.
 *
 * Args:
 *   data: The terminal's text, escape sequences and all.
 *
 * Returns:
 *   The keys in the order they were pressed.
 */
export function decodeKeys(data: string): DemoKey[] {
  const keys: DemoKey[] = [];
  let at = 0;
  while (at < data.length) {
    const code = data.codePointAt(at) ?? 0;
    const character = String.fromCodePoint(code);
    if (code !== 0x1b) {
      at += character.length;
      if (CONTROL_KEYS[code] !== undefined) {
        keys.push({ name: CONTROL_KEYS[code], text: "" });
      } else if (code < 32) {
        const letter = String.fromCharCode(code + 96);
        keys.push({ name: `ctrl_${letter}`, text: "" });
      } else {
        keys.push({ name: "", text: character });
      }
      continue;
    }
    const csi = /^(?:\[|O)(?:1;(\d+))?([0-9]*~|[A-Za-z])/.exec(
      data.slice(at + 1),
    );
    if (csi !== null) {
      at += 1 + csi[0].length;
      const name = CSI_KEYS[csi[2] ?? ""] ?? "";
      const parameter = Number(csi[1] ?? "1");
      const isCtrl = parameter >= 5;
      const isWordMove = isCtrl && (name === "left" || name === "right");
      keys.push({ name: isWordMove ? `word_${name}` : name, text: "" });
      continue;
    }
    const next = data[at + 1];
    if (next !== undefined && next !== "\x1b") {
      at += 2;
      keys.push({ name: `alt_${next}`, text: "" });
      continue;
    }
    at += 1;
    keys.push({ name: "escape", text: "" });
  }
  return keys;
}

/** What a line editor tells its owner. */
export interface DemoLineEvents {
  onSubmit: (line: string) => void;
  onInterrupt: () => void;
  onEof: () => void;
  onClear: () => void;
  /** The ways to finish the word before the cursor, longest match first. */
  complete: (before: string) => { added: string; choices: string[] };
}

const SAVED_LINE_NONE = -1;

/** The line being typed, its cursor and its history. */
export class DemoLineEditor {
  history: string[] = [];
  private prompt = "";
  private promptCells = 0;
  private line = "";
  private cursor = 0;
  private recall = SAVED_LINE_NONE;
  private draft = "";
  private lastDeleted = "";

  constructor(
    private readonly write: (text: string) => void,
    private readonly cols: () => number,
    private readonly events: DemoLineEvents,
  ) {}

  /** Prints a prompt and starts an empty line. */
  begin(prompt: string, promptCells: number): void {
    this.prompt = prompt;
    this.promptCells = promptCells;
    this.line = "";
    this.cursor = 0;
    this.recall = SAVED_LINE_NONE;
    this.draft = "";
    this.write(prompt);
  }

  /** Takes one key. */
  key(key: DemoKey): void {
    if (key.text !== "") {
      this.insert(key.text);
      return;
    }
    switch (key.name) {
      case "enter":
        this.submit();
        break;
      case "backspace":
      case "ctrl_h":
        this.deleteBack();
        break;
      case "delete":
        this.deleteForward();
        break;
      case "ctrl_d":
        if (this.line === "") {
          this.events.onEof();
        } else {
          this.deleteForward();
        }
        break;
      case "ctrl_c":
        this.write("^C\r\n");
        this.events.onInterrupt();
        break;
      case "ctrl_l":
        this.events.onClear();
        break;
      case "left":
      case "ctrl_b":
        this.moveTo(this.cursor - 1);
        break;
      case "right":
      case "ctrl_f":
        this.moveTo(this.cursor + 1);
        break;
      case "home":
      case "ctrl_a":
        this.moveTo(0);
        break;
      case "end":
      case "ctrl_e":
        this.moveTo(this.chars().length);
        break;
      case "word_left":
      case "alt_b":
        this.moveTo(this.wordStart());
        break;
      case "word_right":
      case "alt_f":
        this.moveTo(this.wordEnd());
        break;
      case "up":
      case "ctrl_p":
        this.recallBy(-1);
        break;
      case "down":
      case "ctrl_n":
        this.recallBy(1);
        break;
      case "ctrl_u":
        this.cut(0, this.cursor);
        break;
      case "ctrl_k":
        this.cut(this.cursor, this.chars().length);
        break;
      case "ctrl_w":
        this.cut(this.wordStart(), this.cursor);
        break;
      case "ctrl_y":
        this.insert(this.lastDeleted);
        break;
      case "alt_.":
        this.insertLastWord();
        break;
      case "tab":
        this.completeWord();
        break;
      default:
        break;
    }
  }

  /** Draws the line again after the window changed width. */
  redrawAfterResize(): void {
    this.redraw(
      this.promptCells + textCells(this.chars().slice(0, this.cursor).join("")),
    );
  }

  private chars(): string[] {
    return [...this.line];
  }

  private cellOf(index: number): number {
    return this.promptCells + textCells(this.chars().slice(0, index).join(""));
  }

  /**
   * Writes the prompt and the line again and puts the cursor back.
   *
   * Args:
   *   oldCell: The cell the screen's cursor stands at, counted from the
   *     prompt's start.
   */
  private redraw(oldCell: number): void {
    const cols = this.cols();
    const up = Math.floor(oldCell / cols);
    let out = `${up > 0 ? `\x1b[${up}A` : ""}\r\x1b[J${this.prompt}${this.line}`;
    const total = this.cellOf(this.chars().length);
    if (total > 0 && total % cols === 0) {
      out += " \r";
    }
    const target = this.cellOf(this.cursor);
    const rows = Math.floor(total / cols) - Math.floor(target / cols);
    if (rows > 0) {
      out += `\x1b[${rows}A`;
    }
    out += "\r";
    if (target % cols > 0) {
      out += `\x1b[${target % cols}C`;
    }
    this.write(out);
  }

  private replace(next: string, cursor: number): void {
    const old = this.cellOf(this.cursor);
    this.line = next;
    this.cursor = cursor;
    this.redraw(old);
  }

  private insert(text: string): void {
    const chars = this.chars();
    const added = [...text];
    if (this.cursor === chars.length) {
      this.line += text;
      this.cursor += added.length;
      const total = this.cellOf(this.cursor);
      const cols = this.cols();
      this.write(total % cols === 0 ? `${text} \r` : text);
      return;
    }
    const next = [
      ...chars.slice(0, this.cursor),
      ...added,
      ...chars.slice(this.cursor),
    ].join("");
    this.replace(next, this.cursor + added.length);
  }

  private submit(): void {
    const line = this.line;
    const total = this.cellOf(this.chars().length);
    const rows =
      Math.floor(total / this.cols()) -
      Math.floor(this.cellOf(this.cursor) / this.cols());
    this.write(`${rows > 0 ? `\x1b[${rows}B` : ""}\r\n`);
    if (line.trim() !== "" && this.history[this.history.length - 1] !== line) {
      this.history.push(line);
    }
    this.line = "";
    this.cursor = 0;
    this.events.onSubmit(line);
  }

  private deleteBack(): void {
    if (this.cursor === 0) {
      return;
    }
    const chars = this.chars();
    chars.splice(this.cursor - 1, 1);
    this.replace(chars.join(""), this.cursor - 1);
  }

  private deleteForward(): void {
    const chars = this.chars();
    if (this.cursor >= chars.length) {
      return;
    }
    chars.splice(this.cursor, 1);
    this.replace(chars.join(""), this.cursor);
  }

  private moveTo(index: number): void {
    const next = Math.max(0, Math.min(this.chars().length, index));
    if (next === this.cursor) {
      return;
    }
    const old = this.cellOf(this.cursor);
    this.cursor = next;
    this.redraw(old);
  }

  private wordStart(): number {
    const chars = this.chars();
    let at = this.cursor;
    while (at > 0 && chars[at - 1] === " ") {
      at -= 1;
    }
    while (at > 0 && chars[at - 1] !== " ") {
      at -= 1;
    }
    return at;
  }

  private wordEnd(): number {
    const chars = this.chars();
    let at = this.cursor;
    while (at < chars.length && chars[at] === " ") {
      at += 1;
    }
    while (at < chars.length && chars[at] !== " ") {
      at += 1;
    }
    return at;
  }

  private cut(from: number, to: number): void {
    const chars = this.chars();
    this.lastDeleted = chars.slice(from, to).join("");
    chars.splice(from, to - from);
    this.replace(chars.join(""), from);
  }

  private recallBy(step: number): void {
    const count = this.history.length;
    if (count === 0) {
      return;
    }
    const current = this.recall === SAVED_LINE_NONE ? count : this.recall;
    const next = Math.max(0, Math.min(count, current + step));
    if (next === current) {
      return;
    }
    if (this.recall === SAVED_LINE_NONE) {
      this.draft = this.line;
    }
    this.recall = next === count ? SAVED_LINE_NONE : next;
    const text = next === count ? this.draft : (this.history[next] ?? "");
    this.replace(text, [...text].length);
  }

  private insertLastWord(): void {
    const last = this.history[this.history.length - 1] ?? "";
    const word = last.trim().split(/\s+/).pop() ?? "";
    if (word !== "") {
      this.insert(word);
    }
  }

  private completeWord(): void {
    const before = this.chars().slice(0, this.cursor).join("");
    const { added, choices } = this.events.complete(before);
    if (added !== "") {
      this.insert(added);
      return;
    }
    if (choices.length > 1) {
      const old = this.cellOf(this.chars().length);
      const rows =
        Math.floor(old / this.cols()) -
        Math.floor(this.cellOf(this.cursor) / this.cols());
      const down = rows > 0 ? `\x1b[${rows}B` : "";
      this.write(
        `${down}\r\n${choices.join("  ")}\r\n${this.prompt}${this.line}`,
      );
      const tail = textCells(this.chars().slice(this.cursor).join(""));
      if (tail > 0) {
        this.write(`\x1b[${tail}D`);
      }
    }
  }
}
