"""Fixed values of the Terminal module."""

# The module's name on the wire, and the kind its runner answers for.
TERMINAL_NAME = "terminal"
TERMINAL_KIND = "terminal"

# The two settings of its configuration.
TERMINAL_ACCOUNT_KEY = "account"
TERMINAL_SHELL_PATH_KEY = "shell_path"

# Why a setting cannot be run.
TERMINAL_CODE_ACCOUNT_UNKNOWN = "account_unknown"
TERMINAL_CODE_SHELL_UNUSABLE = "shell_program_unusable"
TERMINAL_CODE_CONFIG_INVALID = "config_invalid"

# What a shell program is started with when the module names it, or when it
# runs for an account: as a login shell. Windows starts the program alone.
TERMINAL_LOGIN_ARGUMENTS = ("-l",)

# A login shell that only refuses a session.
TERMINAL_NOLOGIN_MARK = "nologin"
