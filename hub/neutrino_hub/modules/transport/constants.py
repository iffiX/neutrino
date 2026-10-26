"""Fixed values of the hub's transport: its program, account, files and sockets."""

from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_RUNTIME_ROOT,
    UTILS_STATE_ROOT,
    carried_program,
)

# The Go program that holds the agent port, carried in the hub's package.
TRANSPORT_PROGRAM_NAME = "neutrino_transport"
TRANSPORT_BINARY_PATH = carried_program(TRANSPORT_PROGRAM_NAME)
# The subcommand that serves a hub's agent port, and the one that checks
# whether an address reaches a hub holding a key.
TRANSPORT_COMMAND_HUB = "hub"
TRANSPORT_COMMAND_PROBE = "probe"
# The system account the unit runs as on Linux; root or SYSTEM elsewhere.
TRANSPORT_ACCOUNT = "neutrino_transport"
TRANSPORT_UNIT = "neutrino_hub_transport.service"
TRANSPORT_UNIT_TEMPLATE = "neutrino_hub_transport.service"
# The name the process controller and the panel know the daemon by.
TRANSPORT_SERVICE_NAME = "transport"

# The static key: the one directory of the configuration the hub's Python
# does not write, the private half readable by the transport's account alone,
# the public half beside it (protocol.md, "The hub's static key").
TRANSPORT_KEY_DIR = UTILS_CONFIG_DIR / "transport"
TRANSPORT_KEY_DIR_MODE = 0o700
TRANSPORT_PRIVATE_KEY_NAME = "static_key"
TRANSPORT_PUBLIC_KEY_NAME = "public_key"
# The private half as a backup carries it, sealed under the vault's data key.
TRANSPORT_SEALED_KEY_NAME = "static_key.sealed"
TRANSPORT_KEY_AAD = b"transport:static_key"
TRANSPORT_KEY_HEX_CHARS = 64
TRANSPORT_PRIVATE_KEY_MODE = 0o600

# The transport's state directory and the local channel's secret in it: 32
# random bytes in hex, root's with the transport's group, mode 0640.
TRANSPORT_STATE_DIR = UTILS_STATE_ROOT / "transport"
TRANSPORT_SECRET_NAME = "control_secret"
TRANSPORT_SECRET_BYTES = 32
TRANSPORT_SECRET_MODE = 0o640
TRANSPORT_STATE_DIR_MODE = 0o750

# The transport's run directory and its listener in it, 0700 and 0600, its
# own; the named pipe on Windows.
TRANSPORT_RUN_DIR = UTILS_RUNTIME_ROOT / "transport"
TRANSPORT_RUN_DIR_MODE = 0o700
TRANSPORT_SOCKET_NAME = "transport.sock"
TRANSPORT_WINDOWS_PIPE = r"\\.\pipe\neutrino_hub_transport"

# What the transport opens, rendered by the hub's Python under the state
# root, read by the transport at its start.
TRANSPORT_GENERATED_NAME = "transport.json"
TRANSPORT_GENERATED_MODE = 0o644
# The listener names the transport reports a session on.
TRANSPORT_LISTENER_MAIN = "main"

# How long a probe may take to complete a handshake.
TRANSPORT_PROBE_TIMEOUT_S = 10.0

# What an apply of the transport reports.
TRANSPORT_CHANGE_STARTED = "transport_started"
TRANSPORT_CHANGE_RESTARTED = "transport_restarted"
