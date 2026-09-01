import { Icon } from "./icon";
import { isInSubnet } from "../ipv4_address";
import type {
  DeviceView,
  InterfaceView,
  NetworkView,
  PlannedUplink,
} from "../api_types";

import "./network_diagram.css";

/**
 * The wiring of the box, drawn.
 *
 * Three lanes, divided: what reaches the internet on the left, the gateway in
 * the middle, what the gateway serves on the right. Traffic runs left to right
 * and so does the reading, which is also why the middle lane is the narrow one
 * — the box is a waypoint, and the interesting question is always what sits on
 * either side of it.
 *
 * The right lane is a chain: each served port, then the VLANs riding on it if
 * the port is split, then the devices living on each network. Devices that are
 * online flow; devices remembered but silent hang dim and dashed. The lane is
 * wider than the left one because the chain is where the depth is.
 *
 * Every interface hangs off the gateway, the ones with no job included: an
 * unused port is still physically in the box, and drawing it detached would be
 * a lie about the hardware. What marks them out is the edge — dim and dashed,
 * against the flowing edges that are carrying traffic.
 *
 * Two interfaces reaching the same next hop converge at a junction before the
 * internet, which makes "why doesn't my second uplink help" answer itself with
 * no warning text to read. A VLAN holding the WAN role is an uplink and sits
 * in the left lane with the others.
 */

const VIEW_WIDTH = 1180;

const NODE_WIDTH = 150;
const NODE_HEIGHT = 46;
const ROW_GAP = 12;
const DEVICE_WIDTH = 132;
const DEVICE_HEIGHT = 40;

const CLOUD_WIDTH = 92;
const GATEWAY_WIDTH = 168;
const GATEWAY_HEIGHT = 54;
const JUNCTION_RADIUS = 4;

// The middle lane is the narrow one; both side lanes hold chains now — the
// left one gains a trunk column when an uplink is a VLAN.
const LANE_MIDDLE_WIDTH = 220;
const LANE_LEFT_WIDTH = 450;
const DIVIDER_LEFT = LANE_LEFT_WIDTH;
const DIVIDER_RIGHT = LANE_LEFT_WIDTH + LANE_MIDDLE_WIDTH;
const LANE_RIGHT_WIDTH = VIEW_WIDTH - DIVIDER_RIGHT;

const CHAIN_GAP = 18;
const COLUMN_CLOUD = 10;
const COLUMN_JUNCTION = 118;
const COLUMN_WAN_TRUNK = DIVIDER_LEFT - NODE_WIDTH - 6;
const COLUMN_UPLINK = COLUMN_WAN_TRUNK - CHAIN_GAP - NODE_WIDTH;
// Where the uplinks sit when no trunk column is needed: hugging the divider
// the way the served ports hug theirs, so the gateway is centred between the
// two sides instead of the WAN side trailing off leftwards.
const COLUMN_UPLINK_SNUG = DIVIDER_LEFT - 20 - NODE_WIDTH;
const COLUMN_GATEWAY = DIVIDER_LEFT + (LANE_MIDDLE_WIDTH - GATEWAY_WIDTH) / 2;
const COLUMN_LAN = DIVIDER_RIGHT + 20;
const COLUMN_VLAN = COLUMN_LAN + NODE_WIDTH + CHAIN_GAP;
const COLUMN_UNUSED = DIVIDER_LEFT + (LANE_MIDDLE_WIDTH - NODE_WIDTH) / 2;

const HEADER_HEIGHT = 26;
const VERTICAL_PADDING = 12;
// How far under the gateway the interfaces with no role begin.
const UNUSED_GAP = 20;
// Per network; the rest collapse into a "+n more" row so one busy LAN cannot
// stretch the diagram past reading.
const MAX_DEVICES_PER_NETWORK = 4;

interface NetworkDiagramProps {
  network: NetworkView;
  devices: DeviceView[];
  selectedName: string | null;
  onSelect: (name: string) => void;
}

/** One row in a device column: a device, or the count of the ones folded up. */
interface DeviceRow {
  device: DeviceView | null;
  moreCount: number;
}

interface ChainChild {
  entry: InterfaceView;
  devices: DeviceRow[];
  rowCount: number;
}

interface RightBlock {
  root: InterfaceView;
  children: ChainChild[];
  devices: DeviceRow[];
  rowCount: number;
}

interface PlacedInterface {
  entry: InterfaceView;
  x: number;
  y: number;
  fromX: number;
  fromY: number;
  edgeClassName: string;
}

