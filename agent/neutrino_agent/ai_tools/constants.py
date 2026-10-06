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
# The directory cc-switch writes a tool's files into only once it is there,
# and every file a switch may write in it, below the account's home: what
# is kept aside before the first switch and put back after the switch back.
AI_TOOLS_APP_DIRS = {"claude": ".claude", "codex": ".codex", "gemini": ".gemini"}
AI_TOOLS_APP_KEPT_FILES = {
    "claude": ("settings.json",),
    "codex": ("config.toml", "auth.json"),
    "gemini": (".env", "settings.json"),
}
# The files of a tool that hold the gateway key once it is switched, and
# the mode each is left with: the account alone reads and writes it.
AI_TOOLS_APP_KEY_FILES = {
    "claude": ("settings.json",),
    "codex": ("auth.json",),
    "gemini": (".env",),
}
AI_TOOLS_KEY_FILE_MODE = 0o600

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
# cc-switch's own store for the agent's runs, beside the payload in the
# account's Neutrino tree, named to cc-switch by the variable it reads; the
# store must be the account's alone, mode 700.
AI_TOOLS_STORE_NAME = "cc_switch"
AI_TOOLS_STORE_VARIABLE = "CC_SWITCH_CONFIG_DIR"
AI_TOOLS_STORE_MODE = "700"

# The records: one directory per account under the state root, one file per
# tool, and on Windows the login the account was switched with, kept until
# it is switched back.
AI_TOOLS_DIR_NAME = "ai_tools"
AI_TOOLS_RECORD_SUFFIX = ".json"
AI_TOOLS_LOGIN_NAME = "login.json"
# One lock file per account, in a directory of its own beside the records
# so a switch back that removes an account's records leaves its lock; how
# long a run waits for another that holds the account, how often it looks,
# and what its refusal says.
AI_TOOLS_LOCK_DIR_NAME = ".locks"
AI_TOOLS_LOCK_WAIT_S = 300
AI_TOOLS_LOCK_POLL_S = 0.2
AI_TOOLS_LOCK_HELD_DETAIL = "another run holds the account"

# cc-switch as the hub serves it: the name the agent asks the package
# stream for, the archive's kind and the program's name in it on each
# system, and the directory under the records' directory that holds the
# copy with the version it was fetched for beside it.
AI_TOOLS_CC_SWITCH_PACKAGE = "cc_switch"
AI_TOOLS_CC_SWITCH_KINDS = {"windows": "zip"}
AI_TOOLS_CC_SWITCH_KIND = "tar"
AI_TOOLS_CC_SWITCH_NAMES = {"windows": "cc-switch.exe"}
AI_TOOLS_CC_SWITCH_NAME = "cc-switch"
AI_TOOLS_BIN_DIR_NAME = "bin"
AI_TOOLS_VERSION_NAME = "version"

# An account's result in the report.
AI_TOOLS_STATE_SWITCHED = "switched"
AI_TOOLS_STATE_SWITCHED_BACK = "switched_back"
AI_TOOLS_STATE_FAILED = "failed"
# The codes a failure carries.
AI_TOOLS_CODE_SWITCH_FAILED = "switch_failed"
AI_TOOLS_CODE_DOWNLOAD_FAILED = "cc_switch_download_failed"
AI_TOOLS_CODE_ACCOUNT_UNKNOWN = "account_unknown"
AI_TOOLS_CODE_CREDENTIAL_MISSING = "credential_missing"
AI_TOOLS_CODE_CREDENTIAL_INVALID = "credential_invalid"
