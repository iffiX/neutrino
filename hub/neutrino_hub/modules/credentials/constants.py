"""Fixed values of the credentials module."""

CREDENTIALS_AI_PROVIDERS_PATH = "credentials/ai_providers.json"

# The services Dev Setup knows how to point a machine's tools at. ``custom``
# covers relays and self-hosted endpoints speaking one of these APIs.
CREDENTIALS_AI_PROVIDER_KINDS = ("anthropic", "openai", "gemini", "custom")

CREDENTIALS_VAULT_PATH = "credentials/vault.json"
CREDENTIALS_VAULT_KEY_PATH = "credentials/vault.key"
CREDENTIALS_VAULT_VERSION = 1
CREDENTIALS_VAULT_CIPHER = "aes-256-gcm"

# What each secret kind seals. Field names outside a kind's two sets are
# refused, as is a missing required one.
CREDENTIALS_SECRET_KINDS = {
    "password": {"required": ("password",), "optional": ()},
    "ssh_key": {"required": ("private_key",), "optional": ("passphrase",)},
    "api_token": {"required": ("api_key",), "optional": ()},
    "service_account": {"required": ("password",), "optional": ()},
}
