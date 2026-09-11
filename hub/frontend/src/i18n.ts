/**
 * The catalogs, and the one function every screen words itself through.
 *
 * A catalog is a flat JSON object of whole sentences under `ui.<area>.<thing>`
 * keys, one file per page group, and the loader merges every file of a
 * language into one map. A key the current language has no sentence for falls
 * back to English, and a key English does not have either renders as itself,
 * so a missing translation is a visible key rather than a blank screen.
 *
 * The language is panel-wide and lives on the box: the page reads it from
 * `/api/language` before its first render and `setLanguage` moves every open
 * screen at once.
 */

import { useSyncExternalStore } from "react";

/** The languages this panel ships. Anything else reads as the first. */
export const LANGUAGES = ["en", "zh-CN"] as const;

export type Language = (typeof LANGUAGES)[number];

export const LANGUAGE_DEFAULT: Language = "en";

/** What each language calls itself; a picker never translates its own list. */
export const LANGUAGE_NAMES: Record<Language, string> = {
  en: "English",
  "zh-CN": "简体中文",
};

/** One language's sentences, by key. */
type Catalog = Record<string, string>;

const CATALOGS: Record<Language, Catalog> = {
  en: merged(
    import.meta.glob<Catalog>("./locales/en/*.json", {
      eager: true,
      import: "default",
    }),
  ),
  "zh-CN": merged(
    import.meta.glob<Catalog>("./locales/zh-CN/*.json", {
      eager: true,
      import: "default",
    }),
  ),
};

const listeners = new Set<() => void>();

let currentLanguage: Language = LANGUAGE_DEFAULT;

/**
 * The sentence this key names, with `{name}` filled in from `params`.
 *
 * A placeholder with nothing to fill it stays as it is written, which reads
 * as the mistake it is rather than as an empty space.
 */
export function t(
  key: string,
  params: Record<string, string | number> = {},
): string {
  const sentence =
    CATALOGS[currentLanguage][key] ?? CATALOGS[LANGUAGE_DEFAULT][key] ?? key;
  return sentence.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
    const value = params[name];
    return value === undefined ? placeholder : String(value);
  });
}

/** Whether a key is worded in the current language or in English. */
export function hasWord(key: string): boolean {
  return key in CATALOGS[getLanguage()] || key in CATALOGS[LANGUAGE_DEFAULT];
}

export function getLanguage(): Language {
  return currentLanguage;
}

/**
 * Draw every open screen in this language.
 *
 * A language this panel does not ship is English, so a stored value from
 * another build cannot leave the page wordless.
 */
export function setLanguage(language: string): void {
  const next = asLanguage(language);
  document.documentElement.lang = next;
  if (next === currentLanguage) {
    return;
  }
  currentLanguage = next;
  for (const listener of listeners) {
    listener();
  }
}

/** The language this name is, or English where the panel ships no such one. */
export function asLanguage(language: string): Language {
  return (LANGUAGES as readonly string[]).includes(language)
    ? (language as Language)
    : LANGUAGE_DEFAULT;
}

/** The current language, re-rendering the component when it changes. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage, getLanguage);
}

function merged(files: Record<string, Catalog>): Catalog {
  const catalog: Catalog = {};
  for (const file of Object.values(files)) {
    Object.assign(catalog, file);
  }
  return catalog;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}
