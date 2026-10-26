import { Picker } from "./picker";
import { t, useLanguage } from "../i18n";
import type { AiToolConfigs } from "../api_types";
import type { PickerOption } from "./picker";

import "./ai_tool_models.css";

/**
 * The model rows of an account's AI tools, as the desktop client's AI page
 * draws them: Claude Code's four slots, Codex's model and its effort, and
 * Gemini's model. Each picker's first choice is the gateway's default,
 * which the configuration holds as no entry.
 */

const CLAUDE_SLOTS = ["default", "opus", "sonnet", "haiku"];
const SLOT_KEYS: Record<string, string> = {
  default: "ui.ai_tools.slot_default",
  opus: "ui.ai_tools.slot_opus",
  sonnet: "ui.ai_tools.slot_sonnet",
  haiku: "ui.ai_tools.slot_haiku",
};
const REASONING_EFFORTS = ["minimal", "low", "medium", "high"];
const EFFORT_KEY = "model_reasoning_effort";
const MODEL_KEY = "model";

/** The picker's row for no entry: the gateway's default. */
const GATEWAY_DEFAULT = "";

interface AiToolModelsProps {
  configs: AiToolConfigs;
  /** The names the gateway serves. */
  models: string[];
  isDisabled?: boolean;
  onChange: (configs: AiToolConfigs) => void;
}

export function AiToolModels({
  configs,
  models,
  isDisabled = false,
  onChange,
}: AiToolModelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const modelOptions: PickerOption[] = [
    { id: GATEWAY_DEFAULT, name: t("ui.ai_tools.gateway_default") },
    ...models.map((model) => ({ id: model, name: model })),
  ];
  const effortOptions: PickerOption[] = [
    { id: GATEWAY_DEFAULT, name: t("ui.ai_tools.gateway_default") },
    ...REASONING_EFFORTS.map((level) => ({ id: level, name: level })),
  ];
  const valueOf = (tool: string, knob: string) => configs[tool]?.[knob] ?? "";
  const pick = (tool: string, knob: string, value: string) => {
    const knobs = { ...(configs[tool] ?? {}) };
    if (value === GATEWAY_DEFAULT) {
      delete knobs[knob];
    } else {
      knobs[knob] = value;
    }
    onChange({ ...configs, [tool]: knobs });
  };
  const modelPicker = (tool: string, knob: string, label: string) => (
    <Picker
      key={`${tool}.${knob}`}
      options={modelOptions}
      value={
        models.includes(valueOf(tool, knob))
          ? valueOf(tool, knob)
          : GATEWAY_DEFAULT
      }
      onChange={(value) => pick(tool, knob, value)}
      label={label}
      isDisabled={isDisabled}
    />
  );

  return (
    <div className="ai_tool_models">
      <div className="ai_tool_models_tool">{t("ui.ai_tools.tool_claude")}</div>
      <div className="ai_tool_models_row">
        {CLAUDE_SLOTS.map((slot) =>
          modelPicker("claude", slot, t(SLOT_KEYS[slot] ?? slot)),
        )}
      </div>
      <div className="ai_tool_models_tool">{t("ui.ai_tools.tool_codex")}</div>
      <div className="ai_tool_models_row">
        {modelPicker("codex", MODEL_KEY, t("ui.ai_tools.model"))}
        <Picker
          options={effortOptions}
          value={
            REASONING_EFFORTS.includes(valueOf("codex", EFFORT_KEY))
              ? valueOf("codex", EFFORT_KEY)
              : GATEWAY_DEFAULT
          }
          onChange={(value) => pick("codex", EFFORT_KEY, value)}
          label={t("ui.ai_tools.codex_effort")}
          isDisabled={isDisabled}
        />
      </div>
      <div className="ai_tool_models_tool">{t("ui.ai_tools.tool_gemini")}</div>
      <div className="ai_tool_models_row">
        {modelPicker("gemini", MODEL_KEY, t("ui.ai_tools.model"))}
      </div>
    </div>
  );
}
