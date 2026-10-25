/**
 * The values a code's sentence takes from its params.
 *
 * A string or a number stands as it is. `sources`, the list a
 * `download_failed` names, becomes one text naming each source and why it
 * failed. Anything else is left out.
 */
export function codeParams(value: unknown): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (typeof value !== "object" || value === null) {
    return params;
  }
  for (const [name, item] of Object.entries(value as Record<string, unknown>)) {
    if (typeof item === "string" || typeof item === "number") {
      params[name] = item;
    } else if (name === "sources" && Array.isArray(item)) {
      params[name] = item.map(sourceText).join("; ");
    }
  }
  return params;
}

/** One failed source as `address (reason)`. */
function sourceText(item: unknown): string {
  if (typeof item !== "object" || item === null) {
    return String(item);
  }
  const { source, reason } = item as Record<string, unknown>;
  return `${String(source ?? "")} (${String(reason ?? "")})`;
}
