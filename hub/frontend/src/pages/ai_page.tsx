import { useEffect, useState } from "react";

import { AiAccessPanel } from "../components/ai_access_panel";
import { AiAccountsPanel } from "../components/ai_accounts_panel";
import { AiJournalPanel } from "../components/ai_journal_panel";
import { AiProvidersSection } from "../components/ai_providers_section";
import { AiUsageKeys } from "../components/ai_usage_keys";
import { AiUsageProviders } from "../components/ai_usage_providers";
import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import { apiPut, describeError } from "../api_client";
import { copyText } from "../copy_text";
import { formatCompact } from "../format_compact";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_AI_USAGE, HUB_EVENT_CONFIG } from "../use_hub_events";
import type { AiUsageResponse, CliproxyApiStatusView } from "../api_types";

import "./ai_page.css";

/**
 * The AI gateway: one endpoint every machine's AI tools point at, forever.
 *
 * CLIProxyAPI does the actual serving; this page manages what the panel owns
 * around it — what the gateway is doing right now, which providers it forwards
 * to, the keys machines reach it with, and the port it answers on. Each of
 * those is its own panel, and the ones that change something carry their own
 * apply. The activity tables read the same usage feed the dashboard
 * summarises.
 */

const WORDING = {
  title: "AI",
  subtitle:
    "One endpoint for every machine's AI tools; which provider answers is switched here.",
  notInstalled: "The AI gateway is not installed",
  notInstalledHint: "Install the cliproxyapi module from Services.",

  activity: "Activity",
  running: "running",
  stopped: "stopped",
  answering: "answering",
  notAnswering: "not answering",
  journal: "Journal",
  serving: (message: string) => `Serving: ${message}`,
  servingCount: (count: number) => `Serving ${count} models`,
  copied: "copied",
  copyModel: "Copy the name",
  waitingProbe: "Waiting for the first probe.",
  requestsToday: "requests today",
  tokensToday: "tokens today",
  viewProviders: "Providers",
  viewKeys: "Keys",
  usageWindow: "last 30 days",
  usageUnavailable: "Usage unavailable",
  usageUnavailableHint: "The gateway is not reporting usage on this box yet.",

  gatewayPort: "Gateway port",
  gatewayPortHint: "The TCP port the gateway answers on.",
  port: "Port",
  reachedAt: (origin: string) => `Reached at ${origin}.`,
  movesTo: (origin: string) => `Moves to ${origin}.`,
  portApplyLabel: "Apply gateway port",
  portApplyHint: "Restarts the gateway on the new port.",
  portApplyWarning:
    "Every machine pointed at the old port stops reaching the gateway until its endpoint is changed too.",
  portRangeHint: (low: number, high: number) => `A port is ${low} to ${high}.`,
} as const;

const PORT_MIN = 1;
const PORT_MAX = 65535;
const STATUS_PATH = "/cliproxyapi";
const USAGE_PATH = "/cliproxyapi/usage?range=month";
// What moves the gateway's own state and its numbers: the collector saying
// the counters or the served list changed, and any write to its settings.
const AI_INVALIDATE_ON = [
  { type: HUB_EVENT_AI_USAGE },
  { type: HUB_EVENT_CONFIG },
];

/** Which half of the usage area the chips are showing. */
type UsageView = "providers" | "keys";

const COPIED_FLASH_MS = 1200;

interface ModelFamily {
  name: string;
  models: string[];
}

/** Group served names by their first dash-separated word, largest first. */
function toModelFamilies(models: string[]): ModelFamily[] {
  const byFamily = new Map<string, string[]>();
  for (const model of models) {
    const family = model.split("-")[0] ?? model;
    byFamily.set(family, [...(byFamily.get(family) ?? []), model]);
  }
  return [...byFamily.entries()]
    .map(([name, names]) => ({ name, models: [...names].sort() }))
    .sort((a, b) => b.models.length - a.models.length);
}

