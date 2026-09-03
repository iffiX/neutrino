import { useEffect, useRef } from "react";

import { StatusDot } from "./status_dot";
import { usePolledResource } from "../use_polled_resource";
import type { CliproxyApiJournalResponse } from "../api_types";

import "./journal_panel.css";

/**
 * The AI gateway's journal tail, refreshed on its own. It reuses the service
 * journal's output styling but polls instead of asking to be reloaded, and
 * keeps the newest line in view.
 */

const WORDING = {
  label: (lines: number) => `journal · last ${lines} lines`,
  live: "live",
  empty: "(no journal output)",
  unavailable: "The journal is not readable yet.",
} as const;

const JOURNAL_LINES = 200;

interface AiJournalPanelProps {
  isOpen: boolean;
}

export function AiJournalPanel({ isOpen }: AiJournalPanelProps) {
  const journal = usePolledResource<CliproxyApiJournalResponse>(
    isOpen ? `/cliproxyapi/journal?lines=${JOURNAL_LINES}` : null,
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
  const lines = journal.data?.lines ?? null;

  return (
    <div className="journal_panel">
      <div className="journal_panel_head">
        <span className="section_label">{WORDING.label(JOURNAL_LINES)}</span>
        {lines !== null && (
          <StatusDot tone="ok" isPulsing label={WORDING.live} />
        )}
      </div>

      {lines === null && journal.isLoading && (
        <div className="skeleton journal_panel_loading" />
      )}
      {lines === null && !journal.isLoading && (
        <span className="field_hint">{WORDING.unavailable}</span>
      )}
      {lines !== null && (
        <pre ref={outputRef} className="journal_panel_output">
          {lines.length > 0 ? lines.join("\n") : WORDING.empty}
        </pre>
      )}
    </div>
  );
}
