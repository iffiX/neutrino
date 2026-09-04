import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { AiJournalPanel } from "../components/ai_journal_panel";
import { AiProvidersSection } from "../components/ai_providers_section";
import { AiUsageKeys } from "../components/ai_usage_keys";
import { AiUsageProviders } from "../components/ai_usage_providers";
import { ApplyBar } from "../components/apply_bar";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import { usePolledResource } from "../use_polled_resource";
import { useConfirm } from "../use_confirm";
import type {
  AiUsageResponse,
  CliproxyApiKeyView,
  CliproxyApiStatusView,
} from "../api_types";

import "./ai_page.css";

/**
 * The AI gateway: one endpoint every machine's AI tools point at, forever.
 *
 * CLIProxyAPI does the actual serving; this page manages what the panel owns
 * around it — which providers it forwards to, the keys devices use, and the
 * apply that re-renders its configuration. Switching providers here takes
 * effect on every connected machine at once. The activity tables read the
 * same usage feed the dashboard summarises.
 */

const WORDING = {
  journal: "Journal",
  live: "live",
  listenPort: "Listen port",
  portFieldHint: "Every connected machine reaches the gateway on this port.",
  portApplyLabel: "Apply port",
  portApplyHint:
    "Restarts the gateway on the new port; every machine's endpoint moves with it.",
  portRangeHint: (low: number, high: number) => `A port is ${low} to ${high}.`,
  providerActivity: "Provider activity",
  keyActivity: "Key activity",
  usageWindow: "last 30 days",
  usageUnavailable: "Usage unavailable",
  usageUnavailableHint: "The gateway is not reporting usage on this box yet.",
  revealKey: "Reveal",
  hideKey: "Hide",
} as const;

const PORT_MIN = 1;
const PORT_MAX = 65535;
const USAGE_PATH = "/cliproxyapi/usage?range=month";
const MASKED_KEY = "•".repeat(24);

