"""Fixed values of the credentials module."""

CREDENTIALS_AI_PROVIDERS_PATH = "credentials/ai_providers.json"

# The services Dev Setup knows how to point a machine's tools at. ``custom``
# covers relays and self-hosted endpoints speaking one of these APIs.
CREDENTIALS_AI_PROVIDER_KINDS = ("anthropic", "openai", "gemini", "custom")

CREDENTIALS_VAULT_PATH = "credentials/vault.json"
CREDENTIALS_VAULT_VERSION = 2
# The unwrapped data key, state under /var/lib/neutrino: minted by setup,
# rewritten by a successful restore, and never part of a backup.
CREDENTIALS_VAULT_STATE_KEY_NAME = "vault.key"

# What each secret kind seals. Field names outside a kind's two sets are
# refused, as is a missing required one. Three kinds cover everything the hub
# holds: a bare secret string, an account, and an SSH identity.
CREDENTIALS_SECRET_KINDS = {
    "token": {"required": ("value",), "optional": ()},
    "login": {"required": ("password",), "optional": ("username",)},
    "ssh_key": {"required": ("private_key",), "optional": ("passphrase",)},
}
