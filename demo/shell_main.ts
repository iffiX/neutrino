import { DemoClientCore } from "./demo_client_core";
import { DemoHub } from "./demo_hub";
import type { DemoDisplayChange, DemoEdition } from "./demo_hub";
import { demoWord } from "./demo_words";
import type { DemoWordKey } from "./demo_words";
import type { DemoPanelWindow, DemoWindow } from "./demo_window";

import "../hub/frontend/src/fonts.css";
import "./shell.css";

/**
 * The page around the two frames: the fake hub they share, the switch between
 * them on a phone, the buttons that set both sides' language and palette, the
 * switch between the two editions, and the short messages for the visitor.
 */

const EDITION_CN = "cn";
const EDITION_INTL = "intl";
const PROXY_ROUTE = "#/proxy";
const OVERVIEW_ROUTE = "#/";
const CLIENT_SETTINGS_PATH = "/api/settings/set";
const THEME_DARK = "dark";
const THEME_LIGHT = "light";
const NOTICE_MS = 3600;
const PANEL_PAGE = "panel.html";
const CLIENT_PAGE = "client/index.html";
// The width the panel lays itself out at in a half, scaled down to fit.
const PANEL_LAYOUT_WIDTH = 840;
const ONE_SIDE_QUERY = "(max-width: 1023px)";
// How often a new panel frame is checked, and the longest it can stay under the
// open one.
const PANEL_DRAW_CHECK_MS = 30;
const PANEL_DRAW_MAX_MS = 2000;
// One turn of the loading icon's edge, and the longest the frames can hold it.
const LOADING_MIN_MS = 1200;
const LOADING_MAX_MS = 15000;

const hub = new DemoHub();
const client = new DemoClientCore(hub);
const demoWindow = window as unknown as DemoWindow;
demoWindow.neutrinoDemoHub = hub;
demoWindow.neutrinoDemoClient = client;
demoWindow.neutrinoDemoViewerFrame = (isOpen) => {
  document.body.dataset.viewer = isOpen ? "on" : "";
};

/** This page's language and palette. Only its own buttons change them. */
const display = { language: hub.language(), theme: hub.theme() };

/** The panel's frame in use, and the route it was last opened on. */
let panelFrame = element("panel_half").querySelector("iframe")!;
let panelRoute = OVERVIEW_ROUTE;

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (found === null) {
    throw new Error(`index.html is missing #${id}`);
  }
  return found as T;
}

function showSide(side: string): void {
  document.body.dataset.side = side;
  for (const button of document.querySelectorAll<HTMLButtonElement>(
    "[data-show]",
  )) {
    button.setAttribute("aria-selected", String(button.dataset.show === side));
  }
}

function fitPanel(frame: HTMLIFrameElement, half: HTMLElement): void {
  const isOneSide = window.matchMedia(ONE_SIDE_QUERY).matches;
  const scale = isOneSide
    ? 1
    : Math.min(1, half.clientWidth / PANEL_LAYOUT_WIDTH);
  frame.style.width = `${100 / scale}%`;
  frame.style.height = `${100 / scale}%`;
  frame.style.transform = `scale(${scale})`;
}

function startPanelFit(): void {
  const half = element("panel_half");
  new ResizeObserver(() => fitPanel(panelFrame, half)).observe(half);
}

/** Puts this page's own words in its language. */
function drawWords(): void {
  const { language } = display;
  const word = (key: string | undefined): string =>
    demoWord(language, key as DemoWordKey);
  document.documentElement.lang = language;
  document.title = word("page_title");
  for (const held of document.querySelectorAll<HTMLElement>("[data-word]")) {
    held.textContent = word(held.dataset.word);
  }
  for (const held of document.querySelectorAll<HTMLElement>(
    "[data-word-aria]",
  )) {
    held.setAttribute("aria-label", word(held.dataset.wordAria));
  }
  for (const held of document.querySelectorAll<HTMLIFrameElement>(
    "iframe[data-word-title]",
  )) {
    held.title = word(held.dataset.wordTitle);
  }
  element("demo_home").setAttribute("href", word("home_href"));
  for (const choice of document.querySelectorAll<HTMLElement>(
    "[data-language]",
  )) {
    choice.toggleAttribute(
      "aria-current",
      choice.dataset.language === language,
    );
  }
}

/** Puts this page in its palette. */
function drawTheme(): void {
  const isDark = display.theme === THEME_DARK;
  const root = document.documentElement;
  root.dataset.theme = isDark ? THEME_DARK : THEME_LIGHT;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute(
      "content",
      getComputedStyle(root).getPropertyValue("--demo-surface").trim(),
    );
  const button = element("demo_theme");
  button.setAttribute("aria-checked", String(isDark));
  button.title = demoWord(
    display.language,
    isDark ? "theme_to_light" : "theme_to_dark",
  );
}

/** Sets this page, the panel and the client to one language or palette. */
function overwriteDisplay(change: DemoDisplayChange): void {
  Object.assign(display, change);
  hub.overwriteDisplay(change);
  client.request({ path: CLIENT_SETTINGS_PATH, body: change });
  drawWords();
  drawTheme();
}

/**
 * The language menu, as on the docs site: a mouse opens it by hovering, a tap
 * by tapping.
 */
