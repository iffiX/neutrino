"""Fixed values of the agent.

Anything an operator changes lives in ``/etc/neutrino/agent/agent.json``; this
file holds only what is wired into the protocol.
"""

# The hub and the agent share one configuration root with a directory each,
# so a machine running both has one place to look and one place to back up.
AGENT_CONFIG_PATH = "/etc/neutrino/agent/agent.json"

# How many connections in a row the hub may reject — a refused token, a
# certificate off the pin, an agent newer than the hub — before the agent
# drops its binding. One counter for every kind. More than one, so a hub
# caught mid-restore does not shed its whole fleet over a moment's
# inconsistency.
AGENT_REFUSALS_BEFORE_UNBIND = 3

AGENT_SERVICE_NAME = "neutrino_agent.service"

# The shape of what crosses the hub channel. Bumped on any wire change, so
# a hub upgrade that changed the shapes tells a same-version agent to
# reinstall instead of feeding it frames it cannot read.
AGENT_WIRE_GENERATION = 7

# The one socket to the hub, on the agent TLS port. Every stream rides it.
AGENT_WS_PATH = "/api/agent/ws"
# How long the socket may stay silent before it is taken for dead. The hub
# pings well inside this.
AGENT_WS_SILENCE_TIMEOUT_S = 45
# A binary frame starts with the stream id, this many ASCII characters.
AGENT_WS_STREAM_ID_LENGTH = 8
# The largest binary frame either side sends on one stream.
AGENT_WS_CHUNK_BYTES = 64 * 1024
# What the hub may send on one stream before this side grants more: one
# window of bytes, offered when a stream that takes bytes opens.
AGENT_WS_STREAM_CREDIT_BYTES = 1024 * 1024
# How long a stream waits on the hub's credit before it stops trying.
AGENT_WS_CREDIT_TIMEOUT_S = 60
# Close codes the hub turns a socket away with. The reason is the code word.
AGENT_WS_CLOSE_BAD_HELLO = 4400
AGENT_WS_CLOSE_UNKNOWN_TOKEN = 4401
AGENT_WS_CLOSE_REFUSED = 4409
AGENT_WS_CLOSE_REPLACED = 4410

AGENT_LEAVE_PATH = "/api/agent/leave"
AGENT_PACKAGE_PATH = "/api/agent/package"
# This machine never fetches a module from the internet: the hub's cache did
# that once for every machine of this platform, and an order says which
# artifact to ask it for.
AGENT_MODULE_PACKAGE_PATH = "/api/agent/module_package"

# How much of a failed order's output travels up. Enough to read the package
# manager's own complaint, bounded so a verbose failure cannot fill a beat.
AGENT_MODULE_OUTPUT_LIMIT_BYTES = 16 * 1024

# The transient unit a self-update runs in. Installing the package restarts
# neutrino_agent.service, so the install must outlive the process that
# started it.
AGENT_UPDATE_UNIT = "neutrino_agent_update"
AGENT_UPDATE_LAUNCH_TIMEOUT_S = 30

# How often a report goes up while nothing changes.
AGENT_HEARTBEAT_INTERVAL_S = 5
AGENT_REQUEST_TIMEOUT_S = 10
# Backoff bounds used when the gateway is unreachable. Starting at one interval
# and doubling to a minute keeps a rebooting gateway from being hammered while
# still reconnecting promptly once it returns.
AGENT_BACKOFF_MIN_S = 5
AGENT_BACKOFF_MAX_S = 60

AGENT_COMMAND_TIMEOUT_S = 900
AGENT_OUTPUT_LIMIT_BYTES = 64 * 1024

# The shell a stream opens for the hub: this account's own where it is
# usable, else the first of these.
AGENT_SHELL_FALLBACKS = ("/bin/bash", "/bin/sh")
AGENT_SHELL_READ_BYTES = 4096
# How long a shell's process group may take to die after the hub closes
# the stream, per signal.
AGENT_SHELL_KILL_TIMEOUT_S = 2.0
# How long a signalled process may take to leave before it is killed.
AGENT_KILL_GRACE_S = 2.0

# How long a stepped-down account command may take.
AGENT_STEP_DOWN_TIMEOUT_S = 120

# The local control channel: a socket the agent serves as root. Its file is
# 0600 under a 0700 directory, so only root reaches it.
AGENT_CONTROL_SOCKET_PATH = "/run/neutrino_agent/agent.sock"
AGENT_CONTROL_REQUEST_TIMEOUT_S = 5

# Where the machine keeps what it decided for itself, and the directory
# holding the one secret that never enters it: the desktop's seat password,
# in its own root-only file. The directory both live in is the platform
# contract's ``agent_data_dir``; these are the POSIX paths, which double as
# the defaults where nothing wires a root in.
AGENT_DATA_DIR_POSIX = "/etc/neutrino/agent"
AGENT_STATE_NAME = "state.json"
AGENT_CREDENTIALS_DIR_NAME = "credentials"
AGENT_STATE_PATH = AGENT_DATA_DIR_POSIX + "/" + AGENT_STATE_NAME

# The hub's desired state for this machine, kept beside the state store so
# the last copy taken is readable after a restart. Root-only: a module's
# configuration carries the secrets its service signs with.
AGENT_DESIRED_STATE_NAME = "desired.json"
AGENT_DESIRED_STATE_PATH = AGENT_DATA_DIR_POSIX + "/" + AGENT_DESIRED_STATE_NAME

# What the last reinstall did, written beside the state by the transient
# unit the install ran in and read by the agent that install put here. Both
# files are root-only: the package manager's output is nobody else's.
AGENT_REINSTALL_RESULT_NAME = "reinstall.json"
AGENT_REINSTALL_LOG_NAME = "reinstall.log"
# How much of the install log the result carries up.
AGENT_REINSTALL_OUTPUT_LIMIT_BYTES = 4 * 1024

# How long a module's live details stand in the report before the engine
# reads them again. The reporter never waits on a read.
AGENT_MODULE_DETAILS_TTL_S = 5.0

# Where the agent's own RustDesk build lands. The module is built in: its
# row reads installed while this file exists, and no order moves it. Under
# /usr because RustDesk refuses `--password` unless its own `current_exe`
# is there, and it resolves symlinks before it looks.
AGENT_RUSTDESK_BINARY_PATH = "/usr/lib/neutrino_agent/rustdesk/rustdesk"
# How long a module command waits for a pending desired state to apply
# before it runs against the configuration that state carries.
AGENT_MODULE_COMMAND_SETTLE_S = 30.0
