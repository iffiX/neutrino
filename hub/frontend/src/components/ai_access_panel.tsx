import { useState } from "react";

import { Icon } from "./icon";
import { apiDelete, apiPost, describeError } from "../api_client";
import { copyText } from "../copy_text";
import { formatTimeAgo } from "../format_duration";
import { useConfirm } from "../use_confirm";
import type {
  AiUsageKey,
  CliproxyApiKeyView,
  CliproxyApiStatusView,
} from "../api_types";

import "./ai_access_panel.css";

/**
 * The keys machines reach the gateway with.
 *
 * A managed device is handed its own key over the agent channel, so what is
 * distributed by hand here is the rest: a phone, a tablet, a laptop nobody
 * enrolled. The gateway generates these keys rather than being given them, so
 * each is shown to its owner — masked in the list, and expanded once at the
 * top the moment it is generated, which is when somebody is holding the
 * machine that needs it.
 *
 * Generating and revoking write where they are pressed: a revocation never
 * waits behind an apply bar.
 */

const WORDING = {
  title: "Access",
  hint: "Keys for machines no agent manages: a phone, a tablet, a laptop nobody enrolled. A managed device is handed its own key over the agent channel.",
  endpoint: "Endpoint",
  copy: "Copy",
  copied: "Copied",
  generateKey: "Generate key",
  generate: "Generate",
  cancel: "Cancel",
  namePlaceholder: "what will use it, e.g. laptop",
  defaultKeyName: "device",
  freshHint: "Paste it into the tool beside the endpoint above.",
  copyKey: "Copy key",
  dismiss: "Dismiss",
  reveal: "Reveal",
  hide: "Hide",
  revoke: "Revoke",
  neverUsed: "Never used",
  used: (ago: string) => `Used ${ago}`,
  revokeTitle: (name: string) => `Revoke ${name}`,
  revokeBody:
    "Whatever is using this key stops reaching the gateway at once, and needs a new one to get back in.",
  revokeDeviceBody: (device: string) =>
    `${device} stops reaching the gateway at once, and needs a new key to get back in.`,
  empty: "No keys yet",
  emptyHint: "Generate one for a machine that has no agent on it.",
} as const;

const KEYS_PATH = "/cliproxyapi/keys";
const MASKED_KEY = "•".repeat(24);
const COPIED_CLEAR_MS = 1600;

interface AiAccessPanelProps {
  /** Where the keys are pointed, shown as the copy row above them. */
  endpoint: string;
  keys: CliproxyApiKeyView[];
  /** The usage feed's per-key rows, for last-used and the owning device. */
  usageKeys: AiUsageKey[];
  /** The status view a generate or a revoke answered with. */
  onChanged: (view: CliproxyApiStatusView) => void;
}

export function AiAccessPanel({
  endpoint,
  keys,
  usageKeys,
  onChanged,
}: AiAccessPanelProps) {
  const confirm = useConfirm();
  const [isNaming, setIsNaming] = useState(false);
  const [name, setName] = useState("");
  const [freshKeyId, setFreshKeyId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usageByKeyId = new Map(usageKeys.map((entry) => [entry.key_id, entry]));
  const ordered =
    freshKeyId === null
      ? keys
      : [
          ...keys.filter((key) => key.id === freshKeyId),
          ...keys.filter((key) => key.id !== freshKeyId),
        ];

  const handleGenerate = async () => {
    setIsBusy(true);
    setError(null);
    try {
      const known = new Set(keys.map((key) => key.id));
      const next = await apiPost<CliproxyApiStatusView>(KEYS_PATH, {
        name: name.trim() || WORDING.defaultKeyName,
      });
      const created = next.client_keys.find((key) => !known.has(key.id));
      onChanged(next);
      setFreshKeyId(created?.id ?? null);
      setName("");
      setIsNaming(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setIsBusy(true);
    setError(null);
    try {
      onChanged(
        await apiDelete<CliproxyApiStatusView>(`${KEYS_PATH}/${keyId}`),
      );
      if (freshKeyId === keyId) {
        setFreshKeyId(null);
      }
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askRevoke = (value: CliproxyApiKeyView, deviceName: string | null) =>
    confirm.ask({
      title: WORDING.revokeTitle(value.name),
      body:
        deviceName === null
          ? WORDING.revokeBody
          : WORDING.revokeDeviceBody(deviceName),
      confirmLabel: WORDING.revoke,
      onConfirm: () => void handleRevoke(value.id),
    });

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{WORDING.title}</h2>
        {!isNaming && (
          <button
            type="button"
            className="button button--primary credentials_section_action"
            disabled={isBusy}
            onClick={() => setIsNaming(true)}
          >
            <Icon name="plus" size={14} />
            {WORDING.generateKey}
          </button>
        )}
      </div>
      <p className="field_hint">{WORDING.hint}</p>

      <CopyRow label={WORDING.endpoint} value={endpoint} />

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}

      {isNaming && (
        <div className="ai_key_add">
          <input
            className="input"
            placeholder={WORDING.namePlaceholder}
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void handleGenerate();
              }
            }}
          />
          <div className="ai_key_add_actions">
            <button
              type="button"
              className="button button--ghost"
              onClick={() => {
                setIsNaming(false);
                setName("");
              }}
            >
              {WORDING.cancel}
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy}
              onClick={() => void handleGenerate()}
            >
              <Icon name="check" size={14} />
              {WORDING.generate}
            </button>
          </div>
        </div>
      )}

      {keys.length === 0 ? (
        <div className="placeholder">
          <span>{WORDING.empty}</span>
          <span className="faint">{WORDING.emptyHint}</span>
        </div>
      ) : (
        <div className="ai_keys">
          {ordered.map((value) =>
            value.id === freshKeyId ? (
              <FreshKeyRow
                key={value.id}
                value={value}
                onDismiss={() => setFreshKeyId(null)}
              />
            ) : (
              <KeyRow
                key={value.id}
                value={value}
                usage={usageByKeyId.get(value.id) ?? null}
                isBusy={isBusy}
                onRevoke={() =>
                  askRevoke(
                    value,
                    usageByKeyId.get(value.id)?.device_name ?? null,
                  )
                }
              />
            ),
          )}
        </div>
      )}
      {confirm.modal}
    </section>
  );
}

