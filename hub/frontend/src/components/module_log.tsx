import { useEffect, useRef } from "react";

import { apiPath } from "../api_client";
import { t, useLanguage } from "../i18n";
import { stripAnsi } from "../strip_ansi";
import { usePolledResource } from "../use_polled_resource";
import type { ServiceJournal } from "../api_types";

/**
 * A module tab's log box, under its title `Log · last 200 lines`.
 *
 * The tail of the module's own journal on the machine, in every state,
 * polled while it shows. The page mounts one per device and module, so the
 * box never holds another module's text.
 */

/** How much of the module's journal the box shows. */
const JOURNAL_LINES = 200;

interface ModuleLogProps {
  deviceId: string;
  module: string;
  isAgentOnline: boolean;
}

export function ModuleLog({ deviceId, module, isAgentOnline }: ModuleLogProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const journal = usePolledResource<ServiceJournal>(
    isAgentOnline
      ? apiPath("/agent/module/journal", {
          device_id: deviceId,
          module,
          lines: JOURNAL_LINES,
        })
      : null,
  );
  const journalText = journal.data?.text ?? null;
  const logRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const node = logRef.current;
    if (node !== null) {
      node.scrollTop = node.scrollHeight;
    }
  }, [journalText]);

  return (
    <div className="modules_log">
      <div className="modules_log_head">
        <span className="section_label">{t("ui.modules.log_title")}</span>
      </div>
      {isAgentOnline && journalText === null && journal.isLoading ? (
        <div className="skeleton modules_log_loading" />
      ) : (
        <pre className="modules_log_output" ref={logRef}>
          {!isAgentOnline ? (
            <span className="faint">{t("ui.modules.output_empty")}</span>
          ) : journalText === null ? (
            <span className="faint">{t("ui.journal.unavailable")}</span>
          ) : journalText.trim().length > 0 ? (
            stripAnsi(journalText)
          ) : (
            <span className="faint">{t("ui.journal.empty")}</span>
          )}
        </pre>
      )}
    </div>
  );
}
