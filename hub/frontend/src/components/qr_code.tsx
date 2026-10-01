import qrcode from "qrcode-generator";

import "./qr_code.css";

/**
 * A text drawn as a QR code, one SVG square per dark module.
 *
 * Draws nothing when the text is longer than the largest code holds.
 */

/** The light border around the code, in modules, as scanners expect. */
const QR_QUIET_MODULES = 4;

interface QrCodeProps {
  text: string;
  label: string;
}

export function QrCode({ text, label }: QrCodeProps) {
  const modules = toModules(text);
  if (modules === null) {
    return null;
  }
  const size = modules.length + QR_QUIET_MODULES * 2;
  return (
    <svg
      className="qr_code"
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
    >
      <rect width={size} height={size} className="qr_code_light" />
      <path d={toPath(modules)} className="qr_code_dark" />
    </svg>
  );
}

/** The code's dark modules by row and column, or null when it overflows. */
function toModules(text: string): boolean[][] | null {
  const code = qrcode(0, "M");
  code.addData(text, "Byte");
  try {
    code.make();
  } catch {
    return null;
  }
  const count = code.getModuleCount();
  const rows: boolean[][] = [];
  for (let row = 0; row < count; row += 1) {
    const cells: boolean[] = [];
    for (let col = 0; col < count; col += 1) {
      cells.push(code.isDark(row, col));
    }
    rows.push(cells);
  }
  return rows;
}

/** One SVG path with a unit square for every dark module. */
function toPath(modules: boolean[][]): string {
  const parts: string[] = [];
  modules.forEach((cells, row) => {
    cells.forEach((isDark, col) => {
      if (isDark) {
        parts.push(
          `M${col + QR_QUIET_MODULES} ${row + QR_QUIET_MODULES}h1v1h-1z`,
        );
      }
    });
  });
  return parts.join("");
}
