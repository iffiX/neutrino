import { t } from "./i18n";

/**
 * The placeholder shown in every "paste a private key" box.
 *
 * Deliberately a template, not realistic key material: an earlier version
 * showed convincing-looking base64, which read as though a stored key were
 * being displayed. This makes it unmistakable that the box is empty and what
 * belongs in it.
 */
export function privateKeyPlaceholder(): string {
  return t("ui.vault.private_key_placeholder");
}
