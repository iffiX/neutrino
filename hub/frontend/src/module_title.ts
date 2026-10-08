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
