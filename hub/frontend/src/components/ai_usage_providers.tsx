import { useState } from "react";

import {
  cacheShareOf,
  formatBucketLabel,
  formatShare,
  readHealth,
  successShareOf,
  tokensOf,
} from "../ai_usage";
import { formatCompact } from "../format_compact";
import { formatTimeAgo } from "../format_duration";
import type {
  AiProviderKind,
  AiUsageHealthBucket,
  AiUsageProvider,
} from "../api_types";

/**
 * The upstream activity table on the AI page: one row per keyed provider and
 * per subscription account, filtered by kind, sorted and paged. An account
 * wears a pill saying so, because its kind alone reads like a provider's.
 * Styles live in ai_page.css beside the page.
 */

const WORDING = {
  allKinds: "All",
  account: "account",
  headerProvider: "Provider",
  headerRequests: "Requests",
  headerSuccess: "Success",
  headerTokens: "Tokens",
  headerCache: "Cache",
  headerHealth: "Last 5h",
  headerSeen: "Seen",
  healthWords: {
    healthy: "Healthy",
    degraded: "Degraded",
    quiet: "Quiet",
  },
  healthyPhrase: "no failures in 5h",
  quietPhrase: "no requests in 5h",
  degradedPhrase: (failed: number) => `${failed} failed in 5h`,
  firstSeen: "first",
  lastSeen: "last",
  okWord: "ok",
  failedWord: "failed",
  noRequests: "no requests",
  sort: "Sort",
  size: "Size",
  previous: "Previous",
  next: "Next",
  sortRequests: "Requests",
  sortTokens: "Tokens",
  sortSuccess: "Success rate",
  sortName: "Name",
  empty: "No provider activity yet",
  emptyHint: "Rows appear once the gateway forwards a request.",
} as const;

type SortKey = "requests" | "tokens" | "success" | "name";

const SORT_LABELS: Record<SortKey, string> = {
  requests: WORDING.sortRequests,
  tokens: WORDING.sortTokens,
  success: WORDING.sortSuccess,
  name: WORDING.sortName,
};

const SORT_KEYS: SortKey[] = ["requests", "tokens", "success", "name"];
const PAGE_SIZES = [10, 25, 50];
const KIND_ORDER: AiProviderKind[] = [
  "anthropic",
  "openai",
  "gemini",
  "custom",
];
// An account's kind is its service, which is not one of the provider kinds,
// so membership decides the chip order rather than the type.
const PROVIDER_KINDS = new Set<string>(KIND_ORDER);

// Above this share of failures a health slot turns red instead of amber.
const FAILING_SHARE = 0.5;
const HEALTH_SLOT_MAX_PX = 18;
const HEALTH_SLOT_MIN_PX = 4;
const HEALTH_SLOT_IDLE_PX = 3;

interface AiUsageProvidersProps {
  providers: AiUsageProvider[];
}

