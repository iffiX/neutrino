import { useContext, useEffect } from "react";

import { ServicesContext } from "../services_context";

/**
 * One module's unit state, beside its page title.
 *
 * Read from the list the shell shares with the Services page, so a page and
 * its card say the same thing about the same module. A module page that never
 * mentioned its unit made a service that had died invisible from everywhere
 * except the Services tab: the Proxy page went on drawing nodes and switches
 * with no xray running behind any of it.
 */

const REFRESH_INTERVAL_MS = 10000;

interface ServiceStateBadgeProps {
  /** The panel-facing service name, as the Services page lists it. */
  name: string;
}

export function ServiceStateBadge({ name }: ServiceStateBadgeProps) {
  const resource = useContext(ServicesContext);
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

  const service = resource?.data?.services.find((entry) => entry.name === name);
  if (service === undefined) {
    return null;
  }
  if (!service.is_installed) {
    return <span className="badge">not installed</span>;
  }
  return (
    <span
      className={`badge ${service.is_active ? "badge--ok" : "badge--error"}`}
    >
      {service.is_active ? "running" : "not running"}
    </span>
  );
}
