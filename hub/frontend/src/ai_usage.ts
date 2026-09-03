import type {
  AiUsageBucket,
  AiUsageCounters,
  AiUsageHealthBucket,
  AiUsageRange,
} from "./api_types";

/**
 * Derived readings for the AI usage widgets.
 *
 * The API sends raw counters; every ratio, per-day average and bucket layout
 * is computed here so each widget guards division by zero exactly once and an
 * empty box renders an em dash instead of NaN.
 */

/** How many days each range spans, for the daily-average tile. */
export const RANGE_BUCKET_DAYS: Record<AiUsageRange, number> = {
  day: 1,
  week: 7,
  month: 30,
  year: 365,
};

export const MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

const WEEKDAY_ROWS = 7;
const HEAT_LEVELS = 4;

/** A ratio in [0, 1], or null when the denominator is zero. */
export function shareOf(numerator: number, denominator: number): number | null {
  if (!Number.isFinite(denominator) || denominator <= 0) {
    return null;
  }
  return Math.min(1, Math.max(0, numerator / denominator));
}

/** Format a share as `99.6%`, or an em dash for a null share. */
export function formatShare(share: number | null): string {
  if (share === null) {
    return "—";
  }
  return `${(share * 100).toFixed(1)}%`;
}

/** Tokens a set of counters served: input plus output. */
export function tokensOf(counters: AiUsageCounters): number {
  return counters.input_tokens + counters.output_tokens;
}

/** The fraction of requests that succeeded, null with no requests. */
export function successShareOf(counters: {
  requests: number;
  failed: number;
}): number | null {
  return shareOf(counters.requests - counters.failed, counters.requests);
}

/**
 * The fraction of prompt tokens answered from cache, null with none.
 *
 * `input_tokens` is the vendor's cache-inclusive input total, so the cache
 * reads are a share of it, not an addition to it.
 */
export function cacheShareOf(counters: AiUsageCounters): number | null {
  return shareOf(counters.cache_read_tokens, counters.input_tokens);
}

/**
 * Parse a series bucket into a local Date.
 *
 * Daily buckets are calendar dates (`YYYY-MM-DD`) and stay on the day they
 * name; parsing them as UTC would shift them across midnight for viewers
 * west of it. Hourly buckets are instants and convert to local time.
 */
export function parseBucket(bucket: string): Date | null {
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(bucket);
  if (dateOnly !== null) {
    return new Date(
      Number(dateOnly[1]),
      Number(dateOnly[2]) - 1,
      Number(dateOnly[3]),
    );
  }
  const parsed = Date.parse(bucket);
  return Number.isNaN(parsed) ? null : new Date(parsed);
}

/** Label a bucket for a cell tooltip or an axis: `14:00` or `Sep 3`. */
export function formatBucketLabel(bucket: string, range: AiUsageRange): string {
  const date = parseBucket(bucket);
  if (date === null) {
    return bucket;
  }
  if (range === "day") {
    return `${String(date.getHours()).padStart(2, "0")}:00`;
  }
  const month = MONTH_LABELS[date.getMonth()] ?? "";
  return `${month} ${date.getDate()}`;
}

/** Intensity step 0–4 for a heat cell, 0 meaning no activity. */
export function toHeatLevel(value: number, highest: number): number {
  if (value <= 0 || highest <= 0) {
    return 0;
  }
  return Math.max(1, Math.ceil((value / highest) * HEAT_LEVELS));
}

/**
 * Lay daily buckets out as weekday-aligned columns, one column per week.
 *
 * Rows run Sunday to Saturday; the first and last columns carry nulls where
 * the range does not cover the whole week. Hourly buckets never come here —
 * the day range renders as a single row instead.
 */
export function toWeekColumns(
  series: AiUsageBucket[],
): (AiUsageBucket | null)[][] {
  const columns: (AiUsageBucket | null)[][] = [];
  let column: (AiUsageBucket | null)[] = [];

  for (const point of series) {
    const weekday = parseBucket(point.bucket)?.getDay() ?? 0;
    if (column.length === 0) {
      column = new Array<AiUsageBucket | null>(weekday).fill(null);
    }
    column.push(point);
    if (column.length === WEEKDAY_ROWS) {
      columns.push(column);
      column = [];
    }
  }
  if (column.length > 0) {
    while (column.length < WEEKDAY_ROWS) {
      column.push(null);
    }
    columns.push(column);
  }
  return columns;
}

export type AiHealthState = "healthy" | "degraded" | "quiet";

/** A provider's last-5h window, summed; the table words each state. */
export interface AiHealthReading {
  state: AiHealthState;
  requests: number;
  failed: number;
}

/** Sum the last-5h health window into one state. */
export function readHealth(health: AiUsageHealthBucket[]): AiHealthReading {
  let requests = 0;
  let failed = 0;
  for (const slot of health) {
    requests += slot.requests;
    failed += slot.failed;
  }
  const state: AiHealthState =
    requests === 0 ? "quiet" : failed === 0 ? "healthy" : "degraded";
  return { state, requests, failed };
}
