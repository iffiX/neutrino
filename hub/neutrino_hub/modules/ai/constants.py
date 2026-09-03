"""Fixed values of the ai module."""

AI_PROVIDERS_PATH = "ai/providers.json"

# The services Dev Setup knows how to point a machine's tools at. ``custom``
# covers relays and self-hosted endpoints speaking one of these APIs.
AI_PROVIDER_KINDS = ("anthropic", "openai", "gemini", "custom")
