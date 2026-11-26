import { formatAmounts } from "../ai_usage";
import { t, useLanguage } from "../i18n";
import type { AiUsageCounters } from "../api_types";

/**
 * The **Cost** cell of a usage table: the row's cost, its API value faint
 * under it or in its place, and the no-price word for a row of unpriced
 * requests alone. Styles live in ai_page.css beside the page.
 */

interface AiUsageCostProps {
  counters: AiUsageCounters;
}

export function AiUsageCost({ counters }: AiUsageCostProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const cost = formatAmounts(counters.cost);
  const apiValue = formatAmounts(counters.api_value);
  const hasUnpriced = counters.unpriced_requests > 0;

  if (cost === "" && apiValue === "") {
    return hasUnpriced ? (
      <span className="usage_cost_note faint">{t("ui.usage.no_price")}</span>
    ) : null;
  }
  return (
    <div
      className="usage_cost"
      title={
        hasUnpriced
          ? t("ui.usage.unpriced_requests", {
              count: counters.unpriced_requests,
            })
          : undefined
      }
    >
      {cost !== "" && <div className="mono">{cost}</div>}
      {apiValue !== "" && (
        <div className="usage_cost_note mono faint">
          {t("ui.usage.api_value", { amount: apiValue })}
        </div>
      )}
    </div>
  );
}
