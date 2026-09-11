import { t, useLanguage } from "../i18n";
import type { DeviceView, NetbirdView } from "../api_types";

import "./network_diagram.css";
import "./netbird_topology.css";

/**
 * The overlay, drawn from this gateway's point of view.
 *
 * Same three lanes as the Network diagram: peers on the left, the gateway in
 * the middle, the LAN it serves on the right. A star, not a mesh — the
 * gateway only knows its own tunnels, so those are the only edges drawn.
 * Direct tunnels flow in accent, relayed ones in amber, and a lazy
 * connection waits as a faint dotted line.
 */

const VIEW_WIDTH = 1180;
const NODE_WIDTH = 230;
const NODE_HEIGHT = 46;
const ROW_GAP = 12;
const GATEWAY_WIDTH = 168;
const GATEWAY_HEIGHT = 56;

const LANE_MIDDLE_WIDTH = 260;
const LANE_SIDE_WIDTH = (VIEW_WIDTH - LANE_MIDDLE_WIDTH) / 2;
const DIVIDER_LEFT = LANE_SIDE_WIDTH;
const DIVIDER_RIGHT = LANE_SIDE_WIDTH + LANE_MIDDLE_WIDTH;

const COLUMN_PEER = (LANE_SIDE_WIDTH - NODE_WIDTH) / 2;
const COLUMN_GATEWAY = DIVIDER_LEFT + (LANE_MIDDLE_WIDTH - GATEWAY_WIDTH) / 2;
const COLUMN_DEVICE = DIVIDER_RIGHT + (LANE_SIDE_WIDTH - NODE_WIDTH) / 2;

const HEADER_HEIGHT = 30;
const VERTICAL_PADDING = 16;
const MAX_DEVICES = 8;

interface NetbirdTopologyProps {
  view: NetbirdView;
  devices: DeviceView[];
}

