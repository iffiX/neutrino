import { hasWord, t } from "./i18n";

/**
 * A module's title in the panel's language.
 *
 * The catalog's `ui.module_title.<name>` comes first; a module the catalog
 * does not name keeps the title its manifest gives.
 */
export function moduleTitle(name: string, manifestTitle: string): string {
  const key = `ui.module_title.${name}`;
  return hasWord(key) ? t(key) : manifestTitle;
}

/** The `module` a step lock's wait names for the agent's own update. */
const AGENT_HOLDER = "agent";

/**
 * A code's params with the module its `module` names given by that
 * module's title, and `agent`, the agent's own update, by its words.
 *
 * `manifestTitles` holds the manifest titles the caller knows, by module
 * name; a name it does not hold stands as its own title.
 */
export function withModuleTitle(
  params: Record<string, string | number>,
  manifestTitles: Record<string, string> = {},
): Record<string, string | number> {
  const name = params.module;
  if (typeof name !== "string") {
    return params;
  }
  if (name === AGENT_HOLDER) {
    return { ...params, module: t("ui.modules.holder_agent") };
  }
  return { ...params, module: moduleTitle(name, manifestTitles[name] ?? name) };
}
