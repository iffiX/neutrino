import type { ZfsDisk, ZfsPool, ZfsVdevMember } from "../api_types";
import { formatBytes } from "../format_bytes";

import "./network_diagram.css";
import "./zfs_topology.css";

/**
 * The storage, drawn: pool, then its vdevs, then their disks, left to right.
 *
 * The same visual language as the other diagrams: healthy paths flow as
 * bright dashes — running from the disks toward the pool, the way the data
 * does — dead ones hang dim and dotted, a resilver runs amber. Every disk is
 * the same bar at the same width, pooled or waiting; the status dot carries
 * the state, so no word repeats it.
 *
 * The pooled chain is centred; the unassigned disks pack densely below it in
 * up to two columns. Clicking a member disk selects it, and the verbs live in
 * the sections below — the pattern the Network page taught.
 */

const VIEW_WIDTH = 1180;
const MARGIN = 10;

const BAR_WIDTH = 570;
const BAR_GAP_X = 20;
const DISK_HEIGHT = 32;
const ROW_STEP = 40;

const POOL_WIDTH = 190;
const POOL_HEIGHT = 68;
const VDEV_WIDTH = 150;
const VDEV_HEIGHT = 32;

// The chain is narrower than the canvas, so it sits centred.
const CHAIN_WIDTH = POOL_WIDTH + 60 + VDEV_WIDTH + 70 + BAR_WIDTH;
const POOL_X = (VIEW_WIDTH - CHAIN_WIDTH) / 2;
const VDEV_X = POOL_X + POOL_WIDTH + 60;
const DISK_X = VDEV_X + VDEV_WIDTH + 70;

const BLOCK_GAP = 26;
const PADDING = 14;
const UNASSIGNED_HEADER = 28;

interface ZfsTopologyProps {
  pools: ZfsPool[];
  disks: ZfsDisk[];
  selectedMember: { pool: string; device: string } | null;
  onSelectMember: (pool: string, device: string) => void;
}

export function ZfsTopology({
  pools,
  disks,
  selectedMember,
  onSelectMember,
}: ZfsTopologyProps) {
  const unassigned = disks.filter((disk) => disk.is_available);
  const diskByName = new Map<string, ZfsDisk>();
  for (const disk of disks) {
    diskByName.set(disk.by_id.split("/").pop() ?? "", disk);
    diskByName.set(disk.device.split("/").pop() ?? "", disk);
  }

  const blockHeights = pools.map((pool) =>
    Math.max(
      poolRowCount(pool) * ROW_STEP - (ROW_STEP - DISK_HEIGHT),
      POOL_HEIGHT,
    ),
  );
  const poolsHeight = blockHeights.reduce(
    (total, height) => total + height + BLOCK_GAP,
    0,
  );
  // Unassigned disks pack column-major into two columns.
  const unassignedRows = Math.ceil(unassigned.length / 2);
  const unassignedHeight =
    unassigned.length > 0 ? UNASSIGNED_HEADER + unassignedRows * ROW_STEP : 0;
  const viewHeight = Math.max(PADDING * 2 + poolsHeight + unassignedHeight, 80);

  let cursorY = PADDING;
  const blocks = pools.map((pool, index) => {
    const top = cursorY;
    const height = blockHeights[index] ?? POOL_HEIGHT;
    cursorY += height + BLOCK_GAP;
    return { pool, top, height };
  });
  const unassignedTop = cursorY;

  return (
    <svg
      className="zfs_topology"
      viewBox={`0 0 ${VIEW_WIDTH} ${viewHeight}`}
      role="img"
      aria-label="Storage topology"
    >
      {blocks.map(({ pool, top, height }) => (
        <PoolBlock
          key={pool.name}
          pool={pool}
          top={top}
          height={height}
          diskByName={diskByName}
          selectedMember={selectedMember}
          onSelectMember={onSelectMember}
        />
      ))}

      {unassigned.length > 0 && (
        <g>
          <text
            className="diagram_lane_title zfs_lane_title"
            x={MARGIN}
            y={unassignedTop + 12}
          >
            UNASSIGNED
          </text>
          {unassigned.map((disk, index) => {
            const column = Math.floor(index / unassignedRows);
            const rowIndex = index % unassignedRows;
            return (
              <DiskBar
                key={disk.by_id}
                x={MARGIN + column * (BAR_WIDTH + BAR_GAP_X)}
                y={unassignedTop + UNASSIGNED_HEADER + rowIndex * ROW_STEP}
                tone="idle"
                name={disk.by_id.split("/").pop() ?? disk.device}
                detail={diskDetail(disk)}
                note={smartNote(disk)}
                isDashed
              />
            );
          })}
        </g>
      )}

      {pools.length === 0 && unassigned.length === 0 && (
        <text className="zfs_empty" x={VIEW_WIDTH / 2} y={viewHeight / 2}>
          no pools and no spare disks
        </text>
      )}
    </svg>
  );
}

