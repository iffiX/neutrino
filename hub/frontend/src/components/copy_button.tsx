import { useEffect, useState } from "react";

import { Icon } from "./icon";
import { copyText } from "../copy_text";
import { t, useLanguage } from "../i18n";

/**
 * A bordered Copy that confirms in place: a check and `Copied` for a moment.
 */

/** How long the confirmation stays. */
const COPIED_CLEAR_MS = 1600;

interface CopyButtonProps {
  text: string;
}

export function CopyButton({ text }: CopyButtonProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isCopied, setIsCopied] = useState(false);

  useEffect(() => {
    if (!isCopied) {
      return;
    }
    const timer = window.setTimeout(() => setIsCopied(false), COPIED_CLEAR_MS);
    return () => window.clearTimeout(timer);
  }, [isCopied]);

  const handleCopy = async () => {
    try {
      await copyText(text);
      setIsCopied(true);
    } catch {
      // The text stays on screen to be selected by hand.
    }
  };

  return (
    <button
      type="button"
      className="button button--small"
      onClick={() => void handleCopy()}
    >
      <Icon name={isCopied ? "check" : "file"} size={13} />
      {isCopied ? t("ui.copy_button.copied") : t("ui.copy_button.copy")}
    </button>
  );
}