interface PlacedDevice {
  row: DeviceRow;
  x: number;
  y: number;
  fromX: number;
  fromY: number;
}

export function NetworkDiagram({
  network,
  devices,
  selectedName,
  onSelect,
}: NetworkDiagramProps) {
  const unused = network.interfaces.filter(
    (entry) =>
      entry.settings.role === "disabled" && entry.settings.vlan === null,
  );

  // Uplinks stack in the order the planner ranked them, so an interface always
  // sits beside the line it belongs to and the edges never cross.
  const uplinks = network.lines.flatMap((line) =>
    line.members
      .map((member) =>
        network.interfaces.find((entry) => entry.settings.name === member.name),
      )
      .filter((entry): entry is InterfaceView => entry !== undefined),
  );

  // Devices worth drawing: everything online, plus the silent ones somebody
  // cared enough to name. Unnamed neighbours that stopped answering are scan
  // residue, not topology.
  const shownDevices = devices.filter(
    (device) => device.is_online || device.name !== null,
  );
  const lanEntries = network.interfaces.filter(
    (entry) =>
      entry.settings.role === "lan" && entry.settings.lan.address.length > 0,
  );
  const devicesByLan = new Map<string, DeviceView[]>();
  for (const device of shownDevices) {
    const owner =
      lanEntries.find((entry) =>
        isInSubnet(
          device.ipv4_address,
          entry.settings.lan.address,
          entry.settings.lan.prefix_len,
        ),
      ) ?? lanEntries[0];
    if (owner === undefined) {
      break;
    }
    const list = devicesByLan.get(owner.settings.name) ?? [];
    list.push(device);
    devicesByLan.set(owner.settings.name, list);
  }

  const blocks = buildRightBlocks(network, devicesByLan);
  const rightRows = blocks.reduce((total, block) => total + block.rowCount, 0);

  const sideHeight = Math.max(
    columnHeight(uplinks.length),
    columnHeight(rightRows),
  );
  const unusedHeight =
    unused.length > 0 ? UNUSED_GAP + columnHeight(unused.length) : 0;
  // Everything is centred on one line, and the body grows only if what hangs
  // under the gateway reaches past where the side lanes end.
  const half = Math.max(sideHeight / 2, GATEWAY_HEIGHT / 2 + unusedHeight);
  const bodyHeight = half * 2;
  const middle = HEADER_HEIGHT + VERTICAL_PADDING + half;
  const viewHeight = HEADER_HEIGHT + VERTICAL_PADDING * 2 + bodyHeight;

  const uplinkY = new Map<string, number>();
  uplinks.forEach((entry, index) => {
    uplinkY.set(entry.settings.name, rowY(index, uplinks.length, middle));
  });

  const lineY = new Map<string, number>();
  network.lines.forEach((line) => {
    const positions = line.members
      .map((member) => uplinkY.get(member.name))
      .filter((value): value is number => value !== undefined);
    lineY.set(line.id, positions.length > 0 ? average(positions) : middle);
  });

  const { placedInterfaces, placedDevices } = placeRightLane(
    blocks,
    rightRows,
    middle,
  );

  // A VLAN uplink rides a trunk, and the trunk is drawn beside it — the same
  // box the served side shows, mirrored, so a port split into both WAN and
  // LAN appears as one port in each lane.
  const wanTrunks = buildWanTrunks(network, uplinks, uplinkY, middle);
  const uplinkColumn =
    wanTrunks.length > 0 ? COLUMN_UPLINK : COLUMN_UPLINK_SNUG;

  // A side gateway is a way out with no WAN lane presence: a LAN whose
  // upstream router carries the box's traffic. It lights the cloud, and when
  // it is the only exit, an edge straight to the gateway says so.
  const isSideExitUp = network.interfaces.some(
    (entry) =>
      entry.settings.role === "lan" &&
      entry.settings.lan.upstream_gateway !== null &&
      entry.link.is_up,
  );
  const isCarrying =
    network.lines.some((line) => line.is_carrying) || isSideExitUp;
  const unusedTop = middle + GATEWAY_HEIGHT / 2 + UNUSED_GAP;

  return (
    <svg
      className="network_diagram"
      viewBox={`0 0 ${VIEW_WIDTH} ${viewHeight}`}
      role="img"
      aria-label="Network topology"
    >
      {/* The three lanes, and what each is for. */}
      <line
        className="diagram_divider"
        x1={DIVIDER_LEFT}
        y1={0}
        x2={DIVIDER_LEFT}
        y2={viewHeight}
      />
      <line
        className="diagram_divider"
        x1={DIVIDER_RIGHT}
        y1={0}
        x2={DIVIDER_RIGHT}
        y2={viewHeight}
      />
      <text className="diagram_lane_title" x={DIVIDER_LEFT / 2} y={18}>
        WAN
      </text>
      <text
        className="diagram_lane_title"
        x={DIVIDER_RIGHT + LANE_RIGHT_WIDTH / 2}
        y={18}
      >
        LAN
      </text>

      <g className={`diagram_cloud ${isCarrying ? "" : "diagram_cloud--dark"}`}>
        <rect
          x={COLUMN_CLOUD}
          y={middle - 20}
          width={CLOUD_WIDTH}
          height={40}
          rx={20}
        />
        <text x={COLUMN_CLOUD + CLOUD_WIDTH / 2} y={middle + 4}>
          Internet
        </text>
      </g>

      {/* One edge per line from the internet. A line reached by a single port
          runs straight to it; a line reached by two converges at a junction
          first, which is the whole of "these are one connection, not two". */}
      {network.lines.map((line) => {
        const y = lineY.get(line.id) ?? middle;
        const first = line.members[0];
        return (
          <path
            key={`cloud_${line.id}`}
            className={edgeClass(line.is_carrying)}
            d={curve(
              COLUMN_CLOUD + CLOUD_WIDTH,
              middle,
              line.is_shared ? COLUMN_JUNCTION : uplinkColumn,
              line.is_shared ? y : (uplinkY.get(first?.name ?? "") ?? y),
            )}
          />
        );
      })}

      {network.lines.length === 0 && isSideExitUp && (
        <path
          className={edgeClass(true)}
          d={curve(COLUMN_CLOUD + CLOUD_WIDTH, middle, COLUMN_GATEWAY, middle)}
        />
      )}

      {network.lines
        .filter((line) => line.is_shared)
        .map((line) => (
          <circle
            key={`junction_${line.id}`}
            className={`diagram_junction ${line.is_carrying ? "diagram_junction--live" : ""}`}
            cx={COLUMN_JUNCTION}
            cy={lineY.get(line.id) ?? middle}
            r={JUNCTION_RADIUS}
          />
        ))}

      {network.lines
        .filter((line) => line.is_shared)
        .flatMap((line) =>
          line.members.map((member) => (
            <path
              key={`member_${member.name}`}
              className={edgeClass(member.is_active)}
              d={curve(
                COLUMN_JUNCTION,
                lineY.get(line.id) ?? middle,
                uplinkColumn,
                uplinkY.get(member.name) ?? middle,
              )}
            />
          )),
        )}

      {uplinks.map((entry) => {
        const trunk = wanTrunks.find(
          (candidate) =>
            candidate.entry.settings.name === entry.settings.vlan?.parent,
        );
        return (
          <path
            key={`gw_${entry.settings.name}`}
            className={edgeClass(
              plannedFor(network, entry.settings.name)?.is_active ?? false,
            )}
            d={curve(
              uplinkColumn + NODE_WIDTH,
              uplinkY.get(entry.settings.name) ?? middle,
              trunk !== undefined ? COLUMN_WAN_TRUNK : COLUMN_GATEWAY,
              trunk !== undefined ? trunk.y : middle,
            )}
          />
        );
      })}

      {wanTrunks.map((trunk) => (
        <path
          key={`wan_trunk_edge_${trunk.entry.settings.name}`}
          className={edgeClass(trunk.isLive)}
          d={curve(
            COLUMN_WAN_TRUNK + NODE_WIDTH,
            trunk.y,
            COLUMN_GATEWAY,
            middle,
          )}
        />
      ))}

      {/* The served chain: gateway to port, port to VLAN, network to device. */}
      {placedInterfaces.map((placed) => (
        <path
          key={`chain_${placed.entry.settings.name}`}
          className={placed.edgeClassName}
          d={curve(placed.fromX, placed.fromY, placed.x, placed.y)}
        />
      ))}

      {/* Interfaces with no role: still wired to the box, doing nothing. */}
      {unused.map((entry, index) => (
        <path
          key={`unused_${entry.settings.name}`}
          className={edgeClass(false, true)}
          d={dropCurve(
            COLUMN_GATEWAY + GATEWAY_WIDTH / 2,
            middle + GATEWAY_HEIGHT / 2,
            COLUMN_UNUSED + NODE_WIDTH / 2,
            unusedTop + index * (NODE_HEIGHT + ROW_GAP),
          )}
        />
      ))}

      <g className="diagram_gateway">
        <rect
          x={COLUMN_GATEWAY}
          y={middle - GATEWAY_HEIGHT / 2}
          width={GATEWAY_WIDTH}
          height={GATEWAY_HEIGHT}
          rx={12}
        />
        <text
          x={COLUMN_GATEWAY + GATEWAY_WIDTH / 2}
          y={middle + 5}
          className="diagram_gateway_name"
        >
          NEUTRINO
        </text>
      </g>

      {uplinks.map((entry) => (
        <InterfaceNode
          key={entry.settings.name}
          entry={entry}
          planned={plannedFor(network, entry.settings.name)}
          x={uplinkColumn}
          y={uplinkY.get(entry.settings.name) ?? middle}
          isSelected={entry.settings.name === selectedName}
          onSelect={onSelect}
        />
      ))}

      {wanTrunks.map((trunk) => (
        <InterfaceNode
          key={`wan_trunk_${trunk.entry.settings.name}`}
          entry={trunk.entry}
          planned={null}
          x={COLUMN_WAN_TRUNK}
          y={trunk.y}
          isSelected={trunk.entry.settings.name === selectedName}
          onSelect={onSelect}
        />
      ))}

      {placedInterfaces.map((placed) => (
        <InterfaceNode
          key={placed.entry.settings.name}
          entry={placed.entry}
          planned={null}
          x={placed.x}
          y={placed.y}
          isSelected={placed.entry.settings.name === selectedName}
          onSelect={onSelect}
        />
      ))}

      {placedDevices.map((placed, index) =>
        placed.row.device !== null ? (
          <DeviceNode key={placed.row.device.mac_address} placed={placed} />
        ) : (
          <text
            key={`more_${index}`}
            className="diagram_device_more"
            x={placed.x}
            y={placed.y + 4}
          >
            +{placed.row.moreCount} more devices
          </text>
        ),
      )}

      {unused.map((entry, index) => (
        <InterfaceNode
          key={entry.settings.name}
          entry={entry}
          planned={null}
          x={COLUMN_UNUSED}
          y={unusedTop + index * (NODE_HEIGHT + ROW_GAP) + NODE_HEIGHT / 2}
          isSelected={entry.settings.name === selectedName}
          onSelect={onSelect}
        />
      ))}
    </svg>
  );
}