interface PoolBlockProps {
  pool: ZfsPool;
  top: number;
  height: number;
  diskByName: Map<string, ZfsDisk>;
  selectedMember: { pool: string; device: string } | null;
  onSelectMember: (pool: string, device: string) => void;
}

function PoolBlock({
  pool,
  top,
  height,
  diskByName,
  selectedMember,
  onSelectMember,
}: PoolBlockProps) {
  const poolY = top + height / 2;
  const tone = stateTone(pool.state);
  const capacityTone = pool.capacity_percent >= 80 ? "warn" : "ok";
  const capacityWidth =
    (POOL_WIDTH - 28) * Math.min(pool.capacity_percent, 100) * 0.01;

  // Row layout: each vdev owns max(1, members) rows; the vdev node sits
  // centred on its rows, each member on its own.
  let row = 0;
  const placed = pool.vdevs.map((vdev) => {
    const rows = Math.max(1, vdev.members.length);
    const firstY = top + row * ROW_STEP + DISK_HEIGHT / 2;
    const lastY = top + (row + rows - 1) * ROW_STEP + DISK_HEIGHT / 2;
    const vdevY = (firstY + lastY) / 2;
    const members = vdev.members.map((member, index) => ({
      member,
      y: top + (row + index) * ROW_STEP,
    }));
    row += rows;
    return { vdev, vdevY, members };
  });

  return (
    <g>
      {/* Edges first, nodes on top. Flow runs disk to pool. */}
      {placed.map(({ vdev, vdevY }) => (
        <path
          key={`edge_${vdev.name}`}
          className={edgeClass(stateTone(vdev.state), false)}
          d={curve(POOL_X + POOL_WIDTH, poolY, VDEV_X, vdevY)}
        />
      ))}
      {placed.flatMap(({ vdev, vdevY, members }) =>
        members.map(({ member, y }) => (
          <path
            key={`edge_${vdev.name}_${member.name}`}
            className={edgeClass(
              stateTone(member.state),
              member.is_resilvering,
            )}
            d={curve(VDEV_X + VDEV_WIDTH, vdevY, DISK_X, y + DISK_HEIGHT / 2)}
          />
        )),
      )}

      <g className={`zfs_pool zfs_pool--${tone}`}>
        <rect
          x={POOL_X}
          y={poolY - POOL_HEIGHT / 2}
          width={POOL_WIDTH}
          height={POOL_HEIGHT}
          rx={11}
        />
        <text className="zfs_node_name" x={POOL_X + 14} y={poolY - 12}>
          Pool: {pool.name}
        </text>
        <text className="zfs_node_detail" x={POOL_X + 14} y={poolY + 5}>
          {formatBytes(pool.allocated_bytes)} / {formatBytes(pool.size_bytes)}
          {pool.scan.kind !== null &&
            ` · ${pool.scan.kind} ${pool.scan.percent?.toFixed(0) ?? "?"}%`}
        </text>
        <rect
          className="zfs_capacity_track"
          x={POOL_X + 14}
          y={poolY + 14}
          width={POOL_WIDTH - 28}
          height={3}
          rx={1.5}
        />
        {capacityWidth >= 3 ? (
          <rect
            className={`zfs_capacity_fill zfs_capacity_fill--${capacityTone}`}
            x={POOL_X + 14}
            y={poolY + 14}
            width={capacityWidth}
            height={3}
            rx={1.5}
          />
        ) : (
          <circle
            className={`zfs_capacity_fill zfs_capacity_fill--${capacityTone}`}
            cx={POOL_X + 15.5}
            cy={poolY + 15.5}
            r={1.5}
          />
        )}
      </g>

      {placed.map(({ vdev, vdevY }) => (
        <g
          key={vdev.name}
          className={`zfs_vdev zfs_vdev--${stateTone(vdev.state)}`}
        >
          <rect
            x={VDEV_X}
            y={vdevY - VDEV_HEIGHT / 2}
            width={VDEV_WIDTH}
            height={VDEV_HEIGHT}
            rx={9}
          />
          <text className="zfs_node_name" x={VDEV_X + 12} y={vdevY + 4}>
            {vdev.layout === "single" ? "single" : vdev.name}
          </text>
        </g>
      ))}

      {placed.flatMap(({ members }) =>
        members.map(({ member, y }) => {
          const disk = diskByName.get(member.name);
          return (
            <DiskBar
              key={member.name}
              x={DISK_X}
              y={y}
              tone={member.is_resilvering ? "warn" : stateTone(member.state)}
              name={member.name}
              detail={disk !== undefined ? diskDetail(disk) : ""}
              note={memberNote(member, disk)}
              noteTone={
                member.is_resilvering
                  ? "warn"
                  : memberErrors(member) > 0 ||
                      stateTone(member.state) === "bad"
                    ? "bad"
                    : undefined
              }
              isSelected={
                selectedMember !== null && selectedMember.device === member.name
              }
              onSelect={() => onSelectMember(pool.name, member.name)}
            />
          );
        }),
      )}
    </g>
  );
}

