import { AiUsageCost } from "./ai_usage_cost";
import {
  cacheShareOf,
  formatShare,
  successShareOf,
  tokensOf,
} from "../ai_usage";
import { formatCompact } from "../format_compact";
import { t, useLanguage } from "../i18n";
import type { AiUsageModel } from "../api_types";

/**
 * The per-model activity table on the AI page: one row per served name of
 * the range, and the days stored before the model field as model unknown.
 * Styles live in ai_page.css beside the page.
 */

interface AiUsageModelsProps {
  models: AiUsageModel[];
}

export function AiUsageModels({ models }: AiUsageModelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  if (models.length === 0) {
    return (
      <div className="placeholder">
        <span>{t("ui.usage.models_empty")}</span>
      </div>
    );
  }

  const sorted = [...models].sort((a, b) => b.requests - a.requests);

  return (
    <div className="usage_table_scroll">
      <table className="usage_table">
        <thead>
          <tr>
            <th>{t("ui.usage.header_model")}</th>
            <th className="num">{t("ui.usage.header_requests")}</th>
            <th className="num">{t("ui.usage.header_success")}</th>
            <th className="num">{t("ui.usage.header_tokens")}</th>
            <th className="num">{t("ui.usage.header_cache")}</th>
            <th className="num">{t("ui.usage.header_cost")}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const isUnknown = row.model.length === 0;
            return (
              <tr key={row.model}>
                <td>
                  {isUnknown ? (
                    <span className="usage_name faint">
                      {t("ui.usage.model_unknown")}
                    </span>
                  ) : (
                    <span className="usage_name mono" title={row.model}>
                      {row.model}
                    </span>
                  )}
                </td>
                <td className="num">
                  <div className="mono">{formatCompact(row.requests)}</div>
                  <div className="usage_split mono">
                    <span className="usage_ok">
                      {formatCompact(row.requests - row.failed)}
                    </span>
                    <span className="faint">/</span>
                    <span className={row.failed > 0 ? "usage_bad" : "faint"}>
                      {formatCompact(row.failed)}
                    </span>
                  </div>
                </td>
                <td className="num mono">{formatShare(successShareOf(row))}</td>
                <td className="num mono">{formatCompact(tokensOf(row))}</td>
                <td className="num mono">{formatShare(cacheShareOf(row))}</td>
                <td className="num">
                  {!isUnknown && <AiUsageCost counters={row} />}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
