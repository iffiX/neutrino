import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { AiProvidersSection } from "../components/ai_providers_section";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { StatusDot } from "../components/status_dot";
import { apiDelete, apiGet, apiPost, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type { CliproxyApiStatusView } from "../api_types";

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
  const resource = useApiResource<CliproxyApiStatusView>("/cliproxyapi");
  const [view, setView] = useState<CliproxyApiStatusView | null>(null);
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [keyName, setKeyName] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    if (resource.data !== null) {
      setView(resource.data);
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

  const handleApply = () => {
    setApplyMessage(null);
    void run(async () => {
      const result = await apiPost<{ message: string }>("/cliproxyapi/apply");
      setApplyMessage(result.message);
      setView(await apiGet<CliproxyApiStatusView>("/cliproxyapi"));
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

      <AiProvidersSection />

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
                onClick={() => void copyText(key.key)}
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
      {confirm.modal}
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