interface DiskBarProps {
  x: number;
  y: number;
  tone: "ok" | "warn" | "bad" | "idle";
  name: string;
  detail: string;
  note: string;
  noteTone?: "warn" | "bad";
  isDashed?: boolean;
  isSelected?: boolean;
  onSelect?: () => void;
}

function DiskBar({
  x,
  y,
  tone,
  name,
  detail,
  note,
  noteTone,
  isDashed = false,
  isSelected = false,
  onSelect,
}: DiskBarProps) {
  return (
    <g
      className={[
        "zfs_disk",
        `zfs_disk--${tone}`,
        isDashed ? "zfs_disk--dashed" : "",
        isSelected ? "zfs_disk--selected" : "",
        onSelect !== undefined ? "zfs_disk--clickable" : "",
      ]
        .filter((part) => part.length > 0)
        .join(" ")}
      onClick={onSelect}
      role={onSelect !== undefined ? "button" : undefined}
      tabIndex={onSelect !== undefined ? 0 : undefined}
      onKeyDown={
        onSelect !== undefined
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect();
              }
            }
          : undefined
      }
      aria-label={name}
    >
      <rect x={x} y={y} width={BAR_WIDTH} height={DISK_HEIGHT} rx={7} />
      <circle
        className="zfs_disk_dot"
        cx={x + 16}
        cy={y + DISK_HEIGHT / 2}
        r={4}
      />
      <text className="zfs_disk_name" x={x + 30} y={y + 20}>
        {name}
      </text>
      {detail.length > 0 && (
        <text className="zfs_node_detail" x={x + 268} y={y + 20}>
          {detail}
        </text>
      )}
      <text
        className={`zfs_node_detail ${noteTone !== undefined ? `zfs_note--${noteTone}` : ""}`}
        x={x + BAR_WIDTH - 12}
        y={y + 20}
        textAnchor="end"
      >
        {note}
      </text>
    </g>
  );
}

function diskDetail(disk: ZfsDisk): string {
  const parts = [formatBytes(disk.size_bytes)];
  if (disk.model) {
    parts.push(disk.model);
  }
  if (disk.fstype && disk.pool === null) {
    parts.push(`has ${disk.fstype}`);
  }
  return parts.join(" · ");
}

function smartNote(disk: ZfsDisk): string {
  if (disk.smart_passed === null) {
    return "";
  }
  if (!disk.smart_passed) {
    return "SMART FAILING";
  }
  return `SMART ok${disk.temperature_c !== null ? ` · ${disk.temperature_c}°C` : ""}`;
}

function memberErrors(member: ZfsVdevMember): number {
  return member.read_errors + member.write_errors + member.checksum_errors;
}

function memberNote(member: ZfsVdevMember, disk: ZfsDisk | undefined): string {
  if (member.is_resilvering) {
    return "resilvering";
  }
  const errors = memberErrors(member);
  if (errors > 0) {
    return `${errors} errors`;
  }
  if (stateTone(member.state) !== "ok") {
    return member.state.toLowerCase();
  }
  return disk !== undefined ? smartNote(disk) : "";
}

function poolRowCount(pool: ZfsPool): number {
  return Math.max(
    1,
    pool.vdevs.reduce(
      (total, vdev) => total + Math.max(1, vdev.members.length),
      0,
    ),
  );
}

function stateTone(state: string): "ok" | "warn" | "bad" | "idle" {
  switch (state) {
    case "ONLINE":
      return "ok";
    case "DEGRADED":
      return "warn";
    case "OFFLINE":
      return "idle";
    case "":
      return "idle";
    default:
      return "bad";
  }
}

function edgeClass(
  tone: "ok" | "warn" | "bad" | "idle",
  isResilvering: boolean,
): string {
  if (isResilvering) {
    return "zfs_edge zfs_edge--resilver";
  }
  if (tone === "ok") {
    return "zfs_edge zfs_edge--live";
  }
  if (tone === "bad" || tone === "warn") {
    return "zfs_edge zfs_edge--bad";
  }
  return "zfs_edge zfs_edge--idle";
}

/** A horizontal S-curve, matching the network diagrams' hand. */
function curve(x1: number, y1: number, x2: number, y2: number): string {
  const midway = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${midway} ${y1}, ${midway} ${y2}, ${x2} ${y2}`;
}
