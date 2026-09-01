import { useCallback, useState } from "react";
import type { ReactNode } from "react";

import { ConfirmModal } from "./components/confirm_modal";

/**
 * Asking before an irreversible button acts.
 *
 * One hook rather than a modal wired up in each page, so every confirmation in
 * the panel is the same dialog with the same three parts: what is about to
 * happen, what it costs, and the action's own verb on the button.
 *
 * Settings do not come through here. A group of them ends in an apply bar, and
 * the bar's warning is where its cost is stated.
 */

export interface ConfirmRequest {
  /** What is about to happen: "Destroy tank/media". */
  title: string;
  /** What it costs. One or two sentences, mechanism first. */
  body: string;
  /** The action's own verb, on the button that performs it. */
  confirmLabel: string;
  onConfirm: () => void;
}

export interface Confirm {
  /** Put the question up. It acts when the button is pressed, not before. */
  ask: (request: ConfirmRequest) => void;
  /** Render this where the asking component renders. */
  modal: ReactNode;
}

export function useConfirm(): Confirm {
  const [pending, setPending] = useState<ConfirmRequest | null>(null);

  const ask = useCallback((request: ConfirmRequest) => {
    setPending(request);
  }, []);

  const modal =
    pending === null ? null : (
      <ConfirmModal
        title={pending.title}
        body={pending.body}
        confirmLabel={pending.confirmLabel}
        onConfirm={() => {
          setPending(null);
          pending.onConfirm();
        }}
        onCancel={() => setPending(null)}
      />
    );

  return { ask, modal };
}
