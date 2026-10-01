import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./icon";

import "./picker.css";

/**
 * The one control that offers a list to choose from.
 *
 * A control shaped like an input over a panel fixed to the viewport. The
 * control is a button, or with `isTyped` an input whose rows filter as the
 * person types and whose text stays when no row is chosen. An optional last
 * row creates an entry, with its form drawn in the same panel.
 */

// How the open list is sized: five rows at once, the add row among them,
// and the rest reached by scrolling.
const VISIBLE_ROW_COUNT = 5;
const ROW_HEIGHT_PX = 34;
const PANEL_GAP_PX = 4;
const PANEL_EDGE_PX = 12;
const FORM_HEIGHT_PX = 260;

/** One row of the list. */
export interface PickerOption {
  id: string;
  name: string;
  /** What tells two rows apart, drawn faint at the right. */
  detail?: string;
}

/** The last row, which creates an entry rather than picking one. */
export interface PickerAddRow {
  label: string;
  /**
   * The form drawn in the panel once the row is chosen. `finish` with an id
   * picks that entry and closes; with null it returns to the list.
   */
  renderForm: (finish: (id: string | null) => void) => ReactNode;
}

/** Where the open panel sits, measured against the viewport. */
interface PanelPlacement {
  left: number;
  width: number;
  top: number | null;
  bottom: number | null;
  available: number;
  /** The palette the control is drawn in, which the panel keeps. */
  theme: string | null;
}

interface PickerProps {
  options: PickerOption[];
  /** The chosen row's id, or with `isTyped` the text in the field. */
  value: string | null;
  onChange: (id: string) => void;
  label: string;
  /** The line under the control, where the screen has one to say. */
  hint?: string;
  /** The line under the control when the list could not be read. */
  error?: string | null;
  addRow?: PickerAddRow;
  isTyped?: boolean;
  /** Whether the label is read only by assistive technology. */
  isLabelHidden?: boolean;
  /** What the control shows while nothing is chosen or typed. */
  placeholder?: string;
  /** The line the open panel shows when the list has no rows. */
  emptyText?: string;
  isDisabled?: boolean;
  isInvalid?: boolean;
  onBlur?: () => void;
  className?: string;
}

