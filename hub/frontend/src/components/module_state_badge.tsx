import { useContext, useEffect } from "react";

import { ModulesContext } from "../modules_context";

/**
 * One module's unit state, beside its page title.
 *
 * Read from the list the shell shares with the Modules page, so a page and
 * its card say the same thing about the same module. A module page that never
 * mentioned its unit made a service that had died invisible from everywhere
 * except the Modules tab: the Proxy page went on drawing nodes and switches
 * with no xray running behind any of it.
 */

const REFRESH_INTERVAL_MS = 10000;

interface ModuleStateBadgeProps {
  /** The panel-facing module name, as the Modules page lists it. */
  name: string;
}

export function ModuleStateBadge({ name }: ModuleStateBadgeProps) {
  const resource = useContext(ModulesContext);
  const reload = resource?.reload;

  useEffect(() => {
    if (reload === undefined) {
      return;
    }
    reload();
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const module = resource?.data?.modules.find((entry) => entry.name === name);
  if (module === undefined) {
    return null;
  }
  if (!module.is_installed) {
    return <span className="badge">not installed</span>;
  }
  return (
    <span
      className={`badge ${module.is_active ? "badge--ok" : "badge--error"}`}
    >
      {module.is_active ? "running" : "not running"}
    </span>
  );
}