export function NetbirdTopology({ view, devices }: NetbirdTopologyProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const peers = view.peers;
  // Everything online, plus the silent devices somebody cared enough to name;
  // unnamed neighbours that stopped answering are scan residue, not topology.
  const remembered = devices.filter(
    (device) => device.is_online || device.name !== null,
  );
  const shown = remembered
    .slice()
    .sort((a, b) => Number(b.is_online) - Number(a.is_online))
    .slice(0, MAX_DEVICES);
  const hiddenCount = remembered.length - shown.length;

  const leftRows = Math.max(1, peers.length);
  const rightRows = Math.max(1, shown.length + (hiddenCount > 0 ? 1 : 0));
  const rows = Math.max(leftRows, rightRows);
  const height =
    HEADER_HEIGHT +
    VERTICAL_PADDING * 2 +
    Math.max(rows * (NODE_HEIGHT + ROW_GAP) - ROW_GAP, GATEWAY_HEIGHT);

  const laneTop = HEADER_HEIGHT + VERTICAL_PADDING;
  const laneHeight = height - laneTop - VERTICAL_PADDING;
  const rowY = (index: number, count: number) => {
    const total = count * (NODE_HEIGHT + ROW_GAP) - ROW_GAP;
    return laneTop + (laneHeight - total) / 2 + index * (NODE_HEIGHT + ROW_GAP);
  };

  const gatewayY = laneTop + (laneHeight - GATEWAY_HEIGHT) / 2;
  const gatewayMidY = gatewayY + GATEWAY_HEIGHT / 2;

  return (
    <svg
      className="netbird_topology"
      viewBox={`0 0 ${VIEW_WIDTH} ${height}`}
      role="img"
      aria-label={t("ui.overlay.topology_label")}
    >
      <text
        className="diagram_lane_title"
        x={LANE_SIDE_WIDTH / 2}
        y={18}
        textAnchor="middle"
      >
        {t("ui.overlay.topology_lane_overlay")}
      </text>
      <text
        className="diagram_lane_title"
        x={DIVIDER_RIGHT + LANE_SIDE_WIDTH / 2}
        y={18}
        textAnchor="middle"
      >
        {t("ui.overlay.topology_lane_lan")}
      </text>
      <text
        className="topo_subnet"
        x={DIVIDER_RIGHT + LANE_SIDE_WIDTH / 2}
        y={34}
        textAnchor="middle"
      >
        {view.lan_subnets.join("  ")}
      </text>

      <line
        className="diagram_divider"
        x1={DIVIDER_LEFT}
        y1={8}
        x2={DIVIDER_LEFT}
        y2={height - 8}
      />
      <line
        className="diagram_divider"
        x1={DIVIDER_RIGHT}
        y1={8}
        x2={DIVIDER_RIGHT}
        y2={height - 8}
      />

      {/* Tunnels: peer to gateway. */}
      {peers.map((peer, index) => {
        const y = rowY(index, leftRows) + NODE_HEIGHT / 2;
        const x = COLUMN_PEER + NODE_WIDTH;
        const midX = (x + COLUMN_GATEWAY) / 2;
        const edgeClass = !peer.is_connected
          ? "topo_edge topo_edge--idle"
          : peer.connection_type === "P2P"
            ? "topo_edge topo_edge--direct"
            : "topo_edge topo_edge--relay";
        const kind = !peer.is_connected
          ? t("state.idle")
          : peer.connection_type === "P2P"
            ? t("state.direct")
            : t("state.relay");
        const latency =
          peer.is_connected && peer.latency_ms !== null
            ? `${peer.latency_ms} ms`
            : null;
        return (
          <g key={peer.fqdn}>
            <path
              className={edgeClass}
              d={`M ${x} ${y} C ${midX} ${y}, ${midX} ${gatewayMidY}, ${COLUMN_GATEWAY} ${gatewayMidY}`}
            />
            {/* At the peer's own row the line is flat: kind above it,
                latency below, neither ever on it. */}
            <text
              className="topo_edge_label"
              x={x + 12}
              y={y - 8}
              textAnchor="start"
            >
              {kind}
            </text>
            {latency !== null && (
              <text
                className="topo_edge_label"
                x={x + 12}
                y={y + 16}
                textAnchor="start"
              >
                {latency}
              </text>
            )}
          </g>
        );
      })}

      {/* LAN side: gateway to each device. Calm lines; the animation belongs
          to the tunnels. */}
      {shown.map((device, index) => {
        const y = rowY(index, rightRows) + NODE_HEIGHT / 2;
        const x = COLUMN_GATEWAY + GATEWAY_WIDTH;
        const midX = (x + COLUMN_DEVICE) / 2;
        return (
          <path
            key={device.mac_address}
            className={
              device.is_online
                ? "topo_lan_edge topo_lan_edge--on"
                : "topo_lan_edge"
            }
            d={`M ${x} ${gatewayMidY} C ${midX} ${gatewayMidY}, ${midX} ${y}, ${COLUMN_DEVICE} ${y}`}
          />
        );
      })}

      {/* Peers. */}
      {peers.map((peer, index) => (
        <g key={peer.fqdn}>
          <rect
            x={COLUMN_PEER}
            y={rowY(index, leftRows)}
            width={NODE_WIDTH}
            height={NODE_HEIGHT}
            rx={9}
            className={
              peer.is_connected
                ? "topo_peer_box topo_peer_box--on"
                : "topo_peer_box"
            }
          />
          <text
            className="topo_node_name"
            x={COLUMN_PEER + 12}
            y={rowY(index, leftRows) + 19}
          >
            {peer.fqdn.split(".")[0]}
          </text>
          <text
            className="topo_node_detail"
            x={COLUMN_PEER + 12}
            y={rowY(index, leftRows) + 35}
          >
            {peer.netbird_ip}
          </text>
        </g>
      ))}
      {peers.length === 0 && (
        <text
          className="topo_empty"
          x={LANE_SIDE_WIDTH / 2}
          y={laneTop + laneHeight / 2}
          textAnchor="middle"
        >
          {t("ui.overlay.topology_no_peers")}
        </text>
      )}

      {/* The gateway. */}
      <g className="diagram_gateway">
        <rect
          x={COLUMN_GATEWAY}
          y={gatewayY}
          width={GATEWAY_WIDTH}
          height={GATEWAY_HEIGHT}
          rx={11}
        />
        <text
          className="diagram_gateway_name"
          x={COLUMN_GATEWAY + GATEWAY_WIDTH / 2}
          y={gatewayY + 24}
          textAnchor="middle"
        >
          {(view.fqdn.split(".")[0] || "gateway").toUpperCase()}
        </text>
        <text
          className="diagram_gateway_sub"
          x={COLUMN_GATEWAY + GATEWAY_WIDTH / 2}
          y={gatewayY + 41}
          textAnchor="middle"
        >
          {view.netbird_ip.split("/")[0]}
        </text>
      </g>

      {/* LAN devices. */}
      {shown.map((device, index) => (
        <g key={device.mac_address}>
          <rect
            x={COLUMN_DEVICE}
            y={rowY(index, rightRows)}
            width={NODE_WIDTH}
            height={NODE_HEIGHT}
            rx={9}
            className={
              device.is_online
                ? "topo_device_box topo_device_box--on"
                : "topo_device_box"
            }
          />
          <text
            className="topo_node_name"
            x={COLUMN_DEVICE + 12}
            y={rowY(index, rightRows) + 19}
          >
            {device.name ?? device.ipv4_address}
          </text>
          <text
            className="topo_node_detail"
            x={COLUMN_DEVICE + 12}
            y={rowY(index, rightRows) + 35}
          >
            {device.ipv4_address}
          </text>
        </g>
      ))}
      {hiddenCount > 0 && (
        <text
          className="topo_node_detail"
          x={COLUMN_DEVICE + 12}
          y={rowY(rightRows - 1, rightRows) + NODE_HEIGHT / 2 + 4}
        >
          {t("ui.overlay.topology_more_devices", { count: hiddenCount })}
        </text>
      )}
      {remembered.length === 0 && (
        <text
          className="topo_empty"
          x={DIVIDER_RIGHT + LANE_SIDE_WIDTH / 2}
          y={laneTop + laneHeight / 2}
          textAnchor="middle"
        >
          {t("ui.overlay.topology_no_devices")}
        </text>
      )}
    </svg>
  );
}
