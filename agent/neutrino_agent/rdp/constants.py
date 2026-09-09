"""Fixed values of the desktop share."""

# The module a share cannot work without, named the way every other
# dependency is.
RDP_MODULE_NAME = "rustdesk"

# What sharing looks like from here. ``starting`` is a configured share that
# is not yet answering.
RDP_STATE_NOT_SHARED = "not_shared"
RDP_STATE_SHARING = "sharing"
RDP_STATE_STARTING = "starting"

# Where the access password is kept, mode 0600 under the agent's own root.
RDP_PASSWORD_FILE = "rdp_access_password"

# How long a probe of the direct port is believed. The heartbeat reads every
# few seconds, and nothing wants a connect attempt each time.
RDP_PROBE_TTL_S = 3.0
RDP_PROBE_TIMEOUT_S = 1.0
RDP_PROBE_HOST = "127.0.0.1"

# How long the answer to "what would a peer wait on" is believed. Reading it
# asks the session table and a file, and the heartbeat asks every few
# seconds; nothing about a seat changes faster than this.
RDP_ATTENTION_TTL_S = 15.0

# What a session's type has to be for there to be a desktop to share, and how
# long the machine's own session list is waited for.
RDP_GRAPHICAL_SESSION_TYPES = ("x11", "wayland", "mir")
RDP_SESSION_TIMEOUT_S = 5

# What a window needs to open on the seat's screen, read from the session's
# own processes — the same place RustDesk's service reads it before spawning
# its screen server into the session.
RDP_SESSION_ENVIRONMENT_KEYS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
)
RDP_PROC_DIR = "/proc"

# The option RustDesk stores the screen-capture permission under once a
# person has granted it. Wayland asks for that permission on the shared
# machine's own screen, so until it is there every connection waits on a
# dialog only somebody sitting at that machine can answer.
RDP_WAYLAND_TOKEN_OPTION = "wayland-restore-token"

# The greeter's session owns a home on a tmpfs, so it can hold no such
# permission and a peer would wait for a dialog nobody is there to answer.
RDP_GREETER_ACCOUNTS = ("gdm", "gdm-greeter", "sddm", "lightdm", "greetd")

# What a peer would wait on if it dialed now. Typed, like every refusal:
# each surface words them itself.
RDP_ATTENTION_NOBODY_SEATED = "rdp_nobody_seated"
RDP_ATTENTION_SCREEN_NOT_ALLOWED = "rdp_screen_not_allowed"
