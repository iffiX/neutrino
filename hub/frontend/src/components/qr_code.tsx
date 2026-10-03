import { useMemo } from "react";
import qrcode from "qrcode-generator";

import "./qr_code.css";

/**
 * A text drawn as a QR code: a PNG image, so a long press or a right click
 * saves it.
 *
 * Draws nothing when the text is longer than the largest code holds.
 */

/** The light border around the code, in modules, as scanners expect. */
const QR_QUIET_MODULES = 4;
/** The pixels one module takes in the image. */
const QR_MODULE_PX = 6;
/** The image's smallest side, in pixels. */
const QR_MIN_PX = 240;

interface QrCodeProps {
  text: string;
  label: string;
}

export function QrCode({ text, label }: QrCodeProps) {
  const image = useMemo(() => toImage(text), [text]);
  if (image === null) {
    return null;
  }
  return (
    <img
      className="qr_code"
      src={image.url}
      alt={label}
      width={image.size}
      height={image.size}
    />
  );
}

/** The code as a PNG data URL and its side in pixels, or null when it overflows. */
function toImage(text: string): { url: string; size: number } | null {
  const modules = toModules(text);
  if (modules === null) {
    return null;
  }
  const count = modules.length + QR_QUIET_MODULES * 2;
  const modulePx = Math.max(QR_MODULE_PX, Math.ceil(QR_MIN_PX / count));
  const size = count * modulePx;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  if (context === null) {
    return null;
  }
  context.fillStyle = "#fff";
  context.fillRect(0, 0, size, size);
  context.fillStyle = "#000";
  modules.forEach((cells, row) => {
    cells.forEach((isDark, col) => {
      if (isDark) {
        context.fillRect(
          (col + QR_QUIET_MODULES) * modulePx,
          (row + QR_QUIET_MODULES) * modulePx,
          modulePx,
          modulePx,
        );
      }
    });
  });
  return { url: canvas.toDataURL("image/png"), size };
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
