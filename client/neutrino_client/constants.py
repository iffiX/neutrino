"""Fixed values of the client.

Anything a person changes lives in the client's own configuration directory;
this file holds only what is wired into the protocol and the desktop.
"""

# The languages every localized surface offers; anything else reads as the
# default.
CLIENT_LANGUAGES = ("en", "zh-CN")
CLIENT_DEFAULT_LANGUAGE = "en"

# The palettes the window draws itself in; ``system`` follows the desktop's
# own scheme, and anything else reads as the default.
CLIENT_THEMES = ("system", "dark", "light")
CLIENT_DEFAULT_THEME = "dark"

# The protocol number this build speaks. The name has no package prefix:
# one number has one name in every package.
PROTOCOL = 1
CLIENT_ROLE = "client"
# What ``software`` reads in the join body and the hello, before the version.
CLIENT_SOFTWARE_PREFIX = "neutrino_client/"
# The refusals the hub answers a protocol number it does not speak with.
CLIENT_PROTOCOL_REFUSAL_CODES = ("protocol_too_old", "protocol_too_new")
# The one refusal that unbinds: the hub holds no such binding.
CLIENT_REFUSAL_CODE_BINDING_UNKNOWN = "binding_unknown"

# What the hub answers as in its welcome.
CLIENT_HUB_ROLE = "hub"

# The hub's channel, on the pinned-TLS agent port. Joining and leaving are
# HTTP; everything else rides the one socket.
CLIENT_JOIN_PATH = "/api/channel/join"
CLIENT_LEAVE_PATH = "/api/channel/leave"
CLIENT_CHANNEL_WS_PATH = "/api/channel/socket"

# The one stream kind a client opens, and the code it closes a stream the
# hub opened with.
CLIENT_STREAM_KIND_SERVICE = "service"
CLIENT_STREAM_CODE_KIND_UNKNOWN = "kind_unknown"

# How often an unbound resident looks at its configuration again.
CLIENT_IDLE_POLL_INTERVAL_S = 2
CLIENT_REQUEST_TIMEOUT_S = 10
CLIENT_BACKOFF_MIN_S = 5
CLIENT_BACKOFF_MAX_S = 60

# How long the open socket may stay silent before it counts as dead.
CLIENT_WS_SILENCE_TIMEOUT_S = 45
# How long connecting to the hub and the handshake on top of it may take
# together, before the socket is open and the silence window takes over.
CLIENT_CONNECT_TIMEOUT_S = 10
# How often a report goes up while nothing changes.
CLIENT_REPORT_INTERVAL_S = 30
# How long a stream this side opened waits for the hub's close.
CLIENT_STREAM_TIMEOUT_S = 15

# What the hub's close codes mean: a refused hello, and a second socket for
# the same binding replacing this one.
CLIENT_WS_CLOSE_REFUSED = 4000
CLIENT_WS_CLOSE_REPLACED = 4010

# The files under the platform's configuration directory.
CLIENT_CONFIG_FILE_NAME = "client.json"
CLIENT_STATE_FILE_NAME = "state.json"
CLIENT_MOUNT_CREDENTIALS_DIR_NAME = "mount_credentials"
# Where a tool's own configuration is kept while the hub has replaced it.
CLIENT_ORIGINAL_DIR_NAME = "original"

# The local control channel: a per-person socket the CLI and the window
# reach the resident over.
CLIENT_CONTROL_SOCKET_NAME = "neutrino_client.sock"
CLIENT_CONTROL_PIPE_PREFIX = "\\\\.\\pipe\\"
CLIENT_CONTROL_PIPE_NAME_PREFIX = "neutrino_client_"
CLIENT_CONTROL_REQUEST_TIMEOUT_S = 5

# The name the packages install the launcher and the icon under.
CLIENT_DESKTOP_NAME = "neutrino_client"
# What the window and the tray say, as catalog keys: the words themselves
# are in the catalogs, in every language the client offers.
CLIENT_GUI_WINDOW_TITLE_KEY = "ui.window.title"
CLIENT_TRAY_OPEN_LABEL_KEY = "ui.tray.open"
CLIENT_TRAY_QUIT_LABEL_KEY = "ui.tray.quit"
CLIENT_GUI_WINDOW_WIDTH = 760
CLIENT_GUI_WINDOW_HEIGHT = 900
# The WebKit2 ABIs the Linux window opens on, newest first: each API version
# with the library carrying it. 4.1 is the libsoup3 ABI and 4.0 the libsoup2
# one; a distribution carries one, the other, or both.
CLIENT_WEBKITGTK_ABIS = (
    ("4.1", "libwebkit2gtk-4.1.so.0"),
    ("4.0", "libwebkit2gtk-4.0.so.37"),
)

# Where the packages install the client and the binaries it carries.
CLIENT_INSTALL_PREFIX_LINUX = "/opt/neutrino_client"
CLIENT_BUNDLED_PATHS_LINUX = {
    "cc-switch": "bin/cc-switch",
    "rustdesk": "rustdesk/rustdesk",
}
CLIENT_BUNDLED_PATHS_WINDOWS = {
    "cc-switch": "bin\\cc-switch.exe",
    "rustdesk": "bin\\rustdesk.exe",
}
# Under the app bundle's Contents directory, beside the MacOS directory the
# compiled package runs from.
CLIENT_BUNDLED_PATHS_DARWIN = {
    "cc-switch": "Resources/bin/cc-switch",
    "rustdesk": "Resources/rustdesk/RustDesk.app/Contents/MacOS/RustDesk",
}

# The root helper a mount goes through on Linux, and the polkit action that
# gates it.
CLIENT_MOUNT_HELPER_PATH = "/usr/libexec/neutrino_client/mount_helper"
CLIENT_MOUNT_POLKIT_ACTION = "com.neutrino.client.mount"
# What each helper exit status means; pkexec's own 126 and 127 mean the
# person declined or was not allowed.
CLIENT_MOUNT_HELPER_EXIT_CODES = {
    2: "mount_not_authorized",
    3: "mountpoint_invalid",
    4: "mountpoint_not_empty",
    5: "credentials_missing",
    6: "mount_failed",
    7: "unmount_failed",
}
CLIENT_PKEXEC_REFUSAL_EXIT_CODES = (126, 127)

# How often a record this run attached and lost is mounted again.
CLIENT_MOUNT_RECHECK_INTERVAL_S = 60

# How long the four release steps of a quit are given together. A step past
# its share of what is left is given up and the next one runs.
CLIENT_SHUTDOWN_DEADLINE_S = 10

# The resident's own log, beside its state; one file, kept to a size, the
# previous one beside it. A window process has no terminal to speak to.
CLIENT_LOG_FILE_NAME = "client.log"
CLIENT_LOG_KEEP_BYTES = 1024 * 1024
