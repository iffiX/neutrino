"""Names shared by the platform layer."""

import re

PLATFORM_OS_LINUX = "linux"
PLATFORM_OS_DARWIN = "darwin"
PLATFORM_OS_WINDOWS = "windows"
PLATFORM_OS_KEYS = (PLATFORM_OS_LINUX, PLATFORM_OS_DARWIN, PLATFORM_OS_WINDOWS)

# The five roots, by the question each answers; design/files.md.
PLATFORM_ROOT_STATIC = "static"
PLATFORM_ROOT_CONFIG = "config"
PLATFORM_ROOT_STATE = "state"
PLATFORM_ROOT_LOG = "log"
PLATFORM_ROOT_RUNTIME = "runtime"
PLATFORM_ROOTS = {
    PLATFORM_OS_LINUX: {
        PLATFORM_ROOT_STATIC: "/opt/neutrino/hub",
        PLATFORM_ROOT_CONFIG: "/etc/neutrino/hub",
        PLATFORM_ROOT_STATE: "/var/lib/neutrino/hub",
        PLATFORM_ROOT_LOG: "/var/log/neutrino/hub",
        PLATFORM_ROOT_RUNTIME: "/run/neutrino/hub",
    },
    PLATFORM_OS_DARWIN: {
        PLATFORM_ROOT_STATIC: "/Library/Application Support/Neutrino/hub/app",
        PLATFORM_ROOT_CONFIG: "/Library/Application Support/Neutrino/hub/config",
        PLATFORM_ROOT_STATE: "/Library/Application Support/Neutrino/hub/state",
        PLATFORM_ROOT_LOG: "/Library/Logs/Neutrino/hub",
        PLATFORM_ROOT_RUNTIME: "/var/run/neutrino/hub",
    },
    PLATFORM_OS_WINDOWS: {
        PLATFORM_ROOT_STATIC: "C:\\Program Files\\Neutrino\\hub",
        PLATFORM_ROOT_CONFIG: "C:\\ProgramData\\Neutrino\\hub\\config",
        PLATFORM_ROOT_STATE: "C:\\ProgramData\\Neutrino\\hub\\state",
        PLATFORM_ROOT_LOG: "C:\\ProgramData\\Neutrino\\hub\\log",
        PLATFORM_ROOT_RUNTIME: "C:\\ProgramData\\Neutrino\\hub\\run",
    },
}

# Where a Unix system names the resolvers it asks, first match wins:
# systemd-resolved's list of its upstreams, then the file every resolver
# library reads, which on such a machine names only resolved's stub.
PLATFORM_RESOLVER_FILES = ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf")
# The resolvers Windows asks: every connected adapter's, by interface metric.
PLATFORM_WINDOWS_RESOLVERS_SCRIPT = """
$metric = @{}
Get-NetIPInterface -AddressFamily IPv4 -ConnectionState Connected |
    ForEach-Object { $metric[$_.InterfaceIndex] = $_.InterfaceMetric }
$servers = @(Get-DnsClientServerAddress -AddressFamily IPv4 |
    Where-Object { $metric.ContainsKey($_.InterfaceIndex) } |
    Sort-Object { $metric[$_.InterfaceIndex] } |
    ForEach-Object { $_.ServerAddresses })
@{ servers = $servers } | ConvertTo-Json -Compress
"""

# The one service the hub registers on macOS and Windows.
PLATFORM_DARWIN_SERVICE_LABEL = "com.neutrino.hub"
PLATFORM_DARWIN_SERVICE_TARGET = f"system/{PLATFORM_DARWIN_SERVICE_LABEL}"
PLATFORM_DARWIN_SERVICE_PLIST = (
    f"/Library/LaunchDaemons/{PLATFORM_DARWIN_SERVICE_LABEL}.plist"
)
PLATFORM_DARWIN_STATE_PATTERN = re.compile(r"^\s*state\s*=\s*(\S+)", re.MULTILINE)
PLATFORM_WINDOWS_SERVICE_NAME = "neutrino_hub"
PLATFORM_WINDOWS_STATE_PATTERN = re.compile(r"STATE\s*:\s*(\d+)")
PLATFORM_WINDOWS_SERVICE_STATES = {
    1: "stopped",
    2: "start_pending",
    3: "stop_pending",
    4: "running",
    5: "continue_pending",
    6: "pause_pending",
    7: "paused",
}
# The words every platform uses for the one service's state.
PLATFORM_SERVICE_RUNNING = "running"
PLATFORM_SERVICE_STOPPED = "stopped"
PLATFORM_SERVICE_UNKNOWN = "unknown"
PLATFORM_COMMAND_TIMEOUT_S = 30
# How long a stop is waited for before the start that follows it.
PLATFORM_SERVICE_WAIT_S = 30
PLATFORM_SERVICE_POLL_S = 0.5
PLATFORM_SERVICE_STOP_PENDING = "stop_pending"
# How long the Windows service, once asked to stop, waits for the panel and
# its children to end before it reports stopped; under the 30 s wait hint.
PLATFORM_WINDOWS_SERVICE_STOP_WAIT_S = 25

# Where the hub's own NetBird daemon answers, apart from the vendor's default
# a client's NetBird on the same machine keeps.
PLATFORM_NETBIRD_SOCKET_NAME = "netbird.sock"
PLATFORM_NETBIRD_DAEMON_PORT_WINDOWS = 41732

# The agent's command once its package is installed.
PLATFORM_AGENT_COMMANDS = {
    PLATFORM_OS_LINUX: "nagent",
    PLATFORM_OS_DARWIN: "/usr/local/bin/nagent",
    PLATFORM_OS_WINDOWS: "C:\\Program Files\\Neutrino\\agent\\nagent.exe",
}

# What opens a page: on a Linux desktop through the signed-in account's
# session bus, on a Mac through LaunchServices.
PLATFORM_LINUX_BROWSER_OPENER = "xdg-open"
PLATFORM_LINUX_USER_RUNTIME_ROOT = "/run/user"
PLATFORM_BROWSER_TIMEOUT_S = 5
PLATFORM_DARWIN_BROWSER_OPENER = "open"
# Where the signed-in account on a Mac is read from, when sudo names none.
PLATFORM_DARWIN_CONSOLE = "/dev/console"
# What opens a page from an elevated Windows process, as the signed-in
# account rather than as the administrator.
PLATFORM_WINDOWS_SHELL = "explorer.exe"

# What asks the person for the rights to run nhub elevated.
PLATFORM_LINUX_ELEVATOR = "pkexec"
PLATFORM_DARWIN_ELEVATOR = "osascript"

# A child started with no console window of its own.
PLATFORM_WINDOWS_CREATE_NO_WINDOW = 0x08000000
# A file readable by SYSTEM (S-1-5-18) and the Administrators group
# (S-1-5-32-544) alone, with nothing inherited from its folder; OpenSSH's
# ssh.exe refuses a key file any other account can read.
PLATFORM_WINDOWS_ICACLS = "icacls.exe"
PLATFORM_WINDOWS_ROOT_ONLY_ACL = (
    "/inheritance:r",
    "/grant:r",
    "*S-1-5-18:F",
    "*S-1-5-32-544:F",
)
# The proactor callback that raises when a browser drops its connection.
PLATFORM_WINDOWS_CONNECTION_LOST_CALLBACK = "_call_connection_lost"

# How often the service on macOS and Windows looks for the configuration
# before nhub setup has written it.
PLATFORM_SETUP_POLL_S = 5
