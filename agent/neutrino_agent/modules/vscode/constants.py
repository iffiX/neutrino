"""Fixed values of the VS Code module."""

# The recipe kind and the module's name on the wire.
VSCODE_KIND = "vscode"
VSCODE_NAME = "vscode"

# The CLI's own name inside the archive Microsoft publishes, by system.
VSCODE_CLI_NAMES = {"windows": "code.exe", "linux": "code", "darwin": "code"}
# The archive kinds a manifest entry names in ``package_kind``.
VSCODE_PACKAGE_TAR = "tar"
VSCODE_PACKAGE_ZIP = "zip"
# Where the CLI lives on Linux; on Windows and macOS it is this directory's
# name under the platform's hub package root.
VSCODE_LINUX_DIR = "/usr/local/lib/neutrino_vscode"
VSCODE_DIR_NAME = "vscode"
# Where the token files live on Linux; elsewhere beside the CLI.
VSCODE_LINUX_TOKEN_DIR = "/etc/neutrino/vscode"
VSCODE_TOKEN_DIR_NAME = "tokens"

# What every instance runs after the CLI's path.
VSCODE_SERVE_ARGUMENTS = ("serve-web", "--accept-server-license-terms")
# The address an instance listens on when the hub names none.
VSCODE_ANY_ADDRESS = "0.0.0.0"
VSCODE_PORT_MIN = 1024
VSCODE_PORT_MAX = 65535

# Linux: one systemd unit per account, from a template.
VSCODE_UNIT_TEMPLATE = "neutrino_vscode@.service"
VSCODE_UNIT_PREFIX = "neutrino_vscode@"
VSCODE_SYSTEMD_DIR = "/etc/systemd/system"

# macOS: one LaunchDaemon per account.
VSCODE_LAUNCHD_PREFIX = "com.neutrino.vscode."
VSCODE_LAUNCHD_DIR = "/Library/LaunchDaemons"

# Windows: one scheduled task per account, started at boot with its login.
VSCODE_TASK_PREFIX = "neutrino_vscode_"
VSCODE_TASK_MARKER = "neutrino:"
# What a task's last result is when Windows could not sign its account in.
VSCODE_LOGON_FAILURES = (0x8007052E,)

# How long one reading of the instances is believed.
VSCODE_STATUS_TTL_S = 30.0
