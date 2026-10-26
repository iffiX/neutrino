"""Fixed values of the Terminal module."""

# The module's name on the wire, and the runner a recipe names for it.
TERMINAL_NAME = "terminal"
TERMINAL_RUNNER = "terminal"

# Its configuration: the enabled accounts, each with its shell and its login.
TERMINAL_ACCOUNTS_KEY = "accounts"
TERMINAL_ACCOUNT_KEY = "account"
TERMINAL_SHELL_PATH_KEY = "shell_path"
TERMINAL_PASSWORD_KEY = "password"

# Why a shell or a command cannot run.
TERMINAL_CODE_ACCOUNT_MISSING = "terminal_account_missing"
TERMINAL_CODE_ACCOUNT_NOT_ENABLED = "account_not_enabled"
TERMINAL_CODE_ACCOUNT_UNKNOWN = "account_unknown"
TERMINAL_CODE_ACCOUNT_DUPLICATE = "account_duplicate"
TERMINAL_CODE_SHELL_UNUSABLE = "shell_program_unusable"
TERMINAL_CODE_CONFIG_INVALID = "config_invalid"
TERMINAL_CODE_CREDENTIAL_MISSING = "credential_missing"
TERMINAL_CODE_CREDENTIAL_INVALID = "credential_invalid"

# What a shell program is started with on Linux and macOS: as a login shell.
# Windows starts the program alone.
TERMINAL_LOGIN_ARGUMENTS = ("-l",)

# A login shell that only refuses a session.
TERMINAL_NOLOGIN_MARK = "nologin"
