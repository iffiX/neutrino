import type { BalancerSettings, NodeView } from "./api_types";

/**
 * Comparing the node page's local draft against what is actually applied.
 *
 * Toggling a node in the panel must not touch xray until the user says so, so
 * the page holds a draft and this module works out what changed. The summary
 * it produces is the sentence on the apply bar, which is the last thing the
 * user reads before restarting the proxy — it has to be exact.
 */

export interface NodeDraftDiff {
  enabledIds: string[];
  disabledIds: string[];
  isBalancerChanged: boolean;
  isDirty: boolean;
  summary: string;
}

/**
 * Diff a draft against the applied state.
 *
 * Args:
 *   applied: The nodes and balancer as last loaded from the API.
 *   draftNodes: The nodes as the user has them on screen.
 *   draftBalancer: The balancer settings as the user has them on screen.
 *
 * Returns:
 *   The per-node changes, whether the balancer moved, and a one-line summary.
 */
export function diffNodeDraft(
  applied: NodeView[],
  draftNodes: NodeView[],
  appliedBalancer: BalancerSettings,
  draftBalancer: BalancerSettings,
): NodeDraftDiff {
  const appliedById = new Map(applied.map((node) => [node.id, node]));
  const enabledIds: string[] = [];
  const disabledIds: string[] = [];

  for (const node of draftNodes) {
    const original = appliedById.get(node.id);
    if (original === undefined || original.is_enabled === node.is_enabled) {
      continue;
    }
    if (node.is_enabled) {
      enabledIds.push(node.id);
    } else {
      disabledIds.push(node.id);
    }
  }

  const isBalancerChanged =
    appliedBalancer.strategy !== draftBalancer.strategy ||
    appliedBalancer.probe_url !== draftBalancer.probe_url ||
    appliedBalancer.probe_interval_s !== draftBalancer.probe_interval_s;

  const parts: string[] = [];
  if (enabledIds.length > 0) {
    parts.push(
      `${enabledIds.length} ${pluralNodes(enabledIds.length)} enabled`,
    );
  }
  if (disabledIds.length > 0) {
    parts.push(
      `${disabledIds.length} ${pluralNodes(disabledIds.length)} disabled`,
    );
  }
  if (appliedBalancer.strategy !== draftBalancer.strategy) {
    parts.push(`strategy → ${draftBalancer.strategy}`);
  }
  if (appliedBalancer.probe_url !== draftBalancer.probe_url) {
    parts.push("probe URL changed");
  }
  if (appliedBalancer.probe_interval_s !== draftBalancer.probe_interval_s) {
    parts.push(`probe interval → ${draftBalancer.probe_interval_s}s`);
  }

  return {
    enabledIds,
    disabledIds,
    isBalancerChanged,
    isDirty: parts.length > 0,
    summary: parts.join(", "),
  };
}

/** Whether one node differs from its applied counterpart. */
export function isNodeChanged(
  applied: NodeView[],
  draftNode: NodeView,
): boolean {
  const original = applied.find((node) => node.id === draftNode.id);
  if (original === undefined) {
    return true;
  }
  return (
    original.is_enabled !== draftNode.is_enabled ||
    original.name !== draftNode.name
  );
}

function pluralNodes(count: number): string {
  return count === 1 ? "node" : "nodes";
}
