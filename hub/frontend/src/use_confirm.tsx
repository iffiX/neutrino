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
  /** What it costs. One or two sentences, mechanism first; empty for none. */
  body: string;
  /** Names listed under the body, one to a line. */
  items?: string[];
  /** A question under the list. */
  question?: string;
  /** The action's own verb, on the button that performs it. */
  confirmLabel: string;
  /** The button that cancels; `ui.confirm.cancel` when absent. */
  cancelLabel?: string;
  /** A line under the body about the person's data. */
  detail?: string;
  /** Whether the act destroys data. The detail then takes the error tone,
   * and the button `button--danger`. */
  isDanger?: boolean;
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
        items={pending.items}
        question={pending.question}
        confirmLabel={pending.confirmLabel}
        cancelLabel={pending.cancelLabel}
        detail={pending.detail}
        isDanger={pending.isDanger}
        onConfirm={() => {
          setPending(null);
          pending.onConfirm();
        }}
        onCancel={() => setPending(null)}
      />
    );

  return { ask, modal };
}
