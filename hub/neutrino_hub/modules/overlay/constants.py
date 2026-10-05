"""Fixed values of the overlay module."""

from dataclasses import dataclass

from neutrino_hub import edition

# What a machine may be reachable through from outside the building. Any of
# them, all at once or none; the engine table's order is the order the panel
# draws them and the order a client is handed their material in.
OVERLAY_NETBIRD = "netbird"
OVERLAY_EASYTIER = "easytier"

# The unit the EasyTier engine becomes, named here because the overlay module
# owns the table; the module that drives it reads the name from here.
OVERLAY_EASYTIER_UNIT = "neutrino_hub_easytier.service"


@dataclass(frozen=True)
class OverlayEngine:
    """One overlay implementation this hub can run.

    Attributes:
        key: What the configuration stores.
        title: The product's own name, which is the same in every language.
        device_name: The kernel interface the hub names for it, which the
            firewall rules name. EasyTier in console mode picks its own, and
            that one is found at run time by the address it holds.
        peer_port: The UDP port its own peers knock on.
        unit: The systemd unit the hub drives it under.
        subnet: The network its addresses come from when the product fixes
            one; empty when the network is configured or found at run time.
        is_integrated: Whether this hub can actually run it yet. An engine
            that is named but not integrated is offered and refused, rather
            than hidden: the choice is what the page is about, and a missing
            third option reads as a hub that cannot have one.
    """

    key: str
    title: str
    device_name: str
    peer_port: int
    unit: str
    subnet: str
    is_integrated: bool


# NetBird's row is NetBird's own, and present where the tree carries it.
OVERLAY_ENGINES = {
    **{
        key: OverlayEngine(key=key, **fields)
        for key, fields in edition.hooks("overlay_engines")
    },
    OVERLAY_EASYTIER: OverlayEngine(
        key=OVERLAY_EASYTIER,
        title="EasyTier",
        device_name="easytier",
        peer_port=11010,
        unit=OVERLAY_EASYTIER_UNIT,
        subnet="",
        is_integrated=True,
    ),
}

# How long an engine just started is given to hold an address before the
# converge step goes on without it.
OVERLAY_ADDRESS_WAIT_S = 20.0
OVERLAY_ADDRESS_POLL_S = 0.5

# A route an overlay installs for every address. The hub's way out is its own
# uplink, so such a route is deleted wherever it appears.
OVERLAY_DEFAULT_ROUTE = "0.0.0.0/0"

# Direct: the agent port opened on every enabled interface, and the public
# address the person states for the hub. A way in beside the engines, not an
# engine, so it is not a row of the engine table.
OVERLAY_DIRECT = "direct"
OVERLAY_DIRECT_TITLE = "Direct"
OVERLAY_DIRECT_CONFIG_NAME = "overlay/direct.json"
OVERLAY_DIRECT_DEFAULT_PUBLIC_PORT = 8443
OVERLAY_DIRECT_PORT_MIN = 1
OVERLAY_DIRECT_PORT_MAX = 65535
# How Direct stands with the hub's interface addresses: it adds some; it adds
# none because every one already answers on the agent port; no interface has
# an address.
OVERLAY_DIRECT_INTERFACES_ADDED = "added"
OVERLAY_DIRECT_INTERFACES_EXPOSED = "exposed"
OVERLAY_DIRECT_INTERFACES_NONE = "none"
# The longest host name DNS carries.
OVERLAY_DIRECT_HOST_MAX = 253

