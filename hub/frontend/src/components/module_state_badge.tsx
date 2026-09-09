/**
 * Where a module stands on one device, in one word.
 *
 * Only a step in flight and a failure are worth a badge: a machine the module
 * is installed on says so by being selectable, and a machine it is not on
 * says so by its chip being clear. Badging those too would put a word under
 * every chip and leave the two that matter no louder than the rest.
 */

const STATE_WORDING: Record<string, string> = {
  installing: "installing…",
  uninstalling: "uninstalling…",
  failed: "failed",
  unsupported: "not available here",
};

// The tone each badged state wears. A state with no entry is drawn plain.
const STATE_TONES: Record<string, string> = {
  installing: "badge--warn",
  uninstalling: "badge--warn",
  failed: "badge--error",
};

interface ModuleStateBadgeProps {
  /** The agent's word for the module on this device. */
  state: string;
}

export function ModuleStateBadge({ state }: ModuleStateBadgeProps) {
  const wording = STATE_WORDING[state];
  if (wording === undefined) {
    return null;
  }
  return (
    <span className={`badge ${STATE_TONES[state] ?? ""}`.trimEnd()}>
      {wording}
    </span>
  );
}
