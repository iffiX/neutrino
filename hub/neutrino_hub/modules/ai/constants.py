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

# The vendor presets of the provider form, shipped in the package.
AI_VENDORS_PATH = UTILS_DATA_DIR / "ai_vendors.json"
# The vendor of each kind's own endpoint: its base URL, and the models.dev
# provider its requests are priced at. These have no preset of their own.
AI_KIND_VENDORS = {
    "anthropic": ("https://api.anthropic.com", "anthropic"),
    "openai": ("https://api.openai.com/v1", "openai"),
    "gemini": ("https://generativelanguage.googleapis.com", "google"),
}
# The endpoint id of a kind's own endpoint.
AI_KIND_ENDPOINT = "api"
# The models.dev provider an account's records are priced at, by the login
# the gateway names as the account's provider.
AI_LOGIN_PRICE_PROVIDERS = {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "codex": "openai",
    "antigravity": "google",
    "kimi": "moonshotai",
    "xai": "xai",
}

# The prices a person set on the AI page, by served name.
AI_PRICES_PATH = "ai/prices.json"
# The price list carried in the package, made from models.dev with each
# release.
AI_PRICES_SNAPSHOT_PATH = UTILS_DATA_DIR / "model_prices.json"
# Where the hub reads the price list, and how often.
AI_PRICES_URL = "https://models.dev/api.json"
AI_PRICES_INTERVAL_S = 24 * 3600
AI_PRICES_RETRY_S = 3600
AI_PRICES_READ_TIMEOUT_S = 60
# The checks a downloaded price list passes before it replaces the copy in
# force.
AI_PRICES_LIMIT_BYTES = 64 * 1024 * 1024
AI_PRICES_MIN_MODELS = 50
AI_PRICES_MIN_SNAPSHOT_RATIO = 0.5
# The four prices of a model, per million tokens.
AI_PRICE_FIELDS = ("input", "output", "cache_read", "cache_write")
# What a person may set: a currency, and two numbers in a range with at most
# so many decimals.
AI_PRICE_CURRENCIES = ("USD", "CNY")
AI_PRICE_DEFAULT_CURRENCY = "USD"
AI_PRICE_MIN = 0
AI_PRICE_MAX = 10000
AI_PRICE_DECIMALS = 6
# The token breakdown quality a record's cost is computed from.
AI_PRICED_QUALITY = "complete"
# What a record adds to the counters: a cost, an API value, a count of the
# requests with no price, or nothing.
AI_CHARGE_COST = "cost"
AI_CHARGE_API_VALUE = "api_value"
AI_CHARGE_UNPRICED = "unpriced"
AI_CHARGE_NONE = "none"
