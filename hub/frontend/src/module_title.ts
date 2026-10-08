import { hasWord, t } from "./i18n";

/**
 * A module's title in the panel's language.
 *
 * The catalog's `ui.module_title.<name>` comes first; a module the catalog
 * does not name, such as one called after its product, keeps the title its
 * manifest gives.
 */
export function moduleTitle(name: string, manifestTitle: string): string {
  const key = `ui.module_title.${name}`;
  return hasWord(key) ? t(key) : manifestTitle;
}

/**
 * A code's params with the module its `module` names given by that
 * module's title.
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
  return { ...params, module: moduleTitle(name, manifestTitles[name] ?? name) };
}