interface WanTrunk {
  entry: InterfaceView;
  y: number;
  isLive: boolean;
}

/** The trunks behind the VLAN uplinks, one box per port, centred on them. */
function buildWanTrunks(
  network: NetworkView,
  uplinks: InterfaceView[],
  uplinkY: Map<string, number>,
  middle: number,
): WanTrunk[] {
  const groups = new Map<string, { ys: number[]; isLive: boolean }>();
  for (const uplink of uplinks) {
    const parentName = uplink.settings.vlan?.parent;
    if (parentName === undefined) {
      continue;
    }
    const group = groups.get(parentName) ?? { ys: [], isLive: false };
    group.ys.push(uplinkY.get(uplink.settings.name) ?? middle);
    group.isLive =
      group.isLive ||
      (plannedFor(network, uplink.settings.name)?.is_active ?? false);
    groups.set(parentName, group);
  }
  const trunks: WanTrunk[] = [];
  for (const [name, group] of groups) {
    const entry = network.interfaces.find(
      (candidate) => candidate.settings.name === name,
    );
    if (entry !== undefined) {
      trunks.push({ entry, y: average(group.ys), isLive: group.isLive });
    }
  }
  return trunks;
}

/** Group the served side into blocks: a port, its VLANs, their devices. */
function buildRightBlocks(
  network: NetworkView,
  devicesByLan: Map<string, DeviceView[]>,
): RightBlock[] {
  const rowsFor = (name: string): DeviceRow[] => {
    const list = (devicesByLan.get(name) ?? [])
      .slice()
      .sort(
        (a, b) =>
          Number(b.is_online) - Number(a.is_online) ||
          compareAddresses(a.ipv4_address, b.ipv4_address),
      );
    if (list.length <= MAX_DEVICES_PER_NETWORK) {
      return list.map((device) => ({ device, moreCount: 0 }));
    }
    const kept = list.slice(0, MAX_DEVICES_PER_NETWORK - 1);
    return [
      ...kept.map((device) => ({ device, moreCount: 0 })),
      { device: null, moreCount: list.length - kept.length },
    ];
  };

  const roots = network.interfaces.filter(
    (entry) =>
      entry.settings.vlan === null &&
      (entry.settings.role === "lan" || entry.settings.role === "split"),
  );
  const splitNames = new Set(
    roots
      .filter((entry) => entry.settings.role === "split")
      .map((entry) => entry.settings.name),
  );

  const blocks: RightBlock[] = [];
  for (const root of roots) {
    if (root.settings.role === "split") {
      const children = network.interfaces
        .filter(
          (entry) =>
            entry.settings.vlan?.parent === root.settings.name &&
            entry.settings.role !== "wan",
        )
        .map((entry) => {
          const rows = rowsFor(entry.settings.name);
          return {
            entry,
            devices: rows,
            rowCount: Math.max(1, rows.length),
          };
        });
      blocks.push({
        root,
        children,
        devices: [],
        rowCount: Math.max(
          1,
          children.reduce((total, child) => total + child.rowCount, 0),
        ),
      });
    } else {
      const rows = rowsFor(root.settings.name);
      blocks.push({
        root,
        children: [],
        devices: rows,
        rowCount: Math.max(1, rows.length),
      });
    }
  }

  // A serving VLAN whose trunk vanished from the config still holds a network;
  // it stands on its own rather than disappearing from the picture.
  for (const entry of network.interfaces) {
    if (
      entry.settings.vlan !== null &&
      entry.settings.role === "lan" &&
      !splitNames.has(entry.settings.vlan.parent)
    ) {
      const rows = rowsFor(entry.settings.name);
      blocks.push({
        root: entry,
        children: [],
        devices: rows,
        rowCount: Math.max(1, rows.length),
      });
    }
  }
  return blocks;
}

