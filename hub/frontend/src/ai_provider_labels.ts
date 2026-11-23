/**
 * What each AI service is called on the AI page.
 *
 * A login kind is the protocol the gateway speaks, an account's provider the
 * file it was written to, and the two spell one service differently; both
 * spellings are worded here. Anything else shows the name the gateway used.
 */
const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Claude",
  claude: "Claude",
  codex: "ChatGPT",
  antigravity: "Google",
  kimi: "Kimi",
  xai: "xAI",
};

/** The name one service goes by, or the gateway's own where none is worded. */
export function providerLabel(name: string): string {
  return PROVIDER_LABELS[name] ?? name;
}