function startLanguageMenu(): void {
  const root = element<HTMLDivElement>("demo_language");
  const button = element<HTMLButtonElement>("demo_language_button");
  const menu = element<HTMLDivElement>("demo_language_menu");
  let isOpenedByHover = false;

  const isOpen = (): boolean => button.getAttribute("aria-expanded") === "true";
  const setOpen = (isOpening: boolean): void => {
    button.setAttribute("aria-expanded", String(isOpening));
  };
  const close = (): void => {
    setOpen(false);
    isOpenedByHover = false;
  };
  const isInside = (target: EventTarget | null): boolean =>
    target instanceof Node && root.contains(target);
  const closeOnLeave = (event: PointerEvent): void => {
    if (event.pointerType === "mouse" && !isInside(event.relatedTarget)) {
      close();
    }
  };

  button.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse" && !isOpen()) {
      setOpen(true);
      isOpenedByHover = true;
    }
  });
  button.addEventListener("pointerleave", closeOnLeave);
  menu.addEventListener("pointerleave", closeOnLeave);
  button.addEventListener("click", () => {
    if (!isOpenedByHover) {
      setOpen(!isOpen());
    }
    isOpenedByHover = false;
  });
  root.addEventListener("focusout", (event) => {
    if (event.relatedTarget !== null && !isInside(event.relatedTarget)) {
      close();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!isInside(event.target)) {
      close();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) {
      const isFocusInside = isInside(document.activeElement);
      close();
      if (isFocusInside) {
        button.focus();
      }
    }
  });
  // A press inside a frame reaches this window only as its blur.
  window.addEventListener("blur", close);

  for (const choice of menu.querySelectorAll<HTMLButtonElement>(
    "[data-language]",
  )) {
    choice.addEventListener("click", () => {
      close();
      overwriteDisplay({ language: choice.dataset.language });
    });
  }
}

/** Waits until a panel frame has drawn its page, for as long as it may take. */
function panelDrawn(frame: HTMLIFrameElement): Promise<void> {
  const startedAt = Date.now();
  return new Promise((resolve) => {
    const check = (): void => {
      const page = frame.contentDocument?.querySelector(".page");
      const isDrawn = page != null && page.querySelector(".skeleton") === null;
      if (isDrawn || Date.now() - startedAt > PANEL_DRAW_MAX_MS) {
        resolve();
      } else {
        window.setTimeout(check, PANEL_DRAW_CHECK_MS);
      }
    };
    check();
  });
}

/** Ends a panel frame's tree and takes the frame away. */
function closePanelFrame(frame: Element): void {
  const panel = (frame as HTMLIFrameElement).contentWindow;
  (panel as DemoPanelWindow | null)?.neutrinoDemoPanelStop?.();
  frame.remove();
}

/**
 * Opens the panel in a new frame, as the hub's edition stands now. The frame
 * loads under the open one, which covers it until it has drawn.
 */
function reopenPanel(route: string): void {
  const opening = panelFrame.cloneNode(false) as HTMLIFrameElement;
  opening.src = `${PANEL_PAGE}${route}`;
  panelFrame.before(opening);
  panelFrame = opening;
  panelRoute = route;
  void panelDrawn(opening).then(() => {
    if (!opening.isConnected) {
      return;
    }
    while (opening.nextElementSibling !== null) {
      closePanelFrame(opening.nextElementSibling);
    }
  });
}

/** Where the panel stands, or the overview from a page the edition leaves out. */
function routeInEdition(edition: DemoEdition): string {
  const route = panelFrame.contentWindow?.location.hash || panelRoute;
  return edition === EDITION_CN && route.startsWith(PROXY_ROUTE)
    ? OVERVIEW_ROUTE
    : route;
}

function drawEdition(): void {
  element("demo_edition").setAttribute(
    "aria-checked",
    String(hub.edition() === EDITION_INTL),
  );
}

function startEditionSwitch(): void {
  element("demo_edition").addEventListener("click", () => {
    const edition = hub.edition() === EDITION_INTL ? EDITION_CN : EDITION_INTL;
    const route = routeInEdition(edition);
    hub.setEdition(edition);
    drawEdition();
    reopenPanel(route);
  });
}

function startThemeSwitch(): void {
  element("demo_theme").addEventListener("click", () => {
    overwriteDisplay({
      theme: display.theme === THEME_DARK ? THEME_LIGHT : THEME_DARK,
    });
  });
}

function startNotices(): void {
  const notice = element<HTMLDivElement>("demo_notice");
  let timer = 0;
  hub.onNotice((text) => {
    notice.textContent = text;
    notice.hidden = false;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      notice.hidden = true;
    }, NOTICE_MS);
  });
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function frameLoaded(frame: HTMLIFrameElement): Promise<void> {
  return new Promise((resolve) =>
    frame.addEventListener("load", () => resolve(), { once: true }),
  );
}

function endLoadingAfter(frames: HTMLIFrameElement[]): void {
  const loading = element<HTMLDivElement>("demo_loading");
  const loaded = Promise.race([
    Promise.all(frames.map(frameLoaded)),
    delay(LOADING_MAX_MS),
  ]);
  void Promise.all([loaded, delay(LOADING_MIN_MS)]).then(() => {
    loading.classList.add("demo_loading--done");
    loading.addEventListener("transitionend", () => loading.remove(), {
      once: true,
    });
  });
}

for (const button of document.querySelectorAll<HTMLButtonElement>(
  "[data-show]",
)) {
  button.addEventListener("click", () => showSide(button.dataset.show ?? ""));
}
showSide("panel");
startNotices();
startLanguageMenu();
startThemeSwitch();
startEditionSwitch();
// A link from the English docs opens the demo in English on every side, as the international edition.
if (new URLSearchParams(window.location.search).get("lang") === "en") {
  hub.setEdition(EDITION_INTL);
  overwriteDisplay({ language: "en" });
}
drawWords();
drawTheme();
drawEdition();
const clientFrame = element<HTMLIFrameElement>("client_frame");
startPanelFit();
endLoadingAfter([panelFrame, clientFrame]);
panelFrame.src = PANEL_PAGE;
clientFrame.src = CLIENT_PAGE;
