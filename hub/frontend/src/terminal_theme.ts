/**
 * The palette both terminals draw in.
 *
 * Shared so the SSH session on a device and the shell on the gateway look like
 * the same program, and so neither looks pasted in next to the rest of the
 * panel. xterm takes colour strings rather than custom properties, so the
 * tokens are resolved when a terminal is created.
 */

import type { ITheme } from "@xterm/xterm";

import { themeToken } from "./theme";

/** Read the active theme's terminal colours. */
export function terminalTheme(): ITheme {
  return {
    background: themeToken("--color-bg"),
    foreground: themeToken("--color-text"),
    cursor: themeToken("--color-accent"),
    cursorAccent: themeToken("--color-bg"),
    selectionBackground: themeToken("--color-terminal-selection"),
    black: themeToken("--color-terminal-black"),
    red: themeToken("--color-error"),
    green: themeToken("--color-ok"),
    yellow: themeToken("--color-warn"),
    blue: themeToken("--color-accent"),
    magenta: themeToken("--color-accent-secondary"),
    cyan: themeToken("--color-accent"),
    white: themeToken("--color-text"),
    brightBlack: themeToken("--color-text-faint"),
    brightRed: themeToken("--color-error"),
    brightGreen: themeToken("--color-ok"),
    brightYellow: themeToken("--color-warn"),
    brightBlue: themeToken("--color-terminal-bright-accent"),
    brightMagenta: themeToken("--color-terminal-bright-secondary"),
    brightCyan: themeToken("--color-terminal-bright-accent"),
    brightWhite: themeToken("--color-terminal-bright-text"),
  };
}
