import { useLayoutEffect, useState } from "react";
import type { RefObject } from "react";

/**
 * The layout of a table whose rows turn into cards: a table while its box
 * holds every column and each row's actions on one line, a card per row in a
 * narrower box.
 */

/**
 * Pick a table's layout by the width of its box.
 *
 * Args:
 *   boxRef: The box around the table.
 *   actionsSelector: The rows' action groups inside the box. A row whose
 *     group the selector leaves out does not count, and with no group to
 *     measure the layout stays as it was.
 *
 * Returns:
 *   Whether each row lays out as a card.
 */
export function useTableCards(
  boxRef: RefObject<HTMLElement | null>,
  actionsSelector: string,
): boolean {
  const [isCards, setIsCards] = useState(false);

  useLayoutEffect(() => {
    const box = boxRef.current;
    if (box === null) {
      return;
    }
    let isActive = true;
    const measure = () => {
      const width = tableWidth(box, actionsSelector);
      if (isActive && width !== null) {
        setIsCards(box.clientWidth < width);
      }
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    document.fonts.ready.then(measure).catch(() => undefined);
    return () => {
      isActive = false;
      observer.disconnect();
    };
  });

  return isCards;
}

/**
 * The width the table needs with every action group on one line: each column
 * but the last at its set width, then the widest group and its cell's padding.
 */
function tableWidth(box: HTMLElement, actionsSelector: string): number | null {
  const groups = [...box.querySelectorAll<HTMLElement>(actionsSelector)];
  if (groups.length === 0) {
    return null;
  }
  const columns = [...box.querySelectorAll("col")].slice(0, -1);
  const columnsWidth = columns.reduce(
    (sum, column) => sum + pixels(getComputedStyle(column).width),
    0,
  );
  const header = box.querySelector("thead th:last-child");
  const padding =
    header === null
      ? 0
      : pixels(getComputedStyle(header).paddingLeft) +
        pixels(getComputedStyle(header).paddingRight);
  return columnsWidth + Math.max(...groups.map(oneLineWidth)) + padding;
}

/** The width of a group's items side by side, its gaps between them. */
function oneLineWidth(group: HTMLElement): number {
  const items = [...group.children];
  const gap = pixels(getComputedStyle(group).columnGap);
  const itemsWidth = items.reduce(
    (sum, item) => sum + item.getBoundingClientRect().width,
    0,
  );
  return itemsWidth + gap * Math.max(items.length - 1, 0);
}

function pixels(value: string): number {
  const number = parseFloat(value);
  return Number.isFinite(number) ? number : 0;
}
