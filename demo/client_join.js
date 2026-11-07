// The Join page of a phone, in the demo only: the row on the Hubs page opens
// it, and the camera reads the sample code in its frame. A scan and a paste
// are one path, `/api/join`. A page has no camera it may ask for here, so the
// camera's picture is drawn.
(() => {
  const JOIN_TAB = "join";
  const SAMPLE_HUB_ID = "hub_lab";
  // How long the code takes to come into the frame, the moment it is read, and
  // the wait while the link is checked and the binding written.
  const SCAN_LOOK_MS = 1800;
  const SCAN_FOUND_MS = 550;
  const JOIN_CHECK_MS = 450;
  const SCAN_HOLD_MS = 1000;
  const SVG_NAMESPACE_URI = "http://www.w3.org/2000/svg";
  const QR_QUIET_MODULES = 2;

  let sample = null;
  let scanPhase = "";
  let scanTimer = 0;
  let isJoinWaiting = false;
  let draftLink = "";
  let joinRefusal = null;

  function isSampleJoined() {
    return ((lastState && lastState.hubs) || []).some(
      (hub) => hub.hub_id === SAMPLE_HUB_ID,
    );
  }

  function stopScan() {
    window.clearTimeout(scanTimer);
    scanPhase = "";
  }

  function hasPersonTyped() {
    const input = document.querySelector(".join_input");
    return !!input && (input === document.activeElement || input.value !== "");
  }

  function startScan() {
    window.clearTimeout(scanTimer);
    scanPhase = isSampleJoined() ? "idle" : "looking";
    if (scanPhase === "looking") {
      scanTimer = window.setTimeout(readCode, SCAN_LOOK_MS);
    }
  }

  function readCode() {
    if (openTab !== JOIN_TAB) return;
    if (hasPersonTyped()) {
      scanTimer = window.setTimeout(readCode, SCAN_HOLD_MS);
      return;
    }
    scanPhase = "found";
    const camera = document.querySelector(".join_camera");
    if (camera) camera.classList.add("found");
    scanTimer = window.setTimeout(() => runJoin(sample.link), SCAN_FOUND_MS);
  }

  function runJoin(link) {
    if (isJoinWaiting) return;
    isJoinWaiting = true;
    joinRefusal = null;
    redraw();
    window.setTimeout(() => {
      api("/api/join", { link: link }).then((reply) => {
        isJoinWaiting = false;
        if (reply && reply.error) {
          joinRefusal = reply.error;
          if (scanPhase === "found") startScan();
          redraw();
          return;
        }
        stopScan();
        draftLink = "";
        openTab = "hubs";
        lastSerialized = JSON.stringify(reply);
        draw(reply);
      });
    }, JOIN_CHECK_MS);
  }

  function goBack() {
    stopScan();
    draftLink = "";
    joinRefusal = null;
    openTab = "hubs";
    redraw();
  }

  function openJoin() {
    openTab = JOIN_TAB;
    joinRefusal = null;
    startScan();
    redraw();
    if (sample === null) {
      api("/api/demo/sample_hub").then((reply) => {
        sample = reply;
        if (openTab === JOIN_TAB) redraw();
      });
    }
  }

  function codeSvg() {
    const svg = document.createElementNS(SVG_NAMESPACE_URI, "svg");
    const span = sample.size + QR_QUIET_MODULES * 2;
    svg.setAttribute(
      "viewBox",
      -QR_QUIET_MODULES + " " + -QR_QUIET_MODULES + " " + span + " " + span,
    );
    svg.setAttribute("class", "join_code");
    svg.setAttribute("shape-rendering", "crispEdges");
    const path = document.createElementNS(SVG_NAMESPACE_URI, "path");
    path.setAttribute("d", sample.path);
    path.setAttribute("fill", "#0b0f14");
    svg.appendChild(path);
    return svg;
  }

  function sampleScreen() {
    const screen = document.createElement("div");
    screen.className = "join_screen";
    const title = document.createElement("div");
    title.className = "join_screen_title";
    title.textContent = t("demo.join_screen_title");
    screen.appendChild(title);
    screen.appendChild(codeSvg());
    const note = document.createElement("div");
    note.className = "join_screen_note";
    note.textContent = t("demo.join_screen_note");
    screen.appendChild(note);
    return screen;
  }

  function cameraFrame() {
    const camera = document.createElement("div");
    camera.className = "join_camera";
    if (scanPhase === "found" || isJoinWaiting) camera.classList.add("found");
    const scene = document.createElement("div");
    scene.className = "join_scene";
    const room = document.createElement("div");
    room.className = "join_room";
    scene.appendChild(room);
    if (sample !== null && !isSampleJoined()) {
      scene.appendChild(sampleScreen());
    }
    camera.appendChild(scene);
    const corners = document.createElement("div");
    corners.className = "join_corners";
    for (const corner of ["tl", "tr", "bl", "br"]) {
      const arm = document.createElement("i");
      arm.className = corner;
      corners.appendChild(arm);
    }
    camera.appendChild(corners);
    return camera;
  }

  function drawJoin() {
    const page = document.createElement("div");
    page.className = "join_page";
    const frame = document.createElement("div");
    frame.className = "join_frame";
    frame.appendChild(cameraFrame());
    page.appendChild(frame);
    const hint = document.createElement("div");
    hint.className = "join_hint";
    hint.textContent = t("ui.scan_hint");
    page.appendChild(hint);
    const rule = document.createElement("div");
    rule.className = "join_rule";
    rule.appendChild(document.createElement("i"));
    const word = document.createElement("span");
    word.textContent = t("ui.or");
    rule.appendChild(word);
    rule.appendChild(document.createElement("i"));
    page.appendChild(rule);
    const label = document.createElement("label");
    label.textContent = t("ui.paste_hint");
    page.appendChild(label);
    const line = document.createElement("div");
    line.className = "row";
    const input = document.createElement("input");
    input.className = "join_input";
    input.placeholder = "neutrino://enroll/...";
    input.value = draftLink;
    input.oninput = () => {
      draftLink = input.value;
    };
    input.onkeydown = (event) => {
      if (event.key === "Enter") runJoin(input.value);
    };
    input.onblur = settle;
    const button = jobButton(t("ui.join"), isJoinWaiting ? "joining" : "");
    if (!isJoinWaiting) button.onclick = () => runJoin(input.value);
    line.appendChild(input);
    line.appendChild(button);
    page.appendChild(line);
    if (joinRefusal) {
      page.appendChild(
        errorLine(wordCode(joinRefusal.code, joinRefusal.params)),
      );
    }
    return page;
  }

  const desktopKindTab = kindTab;
  kindTab = function (state, kind) {
    return openTab === JOIN_TAB ? drawJoin() : desktopKindTab(state, kind);
  };

  const desktopTabTitle = tabTitle;
  tabTitle = function (tab) {
    return tab === JOIN_TAB ? t("ui.add_hub") : desktopTabTitle(tab);
  };

  // Leaving by the bar stops the camera; the back arrow shows on this page alone.
  const backButton = document.createElement("button");
  backButton.type = "button";
  backButton.className = "head_back";
  backButton.appendChild(icon("chevron_left", 20));
  backButton.onclick = goBack;
  const headTitle = document.getElementById("page_title");
  headTitle.parentElement.insertBefore(backButton, headTitle);

  const pageDraw = draw;
  draw = function (state) {
    if (openTab !== JOIN_TAB && scanPhase !== "") stopScan();
    const isJoinOpen = openTab === JOIN_TAB;
    backButton.hidden = !isJoinOpen;
    backButton.title = t("ui.back");
    backButton.setAttribute("aria-label", t("ui.back"));
    pageDraw(state);
  };

  // The row that opens the page, in a card of its own under the hubs.
  joinRow = function () {
    const row = rowElement({
      tone: "off",
      title: t("ui.add_hub"),
      word: t("ui.join_hint"),
    });
    row.classList.add("join_entry");
    row.appendChild(icon("chevron_right", 18));
    row.onclick = openJoin;
    return row;
  };

  const desktopDrawHubs = drawHubs;
  drawHubs = function (state) {
    const card = desktopDrawHubs(state);
    const entry = card.lastElementChild;
    const page = document.createElement("div");
    page.className = "hubs_page";
    const entryCard = document.createElement("div");
    entryCard.className = "card";
    entryCard.appendChild(entry);
    page.appendChild(card);
    page.appendChild(entryCard);
    return page;
  };
})();
