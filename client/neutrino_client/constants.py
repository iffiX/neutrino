"""Fixed values of the client.

Anything a person changes lives in the client's own configuration directory;
this file holds only what is wired into the protocol and the desktop.
"""

# The hub's client channel, on the pinned-TLS agent port.
CLIENT_ENROLL_PATH = "/api/client/enroll"
CLIENT_POLL_PATH = "/api/client/poll"
CLIENT_RDP_CONNECT_PATH = "/api/client/rdp_connect"
CLIENT_LEAVE_PATH = "/api/client/leave"

# How many polls in a row the hub may reject before the client drops its
# binding. One counter for every kind of rejection.
CLIENT_REFUSALS_BEFORE_UNBIND = 3

CLIENT_POLL_INTERVAL_S = 5
# How often an unbound resident looks at its configuration again.
CLIENT_IDLE_POLL_INTERVAL_S = 2
CLIENT_REQUEST_TIMEOUT_S = 10
CLIENT_BACKOFF_MIN_S = 5
CLIENT_BACKOFF_MAX_S = 60

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

# The window ``nclient gui`` opens, and the name the packages install its
# launcher and icon under.
CLIENT_GUI_WINDOW_TITLE = "Neutrino client"
CLIENT_DESKTOP_NAME = "neutrino_client"
CLIENT_GUI_WINDOW_WIDTH = 760
CLIENT_GUI_WINDOW_HEIGHT = 900

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

# How often enabled mount records that are not attached are remounted.
CLIENT_MOUNT_RECHECK_INTERVAL_S = 60
