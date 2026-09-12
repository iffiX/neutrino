import { formatClock } from "./format_duration";
import type { StatsFrame, TrafficSample } from "./api_types";

/**
 * Turning counters into the series the dashboard charts draw.
 *
 * xray and vnstat both report totals, never rates, so every rate on the
 * dashboard is a difference computed here. Counters also reset when xray
 * restarts, which shows up as a negative delta; those are clamped to zero so a
 * restart leaves a flat gap in the chart instead of a spike into the negative.
 */

const MIN_INTERVAL_S = 0.5;
/** Matches WEB_STATS_PUSH_INTERVAL_S on the backend. */
const NOMINAL_INTERVAL_S = 1;
/** Matches XRAY_NODE_TAG_PREFIX and XRAY_DIRECT_TAG on the backend. */
const NODE_TAG_PREFIX = "node_";
const DIRECT_TAG = "direct";

/** Which outbounds a live series counts: every one, the exits, or direct. */
export type TrafficScope = "all" | "proxied" | "direct";

export interface TrafficPoint {
  label: string;
  downlink_bytes_per_s: number;
  uplink_bytes_per_s: number;
}

export interface HistoryPoint {
  label: string;
  received_bytes: number;
  sent_bytes: number;
}

/**
 * Convert the live stats window into a per-second throughput series.
 *
 * Args:
 *   frames: Retained stats frames, oldest first.
 *   scope: Which outbounds count. `all` is the frame's own total; the other
 *     two sum the exits or the direct outbound out of the frame's per-tag
 *     counters.
 *
 * Returns:
 *   One point per interval between frames, so a window of n frames yields
 *   n - 1 points and an empty or single-frame window yields none.
 */
export function toTrafficSeries(
  frames: StatsFrame[],
  scope: TrafficScope = "all",
): TrafficPoint[] {
  const points: TrafficPoint[] = [];
  for (let index = 1; index < frames.length; index += 1) {
    const previous = frames[index - 1];
    const current = frames[index];
    if (previous === undefined || current === undefined) {
      continue;
    }
    const intervalS = Math.max(
      MIN_INTERVAL_S,
      elapsedSeconds(previous.timestamp, current.timestamp),
    );
    const before = scopedTotals(previous, scope);
    const now = scopedTotals(current, scope);
    points.push({
      label: formatClock(current.timestamp),
      downlink_bytes_per_s: perSecond(now.downlink, before.downlink, intervalS),
      uplink_bytes_per_s: perSecond(now.uplink, before.uplink, intervalS),
    });
  }
  return points;
}

/** A frame's counters summed over the outbounds a scope names. */
function scopedTotals(
  frame: StatsFrame,
  scope: TrafficScope,
): { uplink: number; downlink: number } {
  if (scope === "all") {
    return {
      uplink: frame.total_uplink_bytes,
      downlink: frame.total_downlink_bytes,
    };
  }
  const totals = { uplink: 0, downlink: 0 };
  for (const outbound of frame.outbounds) {
    const isCounted =
      scope === "proxied"
        ? outbound.tag.startsWith(NODE_TAG_PREFIX)
        : outbound.tag === DIRECT_TAG;
    if (isCounted) {
      totals.uplink += outbound.uplink_bytes;
      totals.downlink += outbound.downlink_bytes;
    }
  }
  return totals;
}

/** Shape the vnstat history for the bar chart. */
export function toHistorySeries(samples: TrafficSample[]): HistoryPoint[] {
  return samples.map((sample) => ({
    label: sample.label,
    received_bytes: Math.max(0, sample.received_bytes),
    sent_bytes: Math.max(0, sample.sent_bytes),
  }));
}

/** The peak downlink rate in a series, used to size the chart's axis. */
export function peakDownlink(points: TrafficPoint[]): number {
  return points.reduce(
    (highest, point) => Math.max(highest, point.downlink_bytes_per_s),
    0,
  );
}

function perSecond(
  current: number,
  previous: number,
  intervalS: number,
): number {
  return Math.max(0, current - previous) / intervalS;
}

/**
 * Seconds between two ISO stamps.
 *
 * Returns the nominal push interval when either stamp will not parse, so one
 * malformed frame cannot divide the whole series by a nonsense number.
 */
function elapsedSeconds(fromIso: string, toIso: string): number {
  const from = Date.parse(fromIso);
  const to = Date.parse(toIso);
  if (Number.isNaN(from) || Number.isNaN(to)) {
    return NOMINAL_INTERVAL_S;
  }
  return (to - from) / 1000;
}
