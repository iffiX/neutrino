"""Fixed values of the Remote desktop module: the agent's copy of RustDesk,
where it is registered under RustDesk's own names, and what is kept aside."""

REMOTE_DESKTOP_NAME = "remote_desktop"
REMOTE_DESKTOP_KIND = "remote_desktop"

# Under the state root: what the module registered, and what it found
# registered under RustDesk's names and moved aside.
REMOTE_DESKTOP_DIR_NAME = "remote_desktop"
REMOTE_DESKTOP_REGISTERED_NAME = "registered.json"
REMOTE_DESKTOP_KEPT_DIR_NAME = "kept"
REMOTE_DESKTOP_KEPT_SERVICE_NAME = "service.json"
REMOTE_DESKTOP_KEPT_SETTINGS_DIR_NAME = "settings"
# The lock every process takes before it changes RustDesk's registration.
REMOTE_DESKTOP_LOCK_NAME = ".lock"

# The port a direct connection lands on.
REMOTE_DESKTOP_DIRECT_PORT = 21118
# What a peer is never sent through: the rendezvous and relay servers are
# the machine's own loopback, where nothing answers, since an empty value
# means upstream's public servers.
REMOTE_DESKTOP_NO_SERVER = "127.0.0.1"

# RustDesk's two settings files.
REMOTE_DESKTOP_OPTIONS_FILE = "RustDesk2.toml"
REMOTE_DESKTOP_PASSWORD_FILE = "RustDesk.toml"  # scan: allow

# What a share writes into RustDesk2.toml: direct connection on the port
# above with a permanent password, no rendezvous and no relay, file transfer
# and the clipboard on, the channels the hub does not publish off.
REMOTE_DESKTOP_OPTIONS = (
    ("custom-rendezvous-server", REMOTE_DESKTOP_NO_SERVER),
    ("relay-server", REMOTE_DESKTOP_NO_SERVER),
    ("direct-server", "Y"),
    ("direct-access-port", str(REMOTE_DESKTOP_DIRECT_PORT)),
    ("allow-auto-update", "N"),
    ("verification-method", "use-permanent-password"),
    ("approve-mode", "password"),
    ("enable-file-transfer", "Y"),
    ("enable-tunnel", "N"),
    ("enable-audio", "N"),
)

# The flags a RustDesk process runs as a viewer with: one a person may be
# using, which a takeover leaves running.
REMOTE_DESKTOP_VIEWER_FLAGS = (
    "--connect",
    "--play",
    "--file-transfer",
    "--port-forward",
    "--rdp",
    "--view-camera",
    "--terminal",
)

# How long a stopped service or job is waited for, and how often it is
# asked.
REMOTE_DESKTOP_STOP_TIMEOUT_S = 30
REMOTE_DESKTOP_POLL_S = 0.5
REMOTE_DESKTOP_COMMAND_TIMEOUT_S = 60
# How long the socket table is believed: the report reads it every few
# seconds.
REMOTE_DESKTOP_LISTEN_TTL_S = 3.0

# Linux: the agent's copy, the unit it writes under RustDesk's own name,
# which overrides a packaged one, and the settings of root and the seat.
REMOTE_DESKTOP_LINUX_PROGRAM = "/usr/lib/neutrino/agent/rustdesk/rustdesk"
REMOTE_DESKTOP_LINUX_UNIT = "rustdesk.service"
REMOTE_DESKTOP_LINUX_UNIT_PATH = "/etc/systemd/system/rustdesk.service"
REMOTE_DESKTOP_LINUX_ROOT_SETTINGS = "/root/.config/rustdesk"
REMOTE_DESKTOP_LINUX_SEAT_SETTINGS = ".config/rustdesk"
REMOTE_DESKTOP_LINUX_UNIT_TEXT = """# Written by the Neutrino agent while this machine's desktop is shared.
[Unit]
Description=RustDesk, the Neutrino agent's copy
Requires=network.target
After=systemd-user-sessions.service

[Service]
Type=simple
ExecStart={program} --service
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
User=root
LimitNOFILE=100000
Environment="PULSE_LATENCY_MSEC=60" "PIPEWIRE_LATENCY=1024/48000"

[Install]
WantedBy=multi-user.target
"""

# macOS: the agent's copy, the two jobs under upstream's
# labels and file names, and the settings of root and the seat.
REMOTE_DESKTOP_DARWIN_APP = (
    "/Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app"
)
REMOTE_DESKTOP_DARWIN_SERVICE_LABEL = "com.carriez.RustDesk_service"
REMOTE_DESKTOP_DARWIN_SERVICE_PLIST = (
    "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist"
)
REMOTE_DESKTOP_DARWIN_SESSION_LABEL = "com.carriez.RustDesk_server"
REMOTE_DESKTOP_DARWIN_SESSION_PLIST = (
    "/Library/LaunchAgents/com.carriez.RustDesk_server.plist"
)
REMOTE_DESKTOP_DARWIN_ROOT_SETTINGS = (
    "/var/root/Library/Preferences/com.carriez.RustDesk"
)
REMOTE_DESKTOP_DARWIN_SEAT_SETTINGS = "Library/Preferences/com.carriez.RustDesk"
# What a RustDesk program's path holds on a Mac, whoever's bundle it is.
REMOTE_DESKTOP_DARWIN_PROGRAM_MARK = ".app/Contents/MacOS/"

# Windows: the agent's copy under its own program folder, the service
# under RustDesk's own name, and LocalService's settings.
REMOTE_DESKTOP_WINDOWS_PROGRAM_PARTS = ("Neutrino", "agent", "rustdesk", "rustdesk.exe")
REMOTE_DESKTOP_WINDOWS_PROGRAM_FILES_DEFAULT = "C:\\Program Files"
REMOTE_DESKTOP_WINDOWS_SERVICE = "RustDesk"
REMOTE_DESKTOP_WINDOWS_DISPLAY_NAME = "RustDesk Service"
REMOTE_DESKTOP_WINDOWS_SYSTEM_ROOT_DEFAULT = "C:\\Windows"
REMOTE_DESKTOP_WINDOWS_SETTINGS_PARTS = (
    "ServiceProfiles",
    "LocalService",
    "AppData",
    "Roaming",
    "RustDesk",
    "config",
)
REMOTE_DESKTOP_WINDOWS_PROGRAM_NAME = "rustdesk.exe"
# What sc.exe exits with for a service that does not exist.
REMOTE_DESKTOP_WINDOWS_NO_SERVICE = 1060
