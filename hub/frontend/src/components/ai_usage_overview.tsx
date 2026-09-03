import { useState } from "react";
import type { ReactNode } from "react";

import { Sparkline } from "./sparkline";
import { StatusDot } from "./status_dot";
import { UsageGrid } from "./usage_grid";
import {
  RANGE_BUCKET_DAYS,
  cacheShareOf,
  formatShare,
  successShareOf,
  tokensOf,
} from "../ai_usage";
import { formatCompact, formatSmallRate } from "../format_compact";
import { usePolledResource } from "../use_polled_resource";
import type { AiUsageRange, AiUsageResponse } from "../api_types";

import "./ai_usage_overview.css";

/**
 * The dashboard's AI usage block: what the gateway served over a chosen
 * window, one range selector and key filter feeding every tile and grid.
 */

const WORDING = {
  title: "AI usage",
  live: "live",
  allKeys: "All keys",
  requests: "Requests",
  tokens: "Tokens",
  rpm: "RPM",
  tpm: "TPM",
  cacheRate: "Cache rate",
  dailyAverage: "Daily average",
  requestsPerDay: "req/day",
  tokensPerDay: "tokens/day",
  lastHour: "last 60 min",
  okWord: "ok",
  failedWord: "failed",
  cacheDetail: (read: string, write: string) =>
    `cache read ${read} · write ${write}`,
  cacheReadOf: (read: string, prompt: string) =>
    `${read} of ${prompt} prompt tokens`,
  tokensWord: "tokens",
  tokenActivity: "Token activity",
  requestHealth: "Request health",
  noRequests: "No requests yet",
  unavailable: "Usage unavailable",
  unavailableHint: "The gateway is not reporting usage on this box yet.",
} as const;

const RANGE_OPTIONS: { value: AiUsageRange; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

export function AiUsageOverview() {
  const [range, setRange] = useState<AiUsageRange>("day");
  const [keyId, setKeyId] = useState("");
  const usage = usePolledResource<AiUsageResponse>(usagePath(range, keyId));
  const data = usage.data;

  return (
    <section className="card">
      <div className="card_header">
        <div className="card_title">
          <h2>{WORDING.title}</h2>
          {data !== null && (
            <StatusDot tone="ok" isPulsing label={WORDING.live} />
          )}
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
                {option.label}
              </button>
            ))}
          </div>
          <select
            className="select ai_usage_key_select"
            value={keyId}
            onChange={(event) => setKeyId(event.target.value)}
          >
            <option value="">{WORDING.allKeys}</option>
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
          <span>{WORDING.unavailable}</span>
          <span className="faint">{WORDING.unavailableHint}</span>
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
          label={WORDING.requests}
          tone="accent"
          value={formatCompact(totals.requests)}
          detail={
            hasTraffic ? (
              <>
                <span className="ai_usage_ok">
                  {formatCompact(totals.requests - totals.failed)}{" "}
                  {WORDING.okWord}
                </span>
                {" · "}
                <span className={totals.failed > 0 ? "ai_usage_bad" : ""}>
                  {formatCompact(totals.failed)} {WORDING.failedWord}
                </span>
                {" · "}
                {formatShare(successShareOf(totals))}
              </>
            ) : (
              WORDING.noRequests
            )
          }
          spark={requestSeries}
        />
        <UsageTile
          label={WORDING.tokens}
          tone="secondary"
          value={formatCompact(totalTokens)}
          detail={
            hasTraffic
              ? WORDING.cacheDetail(
                  formatCompact(totals.cache_read_tokens),
                  formatCompact(totals.cache_write_tokens),
                )
              : WORDING.noRequests
          }
          spark={tokenSeries}
        />
        <UsageTile
          label={WORDING.rpm}
          tone="ok"
          value={formatSmallRate(data.rates.rpm)}
          detail={WORDING.lastHour}
        />
        <UsageTile
          label={WORDING.tpm}
          tone="ok"
          value={formatCompact(data.rates.tpm)}
          detail={WORDING.lastHour}
        />
        <UsageTile
          label={WORDING.cacheRate}
          tone="accent"
          value={formatShare(cacheShare)}
          detail={
            hasTraffic
              ? WORDING.cacheReadOf(
                  formatCompact(totals.cache_read_tokens),
                  formatCompact(totals.input_tokens + totals.cache_read_tokens),
                )
              : WORDING.noRequests
          }
        />
        <UsageTile
          label={WORDING.dailyAverage}
          tone="secondary"
          value={formatCompact(totals.requests / days)}
          unit={WORDING.requestsPerDay}
          detail={`${formatCompact(totalTokens / days)} ${WORDING.tokensPerDay}`}
        />
      </div>

      <div className="ai_usage_charts">
        <div className="ai_usage_chart_box">
          <div className="ai_usage_chart_head">
            <h3>{WORDING.tokenActivity}</h3>
            {hasTraffic && (
              <span className="mono muted">
                {formatCompact(totalTokens)} {WORDING.tokensWord}
              </span>
            )}
          </div>
          <UsageGrid series={data.series} range={data.range} mode="tokens" />
        </div>
        <div className="ai_usage_chart_box">
          <div className="ai_usage_chart_head">
            <h3>{WORDING.requestHealth}</h3>
            {hasTraffic && (
              <span className="mono">
                <span className="ai_usage_ok">
                  {formatShare(successShareOf(totals))}
                </span>{" "}
                <span className="muted">
                  · {formatCompact(totals.failed)} {WORDING.failedWord}
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
