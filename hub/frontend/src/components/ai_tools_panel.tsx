import { useState } from "react";

import { apiPath, apiPost, describeError } from "../api_client";
import { hasWord, t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { Picker } from "./picker";
import { StatusDot } from "./status_dot";
import type {
  AiToolAccountView,
  AiToolConfigs,
  AiToolConfigUpdate,
  AiToolDeviceView,
  DeviceRequest,
} from "../api_types";
import type { PickerOption } from "./picker";
import type { StatusTone } from "./status_dot";

import "./ai_tools_panel.css";

/**
 * The Modules page's Global configuration: one machine's AI tools.
 *
 * It follows the desktop client's AI page. The chip acts at once, as the
 * module buttons below it do; Configure opens the client's dialog in place,
 * a picker per tool for its model over the gateway's models and, for Codex,
 * its effort, saved with Save. Under it, the line naming the accounts the
 * setting acts on and a row per account with what the machine reported.
 */

const BASE = "/agent/module/ai_tool";

const CLAUDE_SLOTS = ["default", "opus", "sonnet", "haiku"];
const SLOT_KEYS: Record<string, string> = {
  default: "ui.ai_tools.slot_default",
  opus: "ui.ai_tools.slot_opus",
  sonnet: "ui.ai_tools.slot_sonnet",
  haiku: "ui.ai_tools.slot_haiku",
};
const REASONING_EFFORTS = ["minimal", "low", "medium", "high"];
const EFFORT_KEY = "model_reasoning_effort";

/** What each module an account runs is called, the publisher's own names. */
const MODULE_TITLES: Record<string, string> = {
  vscode: "VS Code",
  code_server: "code-server",
  cloudcli: "CloudCLI",
};

/** The word and the tone of each reported result. */
const STATE_KEYS: Record<string, string> = {
  switched: "state.ai_tools_switched",
  switched_back: "state.ai_tools_switched_back",
};
const STATE_TONES: Record<string, StatusTone> = {
  switched: "ok",
  switched_back: "idle",
  failed: "error",
};
const NOT_REPORTED_KEY = "ui.device_monitor.waiting";

interface AiToolsPanelProps {
  deviceId: string;
}

export function AiToolsPanel({ deviceId }: AiToolsPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<AiToolDeviceView>(
    apiPath(BASE, { device_id: deviceId }),
    {
      invalidateOn: [
        { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
        { type: HUB_EVENT_CONFIG },
      ],
    },
  );
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AiToolConfigs | null>(null);
  const view = resource.data?.device_id === deviceId ? resource.data : null;

  const isDirty =
    draft !== null &&
    view !== null &&
    JSON.stringify(withAllTools(draft)) !==
      JSON.stringify(withAllTools(view.tool_configs));

  const write = async (path: string, body: unknown) => {
    setIsBusy(true);
    setError(null);
    try {
      resource.setData(await apiPost<AiToolDeviceView>(path, body));
      return true;
    } catch (cause: unknown) {
      setError(describeError(cause));
      return false;
    } finally {
      setIsBusy(false);
    }
  };

  const toggle = () => {
    if (view === null) {
      return;
    }
    const request: DeviceRequest = { device_id: deviceId };
    void write(`${BASE}/${view.is_enabled ? "disable" : "enable"}`, request);
  };

  const save = async () => {
    if (draft === null) {
      return;
    }
    const request: AiToolConfigUpdate = {
      device_id: deviceId,
      tool_configs: draft,
    };
    if (await write(`${BASE}/set`, request)) {
      setDraft(null);
    }
  };

  const reason =
    view === null
      ? null
      : !view.is_online
        ? t("ui.modules.agent_offline")
        : !view.is_enabled && !view.is_gateway_serving
          ? t("code.gateway_not_serving")
          : null;
  const canToggle =
    view !== null &&
    view.is_online &&
    !isBusy &&
    (view.is_enabled || view.is_gateway_serving);

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.modules.global_title")}</h2>
      </div>
      {resource.error !== null && view === null ? (
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      ) : view === null ? (
        <div className="skeleton ai_tools_skeleton" />
      ) : (
        <div className="ai_tools">
          <h3 className="ai_tools_title">{t("ui.ai_tools.title")}</h3>
          <div className="ai_tools_controls">
            <button
              type="button"
              className={`ai_tools_chip ${view.is_enabled ? "ai_tools_chip--on" : ""}`}
              aria-pressed={view.is_enabled}
              disabled={!canToggle}
              onClick={toggle}
            >
              <Icon name="sparkles" size={14} />
              {t("ui.ai_tools.use")}
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={!view.is_online || isBusy}
              onClick={() =>
                setDraft(draft === null ? copyOf(view.tool_configs) : null)
              }
            >
              {t("ui.modules.configure")}
            </button>
          </div>
          {reason !== null && <p className="field_hint">{reason}</p>}
          {error !== null && <p className="field_error">{error}</p>}
          {draft !== null && (
            <ToolForm
              draft={draft}
              models={view.models}
              isBusy={isBusy}
              onChange={setDraft}
              onSave={() => void save()}
              onCancel={() => setDraft(null)}
            />
          )}
          <p className="field_hint">
            {view.accounts.length === 0
              ? t("ui.ai_tools.no_accounts")
              : t("ui.ai_tools.accounts", {
                  accounts: view.accounts
                    .map((entry) => entry.account)
                    .join(", "),
                })}
          </p>
          {view.accounts.length > 0 && (
            <div className="ai_tools_accounts">
              {view.accounts.map((entry) => (
                <AccountRow key={entry.account} entry={entry} />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

interface ToolFormProps {
  draft: AiToolConfigs;
  models: string[];
  isBusy: boolean;
  onChange: (draft: AiToolConfigs) => void;
  onSave: () => void;
  onCancel: () => void;
}

/** The client's Configure dialog, drawn in place. */
function ToolForm({
  draft,
  models,
  isBusy,
  onChange,
  onSave,
  onCancel,
}: ToolFormProps) {
  const modelOptions: PickerOption[] = [
    { id: "", name: `(${t("ui.ai_tools.gateway_default")})` },
    ...models.map((model) => ({ id: model, name: model })),
  ];
  const effortOptions: PickerOption[] = [
    { id: "", name: `(${t("ui.ai_tools.gateway_default")})` },
    ...REASONING_EFFORTS.map((level) => ({ id: level, name: level })),
  ];
  const valueOf = (tool: string, knob: string) => draft[tool]?.[knob] ?? "";
  const pick = (tool: string, knob: string, value: string) => {
    const knobs = { ...(draft[tool] ?? {}) };
    if (value === "") {
      delete knobs[knob];
    } else {
      knobs[knob] = value;
    }
    onChange({ ...draft, [tool]: knobs });
  };
  const modelPicker = (tool: string, knob: string, label: string) => (
    <Picker
      key={`${tool}.${knob}`}
      options={modelOptions}
      value={models.includes(valueOf(tool, knob)) ? valueOf(tool, knob) : ""}
      onChange={(value) => pick(tool, knob, value)}
      label={label}
    />
  );

  return (
    <div className="ai_tools_form">
      <div className="ai_tools_form_tool">{t("ui.ai_tools.tool_claude")}</div>
      <div className="ai_tools_form_row">
        {CLAUDE_SLOTS.map((slot) =>
          modelPicker("claude", slot, t(SLOT_KEYS[slot] ?? slot)),
        )}
      </div>
      <div className="ai_tools_form_tool">{t("ui.ai_tools.tool_codex")}</div>
      <div className="ai_tools_form_row">
        {modelPicker("codex", "model", t("ui.ai_tools.model"))}
        <Picker
          options={effortOptions}
          value={
            REASONING_EFFORTS.includes(valueOf("codex", EFFORT_KEY))
              ? valueOf("codex", EFFORT_KEY)
              : ""
          }
          onChange={(value) => pick("codex", EFFORT_KEY, value)}
          label={t("ui.ai_tools.codex_effort")}
        />
      </div>
      <div className="ai_tools_form_tool">{t("ui.ai_tools.tool_gemini")}</div>
      <div className="ai_tools_form_row">
        {modelPicker("gemini", "model", t("ui.ai_tools.model"))}
      </div>
      <div className="ai_tools_form_actions">
        <button
          type="button"
          className="button button--primary button--small"
          disabled={isBusy}
          onClick={onSave}
        >
          {t("ui.ai_tools.save")}
        </button>
        <button
          type="button"
          className="button button--ghost button--small"
          disabled={isBusy}
          onClick={onCancel}
        >
          {t("ui.ai_tools.cancel")}
        </button>
      </div>
    </div>
  );
}

/** One account: its name, the modules it runs, and its last result. */
function AccountRow({ entry }: { entry: AiToolAccountView }) {
  const tone = STATE_TONES[entry.state] ?? "idle";
  return (
    <div className="ai_tools_account">
      <span className="ai_tools_account_name mono">{entry.account}</span>
      <span className="ai_tools_account_modules faint">
        {entry.modules.map((name) => MODULE_TITLES[name] ?? name).join(", ")}
      </span>
      <span className="ai_tools_account_state">
        <StatusDot tone={tone} />
        {describeResult(entry)}
      </span>
    </div>
  );
}

/** What the machine said of one account, worded from its state or code. */
function describeResult(entry: AiToolAccountView): string {
  if (entry.state === "failed") {
    const key = `code.${entry.code}`;
    return hasWord(key)
      ? t(key, { account: entry.account, ...entry.params })
      : t("ui.modules.failed_code", { code: entry.code });
  }
  const key = STATE_KEYS[entry.state];
  return t(key ?? NOT_REPORTED_KEY);
}

/** The choices with every tool present, so two drafts compare by value. */
function withAllTools(configs: AiToolConfigs): AiToolConfigs {
  return {
    claude: configs.claude ?? {},
    codex: configs.codex ?? {},
    gemini: configs.gemini ?? {},
  };
}

function copyOf(configs: AiToolConfigs): AiToolConfigs {
  const copied: AiToolConfigs = {};
  for (const [tool, knobs] of Object.entries(withAllTools(configs))) {
    copied[tool] = { ...knobs };
  }
  return copied;
}
