"""Fixed values of the desktop share."""

# The module a share cannot work without, named the way every other
# dependency is.
RDP_MODULE_NAME = "rustdesk"

# What sharing looks like from here. ``starting`` is a configured share that
# is not yet answering.
RDP_STATE_NOT_SHARED = "not_shared"
RDP_STATE_SHARING = "sharing"
RDP_STATE_STARTING = "starting"

# Where the seat password last set into RustDesk is kept, mode 0600 under
# the agent's own root.
RDP_PASSWORD_FILE = "rdp_access_password"

# Where the kernel lists this machine's connections, and the state word an
# established one carries. A peer that has dialed the direct port is one row
# of these.
RDP_PROC_TCP_PATHS = ("/proc/net/tcp", "/proc/net/tcp6")
RDP_TCP_ESTABLISHED = "01"

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

# Where Windows lists its connections, and how it spells an established one.
RDP_WINDOWS_NETSTAT_COMMAND = ("netstat", "-an", "-p", "TCP")
RDP_WINDOWS_ESTABLISHED = "ESTABLISHED"
# What WTS answers when no session is attached to the console, and the one
# piece of a session this reads.
RDP_WINDOWS_NO_CONSOLE_SESSION = 0xFFFFFFFF
RDP_WINDOWS_WTS_USER_NAME = 5

# Who owns the Mac's console: the account signed in at its screen, or root
# at the login window.
RDP_DARWIN_CONSOLE_OWNER_COMMAND = ("stat", "-f", "%Su", "/dev/console")
RDP_DARWIN_LOGIN_WINDOW_OWNER = "root"
RDP_DARWIN_NETSTAT_COMMAND = ("netstat", "-an", "-p", "tcp")
RDP_DARWIN_ESTABLISHED = "ESTABLISHED"
# What a share start puts on a Mac's screen: a dialog naming the two
# permissions RustDesk needs, and the Screen Recording pane of the system
# settings. Both run as the account in its own session, never waited for.
RDP_DARWIN_PERMISSIONS_TEXT = (
    "Before anyone connecting can see and use this Mac, RustDesk needs two "
    "permissions: Screen Recording and Accessibility. Turn both on for "
    "RustDesk in System Settings, Privacy & Security."
)
RDP_DARWIN_DIALOG_TITLE = "Neutrino"
RDP_DARWIN_DIALOG_GIVE_UP_S = 60
RDP_DARWIN_DIALOG_SCRIPT = (
    f'display dialog "{RDP_DARWIN_PERMISSIONS_TEXT}" '
    f'with title "{RDP_DARWIN_DIALOG_TITLE}" buttons {{"OK"}} '
    f'default button "OK" with icon caution '
    f"giving up after {RDP_DARWIN_DIALOG_GIVE_UP_S}"
)
RDP_DARWIN_SCREEN_RECORDING_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)
RDP_DARWIN_LAUNCHCTL = "/bin/launchctl"
RDP_DARWIN_CHROOT = "/usr/sbin/chroot"
RDP_DARWIN_OSASCRIPT = "/usr/bin/osascript"
RDP_DARWIN_OPEN = "/usr/bin/open"
RDP_DARWIN_SESSION_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
# How long the dialog and the settings pane are each let run before they
# are ended.
RDP_DARWIN_DIALOG_TIMEOUT_S = RDP_DARWIN_DIALOG_GIVE_UP_S + 15
RDP_DARWIN_OPEN_TIMEOUT_S = 15
