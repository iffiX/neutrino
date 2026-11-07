// The remote machine's picture in the demo's viewer: a desktop drawn in the page,
// its windows moved and focused by the mouse events the viewer sends it, as the
// real picture answers RustDesk's. Its size is a fixed frame of pixels.
const DESKTOP_FRAME_WIDTH = 1280;
const DESKTOP_FRAME_HEIGHT = 720;

const makeDesktopScene = (() => {
  const CLOCK_REFRESH_MS = 20000;
  const DOUBLE_TAP_MS = 400;
  const WINDOW_MIN_WIDTH = 320;
  const WINDOW_MIN_HEIGHT = 180;
  const TITLE_KEEP_PX = 80;
  const EDITOR_FONT =
    '13px ui-monospace, Menlo, Consolas, "DejaVu Sans Mono", monospace';
  const EDITOR_LINE_PX = 20;
  const EDITOR_TAB_SIZE = 4;
  const SHELL_CELL_HEIGHT_PX = 16;
  const SHELL_FONT_SIZE = 13;
  const SHELL_FONT =
    'ui-monospace, Menlo, Consolas, "DejaVu Sans Mono", monospace';
  const SHELL_PADDING_PX = 12;
  const WALLPAPERS = ["dusk", "dawn", "night"];
  const ESCAPE = "\x1b";

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
  // The sample files in the language the demo was opened in (?lang=en on the top page).
  const IS_ENGLISH_DEMO = (() => {
    try {
      return (
        new URLSearchParams(window.top.location.search).get("lang") === "en"
      );
    } catch (e) {
      return false;
    }
  })();
  const README_MD = IS_ENGLISH_DEMO
    ? `# The desktop at home

A computer at home that the phone opens anywhere.

- models/    downloaded models
- projects/  code in progress
- train.py   a small script to try a model
`
    : `# 家里的台式机

一台放在家里的电脑，手机上打开就能用。

- models/    下载好的模型
- projects/  正在写的代码
- train.py   试模型的小脚本
`;
  const NOTES_TXT = IS_ENGLISH_DEMO
    ? `Weekend to-do
1. Mount the new disk at /data
2. The 3060 runs models, the 4070 stays for the desktop
3. Back up the projects folder
`
    : `周末要做的事
1. 把新硬盘挂到 /data
2. 3060 专门跑模型，4070 留给桌面
3. 备份 projects 目录
`;
  const WINDOWS_NOTES = IS_ENGLISH_DEMO
    ? `Weekend to-do
1. Update the laptop's system
2. Copy the photos to the desktop
`
    : `周末要做的事
1. 笔记本的系统更新
2. 把照片拷到台式机
`;
  const PYTHON_WORDS = new Set(
    "import from as def return if else elif for while in not and or None True False class with try except pass".split(
      " ",
    ),
  );

  const PICTURE_PATHS = {
    folder:
      "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    file: "M6 3h8l4 4v14H6zM14 3v4h4",
    code: "m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14",
    terminal: "m5 8 5 4-5 4M12 17h7",
    globe:
      "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
    gear: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1",
    wifi: "M4 10a12 12 0 0 1 16 0M7 13.5a7.5 7.5 0 0 1 10 0M12 18h.01",
    volume: "M4 10v4h3l4 4V6l-4 4zM15 9a4 4 0 0 1 0 6",
    battery: "M3 8h16v8H3zM21 11v2M6 11h8v2H6z",
    back: "m14 6-6 6 6 6",
    up: "m6 14 6-6 6 6",
    search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
    window: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    trash: "M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13",
  };

  function element(tag, className, text) {
    const made = document.createElement(tag);
    if (className) made.className = className;
    if (text !== undefined) made.textContent = text;
    return made;
  }

  function picture(name, size) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.7");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", PICTURE_PATHS[name]);
    svg.appendChild(path);
    return svg;
  }

  function wallpaper() {
    const holder = element("div", "ds_wallpaper");
    holder.innerHTML =
      '<svg viewBox="0 0 1280 720" preserveAspectRatio="xMidYMid slice" width="1280" height="720">' +
      '<defs><linearGradient id="ds_sky" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="var(--ds-sky-top)"/>' +
      '<stop offset="0.62" stop-color="var(--ds-sky-mid)"/>' +
      '<stop offset="1" stop-color="var(--ds-sky-low)"/></linearGradient>' +
      '<radialGradient id="ds_sun" cx="0.5" cy="0.5" r="0.5">' +
      '<stop offset="0" stop-color="var(--ds-sun)" stop-opacity="1"/>' +
      '<stop offset="0.28" stop-color="var(--ds-sun)" stop-opacity="0.75"/>' +
      '<stop offset="1" stop-color="var(--ds-sun)" stop-opacity="0"/></radialGradient></defs>' +
      '<rect width="1280" height="720" fill="url(#ds_sky)"/>' +
      '<circle cx="880" cy="400" r="260" fill="url(#ds_sun)"/>' +
      '<path d="M0 470 C120 410 210 440 330 400 S540 330 660 390 S860 450 980 390 S1180 340 1280 400 V720 H0Z" fill="var(--ds-far)"/>' +
      '<path d="M0 540 C150 490 280 530 420 490 S660 440 800 500 S1060 560 1280 480 V720 H0Z" fill="var(--ds-mid)"/>' +
      '<path d="M0 630 C200 580 360 620 560 590 S920 560 1090 610 S1220 640 1280 620 V720 H0Z" fill="var(--ds-near)"/>' +
      "</svg>";
    return holder;
  }

  // The folders the file manager opens, a name per item and where it leads.
  function fileTree(isWindows) {
    if (isWindows) {
      return {
        home: {
          path: "C:\\Users\\xiaoming",
          items: [
            { name: "Desktop", to: "empty" },
            { name: "Documents", to: "documents" },
            { name: "Downloads", to: "empty" },
            { name: "Pictures", to: "empty" },
            { name: "notes.txt", doc: "notes.txt" },
          ],
        },
        documents: {
          path: "C:\\Users\\xiaoming\\Documents",
          items: [{ name: "notes.txt", doc: "notes.txt" }],
        },
        downloads: { path: "C:\\Users\\xiaoming\\Downloads", items: [] },
        pictures: { path: "C:\\Users\\xiaoming\\Pictures", items: [] },
        empty: { path: "C:\\Users\\xiaoming\\Desktop", items: [] },
      };
    }
    return {
      home: {
        path: "/home/xiaoming",
        items: [
          { name: "Desktop", to: "empty" },
          { name: "Documents", to: "documents" },
          { name: "Downloads", to: "downloads" },
          { name: "models", to: "models" },
          { name: "projects", to: "projects" },
          { name: "README.md", doc: "README.md" },
          { name: "notes.txt", doc: "notes.txt" },
          { name: "requirements.txt" },
          { name: "run.sh" },
          { name: "train.py", doc: "train.py" },
        ],
      },
      documents: {
        path: "/home/xiaoming/Documents",
        items: [{ name: IS_ENGLISH_DEMO ? "weekly.md" : "周报.md" }],
      },
      downloads: {
        path: "/home/xiaoming/Downloads",
        items: [{ name: "ubuntu-24.04.1-desktop-amd64.iso" }],
      },
      pictures: { path: "/home/xiaoming/Pictures", items: [] },
      models: {
        path: "/home/xiaoming/models",
        items: [{ name: "qwen-7b", to: "qwen" }],
      },
      qwen: {
        path: "/home/xiaoming/models/qwen-7b",
        items: [{ name: "config.json" }, { name: "model.safetensors" }],
      },
      projects: {
        path: "/home/xiaoming/projects",
        items: [
          { name: "blog", to: "empty" },
          { name: "model-lab", to: "empty" },
        ],
      },
      empty: { path: "/home/xiaoming/Desktop", items: [] },
    };
  }

  return function make(options) {
    const isWindows = options.platformOs === "windows";
    const root = element(
      "div",
      "ds " + (isWindows ? "ds_windows" : "ds_linux"),
    );
    const canvas = document.createElement("canvas").getContext("2d");
    canvas.font = EDITOR_FONT;
    const windows = {};
    let focused = null;
    let topLayer = 10;
    let drag = null;
    let lastTap = { at: 0, target: null };
    let wallpaperIndex = 0;
    let menu = null;
    let clockTimer = 0;
    let shell = null;

    root.dataset.wallpaper = WALLPAPERS[wallpaperIndex];
    root.appendChild(wallpaper());
    const cursor = element("div", "ds_cursor");
    cursor.innerHTML =
      '<svg width="20" height="24" viewBox="0 0 20 24"><path d="M2 1.5v18l5-4.6 3.2 7.2 3.1-1.4-3.2-7H17z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const band = element("div", "ds_band");
    band.hidden = true;

    function moveCursor(x, y) {
      cursor.style.transform = `translate(${x}px, ${y}px)`;
    }

    // --- the bars ---

    const clock = element("span", "ds_clock");
    function drawClock() {
      const now = new Date();
      const time = now.toTimeString().slice(0, 5);
      const date =
        language === "en"
          ? now.toLocaleDateString("en-US", { month: "short", day: "numeric" })
          : now.getMonth() + 1 + "月" + now.getDate() + "日";
      clock.textContent = isWindows ? time : date + " " + time;
    }
    drawClock();
    clockTimer = window.setInterval(drawClock, CLOCK_REFRESH_MS);

    function statusIcons() {
      const icons = element("span", "ds_status");
      for (const name of ["wifi", "volume", "battery"]) {
        icons.appendChild(picture(name, 16));
      }
      return icons;
    }

    if (isWindows) {
      const bar = element("div", "ds_taskbar");
      const middle = element("div", "ds_taskbar_apps");
      middle.appendChild(dockItem("window", "", "start"));
      middle.appendChild(dockItem("search", "", "start"));
      middle.appendChild(dockItem("folder", "files"));
      middle.appendChild(dockItem("code", "code"));
      middle.appendChild(dockItem("terminal", "term"));
      bar.appendChild(middle);
      const tray = element("div", "ds_tray");
      tray.appendChild(statusIcons());
      tray.appendChild(clock);
      bar.appendChild(tray);
      root.appendChild(bar);
    } else {
      const bar = element("div", "ds_topbar");
      bar.appendChild(element("span", "", t("demo.desktop.activities")));
      bar.appendChild(clock);
      bar.appendChild(statusIcons());
      root.appendChild(bar);
      const dock = element("div", "ds_dock");
      dock.appendChild(dockItem("folder", "files"));
      dock.appendChild(dockItem("code", "code"));
      dock.appendChild(dockItem("terminal", "term"));
      dock.appendChild(dockItem("globe", "", "browser"));
      dock.appendChild(dockItem("gear", "", "settings"));
      root.appendChild(dock);
    }

    function dockItem(pictureName, windowName, flavour) {
      const item = element(
        "div",
        "ds_dock_item ds_dock_" + (windowName || flavour),
      );
      item.dataset.action = windowName ? "dock" : "none";
      item.dataset.window = windowName;
      item.appendChild(picture(pictureName, 26));
      return item;
    }

    const icons = element("div", "ds_icons");
    root.appendChild(icons);
    function desktopIcon(name, pictureName) {
      const item = element("div", "ds_icon");
      item.dataset.action = "desktop_icon";
      item.appendChild(picture(pictureName, 40));
      item.appendChild(element("span", "", name));
      icons.appendChild(item);
    }
    desktopIcon(t("demo.desktop.home"), "folder");
    desktopIcon(t("demo.desktop.trash"), "trash");

    // --- the windows ---

    function makeWindow(name, title, box) {
      const frame = element("div", "ds_window");
      const head = element("div", "ds_title");
      const word = element("span", "ds_title_word", title);
      head.appendChild(word);
      const buttons = element("div", "ds_title_buttons");
      for (const [action, mark] of [
        ["win_min", "–"],
        ["win_max", "□"],
        ["win_close", "×"],
      ]) {
        const button = element("div", "ds_title_btn " + action, mark);
        button.dataset.action = action;
        buttons.appendChild(button);
      }
      head.appendChild(buttons);
      frame.appendChild(head);
      const body = element("div", "ds_body");
      frame.appendChild(body);
      frame.appendChild(element("div", "ds_grip"));
      const held = {
        name,
        frame,
        word,
        body,
        x: box.x,
        y: box.y,
        w: box.w,
        h: box.h,
        isOpen: true,
        isMaximized: false,
      };
      frame.dataset.window = name;
      windows[name] = held;
      placeWindow(held);
      root.appendChild(frame);
      return held;
    }

    function topInset() {
      return isWindows ? 0 : 28;
    }

    function leftInset() {
      return isWindows ? 0 : 62;
    }

    function bottomInset() {
      return isWindows ? 44 : 0;
    }

    function placeWindow(held) {
      const box = held.isMaximized
        ? {
            x: leftInset(),
            y: topInset(),
            w: DESKTOP_FRAME_WIDTH - leftInset(),
            h: DESKTOP_FRAME_HEIGHT - topInset() - bottomInset(),
          }
        : held;
      held.frame.style.left = box.x + "px";
      held.frame.style.top = box.y + "px";
      held.frame.style.width = box.w + "px";
      held.frame.style.height = box.h + "px";
      held.frame.classList.toggle("is_max", held.isMaximized);
    }

    function focusWindow(held) {
      focused = held;
      topLayer += 1;
      held.frame.style.zIndex = String(topLayer);
      for (const each of Object.values(windows)) {
        each.frame.classList.toggle("is_focused", each === held);
      }
      drawDock();
      if (held.name === "code") placeCaret();
    }

    function blurWindows() {
      focused = null;
      for (const each of Object.values(windows)) {
        each.frame.classList.remove("is_focused");
      }
    }

    function drawDock() {
      for (const item of root.querySelectorAll(".ds_dock_item")) {
        const held = windows[item.dataset.window];
        item.classList.toggle("is_running", !!held && held.isOpen);
        item.classList.toggle("is_front", !!held && held === focused);
      }
    }

    function setOpen(held, isOpen) {
      held.isOpen = isOpen;
      held.frame.hidden = !isOpen;
      if (!isOpen && focused === held) {
        const next = Object.values(windows).find((each) => each.isOpen);
        if (next) focusWindow(next);
        else blurWindows();
      }
      drawDock();
    }

    // --- the file manager ---

    const tree = fileTree(isWindows);
    let folderKey = "home";
    let folderTrail = [];
    let selectedItem = -1;
    const filesWindow = makeWindow(
      "files",
      isWindows ? t("demo.desktop.explorer") : t("demo.desktop.files"),
      isWindows
        ? { x: 660, y: 40, w: 590, h: 370 }
        : { x: 730, y: 50, w: 530, h: 380 },
    );
    const filesTop = element("div", "fm_top");
    const backButton = element("div", "fm_btn");
    backButton.dataset.action = "fm_back";
    backButton.appendChild(picture("back", 16));
    const pathWord = element("div", "fm_path");
    filesTop.appendChild(backButton);
    filesTop.appendChild(pathWord);
    filesWindow.body.appendChild(filesTop);
    const filesMain = element("div", "fm_main");
    const sideBar = element("div", "fm_side");
    for (const [key, word] of [
      ["home", "demo.desktop.home"],
      ["documents", "demo.desktop.documents"],
      ["downloads", "demo.desktop.downloads"],
      ["pictures", "demo.desktop.pictures"],
    ]) {
      const row = element("div", "fm_side_row", t(word));
      row.dataset.action = "fm_side";
      row.dataset.folder = key;
      row.prepend(picture("folder", 14));
      sideBar.appendChild(row);
    }
    filesMain.appendChild(sideBar);
    const grid = element("div", "fm_grid ds_scroll");
    filesMain.appendChild(grid);
    filesWindow.body.appendChild(filesMain);
    const filesFoot = element("div", "fm_foot");
    filesWindow.body.appendChild(filesFoot);

    function drawFolder() {
      const folder = tree[folderKey];
      pathWord.textContent = folder.path;
      grid.replaceChildren();
      folder.items.forEach((item, index) => {
        const cell = element(
          "div",
          "fm_item" + (index === selectedItem ? " is_selected" : ""),
        );
        cell.dataset.action = "fm_item";
        cell.dataset.index = String(index);
        const mark = picture(item.to ? "folder" : "file", 44);
        mark.classList.add(item.to ? "fm_mark_folder" : "fm_mark_file");
        cell.appendChild(mark);
        cell.appendChild(element("span", "fm_name", item.name));
        grid.appendChild(cell);
      });
      if (folder.items.length === 0) {
        grid.appendChild(element("div", "fm_empty", t("demo.desktop.empty")));
      }
      filesFoot.textContent =
        selectedItem >= 0
          ? t("demo.desktop.selected", {
              name: folder.items[selectedItem].name,
            })
          : t("demo.desktop.items", { count: folder.items.length });
      for (const row of sideBar.children) {
        row.classList.toggle("is_on", row.dataset.folder === folderKey);
      }
      backButton.classList.toggle("is_off", folderTrail.length === 0);
    }

    function openFolder(key) {
      folderTrail.push(folderKey);
      folderKey = key;
      selectedItem = -1;
      drawFolder();
    }

    function openItem(item) {
      if (item.to) {
        openFolder(item.to);
      } else if (item.doc) {
        openDocument(item.doc);
        setOpen(windows.code, true);
        focusWindow(windows.code);
      }
    }

    // --- the code editor ---

    const documents = isWindows
      ? { "notes.txt": { text: WINDOWS_NOTES } }
      : {
          "train.py": { text: TRAIN_PY },
          "README.md": { text: README_MD },
          "notes.txt": { text: NOTES_TXT },
        };
    for (const doc of Object.values(documents)) {
      doc.lines = doc.text.replace(/\n$/, "").split("\n");
      doc.line = 0;
      doc.col = 0;
      doc.isDirty = false;
    }
    let openDocs = Object.keys(documents).slice(0, 2);
    let docName = openDocs[0];
    const codeWindow = makeWindow(
      "code",
      "",
      isWindows
        ? { x: 40, y: 24, w: 640, h: 370 }
        : { x: 84, y: 40, w: 660, h: 400 },
    );
    const editorRoot = element("div", "ed");
    const activity = element("div", "ed_activity");
    for (const name of ["file", "search", "gear"]) {
      activity.appendChild(picture(name, 20));
    }
    const explorer = element("div", "ed_explorer");
    explorer.appendChild(
      element("div", "ed_explorer_title", t("demo.desktop.explorer_side")),
    );
    const explorerList = element("div", "ed_explorer_list");
    explorer.appendChild(explorerList);
    const editorMain = element("div", "ed_main");
    const editorTabs = element("div", "ed_tabs");
    const editorScroll = element("div", "ed_scroll ds_scroll");
    const editorLines = element("div", "ed_lines");
    const caret = element("div", "ed_caret");
    editorScroll.appendChild(editorLines);
    editorScroll.appendChild(caret);
    const editorFoot = element("div", "ed_foot");
    editorMain.appendChild(editorTabs);
    editorMain.appendChild(editorScroll);
    editorMain.appendChild(editorFoot);
    editorRoot.appendChild(activity);
    editorRoot.appendChild(explorer);
    editorRoot.appendChild(editorMain);
    codeWindow.body.appendChild(editorRoot);

    function currentDoc() {
      return documents[docName];
    }

    function colorLine(holder, text) {
      holder.replaceChildren();
      if (docName.endsWith(".md") && /^#/.test(text)) {
        holder.appendChild(element("span", "tk_head", text));
        return;
      }
      if (!docName.endsWith(".py")) {
        holder.textContent = text;
        return;
      }
      const parts =
        text.match(/#.*$|"[^"]*"?|'[^']*'?|\d+|[A-Za-z_]\w*|\s+|./g) || [];
      parts.forEach((part, index) => {
        let kind = "";
        if (part.startsWith("#")) kind = "tk_note";
        else if (/^["']/.test(part)) kind = "tk_text";
        else if (/^\d/.test(part)) kind = "tk_number";
        else if (PYTHON_WORDS.has(part)) kind = "tk_word";
        else if (/^[A-Za-z_]/.test(part) && parts[index + 1] === "(") {
          kind = "tk_call";
        }
        holder.appendChild(element("span", kind, part));
      });
    }

    function lineRow(index) {
      const row = element("div", "ed_line");
      row.dataset.action = "ed_text";
      row.dataset.line = String(index);
      row.appendChild(element("span", "ed_no", String(index + 1)));
      const text = element("span", "ed_code");
      colorLine(text, currentDoc().lines[index]);
      row.appendChild(text);
      return row;
    }

    function drawEditor() {
      const doc = currentDoc();
      codeWindow.word.textContent =
        (doc.isDirty ? "● " : "") + docName + " - Visual Studio Code";
      editorLines.replaceChildren();
      doc.lines.forEach((_line, index) => {
        editorLines.appendChild(lineRow(index));
      });
      editorTabs.replaceChildren();
      for (const name of openDocs) {
        const tab = element(
          "div",
          "ed_tab" + (name === docName ? " is_on" : ""),
          (documents[name].isDirty ? "● " : "") + name,
        );
        tab.dataset.action = "ed_tab";
        tab.dataset.doc = name;
        editorTabs.appendChild(tab);
      }
      explorerList.replaceChildren();
      for (const name of Object.keys(documents)) {
        const row = element(
          "div",
          "ed_file" + (name === docName ? " is_on" : ""),
          name,
        );
        row.dataset.action = "ed_file";
        row.dataset.doc = name;
        explorerList.appendChild(row);
      }
      placeCaret();
    }

    function placeCaret() {
      const doc = currentDoc();
      const text = doc.lines[doc.line].slice(0, doc.col);
      const row = editorLines.children[doc.line];
      if (!row) return;
      const code = row.querySelector(".ed_code");
      caret.style.top = row.offsetTop + "px";
      caret.style.left =
        code.offsetLeft + canvas.measureText(text).width + "px";
      caret.hidden = focused !== windows.code;
      for (const each of editorLines.children) {
        each.classList.toggle("is_current", each === row);
      }
      const top = row.offsetTop;
      if (top < editorScroll.scrollTop) editorScroll.scrollTop = top;
      else if (
        top + EDITOR_LINE_PX >
        editorScroll.scrollTop + editorScroll.clientHeight
      ) {
        editorScroll.scrollTop =
          top + EDITOR_LINE_PX - editorScroll.clientHeight;
      }
      const kind = docName.endsWith(".py")
        ? "Python"
        : docName.endsWith(".md")
          ? "Markdown"
          : "Plain Text";
      editorFoot.textContent =
        "Ln " +
        (doc.line + 1) +
        ", Col " +
        (doc.col + 1) +
        "    UTF-8    " +
        kind;
    }

    function openDocument(name) {
      if (!openDocs.includes(name)) openDocs.push(name);
      docName = name;
      drawEditor();
    }

    function afterEdit(isStructure) {
      const doc = currentDoc();
      const wasDirty = doc.isDirty;
      doc.isDirty = true;
      if (isStructure || !wasDirty) {
        drawEditor();
        return;
      }
      const row = editorLines.children[doc.line];
      colorLine(row.querySelector(".ed_code"), doc.lines[doc.line]);
      placeCaret();
    }

    function editorInsert(text) {
      const doc = currentDoc();
      const pieces = text.split("\n");
      const line = doc.lines[doc.line];
      const head = line.slice(0, doc.col);
      const tail = line.slice(doc.col);
      if (pieces.length === 1) {
        doc.lines[doc.line] = head + text + tail;
        doc.col += text.length;
        afterEdit(false);
        return;
      }
      const last = pieces[pieces.length - 1];
      const added = pieces.slice(1, -1);
      doc.lines.splice(doc.line, 1, head + pieces[0], ...added, last + tail);
      doc.line += pieces.length - 1;
      doc.col = last.length;
      afterEdit(true);
    }

    function editorKey(key) {
      const doc = currentDoc();
      if (key.isCtrl && key.text.toLowerCase() === "s") {
        doc.isDirty = false;
        drawEditor();
        editorFoot.textContent += "    " + t("demo.desktop.saved");
        return;
      }
      if (key.isCtrl && key.text.toLowerCase() === "v") {
        options.onPaste(editorInsert);
        return;
      }
      if (key.isCtrl) return;
      if (key.text) {
        editorInsert(key.isShift ? key.text.toUpperCase() : key.text);
        return;
      }
      const line = doc.lines[doc.line];
      switch (key.name) {
        case "enter": {
          const indent = /^\s*/.exec(line)[0];
          const opener = line.slice(0, doc.col).trimEnd().endsWith(":")
            ? " ".repeat(EDITOR_TAB_SIZE)
            : "";
          editorInsert("\n" + indent + opener);
          break;
        }
        case "backspace":
          if (doc.col > 0) {
            doc.lines[doc.line] =
              line.slice(0, doc.col - 1) + line.slice(doc.col);
            doc.col -= 1;
            afterEdit(false);
          } else if (doc.line > 0) {
            const above = doc.lines[doc.line - 1];
            doc.lines.splice(doc.line - 1, 2, above + line);
            doc.line -= 1;
            doc.col = above.length;
            afterEdit(true);
          }
          break;
        case "tab":
          editorInsert(" ".repeat(EDITOR_TAB_SIZE));
          break;
        case "left":
          if (doc.col > 0) doc.col -= 1;
          else if (doc.line > 0) {
            doc.line -= 1;
            doc.col = doc.lines[doc.line].length;
          }
          placeCaret();
          break;
        case "right":
          if (doc.col < line.length) doc.col += 1;
          else if (doc.line < doc.lines.length - 1) {
            doc.line += 1;
            doc.col = 0;
          }
          placeCaret();
          break;
        case "up":
          if (doc.line > 0) doc.line -= 1;
          doc.col = Math.min(doc.col, doc.lines[doc.line].length);
          placeCaret();
          break;
        case "down":
          if (doc.line < doc.lines.length - 1) doc.line += 1;
          doc.col = Math.min(doc.col, doc.lines[doc.line].length);
          placeCaret();
          break;
        default:
          break;
      }
    }

    // The column of a press on a line, from where the press is in the frame.
    function columnAt(row, x) {
      const code = row.querySelector(".ed_code");
      const text = currentDoc().lines[Number(row.dataset.line)];
      const start = frameLeft(code);
      let best = 0;
      let bestGap = Infinity;
      for (let col = 0; col <= text.length; col += 1) {
        const gap = Math.abs(
          start + canvas.measureText(text.slice(0, col)).width - x,
        );
        if (gap < bestGap) {
          bestGap = gap;
          best = col;
        }
      }
      return best;
    }

    function frameLeft(held) {
      let left = 0;
      for (let at = held; at && at !== root; at = at.offsetParent) {
        left +=
          at.offsetLeft - (at.offsetParent ? at.offsetParent.scrollLeft : 0);
      }
      return left;
    }

    // --- the terminal: the same fake shell the Terminals page drives ---

    const termWindow = makeWindow(
      "term",
      isWindows
        ? "PowerShell"
        : options.account + "@" + options.hostname + ": ~",
      isWindows
        ? { x: 300, y: 400, w: 700, h: 266 }
        : { x: 440, y: 448, w: 720, h: 262 },
    );
    const termHost = element("div", "ds_term");
    termWindow.body.appendChild(termHost);

    function shellSize() {
      const cell = canvas.measureText("W").width;
      const box = termWindow.isMaximized
        ? {
            w: DESKTOP_FRAME_WIDTH - leftInset(),
            h: DESKTOP_FRAME_HEIGHT - topInset() - bottomInset(),
          }
        : termWindow;
      return {
        cols: Math.max(20, Math.floor((box.w - SHELL_PADDING_PX * 2) / cell)),
        rows: Math.max(
          4,
          Math.floor((box.h - 36 - SHELL_PADDING_PX) / SHELL_CELL_HEIGHT_PX),
        ),
      };
    }

    function startShell() {
      const size = shellSize();
      const term = new Terminal({
        cols: size.cols,
        rows: size.rows,
        fontFamily: SHELL_FONT,
        fontSize: SHELL_FONT_SIZE,
        lineHeight: 1.18,
        scrollback: 1000,
        disableStdin: true,
        cursorInactiveStyle: "block",
        drawBoldTextInBrightColors: false,
        theme: Object.assign(
          { background: "#1b1d23", foreground: "#e6edf3", cursor: "#e6edf3" },
          TERMINAL_PALETTE,
        ),
      });
      term.open(termHost);
      shell = { term, id: "" };
      options.onShellOpen(size.cols, size.rows).then((id) => {
        shell.id = id;
      });
    }

    function resizeShell() {
      if (!shell) return;
      const size = shellSize();
      if (size.cols === shell.term.cols && size.rows === shell.term.rows)
        return;
      shell.term.resize(size.cols, size.rows);
      options.onShellResize(shell.id, size.cols, size.rows);
    }

    function shellKey(key) {
      if (!shell || !shell.id) return;
      options.onShellInput(shell.id, shellBytes(key));
    }

    function shellBytes(key) {
      const parameter =
        1 + (key.isShift ? 1 : 0) + (key.isAlt ? 2 : 0) + (key.isCtrl ? 4 : 0);
      const altMark = key.isAlt ? ESCAPE : "";
      if (key.text) {
        let typed = key.isShift ? key.text.toUpperCase() : key.text;
        if (key.isCtrl) {
          const code = typed.toUpperCase().charCodeAt(0);
          if (code >= 64 && code <= 95) typed = String.fromCharCode(code - 64);
        }
        return altMark + typed;
      }
      const arrows = { up: "A", down: "B", right: "C", left: "D" };
      if (arrows[key.name]) {
        return parameter === 1
          ? ESCAPE + "[" + arrows[key.name]
          : ESCAPE + "[1;" + parameter + arrows[key.name];
      }
      switch (key.name) {
        case "enter":
          return "\r";
        case "backspace":
          return "\x7f";
        case "escape":
          return altMark + ESCAPE;
        case "tab":
          return altMark + (key.isShift ? ESCAPE + "[Z" : "\t");
        default:
          return "";
      }
    }

    // --- the menu a right click opens ---

    function closeMenu() {
      if (menu) {
        menu.remove();
        menu = null;
      }
    }

    function openMenu(x, y, rows) {
      closeMenu();
      menu = element("div", "ds_menu");
      for (const [word, run] of rows) {
        const row = element("div", "ds_menu_row", word);
        row.dataset.action = "menu";
        row.onmenu = run;
        menu.appendChild(row);
      }
      root.appendChild(menu);
      menu.style.left =
        Math.min(x, DESKTOP_FRAME_WIDTH - menu.offsetWidth - 6) + "px";
      menu.style.top =
        Math.min(y, DESKTOP_FRAME_HEIGHT - menu.offsetHeight - 6) + "px";
      menu.style.zIndex = String(topLayer + 2);
    }

    function nextWallpaper() {
      wallpaperIndex = (wallpaperIndex + 1) % WALLPAPERS.length;
      root.dataset.wallpaper = WALLPAPERS[wallpaperIndex];
    }

    function addDesktopFolder() {
      desktopIcon(t("demo.desktop.new_folder"), "folder");
    }

    // --- the press, the drag, the wheel and the keys the viewer sends ---

    function windowOf(target) {
      const frame = target.closest(".ds_window");
      return frame ? windows[frame.dataset.window] : null;
    }

    function clearDesktopSelection() {
      for (const held of root.querySelectorAll(".ds_icon.is_selected")) {
        held.classList.remove("is_selected");
      }
    }

    function isDoubleTap(target) {
      const now = Date.now();
      const isDouble =
        lastTap.target === target && now - lastTap.at < DOUBLE_TAP_MS;
      lastTap = { at: now, target: isDouble ? null : target };
      return isDouble;
    }

    function act(held, button, x) {
      const action = button.dataset.action;
      if (action === "win_close" || action === "win_min") {
        setOpen(held, false);
      } else if (action === "win_max") {
        held.isMaximized = !held.isMaximized;
        placeWindow(held);
        if (held.name === "term") resizeShell();
      } else if (action === "dock") {
        const target = windows[button.dataset.window];
        setOpen(target, true);
        focusWindow(target);
      } else if (action === "fm_item") {
        const index = Number(button.dataset.index);
        const key = button.dataset.index + "/" + folderKey;
        selectedItem = index;
        const isDouble = isDoubleTap(key);
        drawFolder();
        if (isDouble) openItem(tree[folderKey].items[index]);
      } else if (action === "fm_side") {
        openFolder(button.dataset.folder);
      } else if (action === "fm_back") {
        if (folderTrail.length > 0) {
          folderKey = folderTrail.pop();
          selectedItem = -1;
          drawFolder();
        }
      } else if (action === "ed_tab") {
        docName = button.dataset.doc;
        drawEditor();
      } else if (action === "ed_file") {
        openDocument(button.dataset.doc);
      } else if (action === "ed_text") {
        const doc = currentDoc();
        doc.line = Number(button.dataset.line);
        doc.col = columnAt(button, x);
        placeCaret();
      } else if (action === "desktop_icon") {
        clearDesktopSelection();
        button.classList.add("is_selected");
        if (isDoubleTap(button)) {
          setOpen(windows.files, true);
          focusWindow(windows.files);
        }
      }
    }

    function tap(target, x, y) {
      moveCursor(x, y);
      const row = target.closest(".ds_menu_row");
      if (row) {
        const run = row.onmenu;
        closeMenu();
        run();
        return;
      }
      closeMenu();
      const held = windowOf(target);
      if (held) focusWindow(held);
      else {
        clearDesktopSelection();
        blurWindows();
        drawDock();
      }
      const button = target.closest("[data-action]");
      if (button) act(held, button, x);
    }

    function rightTap(target, x, y) {
      moveCursor(x, y);
      const held = windowOf(target);
      if (held) focusWindow(held);
      const item = target.closest(".fm_item");
      if (item) {
        const index = Number(item.dataset.index);
        selectedItem = index;
        drawFolder();
        openMenu(x, y, [
          [
            t("demo.desktop.menu_open"),
            () => openItem(tree[folderKey].items[index]),
          ],
        ]);
        return;
      }
      if (held) {
        closeMenu();
        return;
      }
      openMenu(x, y, [
        [
          t("demo.desktop.menu_terminal"),
          () => {
            setOpen(windows.term, true);
            focusWindow(windows.term);
          },
        ],
        [t("demo.desktop.menu_new_folder"), addDesktopFolder],
        [t("demo.desktop.menu_wallpaper"), nextWallpaper],
      ]);
    }

    function dragStart(target, x, y) {
      moveCursor(x, y);
      closeMenu();
      const held = windowOf(target);
      if (held) focusWindow(held);
      if (held && target.closest(".ds_grip") && !held.isMaximized) {
        drag = { kind: "resize", held, x, y, w: held.w, h: held.h };
      } else if (
        held &&
        target.closest(".ds_title") &&
        !target.closest(".ds_title_btn")
      ) {
        if (held.isMaximized) {
          held.isMaximized = false;
          held.x = Math.max(leftInset(), x - held.w / 2);
          held.y = topInset();
          placeWindow(held);
          if (held.name === "term") resizeShell();
        }
        drag = { kind: "move", held, x, y, left: held.x, top: held.y };
      } else if (
        !held &&
        !target.closest(".ds_dock, .ds_topbar, .ds_taskbar")
      ) {
        clearDesktopSelection();
        blurWindows();
        drawDock();
        band.hidden = false;
        drag = { kind: "band", x, y };
        dragMove(x, y);
      } else {
        drag = { kind: "none" };
      }
    }

    function dragMove(x, y) {
      moveCursor(x, y);
      if (!drag) return;
      if (drag.kind === "move") {
        const held = drag.held;
        held.x = Math.max(
          TITLE_KEEP_PX - held.w,
          Math.min(DESKTOP_FRAME_WIDTH - TITLE_KEEP_PX, drag.left + x - drag.x),
        );
        held.y = Math.max(
          topInset(),
          Math.min(
            DESKTOP_FRAME_HEIGHT - bottomInset() - 34,
            drag.top + y - drag.y,
          ),
        );
        placeWindow(held);
      } else if (drag.kind === "resize") {
        const held = drag.held;
        held.w = Math.max(WINDOW_MIN_WIDTH, drag.w + x - drag.x);
        held.h = Math.max(WINDOW_MIN_HEIGHT, drag.h + y - drag.y);
        placeWindow(held);
        if (held.name === "term") resizeShell();
      } else if (drag.kind === "band") {
        band.style.left = Math.min(x, drag.x) + "px";
        band.style.top = Math.min(y, drag.y) + "px";
        band.style.width = Math.abs(x - drag.x) + "px";
        band.style.height = Math.abs(y - drag.y) + "px";
      }
    }

    function dragEnd(x, y) {
      moveCursor(x, y);
      band.hidden = true;
      drag = null;
    }

    function scroll(target, steps) {
      const area = target.closest(".ds_scroll");
      if (area) {
        area.scrollTop += steps * EDITOR_LINE_PX;
        return;
      }
      if (shell && target.closest(".ds_term")) shell.term.scrollLines(steps);
    }

    function key(pressed) {
      if (pressed.isAlt && pressed.name === "tab") {
        const open = Object.values(windows).filter((each) => each.isOpen);
        const at = open.indexOf(focused);
        if (open.length > 0) focusWindow(open[(at + 1) % open.length]);
        return;
      }
      if (pressed.name === "escape") closeMenu();
      if (!focused) return;
      if (focused.name === "term") shellKey(pressed);
      else if (focused.name === "code") editorKey(pressed);
      else if (focused.name === "files") filesKey(pressed);
    }

    function filesKey(pressed) {
      const items = tree[folderKey].items;
      const across = 5;
      const steps = { left: -1, right: 1, up: -across, down: across };
      if (steps[pressed.name] !== undefined && items.length > 0) {
        selectedItem = Math.max(
          0,
          Math.min(items.length - 1, selectedItem + steps[pressed.name]),
        );
        drawFolder();
      } else if (pressed.name === "enter" && selectedItem >= 0) {
        openItem(items[selectedItem]);
      } else if (pressed.name === "backspace" && folderTrail.length > 0) {
        folderKey = folderTrail.pop();
        selectedItem = -1;
        drawFolder();
      }
    }

    function paste(text) {
      if (!focused) return;
      if (focused.name === "code") editorInsert(text);
      else if (focused.name === "term" && shell && shell.id) {
        options.onShellInput(shell.id, text);
      }
    }

    root.appendChild(band);
    root.appendChild(cursor);
    moveCursor(DESKTOP_FRAME_WIDTH / 2, DESKTOP_FRAME_HEIGHT / 2);
    drawFolder();
    drawEditor();
    focusWindow(windows.files);
    focusWindow(windows.code);
    drawDock();

    return {
      element: root,
      start: startShell,
      tap,
      rightTap,
      dragStart,
      dragMove,
      dragEnd,
      scroll,
      key,
      paste,
      moveCursor,
      writeShell(data) {
        if (shell) shell.term.write(data);
      },
      shellId() {
        return shell ? shell.id : "";
      },
      destroy() {
        window.clearInterval(clockTimer);
        if (shell) shell.term.dispose();
      },
    };
  };
})();
