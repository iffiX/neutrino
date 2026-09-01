import type { NodeProbe, StatsFrame } from "./api_types";

/**
 * Working out which exits are actually carrying traffic right now.
 *
 * xray reports cumulative counters per outbound, so "active" is not a flag the
 * backend sends — it is the difference between the oldest and newest frame in
 * the live window. Tags that are not exits (the direct path, the blackhole,
 * the internal DNS outbound) are filtered out so the dashboard shows only
 * nodes a user could switch between.
 */

const RESERVED_TAGS = new Set(["direct", "block", "blocked", "dns", "dns-out"]);

export interface ActiveExit {
  tag: string;
  uplinkBytes: number;
  downlinkBytes: number;
  totalBytes: number;
  delayMs: number | null;
  is_alive: boolean;
}

/**
 * Rank the exit outbounds by how much they moved across the frame window.
 *
 * Args:
 *   frames: The retained stats frames, oldest first.
 *   knownTags: Tags the backend has already named as active, which are kept
 *     even when they moved no bytes during the window.
 *
 * Returns:
 *   Exits sorted by traffic, busiest first.
 */
export function computeActiveExits(
  frames: StatsFrame[],
  knownTags: string[] = [],
): ActiveExit[] {
  const newest = frames[frames.length - 1];
  if (newest === undefined) {
    return [];
  }
  const oldest = frames[0] ?? newest;
  const baseline = new Map(
    oldest.outbounds.map((outbound) => [outbound.tag, outbound]),
  );
  const probes = new Map<string, NodeProbe>(
    newest.nodes.map((probe) => [probe.tag, probe]),
  );

  const exits: ActiveExit[] = [];
  for (const outbound of newest.outbounds) {
    if (RESERVED_TAGS.has(outbound.tag.toLowerCase())) {
      continue;
    }
    const start = baseline.get(outbound.tag);
    const uplinkBytes = Math.max(
      0,
      outbound.uplink_bytes - (start?.uplink_bytes ?? 0),
    );
    const downlinkBytes = Math.max(
      0,
      outbound.downlink_bytes - (start?.downlink_bytes ?? 0),
    );
    const totalBytes = uplinkBytes + downlinkBytes;
    if (totalBytes === 0 && !knownTags.includes(outbound.tag)) {
      continue;
    }
    const probe = probes.get(outbound.tag);
    exits.push({
      tag: outbound.tag,
      uplinkBytes,
      downlinkBytes,
      totalBytes,
      delayMs: probe?.delay_ms ?? null,
      // No probe is not proof of health. The frame carries probes for the
      // enabled nodes only, while the traffic counters carry every tag xray
      // still knows, so an exit without one is one nobody measured.
      is_alive: probe?.is_alive ?? false,
    });
  }

  return exits.sort((left, right) => right.totalBytes - left.totalBytes);
}

/** The busiest exit tag, or null when nothing is moving through the proxy. */
export function primaryExitTag(exits: ActiveExit[]): string | null {
  return exits[0]?.tag ?? null;
}