interface FreshKeyRowProps {
  value: CliproxyApiKeyView;
  onDismiss: () => void;
}

/** The key as it lands: at the top, spelled out, with the copy to hand. */
function FreshKeyRow({ value, onDismiss }: FreshKeyRowProps) {
  const handleCopy = async () => {
    try {
      await copyText(value.key);
    } catch {
      // The value is on screen; copying by hand still works.
    }
    onDismiss();
  };

  return (
    <div className="ai_key_fresh">
      <div className="ai_key_fresh_head">
        <span className="ai_key_name">{value.name}</span>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onDismiss}
        >
          {WORDING.dismiss}
        </button>
      </div>
      <div className="ai_key_fresh_value mono">{value.key}</div>
      <div className="ai_key_fresh_foot">
        <span className="field_hint">{WORDING.freshHint}</span>
        <button
          type="button"
          className="button button--primary"
          onClick={() => void handleCopy()}
        >
          <Icon name="file" size={14} />
          {WORDING.copyKey}
        </button>
      </div>
    </div>
  );
}

interface KeyRowProps {
  value: CliproxyApiKeyView;
  usage: AiUsageKey | null;
  isBusy: boolean;
  onRevoke: () => void;
}

function KeyRow({ value, usage, isBusy, onRevoke }: KeyRowProps) {
  const [isRevealed, setIsRevealed] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const hasUsage = usage !== null && usage.requests > 0;
  const deviceName = usage?.device_name ?? null;

  const handleCopy = async () => {
    try {
      await copyText(value.key);
      setIsCopied(true);
      window.setTimeout(() => setIsCopied(false), COPIED_CLEAR_MS);
    } catch {
      // The value can be revealed and copied by hand.
    }
  };

  return (
    <div className="ai_key_row">
      <span className="ai_key_name">{value.name}</span>
      <span className="ai_key_value mono">
        {isRevealed ? value.key : MASKED_KEY}
      </span>
      <span className="ai_key_meta">
        <span className="ai_key_used">
          {hasUsage
            ? WORDING.used(formatTimeAgo(usage.last_seen_at))
            : WORDING.neverUsed}
        </span>
        {deviceName !== null && (
          <span className="ai_key_device mono">{deviceName}</span>
        )}
      </span>
      <span className="ai_key_actions">
        <button
          type="button"
          className="ai_key_action"
          title={isRevealed ? WORDING.hide : WORDING.reveal}
          aria-label={isRevealed ? WORDING.hide : WORDING.reveal}
          onClick={() => setIsRevealed((current) => !current)}
        >
          <Icon name={isRevealed ? "eye_off" : "eye"} size={13} />
        </button>
        <button
          type="button"
          className="ai_key_action"
          title={isCopied ? WORDING.copied : WORDING.copy}
          aria-label={isCopied ? WORDING.copied : WORDING.copy}
          onClick={() => void handleCopy()}
        >
          <Icon name={isCopied ? "check" : "file"} size={13} />
        </button>
        <button
          type="button"
          className="ai_key_action ai_key_action--danger"
          title={WORDING.revoke}
          aria-label={WORDING.revoke}
          disabled={isBusy}
          onClick={onRevoke}
        >
          <Icon name="trash" size={13} />
        </button>
      </span>
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
      window.setTimeout(() => setIsCopied(false), COPIED_CLEAR_MS);
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
        {isCopied ? WORDING.copied : WORDING.copy}
      </button>
    </div>
  );
}
