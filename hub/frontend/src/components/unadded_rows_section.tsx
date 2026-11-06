import type { ReactNode } from "react";

import { UnaddedRowsContext } from "../use_unadded_rows";
import type { UnaddedRows } from "../use_unadded_rows";

interface UnaddedRowsSectionProps {
  /** The frame's typed rows, from `useUnaddedRows`. */
  rows: UnaddedRows;
  className: string;
  children: ReactNode;
}

/** A frame's section, handing its list editors and its apply bar the
 * frame's typed rows. */
export function UnaddedRowsSection({
  rows,
  className,
  children,
}: UnaddedRowsSectionProps) {
  return (
    <section className={className}>
      <UnaddedRowsContext.Provider value={rows}>
        {children}
      </UnaddedRowsContext.Provider>
    </section>
  );
}
