import { codeParams } from "./code_params";
import { hasWord, t } from "./i18n";
import type { AccountAiToolsView } from "./api_types";
import type { StatusTone } from "./components/status_dot";

/**
 * An account's last AI tools result in words and in a tone, as its row under
 * **Available accounts** shows it and a command line program's tab repeats
 * it.
 */

/** The word of each reported AI tools result but a failure. */
const AI_TOOLS_KEYS: Record<string, string> = {
  switched: "state.ai_tools_switched",
  switched_back: "state.ai_tools_switched_back",
};

/** The tone of each reported AI tools result. */
export const AI_TOOLS_TONES: Record<string, StatusTone> = {
  switched: "ok",
  switched_back: "idle",
  failed: "error",
};

const AI_TOOLS_FAILED = "failed";
const CODE_SWITCH_FAILED = "switch_failed";

/**
 * The machine's last word on an account's AI tools; a failure in its code's
 * words, a detail that is itself a code worded too.
 *
 * Args:
 *   account: The account's name.
 *   result: Its last result, as the machine reported it.
 *   isSwitchOn: Whether its switch is on. A `switch_failed` with the switch
 *     off is a switch back that failed.
 *
 * Returns:
 *   The words, in the panel's language.
 */
export function aiToolsWords(
  account: string,
  result: AccountAiToolsView,
  isSwitchOn: boolean,
): string {
  if (result.state !== AI_TOOLS_FAILED) {
    return t(AI_TOOLS_KEYS[result.state] ?? "ui.device_monitor.waiting");
  }
  const key =
    !isSwitchOn && result.code === CODE_SWITCH_FAILED
      ? "ui.ai_tools.switch_back_failed"
      : `code.${result.code}`;
  const params: Record<string, string | number> = {
    account,
    ...codeParams(result.params),
  };
  const detailKey = `code.${String(params.detail ?? "")}`;
  if (
    params.detail !== undefined &&
    hasWord(detailKey) &&
    !/\{\w+\}/.test(t(detailKey))
  ) {
    params.detail = t(detailKey);
  }
  return hasWord(key)
    ? t(key, params)
    : t("ui.modules.failed_code", { code: result.code });
}
