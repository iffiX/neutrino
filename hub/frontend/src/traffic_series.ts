import { formatClock } from "./format_duration";
import type { StatsFrame, TrafficSample } from "./api_types";

/**
 * Turning counters into the series the dashboard charts draw.
 *
 * The frame carries two kinds of number. The machine's own uplink arrives as
 * a rate the backend already worked out from the kernel's counters, and
 * everything crossing the WAN is in it. xray's per-outbound counters arrive as
 * totals, so a rate out of those is a difference computed here; they also
 * reset when xray restarts, which shows up as a negative delta and is clamped
 * to zero so a restart leaves a flat gap in the chart instead of a spike into
 * the negative.
 *
 * Direct is the first minus the second rather than xray's own `direct`
 * outbound counter, because that counter only sees traffic that entered xray
 * and was then routed straight out: an overlay daemon's traffic crosses the
 * WAN without ever entering xray, and no xray counter can see it. Two things
 * follow from the subtraction. The proxied figure is xray's count of the bytes
 * it handed to the outbound, which is a few percent under the bytes on the
 * wire, so direct comes out slightly high. And the kernel's counters and
 * xray's are not read at the same instant, so the subtraction can come out
 * negative and is clamped like every other one.
 */

const MIN_INTERVAL_S = 0.5;
/** Matches WEB_STATS_PUSH_INTERVAL_S on the backend. */
const NOMINAL_INTERVAL_S = 1;
/** Matches XRAY_NODE_TAG_PREFIX on the backend. */
const NODE_TAG_PREFIX = "node_";

/** Which traffic a live series counts: everything, the exits, or the rest. */
export type TrafficScope = "all" | "proxied" | "direct";

/**
 * One uplink and downlink figure. Byte totals where a frame's counters are
 * summed, bytes per second once two frames have been differenced.
 */
interface TrafficPair {
  uplink: number;
  downlink: number;
}

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
 *   scope: Which traffic counts. `all` is the machine's own uplink, the same
 *     counters the dashboard tiles read; `proxied` is what went out through an
 *     exit; `direct` is what crossed the WAN without going through one.
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
    const rates = scopedRates(previous, current, intervalS, scope);
    points.push({
      label: formatClock(current.timestamp),
      downlink_bytes_per_s: rates.downlink,
      uplink_bytes_per_s: rates.uplink,
    });
  }
  return points;
}

/** The rates one scope counts over the interval between two frames. */
function scopedRates(
  previous: StatsFrame,
  current: StatsFrame,
  intervalS: number,
  scope: TrafficScope,
): TrafficPair {
  const wan = wanRates(current);
  if (scope === "all") {
    return wan;
  }
  const proxied = proxiedRates(previous, current, intervalS);
  if (scope === "proxied") {
    return proxied;
  }
  return {
    uplink: Math.max(0, wan.uplink - proxied.uplink),
    downlink: Math.max(0, wan.downlink - proxied.downlink),
  };
}

/**
 * What the machine's uplink is carrying, as the kernel counts it.
 *
 * Already per second, so nothing is differenced here.
 */
function wanRates(frame: StatsFrame): TrafficPair {
  return {
    uplink: frame.interface_tx_bytes_per_s,
    downlink: frame.interface_rx_bytes_per_s,
  };
}

/** What left through an exit, out of xray's per-outbound totals. */
function proxiedRates(
  previous: StatsFrame,
  current: StatsFrame,
  intervalS: number,
): TrafficPair {
  const before = nodeTotals(previous);
  const now = nodeTotals(current);
  return {
    uplink: perSecond(now.uplink, before.uplink, intervalS),
    downlink: perSecond(now.downlink, before.downlink, intervalS),
  };
}

/** One frame's counters summed over the node outbounds. */
function nodeTotals(frame: StatsFrame): TrafficPair {
  const totals = { uplink: 0, downlink: 0 };
  for (const outbound of frame.outbounds) {
    if (!outbound.tag.startsWith(NODE_TAG_PREFIX)) {
      continue;
    }
    totals.uplink += outbound.uplink_bytes;
    totals.downlink += outbound.downlink_bytes;
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
