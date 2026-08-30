import { Icon } from "./icon";
import { ErrorPanel } from "./error_panel";
import { useApiResource } from "../use_api_resource";
import type { ServiceJournal } from "../api_types";

import "./journal_panel.css";

/**
 * The expandable journal tail under a service card.
 *
 * The fetch is gated on `isOpen` by passing a null path, so collapsed cards
 * cost nothing — a services page with eight units does not pull eight
 * journals until someone actually asks for one.
 */

const JOURNAL_LINES = 200;

interface JournalPanelProps {
  serviceName: string;
  isOpen: boolean;
}

export function JournalPanel({ serviceName, isOpen }: JournalPanelProps) {
  const journalPath = isOpen
    ? `/services/${serviceName}/journal?lines=${JOURNAL_LINES}`
    : null;
  const journal = useApiResource<ServiceJournal>(journalPath);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="journal_panel">
      <div className="journal_panel_head">
        <span className="section_label">
          journal · last {JOURNAL_LINES} lines
        </span>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={journal.reload}
          disabled={journal.isLoading}
        >
          <Icon name="refresh" size={13} />
          Refresh
        </button>
      </div>

      {journal.error !== null && (
        <ErrorPanel
          title="Journal unavailable"
          message={journal.error}
          hint="journalctl may be unreadable for this unit, or the unit may not exist."
          onRetry={journal.reload}
        />
      )}

      {journal.error === null && journal.isLoading && journal.data === null && (
        <div className="skeleton journal_panel_loading" />
      )}

      {journal.error === null && journal.data !== null && (
        <pre className="journal_panel_output">
          {journal.data.text.trim().length > 0
            ? journal.data.text
            : "(no journal output)"}
        </pre>
      )}
    </div>
  );
}
