/**
 * The palette both terminals draw in.
 *
 * Shared so the SSH session on a device and the shell on the gateway look like
 * the same program, and so neither looks pasted in next to the rest of the
 * panel — the colours are the theme's own tokens, resolved.
 */

export const TERMINAL_THEME = {
  background: "#0a0e14",
  foreground: "#e6edf3",
  cursor: "#22d3ee",
  cursorAccent: "#0a0e14",
  selectionBackground: "rgba(34, 211, 238, 0.25)",
  black: "#111721",
  red: "#fb7185",
  green: "#34d399",
  yellow: "#fbbf24",
  blue: "#22d3ee",
  magenta: "#a78bfa",
  cyan: "#22d3ee",
  white: "#e6edf3",
  brightBlack: "#5b6675",
  brightRed: "#fb7185",
  brightGreen: "#34d399",
  brightYellow: "#fbbf24",
  brightBlue: "#67e8f9",
  brightMagenta: "#c4b5fd",
  brightCyan: "#67e8f9",
  brightWhite: "#ffffff",
};
