import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import "./dialog_layer.css";

/**
 * The window-wide layer every dialog of the panel sits in.
 *
 * A child of the body at the top z-index, so it covers and blurs the sidebar,
 * the top bar and the page, and nothing under it takes a press or the
 * keyboard. A dialog opened from a dialog mounts later and lies above its
 * parent. Escape and a press on the backdrop go to the top dialog alone. An
 * open picker takes Escape before any dialog does (`picker.tsx`).
 */

/** A mounted dialog: its layer, and what dismisses it. */
interface MountedLayer {
  element: HTMLDivElement | null;
  dismiss: (() => void) | null;
}

/** Every mounted dialog in the order mounted, the top one last. */
const layers: MountedLayer[] = [];

if (typeof document !== "undefined") {
  document.addEventListener("keydown", takeEscape, true);
}

function takeEscape(event: KeyboardEvent): void {
  const dismiss = layers.at(-1)?.dismiss;
  if (event.key !== "Escape" || dismiss === undefined || dismiss === null) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  dismiss();
}

/** Marks the page and every dialog under the top one inert. */
function settleInert(): void {
  document.getElementById("root")?.toggleAttribute("inert", layers.length > 0);
  layers.forEach((layer, index) => {
    layer.element?.toggleAttribute("inert", index < layers.length - 1);
  });
}

interface DialogLayerProps {
  /** The dialog's name for a screen reader. */
  label?: string;
  /** What Escape and a press on the backdrop do. Null leaves Escape to what
   * the dialog holds, and a press on the backdrop does nothing. */
  onDismiss: (() => void) | null;
  children: ReactNode;
}

export function DialogLayer({ label, onDismiss, children }: DialogLayerProps) {
  const elementRef = useRef<HTMLDivElement | null>(null);
  const layerRef = useRef<MountedLayer>({ element: null, dismiss: onDismiss });
  layerRef.current.dismiss = onDismiss;

  useEffect(() => {
    const layer = layerRef.current;
    layer.element = elementRef.current;
    layers.push(layer);
    settleInert();
    return () => {
      layers.splice(layers.indexOf(layer), 1);
      settleInert();
    };
  }, []);

  return createPortal(
    <div
      ref={elementRef}
      className="dialog_layer"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onDismiss?.();
        }
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
