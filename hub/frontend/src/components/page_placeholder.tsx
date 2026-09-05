import { Link } from "react-router-dom";

import { Icon } from "./icon";

/**
 * A page that exists in the sidebar before it exists as a page.
 *
 * An optional service appears in the rail as soon as it is switched on, and
 * each of those pages is being built one at a time. Until one arrives this
 * stands in and says so plainly, with the link to where the service can be
 * controlled meanwhile — better than a page missing from a rail that promises
 * it, and better than a page that pretends to configure something.
 */

interface PagePlaceholderProps {
  title: string;
  /** What the page will be for, in one line. */
  summary: string;
}

export function PagePlaceholder({ title, summary }: PagePlaceholderProps) {
  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{title}</h1>
          <span className="badge">not built yet</span>
        </div>
      </div>

      <div className="placeholder">
        <span>{summary}</span>
        <span className="faint">
          Not configurable yet; control the module from Modules.
        </span>
        <Link className="button" to="/modules">
          <Icon name="services" size={14} />
          Modules
        </Link>
      </div>
    </div>
  );
}