/** Turn the blocks into coordinates, centred as one column of rows. */
function placeRightLane(
  blocks: RightBlock[],
  rowCount: number,
  middle: number,
): { placedInterfaces: PlacedInterface[]; placedDevices: PlacedDevice[] } {
  const placedInterfaces: PlacedInterface[] = [];
  const placedDevices: PlacedDevice[] = [];
  const rowAt = (index: number) => rowY(index, rowCount, middle);

  let cursor = 0;
  for (const block of blocks) {
    const rootY = (rowAt(cursor) + rowAt(cursor + block.rowCount - 1)) / 2;
    placedInterfaces.push({
      entry: block.root,
      x: COLUMN_LAN,
      y: rootY,
      fromX: COLUMN_GATEWAY + GATEWAY_WIDTH,
      fromY: middle,
      edgeClassName: edgeClass(block.root.link.is_up),
    });

    if (block.children.length > 0) {
      let childCursor = cursor;
      for (const child of block.children) {
        const childY =
          (rowAt(childCursor) + rowAt(childCursor + child.rowCount - 1)) / 2;
        placedInterfaces.push({
          entry: child.entry,
          x: COLUMN_VLAN,
          y: childY,
          fromX: COLUMN_LAN + NODE_WIDTH,
          fromY: rootY,
          edgeClassName:
            child.entry.settings.role === "disabled"
              ? edgeClass(false, true)
              : edgeClass(child.entry.link.is_up),
        });
        child.devices.forEach((row, index) => {
          placedDevices.push({
            row,
            x: COLUMN_VLAN + NODE_WIDTH + CHAIN_GAP,
            y: rowAt(childCursor + index),
            fromX: COLUMN_VLAN + NODE_WIDTH,
            fromY: childY,
          });
        });
        childCursor += child.rowCount;
      }
    } else {
      block.devices.forEach((row, index) => {
        placedDevices.push({
          row,
          x: COLUMN_VLAN,
          y: rowAt(cursor + index),
          fromX: COLUMN_LAN + NODE_WIDTH,
          fromY: rootY,
        });
      });
    }
    cursor += block.rowCount;
  }
  return { placedInterfaces, placedDevices };
}