# The relay: a reverse SSH forward from this box to a server the person owns.
# It is a way in beside the engines, not an engine, so it is not a row of the
# engine table.
OVERLAY_RELAY = "relay"
OVERLAY_RELAY_TITLE = "SSH Relay"
OVERLAY_RELAY_CONFIG_NAME = "overlay/relay.json"
OVERLAY_RELAY_DEFAULT_SSH_PORT = 22
OVERLAY_RELAY_DEFAULT_PUBLIC_PORT = 8443
OVERLAY_RELAY_PORT_MIN = 1
OVERLAY_RELAY_PORT_MAX = 65535
# The name the process controller knows the relay by: the unit
# neutrino_hub_relay.service on Linux, a child of the hub's service elsewhere.
OVERLAY_RELAY_SERVICE_NAME = "relay"
OVERLAY_RELAY_UNIT = "neutrino_hub_relay.service"
# Under the state root: the key file ssh reads and the host key it records.
OVERLAY_RELAY_DIR_NAME = "relay"
OVERLAY_RELAY_KEY_NAME = "key"
OVERLAY_RELAY_KNOWN_HOSTS_NAME = "known_hosts"
OVERLAY_RELAY_DIR_MODE = 0o700
OVERLAY_RELAY_FILE_MODE = 0o600
# With a login: the password file, and the program ssh asks for it, which
# prints that file. Windows runs a command script.
OVERLAY_RELAY_PASSWORD_NAME = "password"
OVERLAY_RELAY_ASKPASS_NAME = "askpass"
OVERLAY_RELAY_ASKPASS_WINDOWS_NAME = "askpass.cmd"
OVERLAY_RELAY_ASKPASS_MODE = 0o700
# The system's OpenSSH client: found on the path on Linux and macOS, at this
# place under the system root on Windows.
OVERLAY_RELAY_SSH_NAME = "ssh"
OVERLAY_RELAY_WINDOWS_SSH = ("System32", "OpenSSH", "ssh.exe")
OVERLAY_RELAY_WINDOWS_ROOT_ENV = "SystemRoot"
OVERLAY_RELAY_WINDOWS_ROOT_DEFAULT = "C:\\Windows"
# The options of the start line, in the order network.md gives them.
OVERLAY_RELAY_SSH_OPTIONS = (
    "ExitOnForwardFailure=yes",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "ConnectTimeout=15",
    "BatchMode=yes",
    "IdentitiesOnly=yes",
    "StrictHostKeyChecking=accept-new",
)
OVERLAY_RELAY_KNOWN_HOSTS_OPTION = "UserKnownHostsFile"
# The options a start line with a login takes in place of the key's
# BatchMode and IdentitiesOnly: a password asked once, through askpass.
OVERLAY_RELAY_PASSWORD_SSH_OPTIONS = (
    "ExitOnForwardFailure=yes",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "ConnectTimeout=15",
    "BatchMode=no",
    "PubkeyAuthentication=no",
    "PreferredAuthentications=password,keyboard-interactive",
    "NumberOfPasswordPrompts=1",
    "StrictHostKeyChecking=accept-new",
)
# The environment that start line runs with. SSH_ASKPASS_REQUIRE is OpenSSH
# 8.4's; an older ssh asks the askpass program when it has no terminal and
# DISPLAY is set.
OVERLAY_RELAY_ASKPASS_ENV = "SSH_ASKPASS"
OVERLAY_RELAY_ASKPASS_REQUIRE_ENV = "SSH_ASKPASS_REQUIRE"
OVERLAY_RELAY_ASKPASS_REQUIRE = "force"
OVERLAY_RELAY_DISPLAY_ENV = "DISPLAY"
OVERLAY_RELAY_DISPLAY = "neutrino"
OVERLAY_RELAY_LISTEN_ADDRESS = "0.0.0.0"
OVERLAY_RELAY_TARGET_ADDRESS = "127.0.0.1"

# The self-check: the hub dials its own public address and compares the
# certificate it meets with its own agent certificate.
OVERLAY_RELAY_CHECK_FIRST_S = 5.0
OVERLAY_RELAY_CHECK_INTERVAL_S = 60.0
OVERLAY_RELAY_CHECK_TIMEOUT_S = 10.0
# How often the monitor reads the process.
OVERLAY_RELAY_TICK_S = 1.0
# How many of ssh's last lines are read back after an exit.
OVERLAY_RELAY_LOG_LINES = 20

