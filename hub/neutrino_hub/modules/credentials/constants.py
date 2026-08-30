"""Fixed values of the credentials module."""

CREDENTIALS_AI_PROVIDERS_PATH = "credentials/ai_providers.json"

# The services Dev Setup knows how to point a machine's tools at. ``custom``
# covers relays and self-hosted endpoints speaking one of these APIs.
CREDENTIALS_AI_PROVIDER_KINDS = ("anthropic", "openai", "gemini", "custom")

CREDENTIALS_ID_BYTES = 8
