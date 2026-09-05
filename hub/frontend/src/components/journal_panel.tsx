import { useEffect, useRef } from "react";

import { StatusDot } from "./status_dot";
import { usePolledResource } from "../use_polled_resource";
import type { ServiceJournal } from "../api_types";

import "./journal_panel.css";

/**
 * The expandable journal tail under a service card.
 *
 * The fetch is gated on `isOpen` by passing a null path, so collapsed cards
 * cost nothing — a services page with eight units does not pull eight
 * journals until someone actually asks for one. While open it polls and keeps
 * the newest line in view, the same way `ai_journal_panel` does.
 */

const WORDING = {
  label: (lines: number) => `journal · last ${lines} lines`,
  live: "live",
  empty: "(no journal output)",
  unavailable: "The journal is not readable yet.",
} as const;

const JOURNAL_LINES = 200;

interface JournalPanelProps {
  moduleName: string;
  isOpen: boolean;
}

export function JournalPanel({ moduleName, isOpen }: JournalPanelProps) {
  const journal = usePolledResource<ServiceJournal>(
    isOpen ? `/modules/${moduleName}/journal?lines=${JOURNAL_LINES}` : null,
  );
  const outputRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const node = outputRef.current;
    if (node !== null) {
      node.scrollTop = node.scrollHeight;
    }
  }, [journal.data]);

  if (!isOpen) {
    return null;
  }
  const text = journal.data?.text ?? null;

  return (
    <div className="journal_panel">
      <div className="journal_panel_head">
        <span className="section_label">{WORDING.label(JOURNAL_LINES)}</span>
        {text !== null && (
          <StatusDot tone="ok" isPulsing label={WORDING.live} />
        )}
      </div>

      {text === null && journal.isLoading && (
        <div className="skeleton journal_panel_loading" />
      )}
      {text === null && !journal.isLoading && (
        <span className="field_hint">{WORDING.unavailable}</span>
      )}
      {text !== null && (
        <pre ref={outputRef} className="journal_panel_output">
          {text.trim().length > 0 ? text : WORDING.empty}
        </pre>
      )}
    </div>
  );
}
