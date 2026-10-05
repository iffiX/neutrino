"""Fixed values of the machine's AI tools: cc-switch's vocabulary, the records, the codes."""

# The provider the hub is in cc-switch's store, as the desktop client names
# it.
AI_TOOLS_PROVIDER_ID = "neutrino"
AI_TOOLS_PROVIDER_NAME = "Neutrino Hub"

# The tools cc-switch can point at the hub, in its own vocabulary, and where
# each keeps the file that switching replaces, below the account's home.
AI_TOOLS_APPS = ("claude", "codex", "gemini")
AI_TOOLS_APP_FILES = {
    "claude": (".claude", "settings.json"),
    "codex": (".codex", "config.toml"),
    "gemini": (".gemini", ".env"),
}

# Claude Code's role slots, each a flag of cc-switch's provider add.
AI_TOOLS_CLAUDE_SLOT_FLAGS = {
    "default": "--model",
    "opus": "--opus-model",
    "sonnet": "--sonnet-model",
    "haiku": "--haiku-model",
}
# Codex's one knob cc-switch has no flag for, a top-level key of config.toml.
AI_TOOLS_CODEX_EFFORT_KEY = "model_reasoning_effort"
# Codex asks for ``<base>/responses``; the gateway serves the Responses API
# under ``/v1``. Claude Code and Gemini add their own versioned paths.
AI_TOOLS_ENDPOINT_SUFFIXES = {"codex": "/v1"}
# The keys cc-switch's common snippet would carry from a tool's own file
# that belong to the provider, not to the person.
AI_TOOLS_COMMON_OWN_KEYS = {
    "claude": ("model",),
    "codex": ("model",),
    "gemini": ("GEMINI_MODEL",),
}
# The provider cc-switch itself seeds for each tool, there to switch to when
# nothing of the account's own was current before the hub.
AI_TOOLS_OFFICIAL_PROVIDERS = {
    "claude": "claude-official",
    "codex": "codex-official",
    "gemini": "gemini-official",
}
# What cc-switch asks before deleting a provider, and the answer.
AI_TOOLS_DELETE_PROMPT = "(y/N)"
AI_TOOLS_DELETE_ANSWER = "y\n"
# What cc-switch draws its provider table with.
AI_TOOLS_TABLE_SEPARATOR = "┆"
# How long one cc-switch call may take, and how much of a console's or a
# refusal's words a code's detail carries.
AI_TOOLS_COMMAND_TIMEOUT_S = 120
AI_TOOLS_WORDS_LIMIT = 200
AI_TOOLS_DETAIL_LIMIT = 300
# How much of a hub key the record keeps: a digest, never the key.
AI_TOOLS_KEY_DIGEST_CHARS = 16

# The file a payload for cc-switch is handed in, in the account's own
# Neutrino tree, written and removed as the account: below the home, the
# system's place for an account's data, then the tree's own directories.
AI_TOOLS_PAYLOAD_BASE = {
    "linux": (".local", "share"),
    "darwin": ("Library", "Application Support"),
    "windows": ("AppData", "Local"),
}
AI_TOOLS_PAYLOAD_TREE = {
    "linux": ("neutrino", "agent", "ai_tools"),
    "darwin": ("Neutrino", "agent", "ai_tools"),
    "windows": ("Neutrino", "agent", "ai_tools"),
}
AI_TOOLS_PAYLOAD_NAME = "payload"

# The records: one directory per account under the state root, one file per
# tool, and on Windows the login the account was switched with, kept until
# it is switched back.
AI_TOOLS_DIR_NAME = "ai_tools"
AI_TOOLS_RECORD_SUFFIX = ".json"
AI_TOOLS_LOGIN_NAME = "login.json"

# Where the agent's package carries cc-switch: below the program directory
# on each system.
AI_TOOLS_CC_SWITCH_PATHS = {
    "linux": "/opt/neutrino/agent/bin/cc-switch",
    "darwin": "/Library/Application Support/Neutrino/agent/app/bin/cc-switch",
}
AI_TOOLS_CC_SWITCH_WINDOWS_PARTS = ("bin", "cc-switch.exe")
AI_TOOLS_CC_SWITCH_BINARY = "cc-switch"

# An account's result in the report.
AI_TOOLS_STATE_SWITCHED = "switched"
AI_TOOLS_STATE_SWITCHED_BACK = "switched_back"
AI_TOOLS_STATE_FAILED = "failed"
# The codes a failure carries.
AI_TOOLS_CODE_SWITCH_FAILED = "switch_failed"
AI_TOOLS_CODE_BUNDLE_MISSING = "bundle_missing"
AI_TOOLS_CODE_ACCOUNT_UNKNOWN = "account_unknown"
AI_TOOLS_CODE_CREDENTIAL_MISSING = "credential_missing"
AI_TOOLS_CODE_CREDENTIAL_INVALID = "credential_invalid"