# The relay's states, network.md "The states".
OVERLAY_RELAY_STATE_DISABLED = "disabled"
OVERLAY_RELAY_STATE_NOT_CONFIGURED = "not_configured"
OVERLAY_RELAY_STATE_VAULT_LOCKED = "vault_locked"
OVERLAY_RELAY_STATE_CONNECTING = "connecting"
OVERLAY_RELAY_STATE_CONNECTED = "connected"
OVERLAY_RELAY_STATE_PORT_CLOSED = "port_closed"
OVERLAY_RELAY_STATE_AUTH_FAILED = "auth_failed"
OVERLAY_RELAY_STATE_HOST_KEY_CHANGED = "host_key_changed"
OVERLAY_RELAY_STATE_FORWARD_REFUSED = "forward_refused"
OVERLAY_RELAY_STATE_UNREACHABLE = "unreachable"
OVERLAY_RELAY_STATES = (
    OVERLAY_RELAY_STATE_DISABLED,
    OVERLAY_RELAY_STATE_NOT_CONFIGURED,
    OVERLAY_RELAY_STATE_VAULT_LOCKED,
    OVERLAY_RELAY_STATE_CONNECTING,
    OVERLAY_RELAY_STATE_CONNECTED,
    OVERLAY_RELAY_STATE_PORT_CLOSED,
    OVERLAY_RELAY_STATE_AUTH_FAILED,
    OVERLAY_RELAY_STATE_HOST_KEY_CHANGED,
    OVERLAY_RELAY_STATE_FORWARD_REFUSED,
    OVERLAY_RELAY_STATE_UNREACHABLE,
)
# What ssh writes to standard error before it exits, and the state each line
# means. The last line ssh wrote decides; a line holding none of these is
# `unreachable`. Measured on 2026-10-05, the OpenSSH 8.9 client against a 9.2 server:
#
# | ssh writes                                                       | state            |
# | ---------------------------------------------------------------- | ---------------- |
# | relay@203.0.113.5: Permission denied (publickey).                | auth_failed      |
# | @    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @      | host_key_changed |
# | Host key verification failed.                                    | host_key_changed |
# | Error: remote port forwarding failed for listen port 8443        | forward_refused  |
# | ssh: connect to host 203.0.113.5 port 22: Connection refused     | unreachable      |
# | Timeout, server 203.0.113.5 not responding.                      | unreachable      |
OVERLAY_RELAY_EXIT_LINES = (
    ("Permission denied", OVERLAY_RELAY_STATE_AUTH_FAILED),
    ("REMOTE HOST IDENTIFICATION HAS CHANGED", OVERLAY_RELAY_STATE_HOST_KEY_CHANGED),
    ("Host key verification failed", OVERLAY_RELAY_STATE_HOST_KEY_CHANGED),
    ("remote port forwarding failed", OVERLAY_RELAY_STATE_FORWARD_REFUSED),
)
# ssh ignoring the hub's own key file because other accounts can read it,
# which it writes just before the `Permission denied` that ends the run:
#
#   @         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
#   Load key "C:\\...\\relay\\key": bad permissions
#
# The fault is the hub's file, so it is not `auth_failed`; the state is the
# catch-all `unreachable` with a line that names the file.
OVERLAY_RELAY_KEY_FILE_LINES = ("UNPROTECTED PRIVATE KEY FILE", "bad permissions")
OVERLAY_RELAY_KEY_FILE_WINDOW = 3
OVERLAY_RELAY_KEY_FILE_ERROR = (
    "the hub's own key file can be read by other accounts, so ssh ignored it: " "{line}"
)
# What an apply changed, as the panel words it.
OVERLAY_RELAY_CHANGE_STARTED = "relay_started"
OVERLAY_RELAY_CHANGE_STOPPED = "relay_stopped"
# The reasons a failed check gives as `last_error`.
OVERLAY_RELAY_CHECK_NO_ANSWER = "no answer at {address}"
OVERLAY_RELAY_CHECK_FOREIGN = "another certificate at {address}"