export function AiUsageProviders({ providers }: AiUsageProvidersProps) {
  const [kind, setKind] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("requests");
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0] ?? 10);
  const [page, setPage] = useState(0);

  if (providers.length === 0) {
    return (
      <div className="placeholder">
        <span>{WORDING.empty}</span>
        <span className="faint">{WORDING.emptyHint}</span>
      </div>
    );
  }

  const filtered = providers.filter(
    (provider) => kind === "all" || provider.kind === kind,
  );
  const sorted = sortProviders(filtered, sortKey);
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const rows = sorted.slice(
    currentPage * pageSize,
    (currentPage + 1) * pageSize,
  );

  return (
    <div className="usage_table_block">
      <div className="ai_service_chips">
        <button
          type="button"
          className={`ai_chip ${kind === "all" ? "ai_chip--on" : ""}`}
          onClick={() => {
            setKind("all");
            setPage(0);
          }}
        >
          {WORDING.allKinds}
          <span className="ai_chip_count">{providers.length}</span>
        </button>
        {kindsOf(providers).map((option) => {
          const count = providers.filter(
            (provider) => provider.kind === option,
          ).length;
          if (count === 0) {
            return null;
          }
          return (
            <button
              key={option}
              type="button"
              className={`ai_chip ${kind === option ? "ai_chip--on" : ""}`}
              onClick={() => {
                setKind(option);
                setPage(0);
              }}
            >
              {option}
              <span className="ai_chip_count">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="usage_table_scroll">
        <table className="usage_table">
          <thead>
            <tr>
              <th>{WORDING.headerProvider}</th>
              <th className="num">{WORDING.headerRequests}</th>
              <th className="num">{WORDING.headerSuccess}</th>
              <th className="num">{WORDING.headerTokens}</th>
              <th className="num">{WORDING.headerCache}</th>
              <th>{WORDING.headerHealth}</th>
              <th>{WORDING.headerSeen}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((provider) => (
              <ProviderRow key={provider.provider_id} provider={provider} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="usage_table_foot">
        <label className="usage_table_control">
          <span className="faint">{WORDING.sort}</span>
          <select
            className="select"
            value={sortKey}
            onChange={(event) => {
              setSortKey(event.target.value as SortKey);
              setPage(0);
            }}
          >
            {SORT_KEYS.map((option) => (
              <option key={option} value={option}>
                {SORT_LABELS[option]}
              </option>
            ))}
          </select>
        </label>
        <label className="usage_table_control">
          <span className="faint">{WORDING.size}</span>
          <select
            className="select"
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(0);
            }}
          >
            {PAGE_SIZES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="usage_table_pager">
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            {WORDING.previous}
          </button>
          <span className="mono muted">
            {currentPage + 1}/{pageCount}
          </span>
          <button
            type="button"
            className="button button--ghost button--small"
            disabled={currentPage >= pageCount - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            {WORDING.next}
          </button>
        </div>
      </div>
    </div>
  );
}

interface ProviderRowProps {
  provider: AiUsageProvider;
}

function ProviderRow({ provider }: ProviderRowProps) {
  const reading = readHealth(provider.health);
  const phrase =
    reading.state === "quiet"
      ? WORDING.quietPhrase
      : reading.state === "healthy"
        ? WORDING.healthyPhrase
        : WORDING.degradedPhrase(reading.failed);

  return (
    <tr>
      <td>
        <div className="usage_name">{provider.name}</div>
        <span className="usage_kinds">
          <span className="badge">{provider.kind}</span>
          {provider.is_account === true && (
            <span className="badge">{WORDING.account}</span>
          )}
        </span>
      </td>
      <td className="num">
        <div className="mono">{formatCompact(provider.requests)}</div>
        <div className="usage_split mono">
          <span className="usage_ok">
            {formatCompact(provider.requests - provider.failed)}
          </span>
          <span className="faint">/</span>
          <span className={provider.failed > 0 ? "usage_bad" : "faint"}>
            {formatCompact(provider.failed)}
          </span>
        </div>
      </td>
      <td className="num mono">
        <span className={successClass(successShareOf(provider))}>
          {formatShare(successShareOf(provider))}
        </span>
      </td>
      <td className="num mono">{formatCompact(tokensOf(provider))}</td>
      <td className="num mono">{formatShare(cacheShareOf(provider))}</td>
      <td>
        <div className="usage_health">
          <HealthBar health={provider.health} />
          <div className="usage_health_text">
            <span
              className={`usage_health_word usage_health_word--${reading.state}`}
            >
              {WORDING.healthWords[reading.state]}
            </span>
            <span className="faint">{phrase}</span>
          </div>
        </div>
      </td>
      <td>
        <div className="usage_seen mono">
          <span>
            {WORDING.firstSeen} {formatTimeAgo(provider.first_seen_at)}
          </span>
          <span>
            {WORDING.lastSeen} {formatTimeAgo(provider.last_seen_at)}
          </span>
        </div>
      </td>
    </tr>
  );
}

interface HealthBarProps {
  health: AiUsageHealthBucket[];
}

function HealthBar({ health }: HealthBarProps) {
  if (health.length === 0) {
    return <span className="faint mono">—</span>;
  }
  const highest = Math.max(...health.map((slot) => slot.requests), 1);
  return (
    <div className="usage_health_bar">
      {health.map((slot) => {
        const state =
          slot.requests === 0
            ? "idle"
            : slot.failed === 0
              ? "ok"
              : slot.failed / slot.requests > FAILING_SHARE
                ? "error"
                : "warn";
        const height =
          slot.requests === 0
            ? HEALTH_SLOT_IDLE_PX
            : Math.max(
                HEALTH_SLOT_MIN_PX,
                Math.round((slot.requests / highest) * HEALTH_SLOT_MAX_PX),
              );
        const outcome =
          slot.requests === 0
            ? WORDING.noRequests
            : `${slot.requests - slot.failed} ${WORDING.okWord} · ${slot.failed} ${WORDING.failedWord}`;
        return (
          <span
            key={slot.bucket}
            className={`usage_health_slot usage_health_slot--${state}`}
            style={{ height }}
            title={`${formatBucketLabel(slot.bucket, "day")} · ${outcome}`}
          />
        );
      })}
    </div>
  );
}

/** The kinds present, provider kinds in their fixed order and accounts after. */
function kindsOf(list: AiUsageProvider[]): string[] {
  const present = new Set(list.map((entry) => entry.kind));
  return [
    ...KIND_ORDER.filter((option) => present.has(option)),
    ...[...present].filter((option) => !PROVIDER_KINDS.has(option)).sort(),
  ];
}

function sortProviders(
  list: AiUsageProvider[],
  key: SortKey,
): AiUsageProvider[] {
  const sorted = [...list];
  if (key === "name") {
    sorted.sort((a, b) => a.name.localeCompare(b.name));
  } else if (key === "tokens") {
    sorted.sort((a, b) => tokensOf(b) - tokensOf(a));
  } else if (key === "success") {
    sorted.sort(
      (a, b) => (successShareOf(b) ?? -1) - (successShareOf(a) ?? -1),
    );
  } else {
    sorted.sort((a, b) => b.requests - a.requests);
  }
  return sorted;
}

function successClass(share: number | null): string {
  if (share === null) {
    return "muted";
  }
  if (share >= 0.99) {
    return "usage_ok";
  }
  if (share >= 0.9) {
    return "usage_warn";
  }
  return "usage_bad";
}
