import "./sparkline.css";

/**
 * A tiny inline trend line, used for node latency probe history.
 *
 * Recharts is worth its weight for the dashboard's real charts but not for a
 * 60x18 glyph inside a card, so this draws the two paths by hand and stays
 * cheap enough to render once per node.
 */

const VERTICAL_PADDING = 2;

interface SparklineProps {
  values: number[];
  tone?: "accent" | "secondary" | "ok" | "warn" | "error";
  width?: number;
  height?: number;
  /** Fill the parent's width instead of rendering at natural size. */
  isStretchy?: boolean;
}

export function Sparkline({
  values,
  tone = "accent",
  width = 68,
  height = 20,
  isStretchy = false,
}: SparklineProps) {
  if (values.length < 2) {
    return <span className="sparkline_empty">no probes</span>;
  }

  const points = toPoints(values, width, height);
  const linePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x} ${point.y}`)
    .join(" ");
  const areaPath = `${linePath} L${width} ${height} L0 ${height} Z`;
  const head = points[points.length - 1];

  return (
    <svg
      className={`sparkline sparkline--${tone}${
        isStretchy ? " sparkline--stretch" : ""
      }`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio={isStretchy ? "none" : undefined}
      aria-hidden="true"
    >
      <path className="sparkline_area" d={areaPath} />
      <path className="sparkline_line" d={linePath} />
      {head !== undefined && (
        <circle className="sparkline_head" cx={head.x} cy={head.y} r={1.8} />
      )}
    </svg>
  );
}

function toPoints(
  values: number[],
  width: number,
  height: number,
): { x: number; y: number }[] {
  const lowest = Math.min(...values);
  const highest = Math.max(...values);
  const span = highest - lowest || 1;
  const usableHeight = height - VERTICAL_PADDING * 2;
  const step = width / (values.length - 1);

  return values.map((value, index) => ({
    x: Number((index * step).toFixed(2)),
    y: Number(
      (
        VERTICAL_PADDING +
        usableHeight -
        ((value - lowest) / span) * usableHeight
      ).toFixed(2),
    ),
  }));
}
