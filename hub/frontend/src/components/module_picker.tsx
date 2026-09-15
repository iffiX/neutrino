import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import type { DeviceAnnotation, DeviceView } from "../api_types";

import "./module_picker.css";

/**
 * The `+` at the end of a device's module tabs: which modules the page shows.
 *
 * It opens the same small panel the vault picker does, one row per module
 * with a check beside the ones the page shows, and every check is written to
 * the device's row at once.
 */

/** One module the picker can show or hide. */
export interface PickableModule {
  name: string;
  title: string;
}

const PANEL_GAP_PX = 4;
const PANEL_EDGE_PX = 12;
const PANEL_WIDTH_PX = 220;

/** Where the open panel sits, measured against the viewport. */
interface PanelPlacement {
  left: number;
  top: number;
}

interface ModulePickerProps {
  deviceId: string;
  modules: PickableModule[];
  /** The module names the page shows now. */
  shown: string[];
  onChanged: (shown: string[]) => void;
}

export function ModulePicker({
  deviceId,
  modules,
  shown,
  onChanged,
}: ModulePickerProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placement, setPlacement] = useState<PanelPlacement | null>(null);
  const controlRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const measure = useCallback(() => {
    const control = controlRef.current;
    if (control === null) {
      return;
    }
    const rect = control.getBoundingClientRect();
    const left = Math.min(
      rect.left,
      window.innerWidth - PANEL_WIDTH_PX - PANEL_EDGE_PX,
    );
    setPlacement({
      left: Math.max(PANEL_EDGE_PX, left),
      top: rect.bottom + PANEL_GAP_PX,
    });
  }, []);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [isOpen, measure]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) {
        return;
      }
      if (
        panelRef.current?.contains(event.target) === true ||
        controlRef.current?.contains(event.target) === true
      ) {
        return;
      }
      setIsOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setIsOpen(false);
        controlRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown, true);
    window.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      window.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [isOpen]);

  const toggle = async (name: string) => {
    const next = shown.includes(name)
      ? shown.filter((entry) => entry !== name)
      : modules
          .map((module) => module.name)
          .filter((entry) => entry === name || shown.includes(entry));
    setIsSaving(true);
    setError(null);
    const request: DeviceAnnotation = {
      device_id: deviceId,
      shown_module: next,
    };
    try {
      const device = await apiPost<DeviceView>("/hub/device/set", request);
      onChanged(device.shown_module);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <button
        type="button"
        ref={controlRef}
        className="button button--small module_picker_control"
        aria-haspopup="true"
        aria-expanded={isOpen}
        title={t("ui.module_picker.open")}
        aria-label={t("ui.module_picker.open")}
        onClick={() => setIsOpen((current) => !current)}
      >
        <Icon name="plus" size={13} />
      </button>
      {isOpen &&
        placement !== null &&
        createPortal(
          <div
            className="module_picker_panel"
            ref={panelRef}
            role="group"
            aria-label={t("ui.module_picker.label")}
            style={{
              left: placement.left,
              top: placement.top,
              width: PANEL_WIDTH_PX,
            }}
          >
            <span className="module_picker_hint">
              {t("ui.module_picker.hint")}
            </span>
            {modules.map((module) => {
              const isShown = shown.includes(module.name);
              return (
                <button
                  key={module.name}
                  type="button"
                  role="checkbox"
                  aria-checked={isShown}
                  className={`module_picker_row ${
                    isShown ? "module_picker_row--on" : ""
                  }`}
                  disabled={isSaving}
                  onClick={() => void toggle(module.name)}
                >
                  <span className="module_picker_check">
                    {isShown && <Icon name="check" size={12} />}
                  </span>
                  <span className="module_picker_row_name">{module.title}</span>
                </button>
              );
            })}
            {error !== null && (
              <span className="field_error module_picker_error">{error}</span>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}