function DeviceNode({ placed }: { placed: PlacedDevice }) {
  const device = placed.row.device!;
  const primary = device.name ?? device.ipv4_address;
  const secondary = device.name !== null ? device.ipv4_address : null;
  return (
    <g
      className={
        device.is_online
          ? "diagram_device diagram_device--on"
          : "diagram_device"
      }
    >
      <path
        className={
          device.is_online
            ? "diagram_edge diagram_edge--device"
            : "diagram_edge diagram_edge--device_off"
        }
        d={curve(placed.fromX, placed.fromY, placed.x, placed.y)}
      />
      <rect
        x={placed.x}
        y={placed.y - DEVICE_HEIGHT / 2}
        width={DEVICE_WIDTH}
        height={DEVICE_HEIGHT}
        rx={8}
      />
      <text
        className="diagram_device_name"
        x={placed.x + 10}
        y={placed.y + (secondary === null ? 4 : -2)}
      >
        {clip(primary, 15)}
      </text>
      {secondary !== null && (
        <text className="diagram_device_ip" x={placed.x + 10} y={placed.y + 13}>
          {secondary}
        </text>
      )}
    </g>
  );
}

interface InterfaceNodeProps {
  entry: InterfaceView;
  planned: PlannedUplink | null;
  x: number;
  y: number;
  isSelected: boolean;
  onSelect: (name: string) => void;
}

