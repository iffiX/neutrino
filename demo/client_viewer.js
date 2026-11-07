// The phone's viewer page, in the demo only, after RemoteDesktopViewer.kt: the
// picture over the whole screen, three round buttons at the top right that
// always stay, the key bar and the keyboard that start off. A tap clicks, a
// long press right-clicks, one finger drags, a pinch zooms and moves the picture,
// two fingers scroll.
(() => {
  const CONNECT_MS = 900;
  const ZOOM_MAX = 6;
  const PINCH_SLOP_PX = 12;
  const TOUCH_SLOP_PX = 8;
  const LONG_PRESS_MS = 400;
  const SCROLL_STEP_PX = 24;
  const BUTTON_SIZE = 36;
  // The key bar, in the bar's order: its label and what the picture takes.
  const KEY_BAR = [
    { label: "Esc", name: "escape" },
    { label: "Tab", name: "tab" },
    { label: "Ctrl", modifier: "isCtrl" },
    { label: "Shift", modifier: "isShift" },
    { label: "Alt", modifier: "isAlt" },
    { label: "Win", modifier: "isWin" },
    { label: "←", name: "left" },
    { label: "↑", name: "up" },
    { label: "↓", name: "down" },
    { label: "→", name: "right" },
  ];
  const KEYBOARD_BYTES = { "\r": "enter", "\x7f": "backspace" };

  let viewer = null;

  // --- where the picture sits, RemoteDesktopViewport.kt ---

  function fitScale(view) {
    return Math.min(
      view.width / DESKTOP_FRAME_WIDTH,
      view.height / DESKTOP_FRAME_HEIGHT,
    );
  }

  function scaleOf(view) {
    return fitScale(view) * view.zoom;
  }

  function edge(start, space, drawn) {
    return drawn <= space
      ? (space - drawn) / 2
      : Math.max(space - drawn, Math.min(0, start));
  }

  function clamp(view) {
    const scale = scaleOf(view);
    view.left = edge(view.left, view.width, DESKTOP_FRAME_WIDTH * scale);
    view.top = edge(
      view.top,
      view.height - view.covered,
      DESKTOP_FRAME_HEIGHT * scale,
    );
  }

  function zoomBy(view, factor, x, y) {
    const next = Math.max(1, Math.min(ZOOM_MAX, view.zoom * factor));
    const ratio = next / view.zoom;
    view.zoom = next;
    view.left = x - (x - view.left) * ratio;
    view.top = y - (y - view.top) * ratio;
    clamp(view);
  }

  function coverBy(view, height) {
    const next = Math.max(0, height);
    if (next === view.covered) return;
    view.top -= next - view.covered;
    view.covered = next;
    clamp(view);
  }

  function toFrame(view, x, y) {
    const scale = scaleOf(view);
    return {
      x: Math.max(
        0,
        Math.min(DESKTOP_FRAME_WIDTH - 1, (x - view.left) / scale),
      ),
      y: Math.max(
        0,
        Math.min(DESKTOP_FRAME_HEIGHT - 1, (y - view.top) / scale),
      ),
    };
  }

  // --- the page ---

  function drawPicture() {
    const { view, picture, scene } = viewer;
    const scale = scaleOf(view);
    picture.style.left = view.left + "px";
    picture.style.top = view.top + "px";
    picture.style.width = DESKTOP_FRAME_WIDTH * scale + "px";
    picture.style.height = DESKTOP_FRAME_HEIGHT * scale + "px";
    scene.element.style.transform = "scale(" + scale + ")";
  }

  function layOut() {
    const { root, stage, view } = viewer;
    const width = root.clientWidth;
    const height = root.clientHeight;
    if (width === 0 || height === 0) return;
    if (viewer.isTurned && width > height) viewer.isTurned = false;
    const stageWidth = viewer.isTurned ? height : width;
    const stageHeight = viewer.isTurned ? width : height;
    stage.style.width = stageWidth + "px";
    stage.style.height = stageHeight + "px";
    stage.style.transform = viewer.isTurned
      ? "translateX(" + width + "px) rotate(90deg)"
      : "none";
    if (stageWidth !== view.width || stageHeight !== view.height) {
      view.width = stageWidth;
      view.height = stageHeight;
      view.zoom = 1;
      view.left = 0;
      view.top = 0;
      clamp(view);
      coverAgain();
    }
    drawPicture();
    drawTurn();
  }

  function coverAgain() {
    const { keyBar, view } = viewer;
    const keyboardHeight = phoneKeyboard.height();
    keyBar.style.bottom = keyboardHeight + "px";
    const barHeight = keyBar.hidden ? 0 : keyBar.offsetHeight;
    coverBy(view, keyboardHeight + barHeight);
    drawPicture();
  }

  function drawTurn() {
    const { turn, view } = viewer;
    turn.hidden =
      viewer.isTurned ||
      viewer.state !== "showing" ||
      view.width >= view.height ||
      view.covered > 0;
  }

  function drawButtons() {
    const { buttons, keyBar } = viewer;
    const isShowing = viewer.state === "showing";
    buttons.replaceChildren(
      roundButton(
        "keyboard",
        t("ui.rdp_keyboard"),
        phoneKeyboard.isShown(),
        toggleKeyboard,
        BUTTON_SIZE,
        false,
        isShowing,
      ),
      roundButton(
        "command",
        t("ui.rdp_keys"),
        !keyBar.hidden,
        toggleKeyBar,
        BUTTON_SIZE,
        false,
        isShowing,
      ),
      roundButton(
        "close",
        t("ui.rdp_disconnect"),
        false,
        closeViewer,
        BUTTON_SIZE,
        true,
        true,
      ),
    );
  }

  function toggleKeyboard() {
    if (phoneKeyboard.isShown()) phoneKeyboard.hide();
    else phoneKeyboard.show(viewer.stage, typeOnPicture);
    drawButtons();
    coverAgain();
    drawTurn();
  }

  function toggleKeyBar() {
    viewer.keyBar.hidden = !viewer.keyBar.hidden;
    drawButtons();
    coverAgain();
    drawTurn();
  }

  function pressedKey(fields) {
    const held = viewer.held;
    const pressed = Object.assign(
      {
        text: "",
        name: "",
        isCtrl: held.isCtrl,
        isShift: held.isShift,
        isAlt: held.isAlt,
        isWin: held.isWin,
      },
      fields,
    );
    viewer.held = {};
    for (const button of viewer.keyBar.querySelectorAll(".term_key.held")) {
      button.classList.remove("held");
    }
    return pressed;
  }

  function typeOnPicture(text) {
    const name = KEYBOARD_BYTES[text];
    viewer.scene.key(pressedKey(name ? { name: name } : { text: text }));
  }

  function pasteOnPicture() {
    api("/api/clipboard").then((reply) => {
      if (viewer && reply && reply.text) viewer.scene.paste(reply.text);
    });
  }

  function makeKeyBar() {
    const bar = document.createElement("div");
    bar.className = "term_keys rdv_keybar";
    bar.hidden = true;
    for (const key of KEY_BAR) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "term_key";
      button.textContent = key.label;
      button.onmousedown = (event) => event.preventDefault();
      button.onclick = () => {
        if (key.modifier) {
          viewer.held[key.modifier] = !viewer.held[key.modifier];
          button.classList.toggle("held", viewer.held[key.modifier]);
        } else {
          viewer.scene.key(pressedKey({ name: key.name }));
        }
      };
      bar.appendChild(button);
    }
    const paste = document.createElement("button");
    paste.type = "button";
    paste.className = "term_key";
    paste.textContent = t("ui.paste");
    paste.onmousedown = (event) => event.preventDefault();
    paste.onclick = pasteOnPicture;
    bar.appendChild(paste);
    return bar;
  }

  // --- the fingers and the mouse ---

  function isControl(target) {
    return !!target.closest(".rdv_buttons, .rdv_keybar, .kb, .rdv_turn");
  }

  function viewPoint(event) {
    if (!viewer.isTurned) {
      return { x: event.clientX, y: event.clientY };
    }
    return { x: event.clientY, y: viewer.root.clientWidth - event.clientX };
  }

  function frameOf(point) {
    return toFrame(viewer.view, point.x, point.y);
  }

  function cancelLongPress() {
    if (viewer.gesture) window.clearTimeout(viewer.gesture.timer);
  }

  function startOneFinger(event, point) {
    const target = document.elementFromPoint(event.clientX, event.clientY);
    viewer.gesture = {
      kind: "undecided",
      button: event.button,
      isTouch: event.pointerType === "touch",
      first: point,
      target: target || viewer.scene.element,
      timer: 0,
    };
    const start = frameOf(point);
    viewer.scene.moveCursor(start.x, start.y);
    if (event.pointerType === "touch") {
      viewer.gesture.timer = window.setTimeout(() => {
        const gesture = viewer && viewer.gesture;
        if (gesture && gesture.kind === "undecided") {
          gesture.kind = "held";
          viewer.scene.rightTap(gesture.target, start.x, start.y);
        }
      }, LONG_PRESS_MS);
    }
  }

  function twoPoints() {
    const [first, second] = [...viewer.pointers.values()];
    return {
      centre: { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 },
      spread: Math.hypot(first.x - second.x, first.y - second.y),
    };
  }

  function startTwoFingers() {
    cancelLongPress();
    const now = twoPoints();
    viewer.gesture = {
      kind: "two",
      mode: "",
      origin: now,
      before: now,
      travel: 0,
      target: viewer.gesture ? viewer.gesture.target : viewer.scene.element,
      timer: 0,
    };
  }

  function moveTwoFingers() {
    const gesture = viewer.gesture;
    const now = twoPoints();
    const before = gesture.before;
    gesture.before = now;
    if (gesture.mode === "") {
      const moved = Math.hypot(
        now.centre.x - gesture.origin.centre.x,
        now.centre.y - gesture.origin.centre.y,
      );
      if (Math.abs(now.spread - gesture.origin.spread) > PINCH_SLOP_PX) {
        gesture.mode = "pinch";
      } else if (moved > PINCH_SLOP_PX) {
        gesture.mode = "scroll";
      }
    }
    if (gesture.mode === "pinch") {
      const factor = before.spread > 0 ? now.spread / before.spread : 1;
      zoomBy(viewer.view, factor, now.centre.x, now.centre.y);
      viewer.view.left += now.centre.x - before.centre.x;
      viewer.view.top += now.centre.y - before.centre.y;
      clamp(viewer.view);
      drawPicture();
    } else if (gesture.mode === "scroll") {
      gesture.travel += before.centre.y - now.centre.y;
      const steps = Math.trunc(gesture.travel / SCROLL_STEP_PX);
      if (steps !== 0) {
        gesture.travel -= steps * SCROLL_STEP_PX;
        viewer.scene.scroll(gesture.target, steps);
      }
    }
  }

  function onPointerDown(event) {
    if (!viewer || isControl(event.target) || viewer.state !== "showing") {
      return;
    }
    event.preventDefault();
    viewer.stage.setPointerCapture(event.pointerId);
    const point = viewPoint(event);
    viewer.pointers.set(event.pointerId, point);
    if (viewer.pointers.size === 1) startOneFinger(event, point);
    else if (viewer.pointers.size === 2) startTwoFingers();
  }

  function onPointerMove(event) {
    if (!viewer || viewer.state !== "showing") return;
    const point = viewPoint(event);
    if (!viewer.pointers.has(event.pointerId)) {
      if (event.pointerType === "mouse" && !isControl(event.target)) {
        const at = frameOf(point);
        viewer.scene.moveCursor(at.x, at.y);
      }
      return;
    }
    viewer.pointers.set(event.pointerId, point);
    const gesture = viewer.gesture;
    if (!gesture) return;
    if (gesture.kind === "two") {
      if (viewer.pointers.size >= 2) moveTwoFingers();
      return;
    }
    if (gesture.kind === "undecided") {
      const moved = Math.hypot(
        point.x - gesture.first.x,
        point.y - gesture.first.y,
      );
      if (moved <= TOUCH_SLOP_PX || gesture.button === 2) return;
      cancelLongPress();
      gesture.kind = "drag";
      const start = frameOf(gesture.first);
      viewer.scene.dragStart(gesture.target, start.x, start.y);
    }
    if (gesture.kind === "drag") {
      const at = frameOf(point);
      viewer.scene.dragMove(at.x, at.y);
    }
  }

  function onPointerUp(event) {
    if (!viewer || !viewer.pointers.has(event.pointerId)) return;
    const point = viewPoint(event);
    viewer.pointers.delete(event.pointerId);
    const gesture = viewer.gesture;
    if (!gesture) return;
    if (viewer.pointers.size > 0) return;
    cancelLongPress();
    viewer.gesture = null;
    const at = frameOf(point);
    if (gesture.kind === "undecided") {
      if (gesture.button === 2)
        viewer.scene.rightTap(gesture.target, at.x, at.y);
      else viewer.scene.tap(gesture.target, at.x, at.y);
    } else if (gesture.kind === "drag") {
      viewer.scene.dragEnd(at.x, at.y);
    }
  }

  function onPointerCancel(event) {
    if (!viewer) return;
    viewer.pointers.delete(event.pointerId);
    if (viewer.pointers.size === 0) {
      cancelLongPress();
      viewer.gesture = null;
    }
  }

  function onWheel(event) {
    if (!viewer || viewer.state !== "showing" || isControl(event.target))
      return;
    event.preventDefault();
    const point = viewPoint(event);
    if (event.ctrlKey) {
      zoomBy(viewer.view, Math.exp(-event.deltaY / 200), point.x, point.y);
      drawPicture();
      return;
    }
    const steps =
      Math.sign(event.deltaY) *
      Math.max(1, Math.round(Math.abs(event.deltaY) / 60));
    const target = document.elementFromPoint(event.clientX, event.clientY);
    if (target) viewer.scene.scroll(target, steps);
  }

  const PHYSICAL_KEYS = {
    Enter: "enter",
    Backspace: "backspace",
    Tab: "tab",
    Escape: "escape",
    ArrowLeft: "left",
    ArrowUp: "up",
    ArrowDown: "down",
    ArrowRight: "right",
  };

  function onKeyDown(event) {
    if (!viewer || viewer.state !== "showing") return;
    const name = PHYSICAL_KEYS[event.key];
    const isCharacter = event.key.length === 1;
    if (!name && !isCharacter) return;
    event.preventDefault();
    viewer.scene.key({
      text: isCharacter ? event.key : "",
      name: name || "",
      isCtrl: event.ctrlKey || !!viewer.held.isCtrl,
      isShift: !isCharacter && (event.shiftKey || !!viewer.held.isShift),
      isAlt: event.altKey || !!viewer.held.isAlt,
      isWin: event.metaKey || !!viewer.held.isWin,
    });
  }

  // --- the session ---

  function parentFrame() {
    return window.parent.neutrinoDemoViewerFrame;
  }

  function openViewer(entry, key, state) {
    const machine = ((state.terminals || {}).machines || []).find(
      (row) => row.device_id === entry.device_id && row.hub_id === entry.hub_id,
    );
    const root = document.createElement("div");
    root.className = "rdv";
    const stage = document.createElement("div");
    stage.className = "rdv_stage";
    const picture = document.createElement("div");
    picture.className = "rdv_picture";
    const spin = document.createElement("div");
    spin.className = "rdv_spin";
    spin.appendChild(marker("pulse"));
    const buttons = document.createElement("div");
    buttons.className = "rdv_buttons";
    const turn = document.createElement("button");
    turn.type = "button";
    turn.className = "rdv_turn";
    turn.hidden = true;
    turn.textContent = t("demo.viewer_turn");
    turn.onclick = () => {
      viewer.isTurned = true;
      layOut();
    };
    const accounts = machine ? machine.accounts : [];
    const scene = makeDesktopScene({
      platformOs: (entry.payload || {}).platform_os || "linux",
      hostname: machine ? machine.hostname : "desktop",
      account: accounts[0] || "xiaoming",
      onShellOpen: (cols, rows) =>
        api("/api/terminal/open", {
          hub_id: entry.hub_id,
          device_id: entry.device_id,
          cols: cols,
          rows: rows,
          session_id: "",
          account: accounts[0] || "",
          is_viewer: true,
        }).then((reply) => (reply && reply.terminal_id) || ""),
      onShellInput: (id, data) =>
        api("/api/terminal/input", { terminal_id: id, data: textBase64(data) }),
      onShellResize: (id, cols, rows) =>
        api("/api/terminal/resize", {
          terminal_id: id,
          cols: cols,
          rows: rows,
        }),
      onPaste: (insert) => {
        api("/api/clipboard").then((reply) => {
          if (reply && reply.text) insert(reply.text);
        });
      },
    });
    scene.element.hidden = true;
    picture.appendChild(scene.element);
    stage.appendChild(picture);
    stage.appendChild(spin);
    stage.appendChild(turn);
    stage.appendChild(buttons);
    const keyBar = makeKeyBar();
    stage.appendChild(keyBar);
    root.appendChild(stage);
    document.body.appendChild(root);
    viewer = {
      key,
      entry,
      root,
      stage,
      picture,
      scene,
      spin,
      buttons,
      keyBar,
      turn,
      state: "connecting",
      isTurned: false,
      held: {},
      gesture: null,
      pointers: new Map(),
      view: { width: 0, height: 0, zoom: 1, left: 0, top: 0, covered: 0 },
      observer: new ResizeObserver(layOut),
      timer: 0,
    };
    stage.addEventListener("pointerdown", onPointerDown);
    stage.addEventListener("pointermove", onPointerMove);
    stage.addEventListener("pointerup", onPointerUp);
    stage.addEventListener("pointercancel", onPointerCancel);
    stage.addEventListener("wheel", onWheel, { passive: false });
    stage.addEventListener("contextmenu", (event) => event.preventDefault());
    window.addEventListener("keydown", onKeyDown);
    drawButtons();
    viewer.observer.observe(root);
    layOut();
    parentFrame()(true);
    viewer.timer = window.setTimeout(() => {
      viewer.state = "showing";
      spin.remove();
      scene.element.hidden = false;
      scene.start();
      drawButtons();
      drawTurn();
      window.focus();
    }, CONNECT_MS);
  }

  function closeViewer() {
    if (!viewer) return;
    const held = viewer;
    viewer = null;
    window.clearTimeout(held.timer);
    window.removeEventListener("keydown", onKeyDown);
    held.observer.disconnect();
    phoneKeyboard.hide();
    const shellId = held.scene.shellId();
    if (shellId) api("/api/terminal/close", { terminal_id: shellId });
    held.scene.destroy();
    held.root.remove();
    parentFrame()(false);
    serviceAction("rdp", {
      action: "close",
      hub_id: held.entry.hub_id,
      id: held.entry.id,
    });
  }

  // The state names the running viewers; a named one with no page opens here.
  const pageDraw = draw;
  draw = function (state) {
    pageDraw(state);
    const running = Object.keys(state.viewers || {}).find(
      (key) => state.viewers[key].is_running,
    );
    if (running && !viewer) {
      const entry = (state.services || []).find(
        (row) => serviceKey(row) === running,
      );
      if (entry) openViewer(entry, running, state);
    }
  };

  // The viewer's own shell writes to its window; every other piece is the page's.
  const pageTakesState = window.neutrinoState;
  window.neutrinoState = (state) => {
    if (
      viewer &&
      state &&
      state.terminal &&
      state.terminal.id === viewer.scene.shellId()
    ) {
      if (state.terminal.data !== undefined) {
        viewer.scene.writeShell(base64Bytes(state.terminal.data));
      }
      return;
    }
    pageTakesState(state);
  };
})();
