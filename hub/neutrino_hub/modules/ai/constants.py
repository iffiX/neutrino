"""Fixed values of the ai module."""

from neutrino_hub.utils.constants import UTILS_DATA_DIR

AI_PROVIDERS_PATH = "ai/providers.json"

# The services Dev Setup knows how to point a machine's tools at. ``custom``
# covers relays and self-hosted endpoints speaking one of these APIs.
AI_PROVIDER_KINDS = ("anthropic", "openai", "gemini", "custom")

# The context lengths a person set on the AI page, by served name.
AI_CONTEXT_LENGTHS_PATH = "ai/context_lengths.json"
# The table of known models, shipped in the package.
AI_KNOWN_MODELS_PATH = UTILS_DATA_DIR / "context_lengths.json"
# A source's window when neither the table nor the catalog names one.
AI_CONTEXT_LENGTH_FALLBACK = 200000
# The lengths a person may set.
AI_CONTEXT_LENGTH_MIN = 4096
AI_CONTEXT_LENGTH_MAX = 10000000
# Where a served name's source comes from, as the context view names it.
AI_CONTEXT_ORIGIN_ACCOUNT = "account"
AI_CONTEXT_ORIGIN_PROVIDER = "provider"
# The catalog channel of each provider kind; a ``custom`` provider has none.
AI_PROVIDER_KIND_CHANNELS = {
    "anthropic": "claude",
    "openai": "codex",
    "gemini": "gemini",
}
# The catalog channel of each account, by the login the gateway names as the
# account's provider.
AI_ACCOUNT_CHANNELS = {
    "claude": "claude",
    "anthropic": "claude",
    "codex": "codex",
    "antigravity": "antigravity",
    "kimi": "kimi",
    "xai": "xai",
}
