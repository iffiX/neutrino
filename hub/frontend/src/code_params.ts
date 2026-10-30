import { getLanguage, hasWord, t } from "./i18n";
import { moduleTitle } from "./module_title";

/** What joins the modules a `module_in_use` names, by language. */
const MODULE_SEPARATORS: Record<string, string> = { "zh-CN": "、" };
const MODULE_SEPARATOR_DEFAULT = ", ";

/** The params a module's task names that the panel words itself. */
const TASK_PARAMS = ["lock", "state", "holder"];

/**
 * The values a code's sentence takes from its params.
 *
 * A string or a number stands as it is, except three a module's task
 * names: `lock` becomes the step lock's words, `state` the module state's
 * word, and an empty `holder` the words for a program the system does not
 * name. `sources`, the list a `download_failed` names, becomes one text
 * naming each source and why it failed, and `modules`, the list a
 * `module_in_use` names, one text of their titles. Anything else is left
 * out.
 */
export function codeParams(value: unknown): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (typeof value !== "object" || value === null) {
    return params;
  }
  for (const [name, item] of Object.entries(value as Record<string, unknown>)) {
    if (typeof item === "string" && TASK_PARAMS.includes(name)) {
      params[name] = taskParamWords(name, item);
    } else if (typeof item === "string" || typeof item === "number") {
      params[name] = item;
    } else if (name === "sources" && Array.isArray(item)) {
      params[name] = item.map(sourceText).join("; ");
    } else if (name === "modules" && Array.isArray(item)) {
      params[name] = item
        .map((module) => moduleTitle(String(module), String(module)))
        .join(MODULE_SEPARATORS[getLanguage()] ?? MODULE_SEPARATOR_DEFAULT);
    }
  }
  return params;
}

/** The words of a step lock, a module state, or a program holding the
 * system's package manager; a value the catalog lacks stands as it is. */
function taskParamWords(name: string, value: string): string {
  if (name === "holder") {
    return value === "" ? t("ui.modules.holder_unnamed") : value;
  }
  const key = name === "lock" ? `ui.modules.lock.${value}` : `state.${value}`;
  return hasWord(key) ? t(key) : value;
}

/** One failed source as `address (reason)`. */
function sourceText(item: unknown): string {
  if (typeof item !== "object" || item === null) {
    return String(item);
  }
  const { source, reason } = item as Record<string, unknown>;
  return `${String(source ?? "")} (${String(reason ?? "")})`;
}