export function Picker({
  options,
  value,
  onChange,
  label,
  hint,
  error,
  addRow,
  isTyped = false,
  isLabelHidden = false,
  placeholder,
  emptyText,
  isDisabled = false,
  isInvalid = false,
  onBlur,
  className,
}: PickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [placement, setPlacement] = useState<PanelPlacement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const escapeRef = useRef<() => void>(() => {});
  const labelId = useId();
  const listId = useId();

  const rows = isTyped ? filterOptions(options, value ?? "") : options;
  const hasAddRow = addRow !== undefined;
  const rowCount = rows.length + (hasAddRow ? 1 : 0);
  const selected = options.find((option) => option.id === value) ?? null;
  const isPanelShown =
    isOpen &&
    placement !== null &&
    (isAdding || rowCount > 0 || (!isTyped && emptyText !== undefined));

  const focusControl = useCallback(() => {
    (isTyped ? inputRef.current : buttonRef.current)?.focus();
  }, [isTyped]);

  const dismiss = useCallback(() => {
    setIsOpen(false);
    setIsAdding(false);
  }, []);

  const close = useCallback(() => {
    dismiss();
    focusControl();
  }, [dismiss, focusControl]);

  const measure = useCallback(() => {
    const control = isTyped ? inputRef.current : buttonRef.current;
    if (control === null) {
      return;
    }
    const rect = control.getBoundingClientRect();
    const below =
      window.innerHeight - rect.bottom - PANEL_GAP_PX - PANEL_EDGE_PX;
    const above = rect.top - PANEL_GAP_PX - PANEL_EDGE_PX;
    const wanted = isAdding
      ? FORM_HEIGHT_PX
      : Math.max(1, Math.min(rowCount, VISIBLE_ROW_COUNT)) * ROW_HEIGHT_PX;
    const isFlipped = below < wanted && above > below;
    setPlacement({
      left: rect.left,
      width: rect.width,
      top: isFlipped ? null : rect.bottom + PANEL_GAP_PX,
      bottom: isFlipped ? window.innerHeight - rect.top + PANEL_GAP_PX : null,
      available: Math.max(ROW_HEIGHT_PX * 2, isFlipped ? above : below),
      theme:
        control.closest("[data-theme]")?.getAttribute("data-theme") ?? null,
    });
  }, [isTyped, isAdding, rowCount]);

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
    escapeRef.current = () => {
      if (isAdding) {
        setIsAdding(false);
        return;
      }
      close();
    };
  });

  // Escape belongs to the open list before it belongs to whatever holds it,
  // so a modal hosting a picker stays open.
  useEffect(() => {
    if (!isPanelShown) {
      return;
    }
    const handler = () => escapeRef.current();
    escapeHandlers.push(handler);
    return () => {
      const at = escapeHandlers.indexOf(handler);
      if (at >= 0) {
        escapeHandlers.splice(at, 1);
      }
    };
  }, [isPanelShown]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) {
        return;
      }
      const control = isTyped ? inputRef.current : buttonRef.current;
      if (
        panelRef.current?.contains(event.target) === true ||
        control?.contains(event.target) === true
      ) {
        return;
      }
      dismiss();
    };
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () =>
      document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [isOpen, isTyped, dismiss]);

  useEffect(() => {
    if (!isOpen || isAdding || activeIndex < 0) {
      return;
    }
    listRef.current?.children.item(activeIndex)?.scrollIntoView({
      block: "nearest",
    });
  }, [isOpen, isAdding, activeIndex]);

  const handleOpen = () => {
    const at = isTyped ? -1 : rows.findIndex((row) => row.id === value);
    setActiveIndex(at >= 0 || isTyped ? at : 0);
    setIsOpen(true);
  };

  const handlePick = (id: string) => {
    onChange(id);
    close();
  };

  const handleFinish = (id: string | null) => {
    if (id === null) {
      setIsAdding(false);
      return;
    }
    handlePick(id);
  };

  const handleChoose = (index: number) => {
    const picked = rows[index];
    if (picked !== undefined) {
      handlePick(picked.id);
      return;
    }
    if (hasAddRow && index === rows.length) {
      setIsAdding(true);
    }
  };

  const handleKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement | HTMLInputElement>,
  ) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) {
        handleOpen();
        return;
      }
      if (rowCount === 0) {
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((index) =>
        index < 0 && step < 0
          ? rowCount - 1
          : (index + step + rowCount) % rowCount,
      );
      return;
    }
    const isPickKey = event.key === "Enter" || (!isTyped && event.key === " ");
    if (isPickKey) {
      if (!isOpen || isAdding || activeIndex < 0) {
        return;
      }
      event.preventDefault();
      handleChoose(activeIndex);
      return;
    }
    if (event.key === "Tab" && isOpen) {
      dismiss();
    }
  };

  const labelProps = isLabelHidden
    ? { "aria-label": label }
    : { "aria-labelledby": labelId };

  return (
    <div className={`field picker ${className ?? ""}`.trim()}>
      {!isLabelHidden && (
        <span className="field_label" id={labelId}>
          {label}
        </span>
      )}
      {isTyped ? (
        <input
          ref={inputRef}
          className={`input select picker_control picker_control--typed ${
            isInvalid ? "input--invalid" : ""
          }`}
          value={value ?? ""}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          disabled={isDisabled}
          role="combobox"
          {...labelProps}
          aria-autocomplete="list"
          aria-expanded={isOpen}
          aria-controls={listId}
          onChange={(event) => {
            onChange(event.target.value);
            setActiveIndex(-1);
            setIsOpen(true);
          }}
          onClick={() => (isOpen ? dismiss() : handleOpen())}
          onKeyDown={handleKeyDown}
          onBlur={onBlur}
        />
      ) : (
        <button
          type="button"
          ref={buttonRef}
          className={`select picker_control ${
            isInvalid ? "input--invalid" : ""
          }`}
          disabled={isDisabled}
          {...labelProps}
          aria-haspopup="listbox"
          aria-expanded={isOpen}
          aria-controls={listId}
          onClick={() => (isOpen ? close() : handleOpen())}
          onKeyDown={handleKeyDown}
        >
          <span
            className={`picker_value ${
              selected === null ? "picker_value--none" : ""
            }`}
          >
            {selected === null ? (placeholder ?? "") : optionLabel(selected)}
          </span>
        </button>
      )}
      {hint !== undefined && <span className="field_hint">{hint}</span>}
      {error !== undefined && error !== null && (
        <span className="field_error">{error}</span>
      )}
      {isPanelShown &&
        placement !== null &&
        createPortal(
          <div
            className="picker_panel"
            ref={panelRef}
            data-theme={placement.theme ?? undefined}
            style={{
              left: placement.left,
              width: placement.width,
              top: placement.top ?? undefined,
              bottom: placement.bottom ?? undefined,
              maxHeight: placement.available,
            }}
          >
            {isAdding && addRow !== undefined ? (
              addRow.renderForm(handleFinish)
            ) : (
              <>
                {rows.length === 0 && emptyText !== undefined && (
                  <span className="picker_empty">{emptyText}</span>
                )}
                <div
                  className="picker_list"
                  id={listId}
                  role="listbox"
                  ref={listRef}
                  aria-label={label}
                  style={{
                    maxHeight: Math.min(
                      VISIBLE_ROW_COUNT * ROW_HEIGHT_PX,
                      placement.available,
                    ),
                  }}
                  onMouseDown={(event) => event.preventDefault()}
                >
                  {rows.map((row, index) => (
                    <button
                      key={row.id}
                      type="button"
                      role="option"
                      tabIndex={-1}
                      aria-selected={row.id === value}
                      className={`picker_row ${
                        index === activeIndex ? "picker_row--active" : ""
                      }`}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => handlePick(row.id)}
                    >
                      <span className="picker_row_name">{row.name}</span>
                      {row.detail !== undefined && row.detail.length > 0 && (
                        <span className="picker_row_detail">{row.detail}</span>
                      )}
                    </button>
                  ))}
                  {addRow !== undefined && (
                    <button
                      type="button"
                      role="option"
                      tabIndex={-1}
                      aria-selected={false}
                      className={`picker_row picker_row--add ${
                        activeIndex === rows.length ? "picker_row--active" : ""
                      }`}
                      onMouseEnter={() => setActiveIndex(rows.length)}
                      onClick={() => setIsAdding(true)}
                    >
                      <Icon name="plus" size={13} />
                      {addRow.label}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

// The open picker takes Escape before whatever holds it does: one listener
// serves every picker, and it stands before a modal's own.
const escapeHandlers: Array<() => void> = [];

if (typeof window !== "undefined") {
  window.addEventListener("keydown", takeEscape, true);
}

function takeEscape(event: KeyboardEvent): void {
  const handler = escapeHandlers.at(-1);
  if (event.key !== "Escape" || handler === undefined) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  handler();
}

/** The rows whose name, detail or id holds the typed text. */
function filterOptions(options: PickerOption[], text: string): PickerOption[] {
  const needle = text.trim().toLowerCase();
  if (needle === "") {
    return options;
  }
  return options.filter((option) =>
    [option.id, option.name, option.detail ?? ""].some((part) =>
      part.toLowerCase().includes(needle),
    ),
  );
}

/** One row's whole line: the name, and what tells two of them apart. */
function optionLabel(option: PickerOption): string {
  return option.detail === undefined || option.detail.length === 0
    ? option.name
    : `${option.name} · ${option.detail}`;
}