export function AiPage() {
  const resource = useApiResource<CliproxyApiStatusView>("/cliproxyapi");
  const [view, setView] = useState<CliproxyApiStatusView | null>(null);
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [keyName, setKeyName] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [port, setPort] = useState<number | null>(null);
  const [isJournalOpen, setIsJournalOpen] = useState(false);
  const usage = usePolledResource<AiUsageResponse>(
    view !== null && view.is_installed ? USAGE_PATH : null,
  );

  useEffect(() => {
    if (resource.data !== null) {
      setView(resource.data);
      setPort(resource.data.listen_port);
    }
  }, [resource.data]);

  if (resource.error !== null && view === null) {
    return (
      <div className="page">
        <h1>AI</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }
  if (view === null) {
    return (
      <div className="page">
        <h1>AI</h1>
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }
  if (!view.is_installed) {
    return (
      <div className="page">
        <h1>AI</h1>
        <div className="placeholder">
          <span>The AI gateway is not installed</span>
          <span className="faint">
            Install the cliproxyapi module from Services.
          </span>
        </div>
      </div>
    );
  }

  const endpoint = `http://${window.location.hostname}:${view.listen_port}`;
  const isPortDirty = port !== null && port !== view.listen_port;
  const isPortValid = port !== null && port >= PORT_MIN && port <= PORT_MAX;

  const run = async (work: () => Promise<void>) => {
    setIsBusy(true);
    setError(null);
    try {
      await work();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleApplyPort = () => {
    void run(async () => {
      setView(
        await apiPut<CliproxyApiStatusView>("/cliproxyapi", {
          listen_port: port,
        }),
      );
    });
  };

  const handleMintKey = () => {
    void run(async () => {
      setView(
        await apiPost<CliproxyApiStatusView>("/cliproxyapi/keys", {
          name: keyName.trim() || "device",
        }),
      );
      setKeyName("");
    });
  };

  const handleDeleteKey = (keyId: string, name: string) =>
    confirm.ask({
      title: `Revoke ${name}`,
      body: "Whatever is using this key stops working at once.",
      confirmLabel: "Revoke",
      onConfirm: () => void deleteKey(keyId),
    });

  const deleteKey = (keyId: string) => {
    void run(async () => {
      setView(
        await apiDelete<CliproxyApiStatusView>(`/cliproxyapi/keys/${keyId}`),
      );
    });
  };

  return (
    <div className="page ai_page">
      <header className="page_header">
        <div>
          <div className="page_title_row">
            <h1 className="page_title">AI</h1>
          </div>
          <p className="page_subtitle">
            One endpoint for every machine&apos;s AI tools; which provider
            answers is switched here.
          </p>
        </div>
      </header>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      <section
        className={`settings_group ${isPortDirty ? "settings_group--dirty" : ""}`}
      >
        <div className="settings_group_title">
          <h2>Gateway</h2>
          <span className="ai_status_row">
            <StatusDot
              tone={view.is_active ? "ok" : "error"}
              label={view.is_active ? "running" : "stopped"}
            />
            <StatusDot
              tone={view.is_reachable ? "ok" : "warn"}
              label={view.is_reachable ? "answering" : "not answering"}
            />
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
          </span>
        </div>
        <p className="field_hint">
          {view.is_reachable
            ? `Serving: ${view.probe_message}`
            : view.probe_message.length > 0
              ? view.probe_message
              : "Waiting for the first probe."}
        </p>
        <div className="field_grid">
          <label className="field">
            <span className="field_label">{WORDING.listenPort}</span>
            <input
              className="input"
              inputMode="numeric"
              value={port === null ? "" : String(port)}
              onChange={(event) => setPort(Number(event.target.value) || 0)}
            />
            <span className="field_hint">{WORDING.portFieldHint}</span>
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
          onReset={() => setPort(view.listen_port)}
          onApply={handleApplyPort}
        />
        <AiJournalPanel isOpen={isJournalOpen} />
      </section>

      <AiProvidersSection
        isServingStale={view.is_serving_stale ?? false}
        onApplied={resource.reload}
      />

      <section className="card">
        <div className="card_header">
          <div className="card_title">
            <h2>{WORDING.providerActivity}</h2>
            <span className="badge">{WORDING.usageWindow}</span>
            {usage.data !== null && (
              <StatusDot tone="ok" isPulsing label={WORDING.live} />
            )}
          </div>
        </div>
        {usage.data !== null ? (
          <AiUsageProviders providers={usage.data.providers} />
        ) : usage.isLoading ? (
          <div className="skeleton" style={{ height: 160 }} />
        ) : (
          <div className="placeholder">
            <span>{WORDING.usageUnavailable}</span>
            <span className="faint">{WORDING.usageUnavailableHint}</span>
          </div>
        )}
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>Connect a machine</h2>
        </div>
        <p className="field_hint">
          Point a tool at the endpoint with one of these keys as its API key —
          Claude Code, Codex and Gemini CLI all speak to the same address.
        </p>
        <CopyRow label="Endpoint" value={endpoint} />
        <div className="ai_keys">
          {view.client_keys.map((key) => (
            <KeyRow
              key={key.id}
              value={key}
              isBusy={isBusy}
              onDelete={() => handleDeleteKey(key.id, key.name)}
            />
          ))}
        </div>
        <div className="ai_key_add">
          <input
            className="input"
            placeholder="key name, e.g. laptop"
            value={keyName}
            onChange={(event) => setKeyName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                handleMintKey();
              }
            }}
          />
          <button
            type="button"
            className="button"
            disabled={isBusy}
            onClick={handleMintKey}
          >
            <Icon name="plus" size={14} />
            Mint key
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card_header">
          <div className="card_title">
            <h2>{WORDING.keyActivity}</h2>
            <span className="badge">{WORDING.usageWindow}</span>
            {usage.data !== null && (
              <StatusDot tone="ok" isPulsing label={WORDING.live} />
            )}
          </div>
        </div>
        {usage.data !== null ? (
          <AiUsageKeys keys={usage.data.keys} />
        ) : usage.isLoading ? (
          <div className="skeleton" style={{ height: 120 }} />
        ) : (
          <div className="placeholder">
            <span>{WORDING.usageUnavailable}</span>
            <span className="faint">{WORDING.usageUnavailableHint}</span>
          </div>
        )}
      </section>
      {confirm.modal}
    </div>
  );
}

interface KeyRowProps {
  value: CliproxyApiKeyView;
  isBusy: boolean;
  onDelete: () => void;
}

function KeyRow({ value, isBusy, onDelete }: KeyRowProps) {
  const [isRevealed, setIsRevealed] = useState(false);

  return (
    <div className="ai_key_row">
      <span className="ai_key_name">{value.name}</span>
      <span className="ai_key_value">
        {isRevealed ? value.key : MASKED_KEY}
      </span>
      <button
        type="button"
        className="file_modal_action"
        title={isRevealed ? WORDING.hideKey : WORDING.revealKey}
        onClick={() => setIsRevealed((current) => !current)}
      >
        <Icon name={isRevealed ? "eye_off" : "eye"} size={13} />
      </button>
      <button
        type="button"
        className="file_modal_action"
        title="Copy"
        onClick={() => void copyText(value.key)}
      >
        <Icon name="file" size={13} />
      </button>
      <button
        type="button"
        className="file_modal_action file_modal_action--danger"
        title="Revoke"
        disabled={isBusy}
        onClick={onDelete}
      >
        <Icon name="trash" size={13} />
      </button>
    </div>
  );
}

interface CopyRowProps {
  label: string;
  value: string;
}

function CopyRow({ label, value }: CopyRowProps) {
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await copyText(value);
      setIsCopied(true);
      window.setTimeout(() => setIsCopied(false), 1600);
    } catch {
      // The value is visible; copying by hand still works.
    }
  };

  return (
    <div className="ai_copy_row">
      <span className="ai_copy_label">{label}</span>
      <span className="ai_copy_value">{value}</span>
      <button
        type="button"
        className="button button--small"
        onClick={() => void handleCopy()}
      >
        <Icon name={isCopied ? "check" : "file"} size={13} />
        {isCopied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
