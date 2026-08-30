/**
 * Converting between a node's id and its xray outbound tag.
 *
 * The gateway names every node outbound `node_<id>`, so stats frames and
 * observatory probes arrive tagged that way while the Nodes API speaks in bare
 * ids. Both sides of that translation live here so no page re-derives it.
 */

const NODE_TAG_PREFIX = "node_";

/**
 * Build the outbound tag for a node id.
 *
 * Args:
 *   nodeId: The node's id as the Nodes API reports it.
 *
 * Returns:
 *   The tag the gateway uses for that node's outbound.
 */
export function nodeTagFromId(nodeId: string): string {
  return `${NODE_TAG_PREFIX}${nodeId}`;
}

/**
 * Recover a node id from an outbound tag.
 *
 * Args:
 *   tag: An outbound tag from a stats frame or probe.
 *
 * Returns:
 *   The node id, or null when the tag names something that is not a node —
 *   the direct and block outbounds both appear in the same frames.
 */
export function nodeIdFromTag(tag: string): string | null {
  if (!tag.startsWith(NODE_TAG_PREFIX)) {
    return null;
  }
  return tag.slice(NODE_TAG_PREFIX.length);
}