function InterfaceNode({
  entry,
  planned,
  x,
  y,
  isSelected,
  onSelect,
}: InterfaceNodeProps) {
  const { settings, link } = entry;
  const classNames = [
    "diagram_node",
    `diagram_node--${settings.role}`,
    isSelected ? "diagram_node--selected" : "",
    planned !== null && !planned.is_active ? "diagram_node--standby" : "",
  ]
    .filter((name) => name.length > 0)
    .join(" ");

  return (
    <g
      className={classNames}
      onClick={() => onSelect(settings.name)}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(settings.name);
        }
      }}
      aria-label={`${settings.name}, role ${settings.role}`}
    >
      <title>{planned?.reason ?? describe(entry)}</title>
      <rect
        x={x}
        y={y - NODE_HEIGHT / 2}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={10}
      />
      <foreignObject
        x={x}
        y={y - NODE_HEIGHT / 2}
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        pointerEvents="none"
      >
        <div className="diagram_node_body">
          <span className="diagram_node_head">
            <Icon name={link.kind === "wifi" ? "wifi" : "link"} size={11} />
            <span className="diagram_node_name">{settings.name}</span>
            {planned !== null && (
              <span className="diagram_node_rank">#{planned.rank}</span>
            )}
          </span>
          <span className="diagram_node_detail">{describe(entry)}</span>
        </div>
      </foreignObject>
    </g>
  );
}

/** The one line of detail a node shows under its name. */
function describe(entry: InterfaceView): string {
  const { settings, link } = entry;
  if (settings.role === "disabled") {
    if (settings.vlan !== null) {
      return "not configured yet";
    }
    return link.is_present ? "unused" : "not present";
  }
  if (!link.is_up) {
    return "link down";
  }
  if (settings.role === "split") {
    return "vlan trunk";
  }
  return link.ipv4_address ?? "no address";
}

function plannedFor(network: NetworkView, name: string): PlannedUplink | null {
  for (const line of network.lines) {
    const member = line.members.find((entry) => entry.name === name);
    if (member !== undefined) {
      return member;
    }
  }
  return null;
}

function edgeClass(isLive: boolean, isUnused = false): string {
  if (isUnused) {
    return "diagram_edge diagram_edge--unused";
  }
  return `diagram_edge ${isLive ? "diagram_edge--live" : "diagram_edge--idle"}`;
}

function columnHeight(count: number): number {
  if (count === 0) {
    return NODE_HEIGHT;
  }
  return count * NODE_HEIGHT + (count - 1) * ROW_GAP;
}

function rowY(index: number, count: number, middle: number): number {
  const start = middle - columnHeight(count) / 2;
  return start + index * (NODE_HEIGHT + ROW_GAP) + NODE_HEIGHT / 2;
}

function average(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function compareAddresses(a: string, b: string): number {
  const left = a.split(".").map(Number);
  const right = b.split(".").map(Number);
  for (let index = 0; index < 4; index += 1) {
    if ((left[index] ?? 0) !== (right[index] ?? 0)) {
      return (left[index] ?? 0) - (right[index] ?? 0);
    }
  }
  return 0;
}

function clip(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

/** A horizontal S-curve, so a fan-out reads as one flow rather than a bracket. */
function curve(x1: number, y1: number, x2: number, y2: number): string {
  const midway = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${midway} ${y1}, ${midway} ${y2}, ${x2} ${y2}`;
}

/** A vertical S-curve, for what hangs below the gateway rather than beside it. */
function dropCurve(x1: number, y1: number, x2: number, y2: number): string {
  const midway = (y1 + y2) / 2;
  return `M ${x1} ${y1} C ${x1} ${midway}, ${x2} ${midway}, ${x2} ${y2}`;
}
