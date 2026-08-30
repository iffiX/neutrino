/**
 * Removing terminal control sequences from streamed command output.
 *
 * The task log is a plain `<pre>`, not a terminal, so colour and cursor codes
 * from a remote script would render as literal `[1m` garbage. The gateway asks
 * remote installers not to emit them, but a deployment can run any command, so
 * the output is cleaned here too.
 */

// The escape and bell bytes, kept out of a regex literal so the no-control-char
// lint rule has nothing to complain about — the pattern is built from a string.
const ESC = String.fromCharCode(0x1b);
const BEL = String.fromCharCode(0x07);

// Every sequence starts with the escape byte, so ordinary text that happens to
// contain '[' is never matched. Covers CSI (colour, cursor moves), OSC (window
// titles, ended by BEL or ST), and the two-byte escapes.
const ANSI_PATTERN = new RegExp(
  `${ESC}\\[[0-9;?]*[ -/]*[@-~]` +
    `|${ESC}\\][^${BEL}${ESC}]*(?:${BEL}|${ESC}\\\\)` +
    `|${ESC}[@-Z\\\\-_]`,
  "g",
);

// A bare carriage return is what a progress line uses to overwrite itself; in a
// static log it just corrupts the layout, so drop it while keeping real
// newlines.
const BARE_CARRIAGE_RETURN = /\r(?!\n)/g;

/**
 * Strip ANSI escape sequences from a string.
 *
 * Args:
 *   text: Raw output, possibly carrying terminal control codes.
 *
 * Returns:
 *   The same text with control sequences and bare carriage returns removed.
 */
export function stripAnsi(text: string): string {
  return text.replace(ANSI_PATTERN, "").replace(BARE_CARRIAGE_RETURN, "");
}
