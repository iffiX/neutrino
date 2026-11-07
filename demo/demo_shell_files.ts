/**
 * The folders a demo machine's shell lists: a small tree in memory, one per
 * shell, that its commands read and write.
 */

import { sample } from "./demo_fixtures";

/** A file of the tree. `size` stands in for its text where the two differ. */
export interface DemoFile {
  kind: "file";
  text: string;
  size: number;
  isExecutable: boolean;
}

/** A folder of the tree. */
export interface DemoFolder {
  kind: "folder";
  entries: Map<string, DemoEntry>;
}

export type DemoEntry = DemoFile | DemoFolder;

const TRAIN_PY = `import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_DIR = "models/qwen-7b"
DEVICE = "cuda:1"


def main() -> None:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR).to(DEVICE)
    prompt = tokenizer("Hello", return_tensors="pt").to(DEVICE)
    print(tokenizer.decode(model.generate(**prompt, max_new_tokens=32)[0]))


if __name__ == "__main__":
    main()
`;

const README_MD = sample(
  `# 家里的台式机

一台放在家里的电脑，手机上打开就能用。

- models/    下载好的模型
- projects/  正在写的代码
- train.py   试模型的小脚本
`,
  `# The desktop at home

A computer at home that the phone opens anywhere.

- models/    downloaded models
- projects/  code in progress
- train.py   a small script to try a model
`,
);

const NOTES_TXT = sample(
  `周末要做的事
1. 把新硬盘挂到 /data
2. 3060 专门跑模型，4070 留给桌面
3. 备份 projects 目录
`,
  `Weekend to-do
1. Mount the new disk at /data
2. The 3060 runs models, the 4070 stays for the desktop
3. Back up the projects folder
`,
);

const BASHRC = `# ~/.bashrc
export EDITOR=vim
alias ll='ls -l'
alias la='ls -a'
`;

const OS_RELEASE = `PRETTY_NAME="Ubuntu 24.04.1 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.1 LTS (Noble Numbat)"
ID=ubuntu
ID_LIKE=debian
`;

const WINDOWS_NOTES = sample(
  `周末要做的事
1. 笔记本的系统更新
2. 把照片拷到台式机
`,
  `Weekend to-do
1. Update the laptop's system
2. Copy the photos to the desktop
`,
);

function file(text: string, size?: number, isExecutable = false): DemoFile {
  return {
    kind: "file",
    text,
    size: size ?? new TextEncoder().encode(text).length,
    isExecutable,
  };
}

function folder(entries: Record<string, DemoEntry> = {}): DemoFolder {
  return { kind: "folder", entries: new Map(Object.entries(entries)) };
}

function linuxTree(account: string, hostname: string): DemoFolder {
  return folder({
    bin: folder(),
    etc: folder({
      hostname: file(`${hostname}\n`),
      "os-release": file(OS_RELEASE),
    }),
    home: folder({
      [account]: folder({
        ".bashrc": file(BASHRC),
        "README.md": file(README_MD),
        "notes.txt": file(NOTES_TXT),
        "requirements.txt": file("torch\ntransformers\naccelerate\n"),
        "train.py": file(TRAIN_PY),
        "run.sh": file("#!/bin/bash\npython3 train.py\n", undefined, true),
        Desktop: folder(),
        Documents: folder(
          sample("周报", "weekly") === "周报"
            ? { "周报.md": file("# 本周\n- 把代码跑通了\n") }
            : { "weekly.md": file("# This week\n- Got the code running\n") },
        ),
        Downloads: folder({
          "ubuntu-24.04.1-desktop-amd64.iso": file("", 6_114_656_256),
        }),
        models: folder({
          "qwen-7b": folder({
            "config.json": file('{"model_type": "qwen"}\n'),
            "model.safetensors": file("", 4_320_000_000),
          }),
        }),
        projects: folder({
          blog: folder({
            "index.md": file(sample("# 我的博客\n", "# My blog\n")),
          }),
          "model-lab": folder({ "eval.py": file("print('eval')\n") }),
        }),
      }),
    }),
    tmp: folder(),
    usr: folder({ bin: folder(), lib: folder() }),
    var: folder({ log: folder() }),
  });
}

function windowsTree(account: string): DemoFolder {
  return folder({
    Users: folder({
      [account]: folder({
        Desktop: folder(),
        Documents: folder({ "notes.txt": file(WINDOWS_NOTES) }),
        Downloads: folder(),
        Pictures: folder(),
        "notes.txt": file(WINDOWS_NOTES),
      }),
    }),
    Windows: folder(),
    "Program Files": folder(),
  });
}

/** One shell's tree and the path rules over it, `/` separated inside. */
export class DemoFileTree {
  readonly home: string;
  private readonly root: DemoFolder;

  /**
   * Builds the tree a machine starts with.
   *
   * Args:
   *   account: The account the shell runs as.
   *   hostname: The machine's host name.
   *   platformOs: The machine's system.
   */
  constructor(account: string, hostname: string, platformOs: string) {
    const isWindows = platformOs === "windows";
    this.root = isWindows ? windowsTree(account) : linuxTree(account, hostname);
    this.home = isWindows ? `/Users/${account}` : `/home/${account}`;
  }

  /** The absolute path a typed path names, from a working folder. */
  resolve(cwd: string, path: string): string {
    const expanded = path
      .replace(/^~(?=\/|$)/, this.home)
      .replaceAll("\\", "/");
    const start = expanded.startsWith("/") ? "" : cwd;
    const parts: string[] = [];
    for (const part of `${start}/${expanded}`.split("/")) {
      if (part === "..") {
        parts.pop();
      } else if (part !== "" && part !== ".") {
        parts.push(part);
      }
    }
    return `/${parts.join("/")}`;
  }

  /** The entry at an absolute path, or null. */
  find(path: string): DemoEntry | null {
    let entry: DemoEntry = this.root;
    for (const part of path.split("/").filter((piece) => piece !== "")) {
      if (entry.kind !== "folder") {
        return null;
      }
      const next: DemoEntry | undefined = entry.entries.get(part);
      if (next === undefined) {
        return null;
      }
      entry = next;
    }
    return entry;
  }

  /** The folder a new entry at an absolute path goes in, or null. */
  parentOf(path: string): DemoFolder | null {
    const parent = this.find(path.slice(0, path.lastIndexOf("/")) || "/");
    return parent?.kind === "folder" ? parent : null;
  }

  /** The last part of an absolute path. */
  nameOf(path: string): string {
    return path.slice(path.lastIndexOf("/") + 1);
  }

  /** Writes a file at an absolute path. Returns false with no folder for it. */
  write(path: string, text: string): boolean {
    const parent = this.parentOf(path);
    if (parent === null) {
      return false;
    }
    parent.entries.set(this.nameOf(path), file(text));
    return true;
  }
}

/** A size in a person's units, as `ls -h` and `df -h` print it. */
export function humanSize(bytes: number): string {
  const units = ["", "K", "M", "G", "T"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text =
    value < 10 && unit > 0 ? value.toFixed(1) : String(Math.ceil(value));
  return `${text}${units[unit]}`;
}
