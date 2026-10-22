/**
 * The palette both terminals draw in.
 *
 * The default foreground, background, cursor and selection are the active
 * theme's tokens, resolved when a terminal is created and again on a theme
 * change, since xterm takes colour strings rather than custom properties. The
 * 16 ANSI colours are the Tango palette of client.md, the same in both themes.
 */

import type { ITheme } from "@xterm/xterm";

import { themeToken } from "./theme";

/** The 16 ANSI colours, the same in both themes. */
const TERMINAL_PALETTE: ITheme = {
  black: "#2e3436",
  red: "#cc0000",
  green: "#4e9a06",
  yellow: "#c4a000",
  blue: "#3465a4",
  magenta: "#75507b",
  cyan: "#06989a",
  white: "#d3d7cf",
  brightBlack: "#555753",
  brightRed: "#ef2929",
  brightGreen: "#8ae234",
  brightYellow: "#fce94f",
  brightBlue: "#729fcf",
  brightMagenta: "#ad7fa8",
  brightCyan: "#34e2e2",
  brightWhite: "#eeeeec",
};

/** Read the active theme's terminal colours over the fixed palette. */
export function terminalTheme(): ITheme {
  return {
    ...TERMINAL_PALETTE,
    background: themeToken("--color-bg"),
    foreground: themeToken("--color-text"),
    cursor: themeToken("--color-accent"),
    cursorAccent: themeToken("--color-bg"),
    selectionBackground: themeToken("--color-terminal-selection"),
  };
}
