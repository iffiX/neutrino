"""Fixed values of the account service layer: the names a module's services
take on each system, and where their definitions and their logs are written."""

# Linux: one template unit per module, systemd's ``%i`` standing for the
# instance's account, and one environment file per instance.
ACCOUNT_SERVICE_SYSTEMD_DIR = "/etc/systemd/system"
ACCOUNT_SERVICE_UNIT_PREFIX = "neutrino_"
ACCOUNT_SERVICE_UNIT_SUFFIX = ".service"
ACCOUNT_SERVICE_TEMPLATE_ACCOUNT = "%i"
ACCOUNT_SERVICE_ENVIRONMENT_SUFFIX = ".env"

# macOS: one LaunchDaemon per instance, its output in its own log file.
ACCOUNT_SERVICE_LAUNCHD_DIR = "/Library/LaunchDaemons"
ACCOUNT_SERVICE_LAUNCHD_PREFIX = "com.neutrino."
ACCOUNT_SERVICE_PLIST_SUFFIX = ".plist"
ACCOUNT_SERVICE_DARWIN_LOG_DIR = "/Library/Logs/Neutrino/agent"

# Windows: one scheduled task per instance under the account's login, run
# through the command interpreter so its output lands in its log beside the
# program; a service with an environment runs a script under ``run``.
ACCOUNT_SERVICE_TASK_PREFIX = "neutrino_"
ACCOUNT_SERVICE_TASK_MARKER = "neutrino:"
ACCOUNT_SERVICE_WINDOWS_SHELL = "cmd.exe"
ACCOUNT_SERVICE_WINDOWS_SCRIPT_DIR_NAME = "run"
ACCOUNT_SERVICE_WINDOWS_SCRIPT_SUFFIX = ".cmd"
# Where a task's output goes when the service discards it.
ACCOUNT_SERVICE_WINDOWS_NULL_DEVICE = "NUL"
# The name an older build gave the inbound firewall rule of an instance's
# port, between the module's name and the port; every rule under it goes.
ACCOUNT_SERVICE_WINDOWS_RULE_INFIX = "_port_"
# What a task's last result is when Windows could not sign its account in.
ACCOUNT_SERVICE_LOGON_FAILURES = (0x8007052E,)

# The end of every instance's log file.
ACCOUNT_SERVICE_LOG_SUFFIX = ".log"
