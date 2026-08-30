import { Icon } from "./icon";
import { Sparkline } from "./sparkline";
import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { ToggleSwitch } from "./toggle_switch";
import { formatBytes } from "../format_bytes";
import { formatLatency } from "../format_duration";
import type { NodeView } from "../api_types";

import "./node_card.css";

/**
 * One JustMySocks exit, as a card.
 *
 * Enabling a node here only changes the draft the page holds; nothing reaches
 * xray until the page's apply bar is used. The card shows that pending state
 * as a small amber mark rather than by pretending the change is live.
 */

const LATENCY_GOOD_MS = 120;
const LATENCY_FAIR_MS = 300;

interface NodeCardProps {
  node: NodeView;
  probeHistory: number[];
  isDirty: boolean;
  isTesting: boolean;
  onToggle: (isEnabled: boolean) => void;
  onTest: () => void;
  onRemove: () => void;
}

export function NodeCard({
  node,
  probeHistory,
  isDirty,
  isTesting,
  onToggle,
  onTest,
  onRemove,
}: NodeCardProps) {
  const latencyTone = toLatencyTone(node.delay_ms, node.is_alive);
  const statusTone: StatusTone = node.is_alive ? "ok" : "error";
  const cardClassNames = [
    "node_card",
    node.is_enabled ? "node_card--enabled" : "node_card--disabled",
    isDirty ? "node_card--dirty" : "",
  ]
    .filter((name) => name.length > 0)
    .join(" ");

  return (
    <article className={cardClassNames}>
      <div className="node_card_head">
        <div className="node_card_identity">
          <div className="node_card_name">
            <StatusDot tone={statusTone} isPulsing={node.is_alive} />
            <span className="node_card_name_text" title={node.name}>
              {node.name}
            </span>
          </div>
          <div className="node_card_address" title={node.address}>
            {node.address}:{node.port}
          </div>
          <div className="node_card_badges">
            <span
              className={`badge ${
                node.protocol === "vless" ? "badge--secondary" : "badge--accent"
              }`}
            >
              {node.protocol === "vless"
                ? node.has_reality
                  ? "VLESS-Reality"
                  : "VLESS"
                : "SS"}
            </span>
            <span className="badge">{node.id}</span>
          </div>
        </div>
      </div>

      <div className="node_card_metrics">
        <div className="node_card_latency">
          <span
            className={`node_card_latency_value node_card_latency_value--${latencyTone}`}
          >
            {isTesting ? "testing…" : formatLatency(node.delay_ms)}
          </span>
          <span className="node_card_latency_label">
            {node.is_alive ? "last probe" : "unreachable"}
          </span>
        </div>
        <Sparkline values={probeHistory} tone={latencyTone} />
      </div>

      <div className="node_card_traffic">
        <span className="node_card_traffic_item node_card_traffic_item--up">
          <Icon name="arrow_up" size={13} />
          {formatBytes(node.uplink_bytes)}
        </span>
        <span className="node_card_traffic_item node_card_traffic_item--down">
          <Icon name="arrow_down" size={13} />
          {formatBytes(node.downlink_bytes)}
        </span>
      </div>

      <div className="node_card_footer">
        <ToggleSwitch
          isOn={node.is_enabled}
          onChange={onToggle}
          label={node.is_enabled ? "Enabled" : "Disabled"}
        />
        <div className="button_row">
          <button
            type="button"
            className="button button--small"
            onClick={onTest}
            disabled={isTesting}
          >
            <Icon name="bolt" size={13} />
            Test
          </button>
          {/* Removal takes effect at once rather than joining the draft: a
              node that is gone has no state left for the apply bar to describe. */}
          <button
            type="button"
            className="button button--small button--danger"
            onClick={onRemove}
            title={`Remove ${node.name}`}
            aria-label={`Remove ${node.name}`}
          >
            <Icon name="trash" size={13} />
          </button>
        </div>
      </div>
    </article>
  );
}

function toLatencyTone(
  delayMs: number | null,
  isAlive: boolean,
): "ok" | "warn" | "error" {
  if (!isAlive || delayMs === null) {
    return "error";
  }
  if (delayMs <= LATENCY_GOOD_MS) {
    return "ok";
  }
  if (delayMs <= LATENCY_FAIR_MS) {
    return "warn";
  }
  return "error";
}
