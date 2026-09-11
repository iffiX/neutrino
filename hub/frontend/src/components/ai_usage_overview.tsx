import { useState } from "react";
import type { ReactNode } from "react";

import { Sparkline } from "./sparkline";
import { UsageGrid } from "./usage_grid";
import {
  RANGE_BUCKET_DAYS,
  cacheShareOf,
  formatShare,
  successShareOf,
  tokensOf,
} from "../ai_usage";
import { formatCompact, formatSmallRate } from "../format_compact";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_AI_USAGE } from "../use_hub_events";
import type { AiUsageRange, AiUsageResponse } from "../api_types";

import "./ai_usage_overview.css";

/**
 * The dashboard's AI usage block: what the gateway served over a chosen
 * window, one range selector and key filter feeding every tile and grid.
 */

// The collector says when what it metered moved.
const USAGE_INVALIDATE_ON = [{ type: HUB_EVENT_AI_USAGE }];

const RANGE_OPTIONS: { value: AiUsageRange; labelKey: string }[] = [
  { value: "day", labelKey: "ui.usage.range_day" },
  { value: "week", labelKey: "ui.usage.range_week" },
  { value: "month", labelKey: "ui.usage.range_month" },
  { value: "year", labelKey: "ui.usage.range_year" },
];

export function AiUsageOverview() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [range, setRange] = useState<AiUsageRange>("day");
  const [keyId, setKeyId] = useState("");
  const usage = useApiResource<AiUsageResponse>(usagePath(range, keyId), {
    invalidateOn: USAGE_INVALIDATE_ON,
  });
  const data = usage.data;

  return (
    <section className="card">
      <div className="card_header ai_usage_head">
        <div className="card_title">
          <h2>{t("ui.usage.title")}</h2>
        </div>
        <div className="ai_usage_controls">
          <div className="ai_usage_ranges">
            {RANGE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`ai_usage_range ${
                  range === option.value ? "ai_usage_range--on" : ""
                }`}
                onClick={() => setRange(option.value)}
              >
                {t(option.labelKey)}
              </button>
            ))}
          </div>
          <select
            className="select ai_usage_key_select"
            value={keyId}
            onChange={(event) => setKeyId(event.target.value)}
          >
            <option value="">{t("ui.usage.all_keys")}</option>
            {(data?.keys ?? []).map((key) => (
              <option key={key.key_id} value={key.key_id}>
                {key.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {data === null && usage.isLoading && (
        <div className="skeleton" style={{ height: 220 }} />
      )}
      {data === null && !usage.isLoading && (
        <div className="placeholder">
          <span>{t("ui.usage.unavailable")}</span>
          <span className="faint">{t("ui.usage.unavailable_hint")}</span>
        </div>
      )}
      {data !== null && <UsageBody data={data} />}
    </section>
  );
}

interface UsageBodyProps {
  data: AiUsageResponse;
}

function UsageBody({ data }: UsageBodyProps) {
  const totals = data.totals;
  const hasTraffic = totals.requests > 0;
  const totalTokens = tokensOf(totals);
  const days = RANGE_BUCKET_DAYS[data.range] ?? 1;
  const requestSeries = data.series.map((point) => point.requests);
  const tokenSeries = data.series.map(tokensOf);
  const cacheShare = cacheShareOf(totals);

  return (
    <div className="ai_usage_body">
      <div className="ai_usage_tiles">
        <UsageTile
          label={t("ui.usage.requests")}
          tone="accent"
          value={formatCompact(totals.requests)}
          detail={
            hasTraffic ? (
              <>
                <span className="ai_usage_ok">
                  {t("ui.usage.count_ok", {
                    count: formatCompact(totals.requests - totals.failed),
                  })}
                </span>
                {" · "}
                <span className={totals.failed > 0 ? "ai_usage_bad" : ""}>
                  {t("ui.usage.count_failed", {
                    count: formatCompact(totals.failed),
                  })}
                </span>
                {" · "}
                {formatShare(successShareOf(totals))}
              </>
            ) : (
              t("ui.usage.no_requests")
            )
          }
          spark={requestSeries}
        />
        <UsageTile
          label={t("ui.usage.tokens")}
          tone="secondary"
          value={formatCompact(totalTokens)}
          detail={
            hasTraffic
              ? t("ui.usage.cache_detail", {
                  read: formatCompact(totals.cache_read_tokens),
                  write: formatCompact(totals.cache_write_tokens),
                })
              : t("ui.usage.no_requests")
          }
          spark={tokenSeries}
        />
        <UsageTile
          label={t("ui.usage.rpm")}
          tone="ok"
          value={formatSmallRate(data.rates.rpm)}
          detail={t("ui.usage.last_hour")}
        />
        <UsageTile
          label={t("ui.usage.tpm")}
          tone="ok"
          value={formatCompact(data.rates.tpm)}
          detail={t("ui.usage.last_hour")}
        />
        <UsageTile
          label={t("ui.usage.cache_rate")}
          tone="accent"
          value={formatShare(cacheShare)}
          detail={
            hasTraffic
              ? t("ui.usage.cache_read_of", {
                  read: formatCompact(totals.cache_read_tokens),
                  prompt: formatCompact(
                    totals.input_tokens + totals.cache_read_tokens,
                  ),
                })
              : t("ui.usage.no_requests")
          }
        />
        <UsageTile
          label={t("ui.usage.daily_average")}
          tone="secondary"
          value={formatCompact(totals.requests / days)}
          unit={t("ui.usage.requests_per_day")}
          detail={t("ui.usage.tokens_per_day", {
            count: formatCompact(totalTokens / days),
          })}
        />
      </div>

      <div className="ai_usage_charts">
        <div className="ai_usage_chart_box">
          <div className="ai_usage_chart_head">
            <h3>{t("ui.usage.token_activity")}</h3>
            {hasTraffic && (
              <span className="mono muted">
                {t("ui.usage.tokens_total", {
                  count: formatCompact(totalTokens),
                })}
              </span>
            )}
          </div>
          <UsageGrid series={data.series} range={data.range} mode="tokens" />
        </div>
        <div className="ai_usage_chart_box">
          <div className="ai_usage_chart_head">
            <h3>{t("ui.usage.request_health")}</h3>
            {hasTraffic && (
              <span className="mono">
                <span className="ai_usage_ok">
                  {formatShare(successShareOf(totals))}
                </span>{" "}
                <span className="muted">
                  {"· "}
                  {t("ui.usage.count_failed", {
                    count: formatCompact(totals.failed),
                  })}
                </span>
              </span>
            )}
          </div>
          <UsageGrid series={data.series} range={data.range} mode="health" />
        </div>
      </div>
    </div>
  );
}

interface UsageTileProps {
  label: string;
  tone: "accent" | "secondary" | "ok" | "warn" | "error";
  value: string;
  unit?: string;
  detail: ReactNode;
  spark?: number[];
}

function UsageTile({
  label,
  tone,
  value,
  unit,
  detail,
  spark,
}: UsageTileProps) {
  return (
    <div className={`stat_tile stat_tile--${tone}`}>
      <div className="stat_tile_head">
        <span className="stat_tile_label">{label}</span>
      </div>
      <div className="stat_tile_value">
        <span>{value}</span>
        {unit !== undefined && <span className="stat_tile_unit">{unit}</span>}
      </div>
      <div className="stat_tile_detail mono">{detail}</div>
      {spark !== undefined && spark.length >= 2 && (
        <div className="ai_usage_spark">
          <Sparkline
            values={spark}
            tone={tone}
            width={220}
            height={26}
            isStretchy
          />
        </div>
      )}
    </div>
  );
}

function usagePath(range: AiUsageRange, keyId: string): string {
  const filter = keyId.length > 0 ? `&key_id=${encodeURIComponent(keyId)}` : "";
  return `/cliproxyapi/usage?range=${range}${filter}`;
}
