import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import {
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  describeError,
} from "../api_client";
import { useApiResource } from "../use_api_resource";
import type {
  AiProviderView,
  AiProvidersResponse,
  CliproxyStatusView,
} from "../api_types";

import "./ai_page.css";

/**
 * The AI gateway: one endpoint every machine's AI tools point at, forever.
 *
 * CLIProxyAPI does the actual serving; this page manages what the panel owns
 * around it — which providers it forwards to, the keys devices use, and the
 * apply that re-renders its configuration. Switching providers here takes
 * effect on every connected machine at once.
 */

export function AiPage() {
  const resource = useApiResource<CliproxyStatusView>("/cliproxy");
  const [view, setView] = useState<CliproxyStatusView | null>(null);
  const [providers, setProviders] = useState<AiProviderView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [keyName, setKeyName] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setView(resource.data);
    }
  }, [resource.data]);

  useEffect(() => {
    let isCancelled = false;
    apiGet<AiProvidersResponse>("/credentials/ai_providers")
      .then((response) => {
        if (!isCancelled) {
          setProviders(response.providers);
        }
      })
      .catch(() => {
        // The section shows its own hint when the list stays empty.
      });
    return () => {
      isCancelled = true;
    };
  }, []);

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
            Install the cliproxy module from Services.
          </span>
        </div>
      </div>
    );
  }

  const endpoint = `http://${window.location.hostname}:${view.listen_port}`;

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

  const handleToggleProvider = (provider: AiProviderView) => {
    void run(async () => {
      const updated = await apiPut<AiProviderView>(
        `/credentials/ai_providers/${provider.id}`,
        { is_enabled: !provider.is_enabled },
      );
      setProviders((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry)),
      );
      await apiPost("/cliproxy/apply");
      setView(await apiGet<CliproxyStatusView>("/cliproxy"));
    });
  };

  const handleApply = () => {
    setApplyMessage(null);
    void run(async () => {
      const result = await apiPost<{ message: string }>("/cliproxy/apply");
      setApplyMessage(result.message);
      setView(await apiGet<CliproxyStatusView>("/cliproxy"));
    });
  };

  const handleMintKey = () => {
    void run(async () => {
      setView(
        await apiPost<CliproxyStatusView>("/cliproxy/keys", {
          name: keyName.trim() || "device",
        }),
      );
      setKeyName("");
    });
  };

  const handleDeleteKey = (keyId: string, name: string) => {
    if (!window.confirm(`Revoke "${name}"? Whatever uses it stops working.`)) {
      return;
    }
    void run(async () => {
      setView(await apiDelete<CliproxyStatusView>(`/cliproxy/keys/${keyId}`));
    });
  };

  return (
    <div className="page ai_page">
      <header className="page_header">
        <div>
          <h1 className="page_title">AI</h1>
          <p className="page_subtitle">
            One endpoint for every machine&apos;s AI tools; which provider
            answers is switched here.
          </p>
        </div>
        <div className="page_actions">
          <button
            type="button"
            className="button button--primary"
            disabled={isBusy}
            onClick={handleApply}
          >
            <Icon name="refresh" size={14} />
            Apply
          </button>
        </div>
      </header>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      {applyMessage !== null && (
        <div className="notice">
          <Icon name="check" size={15} />
          <div className="notice_body">{applyMessage}</div>
        </div>
      )}

      <section className="settings_group">
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
          </span>
        </div>
        <p className="field_hint">
          {view.is_reachable
            ? `Serving: ${view.probe_message}`
            : view.probe_message.length > 0
              ? view.probe_message
              : "Waiting for the first probe."}
        </p>
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>Providers</h2>
        </div>
        <p className="field_hint">
          Click to switch a provider on or off; edits happen on the{" "}
          <Link to="/credentials">Credentials</Link> page. Off is instant on
          every machine.
        </p>
        {providers.length === 0 ? (
          <span className="ai_service_hint">
            No providers stored yet — add one on the Credentials page.
          </span>
        ) : (
          <div className="ai_service_chips">
            {providers.map((provider) => (
              <button
                key={provider.id}
                type="button"
                className={`ai_chip ${provider.is_enabled ? "ai_chip--on" : ""}`}
                disabled={isBusy}
                title={`${provider.kind} · ${
                  provider.base_url.length > 0
                    ? provider.base_url
                    : "default endpoint"
                }`}
                onClick={() => handleToggleProvider(provider)}
              >
                {provider.name}
              </button>
            ))}
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
            <div key={key.id} className="ai_key_row">
              <span className="ai_key_name">{key.name}</span>
              <span className="ai_key_value">{key.key}</span>
              <button
                type="button"
                className="file_modal_action"
                title="Copy"
                onClick={() => void navigator.clipboard.writeText(key.key)}
              >
                <Icon name="file" size={13} />
              </button>
              <button
                type="button"
                className="file_modal_action file_modal_action--danger"
                title="Revoke"
                disabled={isBusy}
                onClick={() => handleDeleteKey(key.id, key.name)}
              >
                <Icon name="trash" size={13} />
              </button>
            </div>
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
      await navigator.clipboard.writeText(value);
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