export function AiPage() {
  const status = useApiResource<CliproxyApiStatusView>(STATUS_PATH, {
    invalidateOn: AI_INVALIDATE_ON,
  });
  const view = status.data;
  const [portError, setPortError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [port, setPort] = useState<number | null>(null);
  const [isJournalOpen, setIsJournalOpen] = useState(false);
  const [isServingOpen, setIsServingOpen] = useState(false);
  const [copiedModel, setCopiedModel] = useState<string | null>(null);
  const [usageView, setUsageView] = useState<UsageView>("providers");
  const isInstalled = view !== null && view.is_installed;
  const usage = useApiResource<AiUsageResponse>(
    isInstalled ? USAGE_PATH : null,
    { invalidateOn: AI_INVALIDATE_ON },
  );
  const listenPort = view?.listen_port ?? null;

  // Seeded once: a refresh landing while somebody is typing a port must not
  // take the field back.
  useEffect(() => {
    setPort((current) => (current === null ? listenPort : current));
  }, [listenPort]);

  if (status.error !== null && view === null) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <ErrorPanel message={status.error} onRetry={status.reload} />
      </div>
    );
  }
  if (view === null) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }
  if (!view.is_installed) {
    return (
      <div className="page">
        <h1>{WORDING.title}</h1>
        <div className="placeholder">
          <span>{WORDING.notInstalled}</span>
          <span className="faint">{WORDING.notInstalledHint}</span>
        </div>
      </div>
    );
  }

  const endpoint = originWith(view.listen_port);
  const isPortDirty = port !== null && port !== view.listen_port;
  const isPortValid = port !== null && port >= PORT_MIN && port <= PORT_MAX;
  const hasToday =
    view.requests_today !== undefined || view.tokens_today !== undefined;
  const servedModels = view.served_models ?? [];
  const servedFamilies = toModelFamilies(servedModels);

  const handleCopyModel = async (name: string) => {
    await copyText(name);
    setCopiedModel(name);
    window.setTimeout(
      () => setCopiedModel((current) => (current === name ? null : current)),
      COPIED_FLASH_MS,
    );
  };

  const handleApplyPort = async () => {
    setIsBusy(true);
    setPortError(null);
    try {
      status.setData(
        await apiPut<CliproxyApiStatusView>(STATUS_PATH, {
          listen_port: port,
        }),
      );
    } catch (cause: unknown) {
      setPortError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="page ai_page">
      <header className="page_header">
        <div>
          <div className="page_title_row">
            <h1 className="page_title">{WORDING.title}</h1>
          </div>
          <p className="page_subtitle">{WORDING.subtitle}</p>
        </div>
      </header>

      <section className="card">
        <div className="card_header">
          <div className="ai_activity_head">
            <div className="card_title">
              <h2>{WORDING.activity}</h2>
              <StatusDot
                tone={view.is_active ? "ok" : "error"}
                label={view.is_active ? WORDING.running : WORDING.stopped}
              />
              <StatusDot
                tone={view.is_reachable ? "ok" : "warn"}
                label={
                  view.is_reachable ? WORDING.answering : WORDING.notAnswering
                }
              />
            </div>
            {servedFamilies.length > 0 ? (
              <div className="ai_serving field_hint ai_probe">
                <span>{WORDING.servingCount(servedModels.length)}</span>
                {servedFamilies.map((family) => (
                  <span key={family.name} className="badge">
                    {family.name}
                    <span className="ai_chip_count">
                      {family.models.length}
                    </span>
                  </span>
                ))}
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() => setIsServingOpen((isOpen) => !isOpen)}
                >
                  <Icon
                    name={isServingOpen ? "chevron_down" : "chevron_right"}
                    size={13}
                  />
                </button>
              </div>
            ) : (
              <p className="field_hint ai_probe">
                {view.is_reachable
                  ? WORDING.serving(view.probe_message)
                  : view.probe_message.length > 0
                    ? view.probe_message
                    : WORDING.waitingProbe}
              </p>
            )}
          </div>
          <div className="ai_activity_actions">
            {hasToday && (
              <span className="ai_today">
                <span className="ai_today_item">
                  <span className="ai_today_value mono">
                    {formatCompact(view.requests_today ?? 0)}
                  </span>
                  <span className="ai_today_label">
                    {WORDING.requestsToday}
                  </span>
                </span>
                <span className="ai_today_item">
                  <span className="ai_today_value mono">
                    {formatCompact(view.tokens_today ?? 0)}
                  </span>
                  <span className="ai_today_label">{WORDING.tokensToday}</span>
                </span>
              </span>
            )}
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => setIsJournalOpen((isOpen) => !isOpen)}
            >
              <Icon
                name={isJournalOpen ? "chevron_down" : "chevron_right"}
                size={13}
              />
              {WORDING.journal}
            </button>
          </div>
        </div>

        {isServingOpen && servedFamilies.length > 0 && (
          <div className="ai_serving_groups">
            {servedFamilies.map((family) => (
              <div key={family.name} className="ai_serving_group">
                <span className="ai_serving_family">{family.name}</span>
                <div className="ai_serving_pills">
                  {family.models.map((model) => (
                    <button
                      key={model}
                      type="button"
                      className="ai_model_pill mono"
                      title={WORDING.copyModel}
                      onClick={() => void handleCopyModel(model)}
                    >
                      {copiedModel === model ? WORDING.copied : model}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="ai_usage_switch">
          <div className="ai_service_chips">
            <button
              type="button"
              className={`ai_chip ${usageView === "providers" ? "ai_chip--on" : ""}`}
              onClick={() => setUsageView("providers")}
            >
              {WORDING.viewProviders}
              {usage.data !== null && (
                <span className="ai_chip_count">
                  {usage.data.providers.length}
                </span>
              )}
            </button>
            <button
              type="button"
              className={`ai_chip ${usageView === "keys" ? "ai_chip--on" : ""}`}
              onClick={() => setUsageView("keys")}
            >
              {WORDING.viewKeys}
              {usage.data !== null && (
                <span className="ai_chip_count">{usage.data.keys.length}</span>
              )}
            </button>
          </div>
          <span className="ai_usage_window">
            <span className="badge">{WORDING.usageWindow}</span>
          </span>
        </div>

        {usage.data !== null ? (
          usageView === "providers" ? (
            <AiUsageProviders providers={usage.data.providers} />
          ) : (
            <AiUsageKeys keys={usage.data.keys} />
          )
        ) : usage.isLoading ? (
          <div className="skeleton" style={{ height: 180 }} />
        ) : (
          <div className="placeholder">
            <span>{WORDING.usageUnavailable}</span>
            <span className="faint">{WORDING.usageUnavailableHint}</span>
          </div>
        )}

        <AiJournalPanel isOpen={isJournalOpen} />
      </section>

      <AiProvidersSection
        isServingStale={view.is_serving_stale ?? false}
        onApplied={status.reload}
      />

      <AiAccountsPanel />

      <AiAccessPanel
        endpoint={endpoint}
        keys={view.client_keys}
        usageKeys={usage.data?.keys ?? []}
        onChanged={status.setData}
      />

      <section
        className={`settings_group ${isPortDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>{WORDING.gatewayPort}</h2>
        </div>
        <p className="field_hint">{WORDING.gatewayPortHint}</p>
        <div className="field_grid">
          <label className="field">
            <span className="field_label">{WORDING.port}</span>
            <input
              className="input"
              inputMode="numeric"
              value={port === null ? "" : String(port)}
              onChange={(event) => setPort(Number(event.target.value) || 0)}
            />
            <span className="field_hint">
              {isPortDirty
                ? WORDING.movesTo(originWith(port ?? 0))
                : WORDING.reachedAt(endpoint)}
            </span>
          </label>
        </div>
        <ApplyBar
          isDirty={isPortDirty && isPortValid}
          isBusy={isBusy}
          label={WORDING.portApplyLabel}
          hint={
            isPortValid
              ? WORDING.portApplyHint
              : WORDING.portRangeHint(PORT_MIN, PORT_MAX)
          }
          warning={WORDING.portApplyWarning}
          error={portError}
          onReset={() => setPort(view.listen_port)}
          onApply={() => void handleApplyPort()}
        />
      </section>
    </div>
  );
}

function originWith(port: number): string {
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}
