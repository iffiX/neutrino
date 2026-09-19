import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { ToggleSwitch } from "./toggle_switch";
import { formatBytes } from "../format_bytes";
import { formatLatency, formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import type { NodeView } from "../api_types";

import "./node_card.css";

/**
 * One exit node, as a card.
 *
 * Enabling a node here only changes the draft the page holds; nothing reaches
 * xray until the page's apply bar is used. The card shows that pending state
 * as a small amber mark rather than by pretending the change is live.
 *
 * The hub measures every node, switched off included, so nothing the card
 * reports is read off the switch. A node nobody has measured, one that
 * answered and one that failed are three states; the switch says only
 * whether this node may be chosen as the exit.
 */

/** Every word this card says. */
const TEXT_KEYS = {
  connect: "ui.proxy.node_connect",
  request: "ui.proxy.node_request",
  selected: "ui.proxy.node_selected",
  notProbed: "ui.proxy.node_not_probed",
  probedAgo: "ui.proxy.node_probed_ago",
  score: "ui.proxy.node_score",
  unreachable: "ui.proxy.node_unreachable",
  enabled: "ui.proxy.node_enabled",
  disabled: "ui.proxy.node_disabled",
  test: "ui.proxy.node_test",
  testing: "ui.proxy.node_testing",
  remove: "ui.proxy.node_remove_title",
};

/** What each protocol is called on the badge, in its own upstream spelling. */
const PROTOCOL_LABELS = {
  shadowsocks: "SS",
  vless: "VLESS",
  vlessReality: "VLESS-Reality",
};

interface LatencyThresholds {
  goodMs: number;
  fairMs: number;
}

/** A TCP connect to the node's own port: one round trip and nothing else. */
const CONNECT_THRESHOLDS: LatencyThresholds = { goodMs: 120, fairMs: 300 };
/** A whole request through the node: the connect, the handshake and a fetch. */
const REQUEST_THRESHOLDS: LatencyThresholds = { goodMs: 400, fairMs: 900 };

const PERCENT_SCALE = 100;

interface NodeCardProps {
  node: NodeView;
  isDirty: boolean;
  isTesting: boolean;
  onToggle: (isEnabled: boolean) => void;
  onTest: () => void;
  onRemove: () => void;
}

export function NodeCard({
  node,
  isDirty,
  isTesting,
  onToggle,
  onTest,
  onRemove,
}: NodeCardProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const isMeasured = node.probed_at !== "";
  const statusTone: StatusTone = !isMeasured
    ? "idle"
    : node.is_alive
      ? "ok"
      : "error";
  const connectTone = toLatencyTone(
    node.connect_ms,
    node.is_alive,
    isMeasured,
    CONNECT_THRESHOLDS,
  );
  const requestTone = toLatencyTone(
    node.request_ms,
    node.is_alive,
    isMeasured,
    REQUEST_THRESHOLDS,
  );
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
            <StatusDot tone={statusTone} />
            <span className="node_card_name_text" title={node.name}>
              {node.name}
            </span>
          </div>
          <div className="node_card_address" title={node.address}>
            {node.address}:{node.port}
          </div>
          <div className="node_card_badges">
            {/* Which node the hub has pinned. */}
            {node.is_selected && (
              <span className="badge badge--ok">{t(TEXT_KEYS.selected)}</span>
            )}
            <span
              className={`badge ${
                node.protocol === "vless" ? "badge--secondary" : "badge--accent"
              }`}
            >
              {toProtocolLabel(node)}
            </span>
            <span className="badge">{node.id}</span>
          </div>
        </div>
      </div>

      <div className="node_card_metrics">
        <div className="node_card_metric">
          <span
            className={`node_card_metric_value node_card_metric_value--${connectTone}`}
          >
            {formatLatency(node.connect_ms)}
          </span>
          <span className="node_card_metric_label">{t(TEXT_KEYS.connect)}</span>
        </div>
        <div className="node_card_metric">
          <span
            className={`node_card_metric_value node_card_metric_value--${requestTone}`}
          >
            {formatLatency(node.request_ms)}
          </span>
          <span className="node_card_metric_label">{t(TEXT_KEYS.request)}</span>
        </div>
        <div className="node_card_probe">
          <span>
            {isMeasured
              ? t(TEXT_KEYS.probedAgo, { ago: formatTimeAgo(node.probed_at) })
              : t(TEXT_KEYS.notProbed)}
          </span>
          {/* The number the exit is ranked by, and how often this node
              answered. */}
          {isMeasured && (
            <span
              className={
                node.is_alive ? "" : "node_card_probe_value--unreachable"
              }
            >
              {node.is_alive
                ? t(TEXT_KEYS.score, {
                    score: formatLatency(node.score_ms),
                    percent: Math.round(node.success_rate * PERCENT_SCALE),
                  })
                : t(TEXT_KEYS.unreachable)}
            </span>
          )}
        </div>
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
          label={node.is_enabled ? t(TEXT_KEYS.enabled) : t(TEXT_KEYS.disabled)}
        />
        <div className="button_row">
          <button
            type="button"
            className="button button--small button--ghost"
            onClick={onTest}
            disabled={isTesting}
          >
            {isTesting ? <Spinner size={13} /> : <Icon name="bolt" size={13} />}
            {isTesting ? t(TEXT_KEYS.testing) : t(TEXT_KEYS.test)}
          </button>
          {/* Removal takes effect at once rather than joining the draft: a
              node that is gone has no state left for the apply bar to describe. */}
          <button
            type="button"
            className="button button--small button--ghost button--danger"
            onClick={onRemove}
            title={t(TEXT_KEYS.remove, { name: node.name })}
            aria-label={t(TEXT_KEYS.remove, { name: node.name })}
          >
            <Icon name="trash" size={13} />
          </button>
        </div>
      </div>
    </article>
  );
}

function toProtocolLabel(node: NodeView): string {
  if (node.protocol !== "vless") {
    return PROTOCOL_LABELS.shadowsocks;
  }
  return node.has_reality
    ? PROTOCOL_LABELS.vlessReality
    : PROTOCOL_LABELS.vless;
}

/**
 * The colour one measurement is drawn in.
 *
 * Four answers: a node with no measurement at all is not a failure, and red
 * is what a failure wears. The dot in the head answers the same way.
 *
 * Args:
 *   delayMs: The measurement, or null when this one did not complete.
 *   isAlive: Whether the latest measurement answered at all.
 *   isMeasured: Whether the node has ever been measured.
 *   thresholds: Where good ends and fair ends for this measurement. The two
 *     are not comparable: a connect is one round trip, a request is a whole
 *     fetch through the node.
 *
 * Returns:
 *   The tone the value is drawn in.
 */
function toLatencyTone(
  delayMs: number | null,
  isAlive: boolean,
  isMeasured: boolean,
  thresholds: LatencyThresholds,
): StatusTone {
  if (!isMeasured) {
    return "idle";
  }
  if (!isAlive || delayMs === null) {
    return "error";
  }
  if (delayMs <= thresholds.goodMs) {
    return "ok";
  }
  if (delayMs <= thresholds.fairMs) {
    return "warn";
  }
  return "error";
}
