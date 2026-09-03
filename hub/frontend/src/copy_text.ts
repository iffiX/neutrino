/**
 * Copy text on a page served over plain http, where the clipboard API is
 * absent. The selection fallback is deprecated but is exactly what still
 * works there.
 */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard !== undefined) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall through to the selection path.
    }
  }
  const holder = document.createElement("textarea");
  holder.value = text;
  holder.style.position = "fixed";
  holder.style.opacity = "0";
  document.body.appendChild(holder);
  holder.select();
  document.execCommand("copy");
  holder.remove();
}
