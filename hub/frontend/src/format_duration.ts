/** Rendering elapsed times: uptimes, probe latencies, last-seen stamps. */

import { t } from "./i18n";

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_DAY = 86400;

/**
 * Format an uptime in seconds as the two largest non-zero units.
 *
 * Args:
 *   seconds: Elapsed seconds. Non-finite or negative input reads as `0m`.
 *
 * Returns:
 *   A string such as `12d 4h`, `4h 09m` or `38s`.
 */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "0m";
  }
  const whole = Math.floor(seconds);
  const days = Math.floor(whole / SECONDS_PER_DAY);
  const hours = Math.floor((whole % SECONDS_PER_DAY) / SECONDS_PER_HOUR);
  const minutes = Math.floor((whole % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const remainder = whole % SECONDS_PER_MINUTE;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
  }
  return `${remainder}s`;
}

/** Format a probe latency, or an em dash when the node never answered. */
export function formatLatency(delayMs: number | null): string {
  if (delayMs === null || !Number.isFinite(delayMs)) {
    return "—";
  }
  return `${Math.round(delayMs)} ms`;
}

/**
 * Format a wall-clock timestamp as a relative "time ago" string.
 *
 * Args:
 *   isoTimestamp: An ISO 8601 stamp from the backend, or null when the thing
 *     has never been seen.
 *
 * Returns:
 *   A string such as `4m ago`, or the word for never when there is nothing
 *   to show.
 */
export function formatTimeAgo(isoTimestamp: string | null): string {
  if (isoTimestamp === null) {
    return t("state.never");
  }
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return t("state.unknown");
  }
  const elapsedS = Math.max(0, (Date.now() - parsed) / 1000);
  if (elapsedS < 10) {
    return t("state.just_now");
  }
  return t("ui.duration.ago", { duration: formatDuration(elapsedS) });
}

/**
 * Format an ISO 8601 stamp as a local `HH:MM:SS` clock reading.
 *
 * Args:
 *   isoTimestamp: The stamp from a stats frame, in UTC.
 *
 * Returns:
 *   The local wall-clock time, or `--:--:--` when the stamp will not parse.
 */
export function formatClock(isoTimestamp: string): string {
  const parsed = Date.parse(isoTimestamp);
  if (Number.isNaN(parsed)) {
    return "--:--:--";
  }
  const date = new Date(parsed);
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

/**
 * Format the syslog stamp dnsmasq writes, e.g. `Aug 27 12:51:40`.
 *
 * The DNS log carries the line's own text rather than an ISO stamp, and it
 * has no year, so parsing it as a date would invent information. The clock
 * portion is already what the list wants to show, so this only trims it down.
 *
 * Args:
 *   stamp: The raw stamp from the log line.
 *
 * Returns:
 *   The `HH:MM:SS` field when the stamp has one, otherwise the stamp itself.
 */
export function formatLogClock(stamp: string): string {
  const match = /\d{1,2}:\d{2}:\d{2}/.exec(stamp);
  return match?.[0] ?? stamp.trim();
}
