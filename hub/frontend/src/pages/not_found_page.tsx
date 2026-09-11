import { Link } from "react-router-dom";

import { Icon } from "../components/icon";
import { t, useLanguage } from "../i18n";

/**
 * The catch-all route.
 *
 * The sidebar is the whole site map, so an unknown path is almost always a
 * stale bookmark; the page says so and offers the one link back rather than
 * dressing a dead end up as an error.
 */
export function NotFoundPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div className="page">
      <h1>{t("ui.not_found.title")}</h1>
      <div>
        <Link className="button button--primary" to="/">
          <Icon name="dashboard" size={14} />
          {t("ui.not_found.back")}
        </Link>
      </div>
    </div>
  );
}
